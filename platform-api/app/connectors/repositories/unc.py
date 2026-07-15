"""UNC/SMB repository connector using the ``smbprotocol`` library."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import mimetypes
import pathlib
import socket
from datetime import UTC, datetime
from typing import Any

import smbclient
import smbclient.path
from smbprotocol.exceptions import SMBAuthenticationError

from app.connectors.repositories._path_utils import (
    effective_root,
    is_path_allowed,
    join_unc,
    normalize_unc_path,
    parse_unc,
    relative_to_root,
    validate_unc_root,
)
from app.connectors.repositories.base import RepositoryConnector, RepositoryConnectorError
from app.connectors.repositories.types import (
    ConnectionCheck,
    ConnectionTestResult,
    RepositoryItem,
    RepositoryPage,
)

logger = logging.getLogger(__name__)


def _safe_message(exc: BaseException) -> str:
    """Return a sanitized, user-facing message from an exception."""
    text = str(exc) or exc.__class__.__name__
    # Never return a full traceback or internal path.
    return text.split("\n")[0][:200]


def _smb_credentials(credentials: dict[str, Any]) -> dict[str, Any]:
    """Build safe keyword arguments for ``smbclient`` from stored credentials."""
    domain = (credentials.get("domain") or "").strip()
    username = (credentials.get("username") or "").strip()
    password = credentials.get("password") or ""
    if not username:
        raise RepositoryConnectorError("Username is required for UNC authentication")
    if domain:
        smb_username = f"{domain}\\{username}"
    else:
        smb_username = username
    return {
        "username": smb_username,
        "password": password,
    }


class UNCRepositoryConnector(RepositoryConnector):
    """Read-only UNC/SMB repository connector.

    Uses ``smbclient`` (from ``smbprotocol``) in a threadpool so the async
    application loop is not blocked by network I/O.
    """

    connector_type = "unc"

    async def validate_config(self, config: dict[str, Any]) -> None:
        root = config.get("rootPath", "")
        validate_unc_root(root)

        allowed_exts = config.get("allowedExtensions") or []
        if not isinstance(allowed_exts, list) or any(
            not isinstance(e, str) for e in allowed_exts
        ):
            raise RepositoryConnectorError("allowedExtensions must be a list of strings")

        for key in ("includePatterns", "excludePatterns"):
            value = config.get(key) or []
            if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
                raise RepositoryConnectorError(f"{key} must be a list of strings")

        max_size = config.get("maxFileSizeBytes")
        if max_size is not None and (not isinstance(max_size, int) or max_size < 0):
            raise RepositoryConnectorError("maxFileSizeBytes must be a non-negative integer")

        if config.get("recursive") not in (None, True, False):
            raise RepositoryConnectorError("recursive must be a boolean")

    async def test_connection(
        self,
        config: dict[str, Any],
        credentials: dict[str, Any],
    ) -> ConnectionTestResult:
        checks: list[ConnectionCheck] = []
        warnings: list[str] = []
        sample_count = 0

        try:
            await self.validate_config(config)
            checks.append(ConnectionCheck("configuration", "passed"))
        except Exception as exc:
            checks.append(ConnectionCheck("configuration", "failed", _safe_message(exc)))
            return ConnectionTestResult(False, checks, warnings=warnings)

        root = effective_root(config)
        server, _, _ = parse_unc(root)
        creds = _smb_credentials(credentials)
        encrypt = bool(config.get("smbEncryption", False))
        signing = bool(config.get("smbSigning", True))

        # DNS resolution
        try:
            await asyncio.to_thread(socket.getaddrinfo, server, None)
            checks.append(ConnectionCheck("dns_resolution", "passed"))
        except Exception as exc:
            checks.append(ConnectionCheck("dns_resolution", "failed", _safe_message(exc)))
            return ConnectionTestResult(False, checks, warnings=warnings)

        # Authentication and SMB session
        try:
            await asyncio.to_thread(
                smbclient.register_session,
                server,
                port=445,
                encrypt=encrypt,
                require_signing=signing,
                connection_timeout=30,
                **creds,
            )
            checks.append(ConnectionCheck("authentication", "passed"))
        except SMBAuthenticationError:
            checks.append(ConnectionCheck("authentication", "failed", "Authentication failed"))
            await self._close_session(server)
            return ConnectionTestResult(False, checks, warnings=warnings)
        except Exception as exc:
            checks.append(ConnectionCheck("authentication", "failed", _safe_message(exc)))
            await self._close_session(server)
            return ConnectionTestResult(False, checks, warnings=warnings)

        try:
            exists = await asyncio.to_thread(smbclient.path.isdir, root)
            if not exists:
                checks.append(
                    ConnectionCheck("root_access", "failed", "Root path does not exist")
                )
                return ConnectionTestResult(False, checks, warnings=warnings)
            checks.append(ConnectionCheck("root_access", "passed"))
        except Exception as exc:
            checks.append(ConnectionCheck("root_access", "failed", _safe_message(exc)))
            return ConnectionTestResult(False, checks, warnings=warnings)

        try:
            entries = await self._scandir_sample(root, max_entries=20)
            sample_count = len(entries)
            checks.append(ConnectionCheck("directory_listing", "passed"))
        except Exception as exc:
            checks.append(ConnectionCheck("directory_listing", "failed", _safe_message(exc)))
            return ConnectionTestResult(False, checks, warnings=warnings)
        finally:
            await self._close_session(server)

        if sample_count == 0 and not config.get("recursive", True):
            warnings.append("The configured root contains no visible items.")

        return ConnectionTestResult(
            True,
            checks,
            sample={"itemsVisible": sample_count},
            warnings=warnings,
        )

    async def list_items(
        self,
        config: dict[str, Any],
        credentials: dict[str, Any],
        checkpoint: dict[str, Any] | None = None,
        page_size: int = 500,
    ) -> RepositoryPage:
        await self.validate_config(config)
        root = effective_root(config)
        server, _, _ = parse_unc(root)
        creds = _smb_credentials(credentials)
        encrypt = bool(config.get("smbEncryption", False))
        signing = bool(config.get("smbSigning", True))

        await asyncio.to_thread(
            smbclient.register_session,
            server,
            port=445,
            encrypt=encrypt,
            require_signing=signing,
            connection_timeout=60,
            **creds,
        )

        try:
            page = await self._list_page(config, root, checkpoint, page_size)
            return page
        finally:
            if not page.has_more:
                await self._close_session(server)

    async def read_item(
        self,
        config: dict[str, Any],
        credentials: dict[str, Any],
        item_ref: str,
        limit_bytes: int | None = None,
    ) -> bytes:
        await self.validate_config(config)
        root = effective_root(config)
        server, _, _ = parse_unc(root)
        # item_ref is treated as a relative path (forward slashes)
        rel = item_ref.lstrip("/")
        full_path = join_unc(root, rel.replace("/", "\\"))
        creds = _smb_credentials(credentials)
        encrypt = bool(config.get("smbEncryption", False))
        signing = bool(config.get("smbSigning", True))

        await asyncio.to_thread(
            smbclient.register_session,
            server,
            port=445,
            encrypt=encrypt,
            require_signing=signing,
            connection_timeout=60,
            **creds,
        )
        try:
            limit = limit_bytes if limit_bytes and limit_bytes > 0 else -1

            def _read() -> bytes:
                with smbclient.open_file(full_path, mode="rb", share_access="r") as fd:
                    return fd.read(limit) if limit > 0 else fd.read()

            return await asyncio.to_thread(_read)
        finally:
            await self._close_session(server)

    # ------------------------------------------------------------------ helpers

    async def _close_session(self, server: str) -> None:
        try:
            await asyncio.to_thread(smbclient.delete_session, server)
        except Exception:
            pass

    def _is_allowed(self, item: RepositoryItem, config: dict[str, Any]) -> bool:
        exts = config.get("allowedExtensions") or []
        max_size = config.get("maxFileSizeBytes")
        if item.item_type == "file":
            if exts and item.extension not in [e.lower().lstrip(".") for e in exts]:
                return False
            if max_size is not None and item.size is not None and item.size > max_size:
                return False
        include = config.get("includePatterns") or []
        exclude = config.get("excludePatterns") or []
        return is_path_allowed(item.relative_path, include, exclude)

    def _build_item(
        self,
        entry: Any,
        root: str,
        current_dir: str,
    ) -> RepositoryItem | None:
        name = entry.name
        if not name or name in (".", ".."):
            return None
        if "\x00" in name or "/" in name or "\\" in name or ".." in name.split("."):
            logger.warning("Skipping suspicious repository entry: %r", name)
            return None

        full_path = join_unc(current_dir, name)
        rel_path = relative_to_root(root, full_path)
        ext = pathlib.Path(name).suffix.lower().lstrip(".")

        is_dir = entry.is_dir()
        is_file = entry.is_file()
        is_symlink = entry.is_symlink()

        if is_symlink:
            item_type = "symlink"
        elif is_dir:
            item_type = "directory"
        elif is_file:
            item_type = "file"
        else:
            item_type = "other"

        size: int | None = None
        created: datetime | None = None
        modified: datetime | None = None
        etag: str | None = None

        if is_file or is_dir:
            try:
                stat = entry.stat(follow_symlinks=False)
                size = stat.st_size if is_file else None
                if stat.st_mtime:
                    modified = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
                if stat.st_ctime:
                    created = datetime.fromtimestamp(stat.st_ctime, tz=UTC)
                if hasattr(stat, "st_ino") and stat.st_ino:
                    etag = str(stat.st_ino)
            except Exception:
                pass

        mime, _ = mimetypes.guess_type(name, strict=False)

        external_id = hashlib.sha256(rel_path.encode("utf-8")).hexdigest()[:40]
        return RepositoryItem(
            external_id=external_id,
            name=name,
            relative_path=rel_path,
            parent_path=str(pathlib.PurePosixPath(rel_path).parent) if "/" in rel_path else "/",
            item_type=item_type,
            size=size,
            created_at=created,
            modified_at=modified,
            etag=etag,
            content_hash=None,
            mime_type=mime,
            extension=ext or None,
            metadata={"full_path": full_path, "file_index": etag},
        )

    async def _list_page(
        self,
        config: dict[str, Any],
        root: str,
        checkpoint: dict[str, Any] | None,
        page_size: int,
    ) -> RepositoryPage:
        cp = checkpoint or {}
        stack: list[str] = [normalize_unc_path(s) for s in (cp.get("stack") or [])]
        current_dir = cp.get("current_dir")
        current_offset = int(cp.get("current_offset") or 0)

        if not current_dir:
            current_dir = root
        elif current_dir not in stack and current_dir != root:
            # The stack may already contain the directory; no-op otherwise.
            pass

        items: list[RepositoryItem] = []
        has_more = True

        while len(items) < page_size:
            entries = await self._scandir_sorted(current_dir)
            start = current_offset
            end = min(len(entries), start + (page_size - len(items)))
            batch = entries[start:end]

            for entry in batch:
                try:
                    item = self._build_item(entry, root, current_dir)
                except Exception:
                    logger.exception("Failed to build item for entry %r", getattr(entry, "name", None))
                    continue
                if item is None:
                    continue
                if item.item_type == "directory" and config.get("recursive", True):
                    stack.append(join_unc(current_dir, item.name))
                if self._is_allowed(item, config):
                    items.append(item)

            current_offset += len(batch)

            if current_offset >= len(entries):
                # Directory exhausted; move to next queued directory.
                current_offset = 0
                if stack:
                    current_dir = stack.pop(0)
                else:
                    has_more = False
                    current_dir = ""
                    break
            else:
                # Page is full.
                break

        new_checkpoint: dict[str, Any] | None = None
        if has_more:
            new_checkpoint = {
                "stack": stack,
                "current_dir": current_dir,
                "current_offset": current_offset,
            }

        return RepositoryPage(
            items=items,
            checkpoint=new_checkpoint,
            has_more=has_more,
        )

    async def _scandir_sorted(self, path: str) -> list[Any]:
        def _scan() -> list[Any]:
            return sorted(smbclient.scandir(path), key=lambda e: e.name)

        return await asyncio.to_thread(_scan)

    async def _scandir_sample(self, path: str, max_entries: int = 20) -> list[Any]:
        def _sample() -> list[Any]:
            out = []
            for entry in smbclient.scandir(path):
                out.append(entry)
                if len(out) >= max_entries:
                    break
            return out

        return await asyncio.to_thread(_sample)
