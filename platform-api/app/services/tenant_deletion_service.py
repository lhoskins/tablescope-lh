"""Cascading deletion of a tenant's application data and on-disk folders.

This is the control-plane counterpart to provisioning: it removes everything an
application (org) tenant owns so a data-plane tenant can be fully decommissioned.
It deliberately performs explicit, dependency-ordered deletes (rather than
relying on database ``ON DELETE CASCADE``) so the behaviour is identical on
PostgreSQL (production) and SQLite (tests), and so the one ``RESTRICT`` edge
(``saas_object_data_sources`` -> ``connector_credentials``) is honoured.

Removing the isolated Docker container + network is a host/root operation, so it
is emitted as a teardown script for an operator to run (mirroring the
provisioning flow, which renders compose/firewall artifacts rather than applying
them itself). The API stays least-privilege.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from sqlalchemy import Delete, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connector_credential import ConnectorCredential
from app.models.database_connection import DatabaseConnection
from app.models.database_data_source import DatabaseDataSource
from app.models.file_source_meta import FileSourceMeta
from app.models.grid_preference import GridPreference
from app.models.organization_vdb import OrganizationVDB
from app.models.project import Project, ProjectMember
from app.models.query_scope import QueryScope
from app.models.saas_object_data_source import SaasObjectDataSource
from app.models.saved_query import SavedQuery
from app.models.shared_vdb import SharedVDB
from app.models.tenant import Tenant
from app.models.user import User
from app.models.user_vdb import UserVDB
from app.services.customer_folders import CustomerFolderService
from app.services.tenant_layout import TenantLayout
from app.services.vdb_management import VDBManagementService, VDBProvisioningError


async def undeploy_tenant_vdbs(
    session: AsyncSession,
    tenant_id: int,
    vdb_svc: VDBManagementService,
) -> int:
    """Undeploy a tenant's shared + user VDBs from Teiid (best-effort).

    Returns the number of VDBs successfully undeployed. Failures are logged and
    skipped so a missing/already-undeployed VDB never blocks tenant deletion.
    The caller passes a ``VDBManagementService`` already pointed at the tenant's
    resolved Teiid (shared global, or the dedicated container when bound).
    """
    undeployed = 0
    shared = (
        await session.scalars(
            select(SharedVDB).where(SharedVDB.tenant_id == tenant_id)
        )
    ).all()
    for vdb in shared:
        try:
            await vdb_svc.delete_vdb(vdb.vdb_id, org_id=tenant_id, vdb_type="shared")
            undeployed += 1
        except VDBProvisioningError:
            pass

    user_vdbs = (
        await session.scalars(
            select(UserVDB).where(UserVDB.tenant_id == tenant_id)
        )
    ).all()
    for uvdb in user_vdbs:
        try:
            await vdb_svc.delete_vdb(
                uvdb.vdb_id,
                org_id=tenant_id,
                vdb_type="user",
                user_id=uvdb.user_id,
            )
            undeployed += 1
        except VDBProvisioningError:
            pass
    return undeployed


async def purge_app_tenant(session: AsyncSession, tenant_id: int) -> dict[str, int]:
    """Delete all rows owned by application tenant ``tenant_id``.

    Returns a mapping of table name -> number of rows deleted. The ``tenants``
    row itself is deleted last. Order satisfies all foreign keys, including the
    ``saas_object_data_sources`` -> ``connector_credentials`` RESTRICT edge.
    """
    counts: dict[str, int] = {}

    async def _run(name: str, stmt: Delete) -> None:
        res = await session.execute(stmt)
        counts[name] = res.rowcount or 0

    project_ids = list(
        (
            await session.scalars(
                select(Project.id).where(Project.tenant_id == tenant_id)
            )
        ).all()
    )

    # Project-scoped tables that have no direct tenant_id column.
    if project_ids:
        await _run(
            "saved_queries",
            delete(SavedQuery).where(SavedQuery.project_id.in_(project_ids)),
        )
        await _run(
            "project_members",
            delete(ProjectMember).where(ProjectMember.project_id.in_(project_ids)),
        )

    # Tenant-scoped tables, ordered so referencing rows go before the rows they
    # point at (saas -> credentials, everything -> tenant).
    await _run(
        "grid_preferences",
        delete(GridPreference).where(GridPreference.tenant_id == tenant_id),
    )
    await _run(
        "query_scopes", delete(QueryScope).where(QueryScope.tenant_id == tenant_id)
    )
    await _run(
        "saas_object_data_sources",
        delete(SaasObjectDataSource).where(
            SaasObjectDataSource.tenant_id == tenant_id
        ),
    )
    await _run(
        "database_data_sources",
        delete(DatabaseDataSource).where(DatabaseDataSource.tenant_id == tenant_id),
    )
    await _run(
        "connector_credentials",
        delete(ConnectorCredential).where(
            ConnectorCredential.tenant_id == tenant_id
        ),
    )
    await _run(
        "database_connections",
        delete(DatabaseConnection).where(DatabaseConnection.tenant_id == tenant_id),
    )
    await _run(
        "file_source_meta",
        delete(FileSourceMeta).where(FileSourceMeta.tenant_id == tenant_id),
    )
    await _run("user_vdbs", delete(UserVDB).where(UserVDB.tenant_id == tenant_id))
    await _run(
        "shared_vdbs", delete(SharedVDB).where(SharedVDB.tenant_id == tenant_id)
    )
    await _run(
        "organization_vdbs",
        delete(OrganizationVDB).where(OrganizationVDB.tenant_id == tenant_id),
    )
    await _run("projects", delete(Project).where(Project.tenant_id == tenant_id))
    await _run("users", delete(User).where(User.tenant_id == tenant_id))
    await _run("tenants", delete(Tenant).where(Tenant.id == tenant_id))
    return counts


def delete_tenant_folders(tenant_slug: str) -> bool:
    """Remove a tenant's shared/customer folder tree. Returns True if removed."""
    base = CustomerFolderService().layout_for_tenant(tenant_slug).base
    if base.exists():
        shutil.rmtree(base, ignore_errors=True)
        return not base.exists()
    return False


def render_teardown_script(layout: TenantLayout) -> str:
    """Render a host script that removes the tenant's container, network, files.

    These are root/Docker operations the least-privilege API cannot perform, so
    an operator runs the returned script on the EC2 host to finish teardown.
    """
    tid = layout.tenant_id
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -uo pipefail",
            f"# Tear down isolated data plane for tenant '{tid}'.",
            f"COMPOSE='{layout.compose_host_path}'",
            'if [ -f "$COMPOSE" ]; then',
            '  docker compose -f "$COMPOSE" down -v --remove-orphans || true',
            "else",
            f"  docker rm -f {layout.teiid_container_name} || true",
            "fi",
            "# Detach the control plane from the tenant network, then remove it.",
            "for c in tablescope-platform-api-1 tablescope-platform-api-worker-1; do",
            f"  docker network disconnect -f {layout.docker_network_name} \"$c\" 2>/dev/null || true",
            "done",
            f"docker network rm {layout.docker_network_name} 2>/dev/null || true",
            f"rm -rf {layout.tenant_root}",
            f"echo 'Tenant {tid} data plane torn down.'",
            "",
        ]
    )


def tenant_root_exists(layout: TenantLayout) -> bool:
    return Path(layout.tenant_root).exists()
