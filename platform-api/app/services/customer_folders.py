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
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger(__name__)


class CustomerFolderError(Exception):
    """Raised when a folder operation fails."""


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
        """
        layout = self.ensure_tenant_folders(tenant_slug)
        user_data = layout.user_data(user_external_id)
        copied: list[Path] = []
        for filename in filenames:
            src = user_data / filename
            if not src.exists():
                raise CustomerFolderError(f"Missing source file: {src}")
            dst = layout.shared_data / filename
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
        layout = self.ensure_user_folders(tenant_slug, user_external_id)
        target = layout.user_uploads(user_external_id) / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with target.open("wb") as fh:
                fh.write(content)
                fh.flush()
                os.fsync(fh.fileno())
        except OSError as exc:
            raise CustomerFolderError(f"Failed to write {target}: {exc}") from exc
        return target
