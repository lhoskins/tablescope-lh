"""Artifact scanner: hashing, GGUF structural validation, and executable guards.

No repository code is executed; validation is structural and byte-level only.
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass


@dataclass(frozen=True)
class ScanResult:
    filename: str
    size_bytes: int
    hash_algorithm: str
    hash_value: str
    is_gguf: bool
    gguf_version: int | None
    tensor_count: int | None
    metadata_kv_count: int | None


# Magic numbers for executable / archive formats we should never accept.
_EXECUTABLE_MAGICS = {
    b"\x7fELF",  # ELF
    b"MZ",  # Windows PE/DOS
    b"\xcf\xfa\xed\xfe",  # Mach-O 64-bit little endian
    b"\xfe\xed\xfa\xcf",  # Mach-O 64-bit big endian
    b"\xca\xfe\xba\xbe",  # Java class / Mach-O universal
    b"PK",  # ZIP archives ( jars, etc.)
    b"7z\xbc\xaf'",  # 7z
    b"Rar!",  # RAR
}


def _executable_prefix(path: str) -> bool:
    with open(path, "rb") as fh:
        prefix = fh.read(8)
    for magic in _EXECUTABLE_MAGICS:
        if prefix.startswith(magic):
            return True
    return False


def _read_gguf_header(path: str) -> tuple[int, int, int] | None:
    """Parse the first 24 bytes of a GGUF file: magic, version, tensor_count, kv_count."""
    with open(path, "rb") as fh:
        magic = fh.read(4)
        if magic != b"GGUF":
            return None
        version_bytes = fh.read(4)
        if len(version_bytes) != 4:
            return None
        (version,) = struct.unpack("<I", version_bytes)
        if version not in (2, 3):
            return None
        tensor_count_bytes = fh.read(8)
        metadata_kv_count_bytes = fh.read(8)
        if len(tensor_count_bytes) != 8 or len(metadata_kv_count_bytes) != 8:
            return None
        (tensor_count,) = struct.unpack("<Q", tensor_count_bytes)
        (metadata_kv_count,) = struct.unpack("<Q", metadata_kv_count_bytes)
        return version, tensor_count, metadata_kv_count
    return None


def scan_file(filename: str, path: str) -> ScanResult:
    """Hash and validate a single artifact file.

    Raises ``ValueError`` if the file fails structural or executable guards.
    """
    if _executable_prefix(path):
        raise ValueError(f"{filename}: rejected executable or archive file type")

    header = _read_gguf_header(path)
    if header is None:
        raise ValueError(f"{filename}: not a valid GGUF file")
    version, tensor_count, metadata_kv_count = header

    hasher = hashlib.sha256()
    size = 0
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            size += len(chunk)
            hasher.update(chunk)

    return ScanResult(
        filename=filename,
        size_bytes=size,
        hash_algorithm="sha256",
        hash_value=hasher.hexdigest(),
        is_gguf=True,
        gguf_version=version,
        tensor_count=tensor_count,
        metadata_kv_count=metadata_kv_count,
    )
