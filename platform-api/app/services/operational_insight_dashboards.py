"""Canonical creation and conversion helpers for Operational Insight dashboards."""

from __future__ import annotations

import re
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dashboard import Dashboard
from app.models.dashboard_template import DashboardGroup, DashboardTemplateBinding

CUSTOM_GROUP_NAME = "Custom dashboards"
CUSTOM_GROUP_SLUG = "custom-dashboards"
OPERATIONAL_PRESENTATION = "operational_insight"


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "dashboard"


def is_custom_group(group: DashboardGroup) -> bool:
    return group.slug == CUSTOM_GROUP_SLUG or (
        group.slug.startswith(f"{CUSTOM_GROUP_SLUG}-")
        and group.name.strip().lower() == CUSTOM_GROUP_NAME.lower()
    )


async def get_or_create_custom_group(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: int,
) -> DashboardGroup:
    """Return the project's single canonical custom group without committing."""
    groups = list(
        await session.scalars(
            select(DashboardGroup)
            .where(
                DashboardGroup.tenant_id == tenant_id,
                DashboardGroup.project_id == project_id,
            )
            .order_by(DashboardGroup.position, DashboardGroup.id)
        )
    )
    exact = next((group for group in groups if group.slug == CUSTOM_GROUP_SLUG), None)
    existing = exact or next((group for group in groups if is_custom_group(group)), None)
    if existing is not None:
        return existing

    position = len(groups)
    group = DashboardGroup(
        tenant_id=tenant_id,
        project_id=project_id,
        name=CUSTOM_GROUP_NAME,
        slug=CUSTOM_GROUP_SLUG,
        icon="activity",
        template_id=None,
        position=position,
        collapsed_default=True,
    )
    session.add(group)
    await session.flush()
    return group


async def resolve_dashboard_group(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: int,
    requested_group_id: int | None,
) -> DashboardGroup:
    if requested_group_id is not None:
        requested = await session.get(DashboardGroup, requested_group_id)
        if (
            requested is not None
            and requested.tenant_id == tenant_id
            and requested.project_id == project_id
        ):
            return requested
    return await get_or_create_custom_group(
        session, tenant_id=tenant_id, project_id=project_id
    )


def operational_insight_config(
    config: dict | None,
    *,
    group: DashboardGroup,
    dashboard_name: str,
) -> dict:
    """Stamp the complete ServiceNow-style contract while preserving data wiring."""
    result = dict(config or {})
    widgets: list[dict] = []
    for widget in result.get("widgets") or []:
        next_widget = dict(widget)
        options = dict(next_widget.get("visualizationOptions") or {})
        options["colorScheme"] = OPERATIONAL_PRESENTATION
        next_widget["visualizationOptions"] = options
        widgets.append(next_widget)

    metadata = dict(result.get("dashboardTemplate") or {})
    parameters = dict(metadata.get("parameters") or {})
    parameters.setdefault("dimensionLabel", "Dimension")
    parameters.setdefault("dimensionField", "dimension")
    parameters.setdefault("valueSource", "manual")
    parameters.setdefault("manualValues", [])
    parameters.setdefault("defaultPeriod", "30_days")
    metadata.update(
        {
            "schemaVersion": 1,
            "presentation": OPERATIONAL_PRESENTATION,
            "templateId": metadata.get("templateId") or "custom",
            "templateName": group.name,
            "groupId": f"group:{group.id}",
            "groupName": group.name,
            "groupIcon": group.icon,
            "dashboardKey": metadata.get("dashboardKey")
            or f"custom-{_slug(dashboard_name)}-{uuid4().hex[:8]}",
            "dashboardIcon": metadata.get("dashboardIcon") or group.icon,
            "parameters": parameters,
            "dashboardGroupId": group.id,
        }
    )
    result.update(
        {
            "widgets": widgets,
            "globalFilters": result.get("globalFilters")
            or result.get("filters")
            or [],
            "layout": "operational_grid",
            "presentation": OPERATIONAL_PRESENTATION,
            "dashboardGroupId": group.id,
            "dashboardTemplate": metadata,
        }
    )
    return result


async def consolidate_custom_groups(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: int,
) -> tuple[DashboardGroup, int]:
    """Move legacy duplicate custom groups into one canonical group."""
    canonical = await get_or_create_custom_group(
        session, tenant_id=tenant_id, project_id=project_id
    )
    groups = list(
        await session.scalars(
            select(DashboardGroup).where(
                DashboardGroup.tenant_id == tenant_id,
                DashboardGroup.project_id == project_id,
            )
        )
    )
    duplicates = [
        group for group in groups if group.id != canonical.id and is_custom_group(group)
    ]
    if not duplicates:
        return canonical, 0

    duplicate_ids = {group.id for group in duplicates}
    dashboards = list(
        await session.scalars(
            select(Dashboard).where(
                Dashboard.tenant_id == tenant_id,
                Dashboard.project_id == project_id,
            )
        )
    )
    for dashboard in dashboards:
        config = dict(dashboard.config or {})
        if config.get("dashboardGroupId") in duplicate_ids:
            config["dashboardGroupId"] = canonical.id
            metadata = dict(config.get("dashboardTemplate") or {})
            metadata.update(
                {
                    "groupId": f"group:{canonical.id}",
                    "groupName": canonical.name,
                    "groupIcon": canonical.icon,
                    "dashboardGroupId": canonical.id,
                }
            )
            config["dashboardTemplate"] = metadata
            dashboard.config = config

    bindings = list(
        await session.scalars(
            select(DashboardTemplateBinding).where(
                DashboardTemplateBinding.tenant_id == tenant_id,
                DashboardTemplateBinding.project_id == project_id,
                DashboardTemplateBinding.dashboard_group_id.in_(duplicate_ids),
            )
        )
    )
    for binding in bindings:
        binding.dashboard_group_id = canonical.id
    for group in duplicates:
        await session.delete(group)
    return canonical, len(duplicates)
