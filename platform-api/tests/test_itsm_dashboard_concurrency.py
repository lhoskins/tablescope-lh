"""ITSM dashboard performance: the metrics/charts/site-options phases of
compute_dashboard() must run CONCURRENTLY, not as three sequential
round-trip batches -- and the background warm loop must pre-warm a
project's real sites, not just the "all sites" bucket, since switching to
any other site was otherwise a guaranteed cache miss on every request.

See the ITSM dashboard performance investigation: dashboards were taking
35-180s to load, dominated by an unpushed-down full CSV file scan per
Teiid query (a cost concurrency limits alone don't reduce) combined with
three phases awaited one after another instead of together, and a warm
cache that only ever covered one (site, period) combination per project.

Run from ``platform-api``:
``pytest -q tests/test_itsm_dashboard_concurrency.py``.
"""

from __future__ import annotations

import asyncio
import time

import pytest

import app.services.itsm_metrics.engine as engine

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _patch_teiid(monkeypatch):
    async def fake_resolve_teiid(*args, **kwargs):
        return ("db", "teiid-host", 5432)

    monkeypatch.setattr(engine, "_resolve_teiid", fake_resolve_teiid)


async def test_dashboard_phases_run_concurrently_not_sequentially(monkeypatch):
    """Each of the 3 phases (metrics, charts, site-options) takes ~50ms of
    simulated Teiid latency. Run sequentially that's ~150ms+; run
    concurrently (as compute_dashboard now does) it's ~50-80ms. A
    regression back to sequential awaits would push this well over the
    generous 120ms ceiling asserted below."""
    call_count = 0

    async def fake_run_sql(database, host, port, sql):
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.05)
        if "AS x, COUNT(*) AS y" in sql and "GROUP BY 1, 2" not in sql:
            return [{"x": "2026-07", "y": 3}]
        if "GROUP BY 1, 2" in sql:
            return [{"priority": "P1", "state": "Open", "y": 2}]
        if "code" in sql and "name" in sql:
            return [{"code": "US01", "name": "United States"}]
        return [{"metric_value": 5}]

    monkeypatch.setattr(engine, "_run_sql", fake_run_sql)

    start = time.monotonic()
    result = await engine.compute_dashboard(
        dashboard_key="incident_insights",
        project_id=1,
        session=None,
        tenant_id=1,
        user_id=1,
        site_code=None,
        period_key="1_year",
    )
    elapsed = time.monotonic() - start

    assert result.dashboard == "incident_insights"
    assert len(result.metrics) == 4
    assert call_count > 0
    # Sequential phases would sum to at least ~150ms (metrics + charts +
    # site-options, each ~50ms); concurrent phases overlap to well under
    # that even with scheduling overhead.
    assert elapsed < 0.12, f"phases appear to run sequentially: {elapsed:.3f}s"


async def test_warm_covers_the_kpi_period_picker_but_not_insight_presets(monkeypatch):
    """warm_itsm_dashboards_for_project still makes exactly one call for an
    insight preset: compute_dashboard's snapshot path (see
    insight_snapshot.py) loads every source CSV for a project/dashboard/
    dimension once and derives every Period/Site/Region combination from it
    in-process, so a single warm call at (site=None/"all", default period)
    covers every combination a user can pick for the life of that snapshot.

    A KPI preset has no such snapshot, so its period picker (the only axis
    that actually varies a request, since availableSites is always [] for
    these five) is warmed in full -- one call per _KPI_WARM_PERIODS entry.
    Each of those calls also populates the cache under BOTH the "site" and
    "region" dimension keys from the single computed result, since at
    site="all" the dimension toggle can't change what SQL runs."""
    from app.services.itsm_metrics.cache import _get_entry, clear_dashboard_cache, make_cache_key

    clear_dashboard_cache()
    warmed: list[tuple[str, str | None, str]] = []

    async def fake_compute_dashboard(*, dashboard_key, site_code, period_key, dimension="site", **kwargs):
        warmed.append((dashboard_key, site_code, period_key))
        from app.services.itsm_metrics.models import DashboardResult

        return DashboardResult(
            dashboard=dashboard_key,
            as_of="2026-08-01T00:00:00Z",
            filters={"site": site_code or "all", "dimension": dimension},
            metrics=[],
            charts=[],
            data_quality={"latestCompleteMonth": "Jul 2026", "missingMetrics": [], "warnings": []},
        )

    monkeypatch.setattr(engine, "compute_dashboard", fake_compute_dashboard)

    await engine.warm_itsm_dashboards_for_project(
        session=None,
        project_id=1,
        tenant_id=1,
        user_id=1,
        presets=["incident_insights", "incident"],
    )

    insight_calls = [call for call in warmed if call[0] == "incident_insights"]
    kpi_calls = [call for call in warmed if call[0] == "incident"]
    assert insight_calls == [("incident_insights", None, "1_year")]
    assert kpi_calls == [("incident", None, period) for period in engine._KPI_WARM_PERIODS]

    insight_site_entry = _get_entry(
        make_cache_key(
            tenant_id=1, project_id=1, dashboard_key="incident_insights",
            site_code=None, as_of=None, duration_unit="hours", period_key="1_year", dimension="site",
        )
    )
    assert insight_site_entry is not None
    insight_region_entry = _get_entry(
        make_cache_key(
            tenant_id=1, project_id=1, dashboard_key="incident_insights",
            site_code=None, as_of=None, duration_unit="hours", period_key="1_year", dimension="region",
        )
    )
    assert insight_region_entry is None  # not dual-cached -- the snapshot path covers it already

    for period in engine._KPI_WARM_PERIODS:
        for cache_dimension in ("site", "region"):
            entry = _get_entry(
                make_cache_key(
                    tenant_id=1, project_id=1, dashboard_key="incident",
                    site_code=None, as_of=None, duration_unit="hours",
                    period_key=period, dimension=cache_dimension,
                )
            )
            assert entry is not None, f"missing cache entry for period={period} dimension={cache_dimension}"
            result, _state, _age = entry
            assert result.filters["dimension"] == cache_dimension


async def test_warm_does_not_expand_sites_when_site_code_already_pinned(monkeypatch):
    """A caller that already scoped the warm to one site (e.g. a live
    request warming its own cache entry) gets exactly that one call, same as
    the top-level "warm everything" call -- there is no per-site expansion
    to trigger any more now that the insight snapshot covers every site."""
    warmed_sites: list[tuple[str, str | None]] = []

    async def fake_compute_dashboard(*, dashboard_key, site_code, **kwargs):
        warmed_sites.append((dashboard_key, site_code))
        from app.services.itsm_metrics.models import DashboardResult

        return DashboardResult(
            dashboard=dashboard_key,
            as_of="2026-08-01T00:00:00Z",
            filters={"site": site_code or "all"},
            metrics=[],
            charts=[],
            data_quality={"latestCompleteMonth": "Jul 2026", "missingMetrics": [], "warnings": []},
        )

    monkeypatch.setattr(engine, "compute_dashboard", fake_compute_dashboard)

    await engine.warm_itsm_dashboards_for_project(
        session=None,
        project_id=1,
        tenant_id=1,
        user_id=1,
        presets=["incident_insights"],
        site_code="US01",
    )

    assert warmed_sites == [("incident_insights", "US01")]


def _snapshot_run_sql_stub(calls: list[str]):
    async def fake_run_sql(database, host, port, sql):
        calls.append(sql)
        if "01_incidents_CSV" in sql:
            return [{
                "sys_id": "INC1", "opened_at": "2026-07-05T00:00:00Z", "resolved_at": None,
                "resolution_minutes": None, "major_incident": False, "priority": "P2",
                "state": "Open", "category": "Software",
                "dimension_code": "US01", "dimension_name": "United States",
            }]
        return []

    return fake_run_sql


async def test_insight_dashboard_loads_snapshot_once_and_reuses_it(monkeypatch):
    """compute_dashboard's snapshot path (see insight_snapshot.py) must load
    each source CSV exactly once via _run_sql -- a second call for the SAME
    dashboard/project/dimension with a DIFFERENT period and site must be
    served entirely from the in-process snapshot, issuing no further Teiid
    queries."""
    from app.services.itsm_metrics.insight_snapshot import clear_insight_snapshot_cache

    clear_insight_snapshot_cache()
    calls: list[str] = []
    monkeypatch.setattr(engine, "_run_sql", _snapshot_run_sql_stub(calls))

    first = await engine.compute_dashboard(
        dashboard_key="incident_insights", project_id=1, session=None, tenant_id=1, user_id=1,
        site_code=None, period_key="1_year",
    )
    second = await engine.compute_dashboard(
        dashboard_key="incident_insights", project_id=1, session=None, tenant_id=1, user_id=1,
        site_code="US01", period_key="30_days",
    )

    assert len(calls) == 2  # incidents + slas, loaded exactly once total
    assert first.data_quality["executionMode"] == "snapshot"
    assert second.data_quality["executionMode"] == "snapshot"
    assert [m.metric_key for m in first.metrics] == [
        "open_backlog", "resolution_sla", "median_resolution", "major_incidents",
    ]


async def test_insight_dashboard_force_refresh_reloads_the_snapshot(monkeypatch):
    """The manual Refresh action must invalidate and reload the source
    snapshot, not just the assembled-dashboard response cache."""
    from app.services.itsm_metrics.insight_snapshot import clear_insight_snapshot_cache

    clear_insight_snapshot_cache()
    calls: list[str] = []
    monkeypatch.setattr(engine, "_run_sql", _snapshot_run_sql_stub(calls))

    await engine.compute_dashboard(
        dashboard_key="incident_insights", project_id=1, session=None, tenant_id=1, user_id=1,
        period_key="1_year",
    )
    assert len(calls) == 2

    await engine.compute_dashboard(
        dashboard_key="incident_insights", project_id=1, session=None, tenant_id=1, user_id=1,
        period_key="1_year", force_refresh=True,
    )
    assert len(calls) == 4


async def test_non_insight_dashboard_keeps_the_per_metric_query_path(monkeypatch):
    """The five original KPI presets are unaffected by the snapshot path --
    they keep issuing per-metric Teiid queries and report executionMode
    "query" rather than "snapshot"."""

    async def fake_run_sql(database, host, port, sql):
        return [{"x": "US01", "y": 1, "metric_value": 1, "current_value": 1, "previous_value": 1}]

    monkeypatch.setattr(engine, "_run_sql", fake_run_sql)

    result = await engine.compute_dashboard(
        dashboard_key="incident", project_id=1, session=None, tenant_id=1, user_id=1,
    )
    assert result.data_quality["executionMode"] == "query"
