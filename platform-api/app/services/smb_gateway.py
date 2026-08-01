"""Application-side SMB gateway for UNC/network-path imports.

A browser cannot read ``\\\\server\\share\\file.xlsx`` and the isolated AI
server must never see a share or a credential, so network files are read here,
on the application plane, and staged into tenant quarantine like any other
import.

Path handling is deliberately split from I/O: :func:`resolve_network_path` is
pure and does all of the traversal/allowlist enforcement, which is what the
security tests exercise. :func:`read_network_file` then performs the SMB2/SMB3
read (``smbprotocol`` speaks no SMB1 and no NTLMv1) with signing and, where
the server supports it, encryption required.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass

from app.config import get_settings
from app.models.network_file_connection import NetworkFileConnection
from app.services.crypto import decrypt_secret

logger = logging.getLogger(__name__)

#: Shares that are never importable — they expose the whole host filesystem.
ADMINISTRATIVE_SHARES = frozenset({"c$", "d$", "admin$", "ipc$", "print$"})

_WILDCARD_CHARS = set('*?"<>|')
_INVALID_SEGMENTS = {"", ".", ".."}


class NetworkPathError(Exception):
    """A network path was refused. ``code`` is a safe error category."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(slots=True)
class ResolvedNetworkPath:
    host: str
    share: str
    #: Share-relative path with forward slashes, e.g. ``finance/q3/sales.csv``.
    relative_path: str
    filename: str

    @property
    def unc_path(self) -> str:
        tail = self.relative_path.replace("/", "\\")
        return f"\\\\{self.host}\\{self.share}\\{tail}"

    @property
    def redacted_locator(self) -> str:
        """Host, share, and filename only — intermediate folders are private."""
        return f"\\\\{self.host}\\{self.share}\\…\\{self.filename}"


def _split_locator(raw: str) -> tuple[str, list[str]]:
    """Split a UNC or smb:// locator into (host, path segments)."""
    value = raw.strip()
    if not value:
        raise NetworkPathError("INVALID_PATH", "Enter a network file path.")
    if any(ord(ch) < 32 for ch in value):
        raise NetworkPathError(
            "INVALID_PATH", "That path contains invalid characters."
        )
    if value.startswith(("\\\\.\\", "\\\\?\\")):
        raise NetworkPathError("INVALID_PATH", "Device paths are not supported.")

    if value.lower().startswith("smb://"):
        remainder = value[len("smb://") :]
    elif value.startswith("\\\\"):
        remainder = value[2:]
    elif value.startswith("//"):
        remainder = value[2:]
    else:
        raise NetworkPathError(
            "INVALID_PATH",
            "Use a UNC path (\\\\server\\share\\file) or smb:// URL.",
        )

    if "@" in remainder.split("/")[0].split("\\")[0]:
        raise NetworkPathError(
            "INVALID_PATH", "Paths with embedded credentials are not accepted."
        )

    parts = [p for p in re.split(r"[\\/]", remainder)]
    if not parts or not parts[0]:
        raise NetworkPathError("INVALID_PATH", "That path has no server name.")
    return parts[0].lower(), parts[1:]


def resolve_network_path(
    raw_path: str, connection: NetworkFileConnection
) -> ResolvedNetworkPath:
    """Validate ``raw_path`` against ``connection`` and normalise it.

    Enforces: matching host/share, the connection's ``approved_root_path``, no
    traversal or wildcards, no administrative shares, and the deployment-level
    SMB host allowlist.
    """
    if not connection.enabled or connection.archived:
        raise NetworkPathError(
            "CONNECTION_DISABLED", "That network location is not enabled."
        )

    host, segments = _split_locator(raw_path)
    if host != connection.host.lower():
        raise NetworkPathError(
            "HOST_NOT_APPROVED",
            "That server does not match the selected network location.",
        )

    allowlist = get_settings().file_import_smb_host_allowlist
    if host not in allowlist:
        raise NetworkPathError(
            "HOST_NOT_APPROVED",
            "That server is not on the approved network list.",
        )

    if not segments:
        raise NetworkPathError("INVALID_PATH", "That path has no share name.")
    share = segments[0].lower()
    if share != connection.share_name.lower():
        raise NetworkPathError(
            "SHARE_NOT_APPROVED",
            "That share does not match the selected network location.",
        )
    if share in ADMINISTRATIVE_SHARES:
        raise NetworkPathError(
            "SHARE_NOT_APPROVED", "Administrative shares cannot be imported."
        )

    tail = segments[1:]
    for segment in tail:
        if segment in _INVALID_SEGMENTS:
            raise NetworkPathError(
                "OUTSIDE_APPROVED_ROOT", "That path is not allowed."
            )
        if _WILDCARD_CHARS & set(segment) or ":" in segment:
            raise NetworkPathError(
                "INVALID_PATH", "That path contains invalid characters."
            )
    if not tail:
        raise NetworkPathError("INVALID_PATH", "That path has no file name.")

    relative = "/".join(tail)
    root = connection.approved_root_path.strip().strip("\\/").replace("\\", "/")
    if root:
        root_segments = [s for s in root.split("/") if s]
        if [s.lower() for s in tail[: len(root_segments)]] != [
            s.lower() for s in root_segments
        ]:
            raise NetworkPathError(
                "OUTSIDE_APPROVED_ROOT",
                "That path is outside the approved folder for this location.",
            )
        if len(tail) <= len(root_segments):
            raise NetworkPathError("INVALID_PATH", "That path has no file name.")

    return ResolvedNetworkPath(
        host=host, share=share, relative_path=relative, filename=tail[-1]
    )


def _register_session(connection: NetworkFileConnection) -> None:
    import smbclient

    password = (
        decrypt_secret(connection.secret_encrypted)
        if connection.secret_encrypted
        else None
    )
    username = connection.username
    if username and connection.domain:
        username = f"{connection.domain}\\{username}"
    # smbprotocol negotiates SMB 2.0.2+ only; SMB1/NTLMv1 are not implemented.
    smbclient.register_session(
        connection.host,
        username=username,
        password=password,
        port=connection.port,
        encrypt=connection.require_encryption,
        require_signing=connection.require_signing,
        auth_protocol="negotiate",
    )


def _read_blocking(
    resolved: ResolvedNetworkPath,
    connection: NetworkFileConnection,
    max_bytes: int,
) -> bytes:
    import smbclient
    from smbprotocol.exceptions import SMBOSError, SMBResponseException

    try:
        _register_session(connection)
        chunks: list[bytes] = []
        total = 0
        with smbclient.open_file(resolved.unc_path, mode="rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise NetworkPathError(
                        "FILE_TOO_LARGE",
                        f"That file exceeds the {max_bytes // (1024 * 1024)}MB "
                        "limit.",
                    )
                chunks.append(chunk)
        return b"".join(chunks)
    except NetworkPathError:
        raise
    except FileNotFoundError as exc:
        raise NetworkPathError("FILE_NOT_FOUND", "That file was not found.") from exc
    except PermissionError as exc:
        raise NetworkPathError(
            "ACCESS_DENIED", "Access to that file was denied."
        ) from exc
    except (SMBOSError, SMBResponseException) as exc:
        # Never surface the raw SMB error: it can echo the full path and the
        # account name used to authenticate.
        logger.info("SMB read failed for %s", resolved.redacted_locator)
        raise NetworkPathError(
            "ACCESS_DENIED", "That file could not be read from the network location."
        ) from exc
    except OSError as exc:
        logger.info("SMB connection failed for host %s", resolved.host)
        raise NetworkPathError(
            "HOST_UNREACHABLE", "The network location could not be reached."
        ) from exc
    finally:
        try:
            smbclient.delete_session(connection.host, port=connection.port)
        except Exception:  # pragma: no cover - best-effort teardown
            logger.debug("SMB session teardown failed", exc_info=True)


async def read_network_file(
    resolved: ResolvedNetworkPath,
    connection: NetworkFileConnection,
    *,
    max_bytes: int | None = None,
) -> bytes:
    """Read an approved network file into memory, off the event loop."""
    limit = max_bytes or get_settings().file_import_max_bytes
    return await asyncio.to_thread(_read_blocking, resolved, connection, limit)


async def test_network_access(
    connection: NetworkFileConnection, raw_path: str | None = None
) -> dict[str, object]:
    """Verify a connection (and optionally one path) without importing bytes."""

    def _probe() -> dict[str, object]:
        import smbclient

        _register_session(connection)
        try:
            if raw_path:
                resolved = resolve_network_path(raw_path, connection)
                info = smbclient.stat(resolved.unc_path)
                return {
                    "ok": True,
                    "locator": resolved.redacted_locator,
                    "file_name": resolved.filename,
                    "file_size_bytes": info.st_size,
                }
            root = connection.approved_root_path.strip().strip("\\/")
            base = f"\\\\{connection.host}\\{connection.share_name}"
            target = f"{base}\\{root}" if root else base
            smbclient.listdir(target)
            return {"ok": True, "locator": connection.label}
        finally:
            try:
                smbclient.delete_session(connection.host, port=connection.port)
            except Exception:  # pragma: no cover - best-effort teardown
                logger.debug("SMB session teardown failed", exc_info=True)

    try:
        return await asyncio.to_thread(_probe)
    except NetworkPathError:
        raise
    except FileNotFoundError as exc:
        raise NetworkPathError("FILE_NOT_FOUND", "That path was not found.") from exc
    except PermissionError as exc:
        raise NetworkPathError("ACCESS_DENIED", "Access was denied.") from exc
    except Exception as exc:
        logger.info("SMB test failed for connection %s", connection.id)
        raise NetworkPathError(
            "HOST_UNREACHABLE", "The network location could not be reached."
        ) from exc
