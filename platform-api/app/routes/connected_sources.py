"""Unified Connected Sources inventory for the Data Source Builder.

This read-only endpoint merges reusable database connection profiles,
database data sources shared with the caller, SaaS credentials, and tenant
network-file connections into one list without collapsing their distinct
security models.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models.connector_credential import ConnectorCredential
from app.models.database_connection import DatabaseConnection
from app.models.database_data_source import DatabaseDataSource
from app.models.database_data_source_assignment import DatabaseDataSourceAssignment
from app.models.network_file_connection import NetworkFileConnection
from app.models.user import User

router = APIRouter(prefix="/connected-sources", tags=["connected-sources"])


_LABELS: dict[str, str] = {
    "postgresql": "PostgreSQL",
    "mysql": "MySQL",
    "sqlserver": "SQL Server",
    "oracle": "Oracle",
    "snowflake": "Snowflake",
    "databricks": "Databricks",
    "salesforce": "Salesforce",
    "hubspot": "HubSpot",
    "quickbooks": "QuickBooks",
    "servicenow": "ServiceNow",
}


def _connector_label(key: str | None) -> str:
    return _LABELS.get(key or "", key or "") or "Unknown"


def _can_manage(context: RequestContext, owner_id: int | None) -> bool:
    if owner_id is not None and owner_id == context.user_id:
        return True
    return context.role in {
        Role.ADMIN,
        Role.DB_ADMIN,
        Role.TENANT_ADMIN,
        Role.ROOT_ADMIN,
    }


def _can_create_source(context: RequestContext, enabled: bool) -> bool:
    return enabled and context.role in {
        Role.EDITOR,
        Role.ADMIN,
        Role.DB_ADMIN,
        Role.TENANT_ADMIN,
        Role.ROOT_ADMIN,
    }


@router.get("")
async def list_connected_sources(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> dict:
    """Return a unified Connected Sources inventory.

    Items are deliberately lightweight: no credentials, no query strings, and no
    full network paths are included.  Each item carries the actions the caller
    is allowed to perform on it.
    """
    items: list[dict] = []

    # Owned database connection profiles.
    db_connections = list(
        await session.scalars(
            select(DatabaseConnection).where(
                DatabaseConnection.tenant_id == context.tenant_id,
                DatabaseConnection.created_by == context.user_id,
            )
        )
    )
    for conn in db_connections:
        can_manage = _can_manage(context, conn.created_by)
        can_create = _can_create_source(context, True)
        actions = []
        if can_create:
            actions.append("create_data_source")
        if can_manage:
            actions.extend(["edit", "delete"])
        actions.append("test")
        status = "connected" if conn.last_tested_at else "configured"
        items.append({
            "id": f"database:{conn.id}",
            "kind": "database",
            "source": "owned",
            "friendlyName": conn.name,
            "connectorType": conn.db_type,
            "displayLocation": conn.host,
            "status": status,
            "enabled": True,
            "allowedActions": actions,
            "connectionId": conn.id,
            "databaseName": conn.database_name,
            "port": conn.port,
        })

    # Database data sources assigned to the caller by an admin / DB admin.
    assignments = list(
        await session.scalars(
            select(DatabaseDataSourceAssignment).where(
                DatabaseDataSourceAssignment.tenant_id == context.tenant_id,
                DatabaseDataSourceAssignment.assigned_user_id == context.user_id,
                DatabaseDataSourceAssignment.is_active.is_(True),
            )
        )
    )
    source_ids = {a.database_data_source_id for a in assignments}
    assigner_ids = {a.assigned_by for a in assignments if a.assigned_by}
    sources = {}
    assigner_map: dict[int, str] = {}
    if source_ids:
        source_rows = list(
            await session.scalars(
                select(DatabaseDataSource).where(
                    DatabaseDataSource.id.in_(source_ids)
                )
            )
        )
        sources = {s.id: s for s in source_rows}
    if assigner_ids:
        users = list(
            await session.scalars(
                select(User).where(User.id.in_(assigner_ids))
            )
        )
        assigner_map = {
            u.id: u.display_name or u.email for u in users
        }
    for a in assignments:
        source = sources.get(a.database_data_source_id)
        if source is None or source.archived:
            continue
        items.append({
            "id": f"database:{source.id}",
            "kind": "database",
            "source": "assigned",
            "friendlyName": a.friendly_name or source.display_name,
            "connectorType": source.db_type,
            "displayLocation": source.host,
            "status": "connected" if source.status == "active" else source.status,
            "enabled": True,
            "allowedActions": ["create_data_source"],
            "dataSourceId": source.id,
            "assignedBy": assigner_map.get(a.assigned_by) if a.assigned_by else None,
            "readOnly": a.read_only,
        })

    # SaaS credentials visible in the tenant.
    saas_creds = list(
        await session.scalars(
            select(ConnectorCredential).where(
                ConnectorCredential.tenant_id == context.tenant_id
            )
        )
    )
    for cred in saas_creds:
        can_manage = _can_manage(context, cred.created_by)
        can_create = _can_create_source(context, True)
        actions = []
        if can_create:
            actions.append("create_data_source")
        if can_manage:
            actions.extend(["edit", "delete"])
        actions.append("test")
        status = "connected" if cred.last_tested_at else "configured"
        items.append({
            "id": f"saas:{cred.id}",
            "kind": "saas",
            "source": "owned" if cred.created_by == context.user_id else "shared",
            "friendlyName": cred.display_name,
            "connectorType": cred.connector_type,
            "displayLocation": _connector_label(cred.connector_type),
            "status": status,
            "enabled": True,
            "allowedActions": actions,
            "credentialId": cred.id,
        })

    # Tenant network-file connections.
    network_connections = list(
        await session.scalars(
            select(NetworkFileConnection).where(
                NetworkFileConnection.tenant_id == context.tenant_id,
                NetworkFileConnection.archived.is_(False),
            )
        )
    )
    for network_conn in network_connections:
        can_manage = _can_manage(context, network_conn.created_by)
        can_create = _can_create_source(context, network_conn.enabled)
        actions = []
        if can_create:
            actions.append("browse")
        if can_manage:
            actions.extend(["edit", "delete"])
        actions.append("test")
        status = network_conn.last_test_status or (
            "configured" if network_conn.last_tested_at is None else "ok"
        )
        items.append({
            "id": f"network:{network_conn.id}",
            "kind": "network_repository",
            "source": "owned" if network_conn.created_by == context.user_id else "shared",
            "friendlyName": network_conn.name,
            "connectorType": network_conn.protocol or "smb",
            "displayLocation": network_conn.label,
            "status": status,
            "enabled": network_conn.enabled,
            "allowedActions": actions,
            "connectionId": network_conn.id,
        })

    return {"items": items}
