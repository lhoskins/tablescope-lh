"""Convert tenant dashboards to Operational Insight styling; dry-run by default."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime

from sqlalchemy import select

from app.database import SessionLocal
from app.models.dashboard import Dashboard
from app.models.tenant import Tenant


def _converted_config(config: dict) -> dict:
    result = dict(config or {})
    widgets = []
    for widget in result.get("widgets", []):
        next_widget = dict(widget)
        options = dict(next_widget.get("visualizationOptions") or {})
        options["colorScheme"] = "operational_insight"
        next_widget["visualizationOptions"] = options
        widgets.append(next_widget)
    result.update({
        "presentation": "operational_insight",
        "widgets": widgets,
        "operationalInsightMigration": {
            "version": 1,
            "previousPresentation": result.get("presentation"),
            "migratedAt": datetime.now(UTC).isoformat(),
            "command": "migrate_operational_insight_dashboards",
        },
    })
    return result


async def migrate(slugs: list[str], *, apply: bool) -> dict:
    summary = {"mode": "apply" if apply else "dry-run", "tenants": {}, "changed": 0}
    async with SessionLocal() as session:
        tenants = list(await session.scalars(select(Tenant).where(Tenant.slug.in_(slugs), Tenant.is_active.is_(True))))
        found = {tenant.slug for tenant in tenants}
        summary["missingTenants"] = sorted(set(slugs) - found)
        for tenant in tenants:
            dashboards = list(await session.scalars(select(Dashboard).where(Dashboard.tenant_id == tenant.id)))
            changed = []
            for dashboard in dashboards:
                config, widgets = dashboard.config or {}, (dashboard.config or {}).get("widgets", [])
                already = config.get("presentation") == "operational_insight" and all((widget.get("visualizationOptions") or {}).get("colorScheme") == "operational_insight" for widget in widgets)
                if already:
                    continue
                changed.append({"id": dashboard.id, "name": dashboard.name, "widgets": len(widgets)})
                if apply:
                    dashboard.config = _converted_config(config)
            summary["tenants"][tenant.slug] = {"dashboards": len(dashboards), "changed": changed}
            summary["changed"] += len(changed)
        if apply:
            await session.commit()
        else:
            await session.rollback()
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", action="append", dest="tenants", default=[])
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(migrate(args.tenants or ["simplicit", "scaitis"], apply=args.apply)), indent=2))


if __name__ == "__main__":
    main()
