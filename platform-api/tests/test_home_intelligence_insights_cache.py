"""Regression tests for TS-002: per-project caching of /ai/home/insights."""

from __future__ import annotations

import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.auth.jwt import create_access_token


@pytest_asyncio.fixture(autouse=True)
def _mock_supabase(monkeypatch):
    import app.routes.tenants_users as tenants_module
    from app.services.supabase_auth_service import SupabaseAuthService, SupabaseUser

    class _FakeSupabase(SupabaseAuthService):
        def __init__(self) -> None:
            pass

        async def create_or_invite_user(
            self, email, *, first_name=None, last_name=None, redirect_to=None
        ) -> SupabaseUser:
            return SupabaseUser(
                id=f"supa-{email}", email=email, created=True, action_link="x"
            )

    class _FakeEmail:
        async def send_transactional_email(self, *, to, template, variables, subject=None, reply_to=None) -> bool:
            return True

    monkeypatch.setattr(tenants_module, "SupabaseAuthService", _FakeSupabase)
    monkeypatch.setattr(tenants_module, "EmailService", _FakeEmail)


def _editor_headers(tenant_id: int, user_id: int) -> dict:
    return {"Authorization": f"Bearer {create_access_token(sub='u', tenant_id=tenant_id, user_id=user_id, role='editor')}"}


async def _setup(client, service_headers):
    r = await client.post(
        "/api/tenants",
        json={"slug": "insights-cache-tenant", "name": "Insights Cache Tenant"},
        headers=service_headers,
    )
    assert r.status_code == 201
    tenant = r.json()
    r = await client.post(
        f"/api/tenants/{tenant['id']}/users",
        json={
            "email": "insights-cache@test.com",
            "display_name": "Insights Cache User",
            "role": "editor",
            "external_id": "ext-insights-cache",
        },
        headers=service_headers,
    )
    assert r.status_code == 201
    user = r.json()
    return tenant["id"], user["id"]


@pytest_asyncio.fixture
async def project(client, service_headers):
    tenant_id, user_id = await _setup(client, service_headers)
    headers = _editor_headers(tenant_id, user_id)
    r = await client.post(
        "/api/projects",
        json={"name": "Cache Project", "description": "x", "is_shared": False},
        headers=headers,
    )
    assert r.status_code == 201
    return r.json()["id"], headers


async def test_home_insights_caches_result(client, db_engine, service_headers, project, monkeypatch):
    project_id, headers = project

    import app.routes.home_intelligence_suggestions as hir
    monkeypatch.setattr(
        hir, "SessionLocal", async_sessionmaker(db_engine, expire_on_commit=False)
    )

    calls: list[int] = []

    async def spy_run_for_project(
        session, context, project, prompt_types, *, write_audit, granularity, **kwargs
    ):
        calls.append(project.id)
        return [{"title": "Cached insight", "insightType": "risk_test", "severity": "warning"}]

    monkeypatch.setattr(hir, "_run_for_project", spy_run_for_project)

    r = await client.post(
        "/api/ai/home/insights",
        json={"project_id": project_id},
        headers=headers,
    )
    assert r.status_code == 200
    assert len(calls) == 1
    assert r.json()["projects"][0]["insights"][0]["title"] == "Cached insight"

    r = await client.post(
        "/api/ai/home/insights",
        json={"project_id": project_id},
        headers=headers,
    )
    assert r.status_code == 200
    assert len(calls) == 1
    assert r.json()["projects"][0]["insights"][0]["title"] == "Cached insight"


async def test_home_insights_refresh_bypasses_cache(client, db_engine, service_headers, project, monkeypatch):
    project_id, headers = project

    import app.routes.home_intelligence_suggestions as hir
    monkeypatch.setattr(
        hir, "SessionLocal", async_sessionmaker(db_engine, expire_on_commit=False)
    )

    calls: list[int] = []

    async def spy_run_for_project(
        session, context, project, prompt_types, *, write_audit, granularity, **kwargs
    ):
        calls.append(project.id)
        return [{"title": f"Insight {len(calls)}", "insightType": "risk_test", "severity": "warning"}]

    monkeypatch.setattr(hir, "_run_for_project", spy_run_for_project)

    r = await client.post(
        "/api/ai/home/insights",
        json={"project_id": project_id},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["projects"][0]["insights"][0]["title"] == "Insight 1"

    r = await client.post(
        "/api/ai/home/insights",
        json={"project_id": project_id},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["projects"][0]["insights"][0]["title"] == "Insight 1"
    assert len(calls) == 1

    r = await client.post(
        "/api/ai/home/insights?refresh=true",
        json={"project_id": project_id},
        headers=headers,
    )
    assert r.status_code == 200
    assert len(calls) == 2
    assert r.json()["projects"][0]["insights"][0]["title"] == "Insight 2"


async def test_home_insights_stale_fallback_on_error(client, db_engine, service_headers, project, monkeypatch):
    project_id, headers = project

    import app.routes.home_intelligence_suggestions as hir
    monkeypatch.setattr(
        hir, "SessionLocal", async_sessionmaker(db_engine, expire_on_commit=False)
    )

    calls: int = 0

    async def spy_run_for_project(
        session, context, project, prompt_types, *, write_audit, granularity, **kwargs
    ):
        nonlocal calls
        calls += 1
        if calls == 1:
            return [{"title": "Stale insight", "insightType": "risk_test", "severity": "warning"}]
        raise RuntimeError("AI unavailable")

    monkeypatch.setattr(hir, "_run_for_project", spy_run_for_project)

    r = await client.post(
        "/api/ai/home/insights",
        json={"project_id": project_id},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["projects"][0]["insights"][0]["title"] == "Stale insight"
    assert calls == 1

    r = await client.post(
        "/api/ai/home/insights?refresh=true",
        json={"project_id": project_id},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["projects"][0]["insights"][0]["title"] == "Stale insight"
    assert calls == 2


async def test_time_series_resolves_a_project_insight_card(
    client, db_engine, service_headers, project, monkeypatch
):
    """A card served by /ai/home/insights (suggestInsights, the Project
    Insight screen's data source) is saved into the "insights" snapshot
    suite. The time-series endpoint's card lookup must find it there --
    it previously only checked an unrelated "project_insight" suite, so
    every Project Insight card's chart View/Interval/Range controls
    silently 404'd and fell back to the card's static baked-in chart."""
    project_id, headers = project

    import app.routes.home_intelligence_suggestions as hir
    monkeypatch.setattr(
        hir, "SessionLocal", async_sessionmaker(db_engine, expire_on_commit=False)
    )

    series = [
        {"label": "2026-01", "value": 10},
        {"label": "2026-02", "value": 20},
        {"label": "2026-03", "value": 15},
        {"label": "2026-04", "value": 25},
    ]

    async def spy_run_for_project(
        session, context, project, prompt_types, *, write_audit, granularity, **kwargs
    ):
        return [
            {
                "insightId": "ins-ts-1",
                "id": "ins-ts-1",
                "title": "Resolution hours trending up",
                "insightType": "trend_resolution",
                "severity": "trend",
                "chart": {"type": "line", "data": {"series": series}},
            }
        ]

    monkeypatch.setattr(hir, "_run_for_project", spy_run_for_project)

    r = await client.post(
        "/api/ai/home/insights",
        json={"project_id": project_id},
        headers=headers,
    )
    assert r.status_code == 200

    r = await client.get(
        "/api/ai/insights/ins-ts-1/time-series",
        params={"project_id": project_id, "interval": "month", "range": "1y"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["insight_id"] == "ins-ts-1"
    assert len(body["points"]) > 0
