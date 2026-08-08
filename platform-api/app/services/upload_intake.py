"""Unified upload intake: capability registry and file classification.

Every governed file upload — structured spreadsheets as well as business
documents — passes through :func:`classify_upload` before any processor runs.
Classification never trusts the filename alone: the extension, the declared
MIME type and the file's magic bytes must agree, and macro-enabled or
encrypted Office documents are rejected outright.

The same registry backs ``GET /api/uploads/capabilities`` so the UI renders the
accepted formats and size limit the server actually enforces.
"""

from __future__ import annotations

import io
import json
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from typing import Any

# Families a file can be routed to after classification.
FAMILY_STRUCTURED = "structured_tabular"
FAMILY_SEMI_STRUCTURED = "semi_structured"
FAMILY_DOCUMENT = "unstructured_document"

# Destinations the intake can hand a classified file to.
DESTINATION_DATA_SOURCE = "data_source"
DESTINATION_DOCUMENT = "document"

MAX_UPLOAD_BYTES = 100 * 1024 * 1024

# Guards against decompression bombs in OOXML containers.
_MAX_ARCHIVE_ENTRIES = 2_000
_MAX_UNCOMPRESSED_BYTES = 500 * 1024 * 1024
_MAX_COMPRESSION_RATIO = 200

# Number of leading bytes inspected for shape detection of text formats.
_SHAPE_SAMPLE_BYTES = 64 * 1024


@dataclass(frozen=True)
class FormatSpec:
    extension: str
    family: str
    destination: str
    mime_types: tuple[str, ...]
    # ``ambiguous`` formats are shape-inspected and may be routed either way.
    ambiguous: bool = False


# The allowlist. Formats absent from this table are rejected by the intake.
SUPPORTED_FORMATS: tuple[FormatSpec, ...] = (
    FormatSpec(".csv", FAMILY_STRUCTURED, DESTINATION_DATA_SOURCE, ("text/csv", "application/csv", "text/plain")),
    FormatSpec(".tsv", FAMILY_STRUCTURED, DESTINATION_DATA_SOURCE, ("text/tab-separated-values", "text/plain")),
    FormatSpec(
        ".xlsx",
        FAMILY_STRUCTURED,
        DESTINATION_DATA_SOURCE,
        ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",),
    ),
    FormatSpec(".xls", FAMILY_STRUCTURED, DESTINATION_DATA_SOURCE, ("application/vnd.ms-excel",)),
    FormatSpec(".json", FAMILY_SEMI_STRUCTURED, DESTINATION_DATA_SOURCE, ("application/json", "text/json"), ambiguous=True),
    FormatSpec(".xml", FAMILY_SEMI_STRUCTURED, DESTINATION_DATA_SOURCE, ("application/xml", "text/xml"), ambiguous=True),
    FormatSpec(".txt", FAMILY_SEMI_STRUCTURED, DESTINATION_DOCUMENT, ("text/plain",), ambiguous=True),
    FormatSpec(".md", FAMILY_DOCUMENT, DESTINATION_DOCUMENT, ("text/markdown", "text/plain")),
    FormatSpec(".pdf", FAMILY_DOCUMENT, DESTINATION_DOCUMENT, ("application/pdf",)),
    FormatSpec(
        ".docx",
        FAMILY_DOCUMENT,
        DESTINATION_DOCUMENT,
        ("application/vnd.openxmlformats-officedocument.wordprocessingml.document",),
    ),
    FormatSpec(
        ".pptx",
        FAMILY_DOCUMENT,
        DESTINATION_DOCUMENT,
        ("application/vnd.openxmlformats-officedocument.presentationml.presentation",),
    ),
)

_BY_EXTENSION = {spec.extension: spec for spec in SUPPORTED_FORMATS}

# Macro-enabled Office formats are never accepted: there is no sanitization
# path that strips embedded code today.
_MACRO_EXTENSIONS = frozenset({".xlsm", ".xlsb", ".docm", ".pptm", ".dotm", ".xltm"})

# OOXML part prefixes that identify the real document type inside a zip
# container, in the order they are probed.
_OOXML_MARKERS: tuple[tuple[str, str], ...] = (
    ("xl/", ".xlsx"),
    ("word/", ".docx"),
    ("ppt/", ".pptx"),
)


class UploadRejected(Exception):
    """Raised when a file cannot be accepted by the governed intake."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class Classification:
    extension: str
    family: str
    destination: str
    confidence: str
    reason: str
    ambiguous: bool = False
    alternatives: list[str] = field(default_factory=list)
    detected_mime: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "extension": self.extension,
            "family": self.family,
            "destination": self.destination,
            "confidence": self.confidence,
            "reason": self.reason,
            "ambiguous": self.ambiguous,
            "alternatives": self.alternatives,
            "detectedMime": self.detected_mime,
        }


def capabilities() -> dict[str, Any]:
    """Server-owned capability document consumed by the upload UI."""
    return {
        "maxFileSizeBytes": MAX_UPLOAD_BYTES,
        "accepted": [
            {
                "extension": spec.extension,
                "family": spec.family,
                "destination": spec.destination,
                "mimeTypes": list(spec.mime_types),
                "ambiguous": spec.ambiguous,
            }
            for spec in SUPPORTED_FORMATS
        ],
    }


def accepted_extensions() -> list[str]:
    return [spec.extension for spec in SUPPORTED_FORMATS]


def _extension_of(filename: str) -> str:
    return f".{filename.rsplit('.', 1)[-1].lower()}" if "." in filename else ""


def _sniff(content: bytes) -> str | None:
    """Return the extension implied by the file's magic bytes, if known."""
    if content.startswith(b"%PDF-"):
        return ".pdf"
    if content.startswith(b"PK\x03\x04"):
        return _sniff_ooxml(content)
    if content.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        # Legacy OLE2 compound file — Excel/Word/PowerPoint 97-2003.
        return ".xls"
    return None


def _sniff_ooxml(content: bytes) -> str | None:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            infos = archive.infolist()
            _guard_archive(infos)
            names = [info.filename for info in infos]
    except zipfile.BadZipFile as exc:
        raise UploadRejected(
            "corrupt_container", "The file looks like an Office document but its container is unreadable."
        ) from exc
    if any(name.lower().endswith("vbaproject.bin") for name in names):
        raise UploadRejected(
            "macro_enabled",
            "Macro-enabled Office files are not accepted. Re-save the file without macros and upload it again.",
        )
    for prefix, extension in _OOXML_MARKERS:
        if any(name.startswith(prefix) for name in names):
            return extension
    return None


def _guard_archive(infos: list[zipfile.ZipInfo]) -> None:
    if len(infos) > _MAX_ARCHIVE_ENTRIES:
        raise UploadRejected("archive_too_complex", "The document contains too many internal parts to process safely.")
    total_uncompressed = sum(info.file_size for info in infos)
    total_compressed = sum(info.compress_size for info in infos) or 1
    if total_uncompressed > _MAX_UNCOMPRESSED_BYTES:
        raise UploadRejected("decompression_bomb", "The document expands to an unsafe size and was rejected.")
    if total_uncompressed // total_compressed > _MAX_COMPRESSION_RATIO:
        raise UploadRejected("decompression_bomb", "The document expands to an unsafe size and was rejected.")


def _reject_encrypted(extension: str, content: bytes) -> None:
    if extension == ".pdf" and b"/Encrypt" in content[:_SHAPE_SAMPLE_BYTES]:
        raise UploadRejected(
            "encrypted",
            "This PDF is password-protected. Upload an unprotected copy — passwords are never collected here.",
        )
    if content.startswith(b"\xd0\xcf\x11\xe0") and b"E\x00n\x00c\x00r\x00y\x00p\x00t\x00e\x00d" in content[:8192]:
        raise UploadRejected(
            "encrypted",
            "This document is password-protected. Upload an unprotected copy — passwords are never collected here.",
        )


def inspect_shape(extension: str, content: bytes) -> tuple[str, str, str]:
    """Decide whether ambiguous text content is record-shaped or narrative.

    Returns ``(destination, confidence, reason)``.
    """
    sample = content[:_SHAPE_SAMPLE_BYTES]
    if extension == ".json":
        try:
            parsed: Any = json.loads(sample.decode("utf-8", errors="replace"))
        except (ValueError, UnicodeDecodeError):
            return DESTINATION_DOCUMENT, "low", "The JSON could not be parsed as records."
        if isinstance(parsed, list) and parsed and all(isinstance(item, dict) for item in parsed):
            return DESTINATION_DATA_SOURCE, "high", "The JSON is a list of uniform records."
        if isinstance(parsed, dict):
            for value in parsed.values():
                if isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
                    return DESTINATION_DATA_SOURCE, "medium", "The JSON wraps a list of records."
        return DESTINATION_DOCUMENT, "medium", "The JSON is not shaped as tabular records."
    if extension == ".xml":
        text = sample.decode("utf-8", errors="replace")
        if "<!DOCTYPE" in text or "<!ENTITY" in text:
            # Entity expansion is an attack surface; never parse such input.
            return DESTINATION_DOCUMENT, "low", "The XML declares a DOCTYPE and is not parsed for records."
        try:
            root = ET.fromstring(text)
        except Exception:
            return DESTINATION_DOCUMENT, "low", "The XML could not be parsed as records."
        children = list(root)
        tags = {child.tag for child in children}
        if len(children) >= 2 and len(tags) == 1:
            return DESTINATION_DATA_SOURCE, "high", "The XML repeats a single record element."
        return DESTINATION_DOCUMENT, "medium", "The XML is not shaped as repeated records."
    # Plain text: treat consistently delimited lines as tabular.
    text = sample.decode("utf-8", errors="replace")
    lines = [line for line in text.splitlines() if line.strip()][:20]
    if len(lines) >= 2:
        for delimiter in (",", "\t", "|", ";"):
            counts = {line.count(delimiter) for line in lines}
            if len(counts) == 1 and counts.pop() >= 1:
                return DESTINATION_DATA_SOURCE, "medium", f"Every line has the same number of '{delimiter}' delimiters."
    return DESTINATION_DOCUMENT, "medium", "The text has no consistent delimiter structure."


def classify_upload(
    filename: str,
    content: bytes,
    declared_mime: str | None = None,
    *,
    max_bytes: int = MAX_UPLOAD_BYTES,
) -> Classification:
    """Classify an uploaded file, or raise :class:`UploadRejected`."""
    if not filename:
        raise UploadRejected("missing_filename", "A filename is required.")
    if len(content) == 0:
        raise UploadRejected("empty_file", f"{filename} is empty.")
    if len(content) > max_bytes:
        raise UploadRejected(
            "too_large",
            f"{filename} exceeds the {max_bytes // (1024 * 1024)}MB upload limit.",
        )

    extension = _extension_of(filename)
    if extension in _MACRO_EXTENSIONS:
        raise UploadRejected(
            "macro_enabled",
            "Macro-enabled Office files are not accepted. Re-save the file without macros and upload it again.",
        )
    spec = _BY_EXTENSION.get(extension)
    if spec is None:
        raise UploadRejected(
            "unsupported_type",
            f"{filename}: unsupported file type. Accepted formats: {', '.join(accepted_extensions())}.",
        )

    sniffed = _sniff(content)
    if sniffed is not None and sniffed != extension:
        # ``.xls`` and OOXML share container families; anything else that
        # disagrees is a renamed (possibly deceptive) file.
        legacy_ole = sniffed == ".xls" and extension in {".xls"}
        if not legacy_ole:
            raise UploadRejected(
                "signature_mismatch",
                f"{filename} does not match its extension — its contents look like a {sniffed} file.",
            )
    if sniffed is None and extension in {".pdf", ".docx", ".pptx", ".xlsx"}:
        raise UploadRejected(
            "signature_mismatch",
            f"{filename} does not contain valid {extension} content.",
        )

    _reject_encrypted(extension, content)

    if declared_mime:
        normalized = declared_mime.split(";")[0].strip().lower()
        if normalized and normalized != "application/octet-stream" and normalized not in spec.mime_types:
            raise UploadRejected(
                "mime_mismatch",
                f"{filename} was sent as {normalized}, which does not match a {extension} file.",
            )

    if spec.ambiguous:
        destination, confidence, reason = inspect_shape(extension, content)
        alternatives = [DESTINATION_DATA_SOURCE, DESTINATION_DOCUMENT]
        return Classification(
            extension=extension,
            family=FAMILY_STRUCTURED if destination == DESTINATION_DATA_SOURCE else FAMILY_DOCUMENT,
            destination=destination,
            confidence=confidence,
            reason=reason,
            ambiguous=confidence != "high",
            alternatives=alternatives,
            detected_mime=declared_mime,
        )

    return Classification(
        extension=extension,
        family=spec.family,
        destination=spec.destination,
        confidence="high",
        reason=f"{extension} files are always processed as {spec.family.replace('_', ' ')}.",
        detected_mime=declared_mime,
    )
