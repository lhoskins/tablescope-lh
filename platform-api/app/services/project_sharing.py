"""Project sharing service.

Handles the workflow when a project is shared inside a tenant:

1. Look up (or provision) the project's own SharedVDB -- one per
   ``(tenant_id, project_id)``, not one per tenant (migration 0087).
2. Upload each shared file straight from the owner's private uploads folder
   into that SharedVDB via the Teiid ``/upload`` servlet, the same
   real view-building mechanism already used for private uploads
   (``finalize_tabular.py``) -- this is what actually creates queryable
   views for the shared data, not just a file copy.
3. Mark the project as shared. ``project.owner_id`` is never touched --
   sharing does not transfer ownership.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.config import get_settings
from app.models.project import Project
from app.models.shared_vdb import SharedVDB
from app.services.crypto import encrypt_secret
from app.services.vdb_management import (
    VDBManagementService,
    VDBProvisioningError,
    VDBProvisionResult,
)

logger = logging.getLogger(__name__)


class ProjectSharingError(Exception):
    """Raised when sharing a project fails."""


@dataclass(slots=True)
class ShareProjectResult:
    project_id: int
    shared_vdb_id: str
    copied_files: list[str]


def _safe_upload_filename(filename: str) -> str:
    """Return ``filename`` stripped of any path components.

    Mirrors ``customer_folders._safe_filename``: a caller-supplied name is
    used to build a filesystem path, so it must not carry directory
    components that could escape the owner's uploads folder.
    """
    if not filename:
        raise ProjectSharingError("Filename is required")
    if "\x00" in filename:
        raise ProjectSharingError("Filename contains NUL byte")
    name = PureWindowsPath(PurePosixPath(filename).name).name
    if name in ("", ".", ".."):
        raise ProjectSharingError(f"Invalid filename: {filename!r}")
    return name


class ProjectSharingService:
    """Async, tenant-aware project sharing workflow."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        vdb_service: VDBManagementService | None = None,
    ) -> None:
        self._session = session
        self._vdb = vdb_service or VDBManagementService()

    async def aclose(self) -> None:
        await self._vdb.aclose()

    async def share_project(
        self,
        *,
        context: RequestContext,
        project_id: int,
        filenames: list[str],
    ) -> ShareProjectResult:
        project = await self._session.get(Project, project_id)
        if project is None or project.tenant_id != context.tenant_id:
            raise ProjectSharingError(f"Project {project_id} not found in tenant {context.tenant_id}")

        if project.owner_id != context.user_id:
            raise ProjectSharingError("Only the project owner can share it")

        shared_vdb = await self._session.scalar(
            select(SharedVDB).where(
                SharedVDB.tenant_id == project.tenant_id,
                SharedVDB.project_id == project.id,
            )
        )
        if shared_vdb is None:
            try:
                provision: VDBProvisionResult = await self._vdb.create_shared_vdb(
                    org_id=project.tenant_id, project_id=project.id
                )
            except VDBProvisioningError as exc:
                raise ProjectSharingError(str(exc)) from exc

            shared_vdb = SharedVDB(
                tenant_id=project.tenant_id,
                project_id=project.id,
                vdb_id=provision.vdb_id,
                vdb_username=provision.vdb_username,
                encrypted_password=encrypt_secret(provision.vdb_password),
                vdb_host=provision.vdb_host,
                vdb_port=provision.vdb_port,
                is_active=True,
            )
            self._session.add(shared_vdb)
            await self._session.flush()

        uploads_dir = (
            Path(get_settings().customer_base_path)
            / str(project.tenant_id)
            / str(project.owner_id)
            / "uploads"
        ).resolve(strict=False)

        copied: list[str] = []
        for filename in filenames:
            safe_name = _safe_upload_filename(filename)
            src = (uploads_dir / safe_name).resolve(strict=False)
            if not src.is_relative_to(uploads_dir) or not src.is_file():
                raise ProjectSharingError(f"Missing source file: {filename!r}")

            content = src.read_bytes()
            try:
                await self._vdb.upload_shared_file(
                    org_id=project.tenant_id,
                    project_id=project.id,
                    filename=safe_name,
                    content=content,
                )
            except VDBProvisioningError as exc:
                logger.error(
                    "Shared upload failed: project_id=%s filename=%s: %s",
                    project.id, safe_name, exc,
                )
                raise ProjectSharingError(str(exc)) from exc
            copied.append(safe_name)

        project.is_shared = True
        self._session.add(project)
        await self._session.flush()

        return ShareProjectResult(
            project_id=project.id,
            shared_vdb_id=shared_vdb.vdb_id,
            copied_files=copied,
        )
