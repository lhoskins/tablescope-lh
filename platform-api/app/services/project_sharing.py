"""Project sharing service.

Async port of `redash/services/project_sharing.py`. Handles the workflow when
a project is shared inside a tenant:

1. Mark the project as shared.
2. Ensure a SharedVDB exists for the tenant (provision via Teiid servlet).
3. Copy data files from the user folder to the shared folder.
4. Trigger a redeploy of the shared VDB so Teiid picks up the new sources.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.models.project import Project
from app.models.shared_vdb import SharedVDB
from app.models.user import User
from app.services.customer_folders import CustomerFolderError, CustomerFolderService
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


class ProjectSharingService:
    """Async, tenant-aware project sharing workflow."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        folder_service: CustomerFolderService | None = None,
        vdb_service: VDBManagementService | None = None,
    ) -> None:
        self._session = session
        self._folders = folder_service or CustomerFolderService()
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

        owner = await self._session.get(User, project.owner_id) if project.owner_id else None
        owner_external = owner.external_id if owner and owner.external_id else str(project.owner_id)

        from app.models.tenant import Tenant

        tenant = await self._session.get(Tenant, project.tenant_id)
        if tenant is None:
            raise ProjectSharingError(f"Tenant {project.tenant_id} missing")
        tenant_slug = tenant.slug

        shared_vdb = await self._session.scalar(
            select(SharedVDB).where(SharedVDB.tenant_id == project.tenant_id)
        )
        if shared_vdb is None:
            try:
                provision: VDBProvisionResult = await self._vdb.provision_shared_vdb(
                    tenant_external_id=tenant.external_id or tenant.slug
                )
            except VDBProvisioningError as exc:
                raise ProjectSharingError(str(exc)) from exc

            shared_vdb = SharedVDB(
                tenant_id=project.tenant_id,
                vdb_id=provision.vdb_id,
                vdb_username=provision.vdb_username,
                encrypted_password=provision.vdb_password,
                vdb_host=provision.vdb_host,
                vdb_port=provision.vdb_port,
                is_active=True,
            )
            self._session.add(shared_vdb)
            await self._session.flush()

        try:
            copied = self._folders.copy_user_data_to_shared(
                tenant_slug=tenant_slug,
                user_external_id=owner_external,
                filenames=filenames,
            )
        except CustomerFolderError as exc:
            raise ProjectSharingError(str(exc)) from exc

        try:
            await self._vdb.redeploy_vdb(shared_vdb.vdb_id)
        except VDBProvisioningError as exc:
            logger.error("Shared VDB redeploy failed: %s", exc)
            raise ProjectSharingError(str(exc)) from exc

        project.is_shared = True
        self._session.add(project)
        await self._session.flush()

        return ShareProjectResult(
            project_id=project.id,
            shared_vdb_id=shared_vdb.vdb_id,
            copied_files=[p.name for p in copied],
        )
