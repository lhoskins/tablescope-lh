# Operational Insight templates: deployment runbook

This change is based on the current PR #187 head and adds reusable dashboard groups, template-to-datasource bindings, versioned batch queries, cached hydration, and Operational Insight chart defaults.

## Release sequence

```bash
git fetch origin
git checkout codex/operational-template-bindings
docker compose build platform-api web-ui
docker compose run --rm platform-api-migrate
docker compose run --rm platform-api-migrate alembic current
docker compose up -d platform-api platform-api-worker web-ui
docker compose ps platform-api platform-api-worker web-ui
docker compose logs --tail=100 platform-api platform-api-worker web-ui
```

Expected Alembic head: `b7e2d8a4c901`.

## Tenant conversion

Dry-run and retain the JSON result:

```bash
docker compose exec platform-api python scripts/migrate_operational_insight_dashboards.py --tenant simplicit --tenant scaitis
```

After review, apply and repeat the dry-run to confirm zero remaining changes:

```bash
docker compose exec platform-api python scripts/migrate_operational_insight_dashboards.py --tenant simplicit --tenant scaitis --apply
```

Numeric tenant IDs are supported. To repair and fully convert tenant 33,
including legacy duplicate Custom dashboard groups, run the dry-run first:

```bash
docker compose exec platform-api python scripts/migrate_operational_insight_dashboards.py --tenant-id 33
```

After reviewing the dashboard IDs and group assignments, apply it and repeat
the dry-run. The final dry-run must report `changed: 0` and
`duplicateGroupsRemoved: 0`.

```bash
docker compose exec platform-api python scripts/migrate_operational_insight_dashboards.py --tenant-id 33 --apply
docker compose exec platform-api python scripts/migrate_operational_insight_dashboards.py --tenant-id 33
```

## Acceptance checks

- Dashboard groups are collapsed initially and can be created or renamed.
- KPI and insight dashboards expose dimension and 30-day, 60-day, 90-day, 6-month, 1-year and 2-year filters.
- KPI cards, charts, Operational Brief and Improvement Opportunities can be reordered/resized and persist after reload.
- Template creation requires datasource mapping and explicit approval; users do not write SQL.
- Approved bindings create versioned saved batch queries and a second hydration request is served from cache.
- Custom dashboards in `simplicit` and `scaitis` use Operational Insight styling without changing query wiring.
- Existing drilldown drawers and ITSM pipelines still work.
- New blank, AI-generated and save-to-dashboard flows use the complete Operational Insight renderer and reuse the existing Custom dashboards group.
- Incident KPI cards and charts share one grid; a chart can be dropped above or between KPI cards and the remaining items reflow.

## Rollback

Prefer restoring the previous application SHA while leaving additive tables in place. Only when no new template data exists:

```bash
docker compose run --rm platform-api-migrate alembic downgrade aaa3f7c03dc3
```

Tenant conversion stores the previous presentation in `config.operationalInsightMigration.previousPresentation`; restore targeted dashboard configs from the backup if needed.
