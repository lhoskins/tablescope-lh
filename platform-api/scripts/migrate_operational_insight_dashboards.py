"""Convert complete tenant dashboards to Operational Insight; dry-run by default."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import defaultdict
from datetime import UTC, datetime

from sqlalchemy import or_, select

from app.database import SessionLocal
from app.models.dashboard import Dashboard
from app.models.dashboard_template import DashboardGroup
from app.models.tenant import Tenant
from app.services.operational_insight_dashboards import (
    OPERATIONAL_PRESENTATION,
    consolidate_custom_groups,
    is_custom_group,
    operational_insight_config,
)


def _is_complete(config: dict) -> bool:
    widgets = config.get("widgets") or []
    metadata = config.get("dashboardTemplate") or {}
    return (
        config.get("presentation") == OPERATIONAL_PRESENTATION
        and config.get("layout") == "operational_grid"
        and isinstance(config.get("dashboardGroupId"), int)
        and metadata.get("presentation") == OPERATIONAL_PRESENTATION
        and metadata.get("groupId")
        and all(
            (widget.get("visualizationOptions") or {}).get("colorScheme")
            == OPERATIONAL_PRESENTATION
            for widget in widgets
        )
    )


async def migrate(
    slugs: list[str],
    *,
    tenant_ids: list[int] | None = None,
    apply: bool,
    all_tenants: bool = False,
) -> dict:
    tenant_ids = tenant_ids or []
    numeric_slugs = [int(value) for value in slugs if value.isdigit()]
    requested_ids = sorted(set([*tenant_ids, *numeric_slugs]))
    requested_slugs = sorted({value for value in slugs if not value.isdigit()})
    summary = {
        "mode": "apply" if apply else "dry-run",
        "requestedTenantIds": requested_ids,
        "requestedTenantSlugs": requested_slugs,
        "tenants": {},
        "changed": 0,
        "duplicateGroupsRemoved": 0,
    }
    async with SessionLocal() as session:
        if all_tenants:
            tenants = list(
                await session.scalars(
                    select(Tenant).where(Tenant.is_active.is_(True))
                )
            )
        else:
            clauses = []
            if requested_ids:
                clauses.append(Tenant.id.in_(requested_ids))
            if requested_slugs:
                clauses.append(Tenant.slug.in_(requested_slugs))
            if not clauses:
                requested_slugs = ["simplicit", "scaitis"]
                clauses.append(Tenant.slug.in_(requested_slugs))
            tenants = list(
                await session.scalars(
                    select(Tenant).where(or_(*clauses), Tenant.is_active.is_(True))
                )
            )
        found_ids = {tenant.id for tenant in tenants}
        found_slugs = {tenant.slug for tenant in tenants}
        summary["missingTenantIds"] = sorted(set(requested_ids) - found_ids)
        summary["missingTenantSlugs"] = sorted(set(requested_slugs) - found_slugs)

        for tenant in tenants:
            dashboards = list(
                await session.scalars(
                    select(Dashboard).where(Dashboard.tenant_id == tenant.id)
                )
            )
            by_project: dict[int, list[Dashboard]] = defaultdict(list)
            for dashboard in dashboards:
                by_project[dashboard.project_id].append(dashboard)
            changed: list[dict] = []
            duplicate_groups = 0

            for project_id, project_dashboards in by_project.items():
                canonical, removed = await consolidate_custom_groups(
                    session, tenant_id=tenant.id, project_id=project_id
                )
                duplicate_groups += removed
                group_rows = list(
                    await session.scalars(
                        select(DashboardGroup).where(
                            DashboardGroup.tenant_id == tenant.id,
                            DashboardGroup.project_id == project_id,
                        )
                    )
                )
                groups = {group.id: group for group in group_rows}

                for dashboard in project_dashboards:
                    config = dict(dashboard.config or {})
                    requested = groups.get(config.get("dashboardGroupId"))
                    group = (
                        requested
                        if requested is not None and not is_custom_group(requested)
                        else canonical
                    )
                    converted = operational_insight_config(
                        config, group=group, dashboard_name=dashboard.name
                    )
                    converted["operationalInsightMigration"] = {
                        "version": 2,
                        "previousPresentation": config.get("presentation"),
                        "previousLayout": config.get("layout"),
                        "migratedAt": datetime.now(UTC).isoformat(),
                        "command": "migrate_operational_insight_dashboards",
                    }
                    if _is_complete(config) and not removed:
                        continue
                    changed.append(
                        {
                            "id": dashboard.id,
                            "projectId": dashboard.project_id,
                            "name": dashboard.name,
                            "widgets": len(config.get("widgets") or []),
                            "groupId": group.id,
                        }
                    )
                    if apply:
                        dashboard.config = converted

            tenant_key = f"{tenant.id}:{tenant.slug}"
            summary["tenants"][tenant_key] = {
                "tenantId": tenant.id,
                "slug": tenant.slug,
                "dashboards": len(dashboards),
                "changed": changed,
                "duplicateGroupsRemoved": duplicate_groups,
            }
            summary["changed"] += len(changed)
            summary["duplicateGroupsRemoved"] += duplicate_groups
        if apply:
            await session.commit()
        else:
            await session.rollback()
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--tenant",
        action="append",
        dest="tenants",
        default=[],
        help="Tenant slug or numeric tenant ID; may be repeated",
    )
    parser.add_argument(
        "--tenant-id",
        action="append",
        type=int,
        dest="tenant_ids",
        default=[],
        help="Explicit numeric tenant ID; may be repeated",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        dest="all_tenants",
        help="Migrate every active tenant",
    )
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            asyncio.run(
                migrate(
                    args.tenants,
                    tenant_ids=args.tenant_ids,
                    apply=args.apply,
                    all_tenants=args.all_tenants,
                )
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
