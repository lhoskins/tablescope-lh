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


async def test_warm_expands_to_every_real_site_for_insight_presets(monkeypatch):
    """warm_itsm_dashboards_for_project must warm each of the project's
    real sites for the insight presets (not just the "all sites" bucket),
    since a user picking a specific site was previously always a cache
    miss. Non-insight presets and an explicitly-pinned site_code must NOT
    trigger the per-site expansion."""
    from app.services.itsm_metrics.cache import _get_entry, clear_dashboard_cache, make_cache_key

    clear_dashboard_cache()
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
            data_quality={
                "latestCompleteMonth": "Jul 2026",
                "missingMetrics": [],
                "warnings": [],
                "availableSites": (
                    [{"code": "US01", "name": "United States"}, {"code": "PLZ", "name": "Plzen"}]
                    if site_code is None
                    else []
                ),
            },
        )

    monkeypatch.setattr(engine, "compute_dashboard", fake_compute_dashboard)

    await engine.warm_itsm_dashboards_for_project(
        session=None,
        project_id=1,
        tenant_id=1,
        user_id=1,
        presets=["incident_insights", "incident"],
    )

    # incident_insights: warmed "all" plus both real sites.
    incident_insights_sites = {site for key, site in warmed_sites if key == "incident_insights"}
    assert incident_insights_sites == {None, "US01", "PLZ"}
    # incident (not an insight preset): only the "all sites" bucket, unchanged.
    incident_sites = {site for key, site in warmed_sites if key == "incident"}
    assert incident_sites == {None}

    cached = _get_entry(
        make_cache_key(
            tenant_id=1, project_id=1, dashboard_key="incident_insights",
            site_code="PLZ", as_of=None, duration_unit="hours", period_key="1_year", dimension="site",
        )
    )
    assert cached is not None


async def test_warm_does_not_expand_sites_when_site_code_already_pinned(monkeypatch):
    """When the caller already scoped the warm to one site (e.g. a live
    request warming its own cache entry), the per-site expansion must not
    fire -- it only applies to the top-level "warm everything" call."""
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
