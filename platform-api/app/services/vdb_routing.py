"""VDB Routing Service.

Modern, async, multi-tenant port of `redash-8.0.0-7/.../services/vdb_routing.py`.
Routes a query to the appropriate VDB (user, shared, or organization) based on
project type, query sharing status, and the authenticated tenant context.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.models.project import Project, ProjectMember
from app.models.shared_vdb import SharedVDB
from app.models.user_vdb import UserVDB

logger = logging.getLogger(__name__)

VdbType = Literal["user", "shared"]


class VDBNotConfiguredError(Exception):
    """No VDB is configured for the user/tenant."""


class VDBInactiveError(Exception):
    """The required VDB exists but is not active."""


class VDBNotFoundError(Exception):
    """The referenced VDB cannot be found."""


@dataclass(slots=True)
class VDBConnectionInfo:
    connection_string: str
    host: str
    port: int
    database: str
    username: str
    password: str
    vdb_type: VdbType
    vdb_id: str


class VDBRoutingService:
    """Async, tenant-aware VDB routing."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_vdb_for_query(
        self,
        *,
        context: RequestContext,
        project_id: int,
        is_shared_override: bool | None = None,
    ) -> tuple[UserVDB | SharedVDB, VdbType]:
        """Return the VDB to use for a query along with its type.

        The decision tree mirrors the original redash service:

        - If `is_shared_override` is provided (e.g. derived from a query row's
          `is_shared` flag), use it.
        - Otherwise, fall back to the project's `is_shared` flag, but
          auto-correct it based on the project's member count when it drifts.
        """
        project = await self._session.get(Project, project_id)
        if project is None:
            raise VDBNotFoundError(f"Project {project_id} not found")
        if project.tenant_id != context.tenant_id:
            raise VDBNotFoundError(f"Project {project_id} not found")

        if is_shared_override is not None:
            is_shared = is_shared_override
        else:
            is_shared = await self._reconcile_is_shared(project)

        logger.info(
            "VDB routing decision: tenant_id=%s project_id=%s is_shared=%s",
            context.tenant_id,
            project_id,
            is_shared,
        )

        if is_shared:
            shared_vdb = await self._session.scalar(
                select(SharedVDB).where(SharedVDB.tenant_id == context.tenant_id)
            )
            if shared_vdb is None:
                raise VDBNotConfiguredError(
                    f"No shared VDB configured for tenant {context.tenant_id}"
                )
            return shared_vdb, "shared"

        user_vdb = await self._session.scalar(
            select(UserVDB).where(
                UserVDB.tenant_id == context.tenant_id,
                UserVDB.user_id == context.user_id,
            )
        )
        if user_vdb is None:
            raise VDBNotConfiguredError(
                f"No user VDB configured for user {context.user_id} "
                f"in tenant {context.tenant_id}"
            )
        return user_vdb, "user"

    async def _reconcile_is_shared(self, project: Project) -> bool:
        """Auto-correct `project.is_shared` from member count, like the
        original redash service."""
        member_count_row = await self._session.execute(
            select(ProjectMember).where(ProjectMember.project_id == project.id)
        )
        member_count = len(list(member_count_row.scalars().all()))
        should_be_shared = member_count > 1
        if project.is_shared != should_be_shared:
            logger.warning(
                "Project %s is_shared drift: stored=%s, members=%s, should_be=%s",
                project.id,
                project.is_shared,
                member_count,
                should_be_shared,
            )
            project.is_shared = should_be_shared
            self._session.add(project)
        return should_be_shared

    async def get_connection_info(
        self,
        *,
        context: RequestContext,
        project_id: int,
        is_shared_override: bool | None = None,
    ) -> VDBConnectionInfo:
        """Return JDBC-equivalent connection info for the chosen VDB."""
        vdb, vdb_type = await self.get_vdb_for_query(
            context=context,
            project_id=project_id,
            is_shared_override=is_shared_override,
        )
        if not vdb.is_active:
            raise VDBInactiveError(
                f"{vdb_type.capitalize()} VDB {vdb.vdb_id} is not active."
            )
        database = f"{vdb.vdb_id}.1"
        return VDBConnectionInfo(
            connection_string=vdb.get_connection_string(),
            host=vdb.vdb_host,
            port=vdb.vdb_port,
            database=database,
            username=vdb.vdb_username,
            password=vdb.get_decrypted_password(),
            vdb_type=vdb_type,
            vdb_id=vdb.vdb_id,
        )
