"""Route tests for the ITSM dashboard preset API."""

from __future__ import annotations

import pytest

from app.auth.jwt import create_access_token
from app.services.itsm_metrics.models import ChartResult, ChartSeries, DashboardResult, MetricValue


def _editor_headers(tenant_id: int = 1, user_id: int = 1) -> dict:
    token = create_access_token(sub="u", tenant_id=tenant_id, user_id=user_id, role="editor")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def _enable_flag(monkeypatch):
    import app.config
    from app.routes import dashboards_crud
    from app.routes import itsm_dashboards as route

    class _Settings:
        servicenow_itsm_dashboards_v2_enabled = True

    async def _allow(*args, **kwargs):
        pass

    monkeypatch.setattr(app.config, "get_settings", lambda: _Settings())
    monkeypatch.setattr(route, "get_settings", lambda: _Settings())
    monkeypatch.setattr(dashboards_crud, "_require_project_access", _allow)
    monkeypatch.setattr(route, "_require_project_access", _allow)


async def test_itsm_dashboards_feature_flag_off(client, service_headers):
    token = create_access_token(sub="u", tenant_id=1, user_id=1, role="editor")
    r = await client.get("/api/projects/1/itsm-dashboards/incident", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 404


async def test_list_itsm_dashboards(client, service_headers, _enable_flag):
    token = create_access_token(sub="u", tenant_id=1, user_id=1, role="editor")
    r = await client.get("/api/projects/1/itsm-dashboards", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert sorted(r.json()) == [
        "availability",
        "incident",
        "incident_insights",
        "problem",
        "productivity",
        "service_request",
        "service_request_insights",
    ]


async def test_get_itsm_dashboard_returns_metric_shape(client, service_headers, _enable_flag, monkeypatch):
    from app.routes import itsm_dashboards
    from app.services.itsm_metrics.cache import clear_dashboard_cache

    clear_dashboard_cache()
    compute_calls = 0

    async def _fake_compute(*args, **kwargs):
        nonlocal compute_calls
        compute_calls += 1
        return DashboardResult(
            dashboard="incident",
            as_of="2026-07-31T23:59:59Z",
            filters={"site": "all"},
            metrics=[
                MetricValue(
                    metric_key="incident_volume",
                    label="Incident volume",
                    value=42.0,
                    display_value="42",
                    period_start="2026-07-01",
                    period_end="2026-07-31",
                    previous_value=38.0,
                    delta=4.0,
                    delta_percent=10.5,
                    direction="up",
                    polarity="neutral",
                    outcome="neutral",
                    comparison_label="↑ 10.5% vs Jun 2026",
                    status="measured",
                    as_of="2026-07-31T23:59:59Z",
                    unit="count",
                    description="Incidents opened during the month.",
                    calculation="Distinct incidents opened in the month.",
                ),
            ],
            charts=[
                ChartResult(
                    chart_key="incident_incident_volume",
                    title="Monthly incident volume",
                    chart_type="bar",
                    x_axis_label="opened_at",
                    y_axis_label="Count",
                    series=[ChartSeries(name="Monthly incident volume", x=["Jul"], y=[42.0])],
                    categories=["Jul"],
                )
            ],
            data_quality={"latestCompleteMonth": "Jul 2026", "missingMetrics": [], "warnings": []},
        )

    monkeypatch.setattr(itsm_dashboards, "compute_dashboard", _fake_compute)

    token = create_access_token(sub="u", tenant_id=1, user_id=1, role="editor")
    r = await client.get("/api/projects/1/itsm-dashboards/incident", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["dashboard"] == "incident"
    assert body["metrics"][0]["metricKey"] == "incident_volume"
    assert body["metrics"][0]["value"] == 42.0
    assert body["metrics"][0]["deltaPercent"] == 10.5
    assert body["metrics"][0]["unit"] == "count"
    assert body["metrics"][0]["calculation"]
    assert body["charts"][0]["chartKey"] == "incident_incident_volume"
    assert body["dataQuality"]["latestCompleteMonth"] == "Jul 2026"
    assert body["dataQuality"]["cacheStatus"] == "miss"

    cached = await client.get("/api/projects/1/itsm-dashboards/incident", headers={"Authorization": f"Bearer {token}"})
    assert cached.status_code == 200
    assert cached.json()["dataQuality"]["cacheStatus"] == "fresh"
    assert compute_calls == 1


async def test_unknown_preset_returns_404(client, service_headers, _enable_flag):
    token = create_access_token(sub="u", tenant_id=1, user_id=1, role="editor")
    r = await client.get("/api/projects/1/itsm-dashboards/not-a-preset", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 404


async def test_period_is_forwarded_and_separates_cached_results(client, service_headers, _enable_flag, monkeypatch):
    from app.routes import itsm_dashboards
    from app.services.itsm_metrics.cache import clear_dashboard_cache

    clear_dashboard_cache()
    seen_periods: list[str] = []

    async def _fake_compute(*args, **kwargs):
        period = kwargs["period_key"]
        seen_periods.append(period)
        return DashboardResult(
            dashboard="incident_insights",
            as_of="2026-07-31T23:59:59Z",
            filters={"period": period},
            metrics=[],
            charts=[],
            data_quality={"latestCompleteMonth": "Jul 2026", "missingMetrics": [], "warnings": []},
        )

    monkeypatch.setattr(itsm_dashboards, "compute_dashboard", _fake_compute)
    token = create_access_token(sub="u", tenant_id=1, user_id=1, role="editor")
    headers = {"Authorization": f"Bearer {token}"}
    first = await client.get("/api/projects/1/itsm-dashboards/incident_insights?period=30_days", headers=headers)
    second = await client.get("/api/projects/1/itsm-dashboards/incident_insights?period=1_year", headers=headers)
    cached = await client.get("/api/projects/1/itsm-dashboards/incident_insights?period=30_days", headers=headers)

    assert first.status_code == second.status_code == cached.status_code == 200
    assert seen_periods == ["30_days", "1_year"]
    assert cached.json()["dataQuality"]["cacheStatus"] == "fresh"
