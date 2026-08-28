"""Installed connector catalog.

Database Connectors lists the connector *types* that are deployed and ready for
end users to build connection profiles against. Installing a new connector type
is a development/deployment task, so this endpoint only reflects what the
backend actually supports (database engines registered in
``database_introspection_service.DB_TYPES`` and SaaS connectors in the connector
registry). Unsupported/placeholder connectors are intentionally not returned.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.config import get_settings
from app.connectors.registry import supported_connectors
from app.services.database_introspection_service import DB_TYPES

router = APIRouter(prefix="/connectors", tags=["connectors"])

# Display metadata for the connectors we ship. Keys must match the backend
# identifiers (DB_TYPES keys / connector registry keys).
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
    "google_drive": "Google Drive",
}

# Order shown in the UI grid.
_ORDER = [
    "postgresql",
    "sqlserver",
    "oracle",
    "mysql",
    "snowflake",
    "databricks",
    "salesforce",
    "hubspot",
    "quickbooks",
    "servicenow",
    "google_drive",
]


@router.get("/installed")
async def list_installed_connectors(
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> dict:
    """Return installed connector types grouped as database vs SaaS."""
    database = set(DB_TYPES.keys())
    saas = set(supported_connectors())

    connectors: list[dict] = []
    for key in _ORDER:
        if key == "google_drive":
            if not get_settings().google_drive_connector_v1_enabled:
                continue
            kind = "saas"
        elif key in database:
            kind = "database"
        elif key in saas:
            kind = "saas"
        else:
            continue
        connectors.append(
            {
                "key": key,
                "name": _LABELS.get(key, key.title()),
                "kind": kind,
                "status": "ready",
            }
        )

    return {"connectors": connectors}
