"""Customer-specific folder management.

Async port of `redash/services/customer_folders.py`. Manages the on-disk
folder layout used by the Teiid VDBs:

    <CUSTOMER_BASE_PATH>/<tenant_slug>/
        ├── shared/
        │   ├── data/
        │   └── uploads/
        └── users/
            └── <user_external_id>/
                ├── data/
                └── uploads/

This runs alongside WildFly so it has direct disk access to the
`/opt/wildfly/teiidfiles` mount.
"""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

from app.config import get_settings

logger = logging.getLogger(__name__)


class CustomerFolderError(Exception):
    """Raised when a folder operation fails."""


class UnsafeFilenameError(CustomerFolderError):
    """Raised when a caller-supplied filename would escape its sandbox."""


def _safe_filename(filename: str) -> str:
    """Return ``filename`` stripped of any path components.

    Rejects values that resolve to empty / dot / dotdot, contain path
    separators, or NUL bytes. Both POSIX and Windows separators are
    handled defensively because uploads may originate from either kind
    of client.
    """
    if not filename:
        raise UnsafeFilenameError("Filename is required")
    if "\x00" in filename:
        raise UnsafeFilenameError("Filename contains NUL byte")
    # Strip directory components from both POSIX and Windows-style paths.
    name = PureWindowsPath(PurePosixPath(filename).name).name
    if name in ("", ".", ".."):
        raise UnsafeFilenameError(f"Invalid filename: {filename!r}")
    if "/" in name or "\\" in name:
        # Belt-and-suspenders — should be impossible after the .name calls.
        raise UnsafeFilenameError(f"Filename must not contain separators: {filename!r}")
    return name


def _resolve_within(parent: Path, filename: str) -> Path:
    """Join ``filename`` onto ``parent`` and guarantee the result stays inside."""
    safe = _safe_filename(filename)
    target = (parent / safe).resolve(strict=False)
    parent_resolved = parent.resolve(strict=False)
    if not target.is_relative_to(parent_resolved):
        raise UnsafeFilenameError(
            f"Filename {filename!r} would escape {parent_resolved}"
        )
    return target


@dataclass(slots=True)
class TenantFolderLayout:
    base: Path
    shared_data: Path
    shared_uploads: Path
    users_root: Path

    def user_data(self, user_external_id: str) -> Path:
        return self.users_root / user_external_id / "data"

    def user_uploads(self, user_external_id: str) -> Path:
        return self.users_root / user_external_id / "uploads"


class CustomerFolderService:
    """Manages tenant + user folders on disk."""

    def __init__(self, *, base_path: str | None = None) -> None:
        settings = get_settings()
        self._base_path = Path(base_path or settings.customer_base_path)

    def layout_for_tenant(self, tenant_slug: str) -> TenantFolderLayout:
        base = self._base_path / tenant_slug
        return TenantFolderLayout(
            base=base,
            shared_data=base / "shared" / "data",
            shared_uploads=base / "shared" / "uploads",
            users_root=base / "users",
        )

    def ensure_tenant_folders(self, tenant_slug: str) -> TenantFolderLayout:
        layout = self.layout_for_tenant(tenant_slug)
        try:
            for path in (
                layout.base,
                layout.shared_data,
                layout.shared_uploads,
                layout.users_root,
            ):
                path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise CustomerFolderError(f"Failed to create tenant folders: {exc}") from exc
        return layout

    def ensure_user_folders(self, tenant_slug: str, user_external_id: str) -> TenantFolderLayout:
        layout = self.ensure_tenant_folders(tenant_slug)
        try:
            layout.user_data(user_external_id).mkdir(parents=True, exist_ok=True)
            layout.user_uploads(user_external_id).mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise CustomerFolderError(f"Failed to create user folders: {exc}") from exc
        return layout

    def copy_user_data_to_shared(
        self,
        *,
        tenant_slug: str,
        user_external_id: str,
        filenames: list[str],
    ) -> list[Path]:
        """Copy specified user-owned data files into the shared folder.

        Mirrors the project-sharing flow: when a project is shared, its
        data files are physically duplicated into the tenant's shared
        folder so Teiid can serve them from the shared VDB.

        Each entry in ``filenames`` is sanitized to its basename — it must
        already exist directly inside the user's data folder. Path-traversal
        attempts (``../etc/passwd``, absolute paths, etc.) raise
        ``UnsafeFilenameError``.
        """
        layout = self.ensure_tenant_folders(tenant_slug)
        user_data = layout.user_data(user_external_id)
        copied: list[Path] = []
        for filename in filenames:
            src = _resolve_within(user_data, filename)
            dst = _resolve_within(layout.shared_data, filename)
            if not src.exists():
                raise CustomerFolderError(f"Missing source file: {src}")
            try:
                shutil.copy2(src, dst)
            except OSError as exc:
                raise CustomerFolderError(f"Failed to copy {src} -> {dst}: {exc}") from exc
            copied.append(dst)
        return copied

    def delete_user_folder(self, tenant_slug: str, user_external_id: str) -> None:
        layout = self.layout_for_tenant(tenant_slug)
        user_root = layout.users_root / user_external_id
        if user_root.exists():
            try:
                shutil.rmtree(user_root)
            except OSError as exc:
                raise CustomerFolderError(f"Failed to delete user folder: {exc}") from exc

    def list_user_files(self, tenant_slug: str, user_external_id: str) -> list[str]:
        layout = self.layout_for_tenant(tenant_slug)
        user_data = layout.user_data(user_external_id)
        if not user_data.exists():
            return []
        return sorted(p.name for p in user_data.iterdir() if p.is_file())

    def write_upload(
        self,
        *,
        tenant_slug: str,
        user_external_id: str,
        filename: str,
        content: bytes,
    ) -> Path:
        """Write ``content`` into the user's uploads folder.

        ``filename`` is sanitized to its basename and the resolved target
        is verified to live inside the user's uploads directory. Anything
        else raises :class:`UnsafeFilenameError`.
        """
        layout = self.ensure_user_folders(tenant_slug, user_external_id)
        uploads = layout.user_uploads(user_external_id)
        target = _resolve_within(uploads, filename)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with target.open("wb") as fh:
                fh.write(content)
                fh.flush()
                os.fsync(fh.fileno())
        except OSError as exc:
            raise CustomerFolderError(f"Failed to write {target}: {exc}") from exc
        return target
