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

To satisfy tenant-bound egress (Gate C) the socket used for SMB is bound to the
worker's IP inside the tenant's Docker network.  The host's ``DOCKER-USER``
per-tenant firewall chain can then classify the traffic by source subnet and
only allow the on-prem CIDRs approved for that tenant.
"""

from __future__ import annotations

import asyncio
import logging
import re
import socket as _socket
import threading
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.network_file_connection import NetworkFileConnection
from app.services.crypto import decrypt_secret

logger = logging.getLogger(__name__)

#: Thread-local source address used to bind SMB sockets to a tenant network.
_thread_source = threading.local()
_orig_create_connection = _socket.create_connection


def _create_connection_bound(address, timeout=None, source_address=None):
    """Wrap ``socket.create_connection`` to inject a per-thread source IP."""
    if source_address is None:
        bound = getattr(_thread_source, "source_address", None)
        if bound:
            source_address = bound
    return _orig_create_connection(address, timeout, source_address)


# Install once. Only calls that set the thread-local source address are
# affected; all other callers fall through to the original function.
_socket.create_connection = _create_connection_bound  # type: ignore[assignment]

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


async def get_approved_smb_hosts(
    session: AsyncSession, tenant_id: int
) -> list[str]:
    """Return the merged SMB host allowlist for a tenant.

    The ``FILE_IMPORT_ALLOWED_SMB_HOSTS`` environment variable is always
    included as a deployment-level fallback; tenant-managed entries in
    ``network_file_hosts`` are merged on top and de-duplicated.
    """
    from app.models.network_file_host import NetworkFileHost

    env_hosts = get_settings().file_import_smb_host_allowlist
    rows = await session.scalars(
        select(NetworkFileHost.host).where(
            NetworkFileHost.tenant_id == tenant_id,
            NetworkFileHost.archived.is_(False),
            NetworkFileHost.enabled.is_(True),
        )
    )
    db_hosts = [h.strip().lower() for h in rows.all() if h and h.strip()]
    return list(dict.fromkeys(env_hosts + db_hosts))


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


def _resolve_locator(
    raw_path: str,
    connection: NetworkFileConnection,
    approved_hosts: list[str] | None,
    *,
    require_filename: bool,
) -> tuple[str, str, list[str]]:
    """Validate a UNC/SMB locator and return (host, share, tail_segments).

    Shared validation used by both file imports and directory browsing.
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

    allowlist = (
        approved_hosts
        if approved_hosts is not None
        else get_settings().file_import_smb_host_allowlist
    )
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

    if require_filename and not tail:
        raise NetworkPathError("INVALID_PATH", "That path has no file name.")

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
        if require_filename and len(tail) <= len(root_segments):
            raise NetworkPathError("INVALID_PATH", "That path has no file name.")

    return host, share, tail


def _normalize_raw_path(raw_path: str, connection: NetworkFileConnection) -> str:
    """If ``raw_path`` is a bare filename or starts with the share name, prepend ``//host/share/``.

    This lets the browse API and older import records supply just a filename
    like ``sample.csv`` while still validating it against the selected
    ``connection``.  Paths that still look like local/relative paths (e.g.
    ``finance/sales.xlsx`` without a host or share) are left as-is so the
    resolver can reject them.
    """
    raw = raw_path.strip()
    lower = raw.lower()
    if lower.startswith(("smb://", "//", "\\\\")):
        return raw

    share = connection.share_name.strip("\\/")
    prefix = share + "/"
    prefix_back = share + "\\"

    if lower.startswith(prefix.lower()) or lower.startswith(prefix_back.lower()):
        relative = raw[len(share) + 1 :].lstrip("\\/")
        return f"//{connection.host}/{share}/{relative}"

    # Allow only bare filenames (no path separators) to be treated as share-relative.
    if "/" not in raw and "\\" not in raw:
        raw_name = raw.lstrip("\\/")
        return f"//{connection.host}/{share}/{raw_name}"

    return raw


def resolve_network_path(
    raw_path: str,
    connection: NetworkFileConnection,
    approved_hosts: list[str] | None = None,
) -> ResolvedNetworkPath:
    """Validate ``raw_path`` against ``connection`` and normalise it.

    Enforces: matching host/share, the connection's ``approved_root_path``, no
    traversal or wildcards, no administrative shares, and the SMB host
    allowlist.  When ``approved_hosts`` is supplied it is used directly;
    otherwise the deployment-level environment allowlist is consulted.
    """
    host, share, tail = _resolve_locator(
        _normalize_raw_path(raw_path, connection), connection, approved_hosts, require_filename=True
    )
    relative = "/".join(tail)
    return ResolvedNetworkPath(
        host=host, share=share, relative_path=relative, filename=tail[-1]
    )


def resolve_network_directory(
    raw_path: str,
    connection: NetworkFileConnection,
    approved_hosts: list[str] | None = None,
) -> ResolvedNetworkPath:
    """Validate a directory locator and normalise it for browsing.

    The path may be the share root or a folder inside ``approved_root_path``.
    """
    host, share, tail = _resolve_locator(
        _normalize_raw_path(raw_path, connection), connection, approved_hosts, require_filename=False
    )
    relative = "/".join(tail)
    return ResolvedNetworkPath(
        host=host,
        share=share,
        relative_path=relative,
        filename=tail[-1] if tail else "",
    )


def _set_thread_source_address(source_ip: str | None) -> None:
    """Bind any socket created in this thread to ``(source_ip, 0)``."""
    if source_ip:
        _thread_source.source_address = (source_ip, 0)
    else:
        _thread_source.source_address = None


def _clear_thread_source_address() -> None:
    _thread_source.source_address = None


def _register_session(connection: NetworkFileConnection, source_ip: str | None) -> None:
    import smbclient

    _set_thread_source_address(source_ip)
    password = (
        decrypt_secret(connection.secret_encrypted)
        if connection.secret_encrypted
        else None
    )
    username = connection.username
    if username and connection.domain:
        username = f"{connection.domain}\\{username}"
    # smbprotocol negotiates SMB 2.0.2+ only; SMB1/NTLMv1 are not implemented.
    try:
        smbclient.register_session(
            connection.host,
            username=username,
            password=password,
            port=connection.port,
            encrypt=connection.require_encryption,
            require_signing=connection.require_signing,
            auth_protocol="negotiate",
        )
    finally:
        _clear_thread_source_address()


def _read_blocking(
    resolved: ResolvedNetworkPath,
    connection: NetworkFileConnection,
    max_bytes: int,
    source_ip: str | None,
) -> bytes:
    import smbclient
    from smbprotocol.exceptions import (
        SMBAuthenticationError,
        SMBConnectionClosed,
        SMBOSError,
        SMBResponseException,
    )

    try:
        _register_session(connection, source_ip)
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
    except (SMBAuthenticationError, SMBConnectionClosed) as exc:
        logger.info("SMB authentication failed for %s", resolved.redacted_locator)
        raise NetworkPathError(
            "AUTH_FAILED",
            "Could not authenticate to the network location. Check the credentials.",
        ) from exc
    except (SMBOSError, SMBResponseException) as exc:
        # Never surface the raw SMB error: it can echo the full path and the
        # account name used to authenticate.
        logger.info("SMB read failed for %s", resolved.redacted_locator)
        raise NetworkPathError(
            "ACCESS_DENIED", "That file could not be read from the network location."
        ) from exc
    except (OSError, ValueError) as exc:
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
    source_ip: str | None = None,
) -> bytes:
    """Read an approved network file into memory, off the event loop.

    When ``source_ip`` is provided, the SMB socket is bound to that address so
    the host firewall can classify the traffic as belonging to the correct
    tenant Docker network.
    """
    limit = max_bytes or get_settings().file_import_max_bytes
    return await asyncio.to_thread(_read_blocking, resolved, connection, limit, source_ip)


async def list_network_path(
    connection: NetworkFileConnection,
    raw_path: str,
    *,
    source_ip: str | None = None,
    approved_hosts: list[str] | None = None,
) -> list[dict[str, object]]:
    """List files and folders in an approved SMB directory."""

    def _list() -> list[dict[str, object]]:
        import smbclient
        from smbprotocol.exceptions import (
            SMBAuthenticationError,
            SMBConnectionClosed,
            SMBOSError,
            SMBResponseException,
        )

        resolved = resolve_network_directory(raw_path, connection, approved_hosts)
        try:
            _register_session(connection, source_ip)
            target = resolved.unc_path
            if not resolved.relative_path:
                target = f"\\\\{resolved.host}\\{resolved.share}"
            entries = []
            for entry in smbclient.scandir(target):
                name = entry.name
                if name in (".", ".."):
                    continue
                is_dir = entry.is_dir()
                info = entry.smb_info
                modified_ts = (
                    info.last_write_time.timestamp()
                    if info.last_write_time
                    else None
                )
                entries.append(
                    {
                        "name": name,
                        "path": (
                            f"{resolved.relative_path}/{name}"
                            if resolved.relative_path
                            else name
                        ),
                        "kind": "directory" if is_dir else "file",
                        "size_bytes": 0 if is_dir else info.end_of_file,
                        "modified_at": modified_ts,
                    }
                )
            return sorted(entries, key=lambda e: (e["kind"] != "directory", e["name"]))
        except (SMBAuthenticationError, SMBConnectionClosed) as exc:
            logger.info("SMB authentication failed for %s", resolved.redacted_locator)
            raise NetworkPathError(
                "AUTH_FAILED",
                "Could not authenticate to the network location. Check the credentials.",
            ) from exc
        except (SMBOSError, SMBResponseException) as exc:
            logger.info("SMB list failed for %s", resolved.redacted_locator)
            raise NetworkPathError(
                "ACCESS_DENIED",
                "That folder could not be read from the network location.",
            ) from exc
        except (OSError, ValueError) as exc:
            logger.info("SMB connection failed for host %s", resolved.host)
            raise NetworkPathError(
                "HOST_UNREACHABLE", "The network location could not be reached."
            ) from exc
        finally:
            try:
                smbclient.delete_session(connection.host, port=connection.port)
            except Exception:  # pragma: no cover - best-effort teardown
                logger.debug("SMB session teardown failed", exc_info=True)

    return await asyncio.to_thread(_list)


async def check_network_access(
    connection: NetworkFileConnection,
    raw_path: str | None = None,
    *,
    source_ip: str | None = None,
    approved_hosts: list[str] | None = None,
) -> dict[str, object]:
    """Verify a connection (and optionally one path) without importing bytes."""

    def _probe() -> dict[str, object]:
        import smbclient

        _register_session(connection, source_ip)
        try:
            if raw_path:
                resolved = resolve_network_path(raw_path, connection, approved_hosts)
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
