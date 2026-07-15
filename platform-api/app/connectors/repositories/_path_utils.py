"""Path normalization and validation utilities for UNC/SMB connectors."""

from __future__ import annotations

import pathlib
import re
from typing import Any

from app.connectors.repositories.base import RepositoryConnectorError


def _safe_message(text: str) -> str:
    """Remove control characters and null bytes from a user-facing string."""
    return re.sub(r"[\x00-\x08\x0b-\x0c\x0e-\x1f]", "", text)


def normalize_unc_path(path: str) -> str:
    """Return a backslash-separated UNC path with no trailing separator."""
    if not isinstance(path, str):
        raise RepositoryConnectorError("UNC path must be a string")
    path = path.replace("/", "\\")

    # Count leading backslashes so the UNC \\ prefix is preserved.
    leading = 0
    for char in path:
        if char == "\\":
            leading += 1
        else:
            break

    # Remove empty segments caused by repeated separators.
    parts = [segment for segment in path.split("\\") if segment]

    if leading >= 2:
        return "\\\\" + "\\".join(parts)
    if leading == 1:
        return "\\\\" + "\\".join(parts)
    return "\\".join(parts)


def parse_unc(path: str) -> tuple[str, str, str]:
    r"""Parse ``\\server\share\subpath`` into (server, share, subpath)."""
    path = normalize_unc_path(path)
    if not path.startswith("\\\\"):
        raise RepositoryConnectorError("UNC path must start with \\\\")
    body = path[2:]
    parts = body.split("\\", 2)
    if len(parts) < 2:
        raise RepositoryConnectorError("UNC path must include a server and a share")
    server = parts[0]
    share = parts[1]
    subpath = parts[2] if len(parts) == 3 else ""
    if not server:
        raise RepositoryConnectorError("UNC server name is missing")
    if not share:
        raise RepositoryConnectorError("UNC share name is missing")
    return server, share, subpath


def validate_unc_root(path: str) -> None:
    """Validate that ``path`` is a safe UNC root and not a traversal vector."""
    if not isinstance(path, str):
        raise RepositoryConnectorError("rootPath must be a string")
    if "\x00" in path:
        raise RepositoryConnectorError("UNC path contains a null byte")
    if path.lower().startswith("\\\\?\\") or path.lower().startswith("\\\\?\\unc\\"):
        raise RepositoryConnectorError("Extended UNC paths are not supported")
    if re.match(r"^[a-zA-Z]:", path):
        raise RepositoryConnectorError("Local drive paths are not supported")
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]+:", path):
        raise RepositoryConnectorError("URI schemes are not supported")
    if "." in path or ".." in path.split("\\"):
        raise RepositoryConnectorError("Path traversal is not allowed")
    normalized = normalize_unc_path(path)
    if not normalized.startswith("\\\\"):
        raise RepositoryConnectorError("UNC path must start with \\\\")
    server, share, _ = parse_unc(normalized)
    if re.search(r"[*?]", server) or re.search(r"[*?]", share):
        raise RepositoryConnectorError("Server and share must not contain wildcards")
    if not server or not share:
        raise RepositoryConnectorError("Server and share are required")


def effective_root(config: dict[str, Any]) -> str:
    """Return the effective UNC scan root for a connector configuration."""
    root = normalize_unc_path(config.get("rootPath", ""))
    validate_unc_root(root)
    subpath = config.get("allowedSubpath", "") or ""
    if subpath:
        subpath = subpath.replace("/", "\\").strip("\\")
        if ".." in subpath.split("\\"):
            raise RepositoryConnectorError("allowedSubpath contains traversal")
        root = f"{root}\\{subpath}"
    return normalize_unc_path(root)


def relative_to_root(root: str, full_path: str) -> str:
    """Return ``full_path`` relative to ``root`` using forward slashes."""
    root = normalize_unc_path(root)
    full = normalize_unc_path(full_path)
    if not full.startswith(root + "\\") and full != root:
        raise RepositoryConnectorError("Item path is outside the configured root")
    rel = full[len(root) :].lstrip("\\")
    return rel.replace("\\", "/")


def join_unc(*parts: str) -> str:
    """Join UNC path components with backslashes and normalize."""
    if not parts:
        return ""
    first = parts[0].replace("/", "\\").rstrip("\\")
    rest = [p.replace("/", "\\").strip("\\") for p in parts[1:] if p]
    if not first:
        joined = "\\".join(rest)
    else:
        joined = "\\".join([first, *rest])
    return normalize_unc_path(joined)


def glob_match(relative_path: str, pattern: str) -> bool:
    """Match a relative path (forward-slash) against a glob pattern."""
    pattern = pattern.replace("\\", "/")
    if not pattern:
        return True
    try:
        return pathlib.PurePosixPath(relative_path).match(pattern)
    except Exception:
        return False


def is_path_allowed(
    relative_path: str,
    include_patterns: list[str],
    exclude_patterns: list[str],
) -> bool:
    """Return True when ``relative_path`` satisfies include/exclude patterns."""
    if exclude_patterns:
        for pattern in exclude_patterns:
            if glob_match(relative_path, pattern):
                return False
    if include_patterns:
        return any(glob_match(relative_path, pattern) for pattern in include_patterns)
    return True
