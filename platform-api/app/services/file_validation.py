"""Content validation for acquired files, run before anything parses them.

Acquisition (local upload, HTTPS, SMB) only decides how bytes arrive. Every
path then lands here: extension, declared MIME type, and magic bytes must all
agree on a supported format, containers are checked for decompression bombs,
and archives/executables are refused outright.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from io import BytesIO

#: Tabular formats feed the existing profile -> Teiid -> FileSourceMeta path.
TABULAR_EXTENSIONS = frozenset({"csv", "tsv", "txt", "xls", "xlsx", "xlsm", "json", "xml"})
#: Document formats feed the existing Project Asset / document pipeline, so
#: this set mirrors that pipeline's supported extensions exactly.
DOCUMENT_EXTENSIONS = frozenset({"pdf", "docx", "pptx", "md"})

EXTENSION_MIME_TYPES: dict[str, tuple[str, ...]] = {
    "csv": ("text/csv", "text/plain", "application/csv", "application/octet-stream"),
    "tsv": ("text/tab-separated-values", "text/plain", "application/octet-stream"),
    "txt": ("text/plain", "application/octet-stream"),
    "json": ("application/json", "text/json", "text/plain", "application/octet-stream"),
    "xml": ("application/xml", "text/xml", "text/plain", "application/octet-stream"),
    "xls": ("application/vnd.ms-excel", "application/octet-stream"),
    "xlsx": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/octet-stream",
        "application/zip",
    ),
    "xlsm": (
        "application/vnd.ms-excel.sheet.macroenabled.12",
        "application/octet-stream",
        "application/zip",
    ),
    "pdf": ("application/pdf", "application/octet-stream"),
    "docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/octet-stream",
        "application/zip",
    ),
    "pptx": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/octet-stream",
        "application/zip",
    ),
    "md": ("text/markdown", "text/plain", "application/octet-stream"),
}

#: Signatures that mean "never process this", checked before anything else.
_FORBIDDEN_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"MZ", "Windows executable"),
    (b"\x7fELF", "ELF executable"),
    (b"\xca\xfe\xba\xbe", "Mach-O/Java executable"),
    (b"\xfe\xed\xfa", "Mach-O executable"),
    (b"Rar!\x1a\x07", "RAR archive"),
    (b"7z\xbc\xaf\x27\x1c", "7-Zip archive"),
    (b"\x1f\x8b", "gzip archive"),
    (b"BZh", "bzip2 archive"),
    (b"\xfd7zXZ", "xz archive"),
    (b"#!", "script with a shebang"),
)

_ZIP_SIGNATURE = b"PK\x03\x04"
_OLE_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_PDF_SIGNATURE = b"%PDF-"

_ZIP_EXTENSIONS = frozenset({"xlsx", "xlsm", "docx", "pptx"})
_OLE_EXTENSIONS = frozenset({"xls"})

#: Zip-bomb guards for OOXML containers.
MAX_CONTAINER_ENTRIES = 2_000
MAX_CONTAINER_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB
MAX_CONTAINER_RATIO = 200


class FileValidationError(Exception):
    """A file was refused. ``code`` is a safe, user-presentable category."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(slots=True)
class ValidatedContent:
    extension: str
    mime_type: str
    content_family: str


def extension_of(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def content_family_for(extension: str) -> str:
    if extension in TABULAR_EXTENSIONS:
        return "tabular"
    if extension in DOCUMENT_EXTENSIONS:
        return "document"
    return "unknown"


def _looks_like_text(head: bytes) -> bool:
    if b"\x00" in head:
        return False
    try:
        head.decode("utf-8")
    except UnicodeDecodeError:
        try:
            head.decode("latin-1")
        except UnicodeDecodeError:
            return False
    return True


def _check_container(data: bytes, extension: str) -> None:
    """Reject OOXML containers that would decompress to an absurd size."""
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_CONTAINER_ENTRIES:
                raise FileValidationError(
                    "CONTAINER_TOO_COMPLEX",
                    "That file contains too many internal entries.",
                )
            uncompressed = sum(info.file_size for info in infos)
            if uncompressed > MAX_CONTAINER_UNCOMPRESSED_BYTES:
                raise FileValidationError(
                    "DECOMPRESSION_LIMIT",
                    "That file expands to an unsafe size.",
                )
            compressed = sum(info.compress_size for info in infos) or 1
            if uncompressed / compressed > MAX_CONTAINER_RATIO:
                raise FileValidationError(
                    "DECOMPRESSION_LIMIT",
                    "That file has an unsafe compression ratio.",
                )
    except zipfile.BadZipFile as exc:
        raise FileValidationError(
            "SIGNATURE_MISMATCH",
            f"That file is not a readable .{extension} container.",
        ) from exc


def validate_content(
    data: bytes,
    filename: str,
    *,
    declared_mime_type: str | None = None,
    allowed_families: tuple[str, ...] = ("tabular", "document"),
) -> ValidatedContent:
    """Validate extension, MIME type, and magic bytes together.

    Neither the URL extension nor the server's ``Content-Type`` is trusted on
    its own: both are cross-checked against the actual leading bytes.
    """
    if not data:
        raise FileValidationError("EMPTY_FILE", "That file is empty.")

    extension = extension_of(filename)
    if not extension:
        raise FileValidationError(
            "UNSUPPORTED_TYPE", "That file has no recognisable extension."
        )

    family = content_family_for(extension)
    if family == "unknown" or family not in allowed_families:
        raise FileValidationError(
            "UNSUPPORTED_TYPE", f".{extension} files are not supported here."
        )

    head = data[:512]
    for signature, label in _FORBIDDEN_SIGNATURES:
        if head.startswith(signature):
            raise FileValidationError(
                "FORBIDDEN_CONTENT", f"That file looks like a {label}."
            )

    if extension in _ZIP_EXTENSIONS:
        if not head.startswith(_ZIP_SIGNATURE):
            raise FileValidationError(
                "SIGNATURE_MISMATCH",
                f"That file is not a real .{extension} file.",
            )
        _check_container(data, extension)
    elif extension in _OLE_EXTENSIONS:
        if not head.startswith(_OLE_SIGNATURE):
            raise FileValidationError(
                "SIGNATURE_MISMATCH",
                f"That file is not a real .{extension} file.",
            )
    elif extension == "pdf":
        if not head.startswith(_PDF_SIGNATURE):
            raise FileValidationError(
                "SIGNATURE_MISMATCH", "That file is not a real PDF."
            )
    elif not _looks_like_text(head):
        raise FileValidationError(
            "SIGNATURE_MISMATCH",
            f"That file is not readable as .{extension} text.",
        )

    allowed_mimes = EXTENSION_MIME_TYPES[extension]
    mime_type = (declared_mime_type or "").split(";")[0].strip().lower()
    if mime_type and mime_type not in allowed_mimes:
        raise FileValidationError(
            "MIME_MISMATCH",
            f"The source reported {mime_type}, which does not match "
            f".{extension}.",
        )

    return ValidatedContent(
        extension=extension,
        mime_type=mime_type or allowed_mimes[0],
        content_family=family,
    )
