"""Tests for project business context, goals, metrics, targets, and risks."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.jwt import TokenClaims, create_access_token
from app.schemas.project_context import (
    ProjectGoalCreate,
    ReorderRequest,
)
from app.services.project_context import ProjectContextService

pytestmark = pytest.mark.anyio


def _headers(tenant_id: int, user_id: int, role: str = "editor") -> dict:
    token = create_access_token(
        sub="u", tenant_id=tenant_id, user_id=user_id, role=role
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def _mock_supabase(monkeypatch):
    import app.routes.tenants as tenants_module
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
        async def send_transactional_email(
            self, *, to, template, variables, subject=None, reply_to=None
        ) -> bool:
            return True

    monkeypatch.setattr(tenants_module, "SupabaseAuthService", _FakeSupabase)
    monkeypatch.setattr(tenants_module, "EmailService", _FakeEmail)


async def _setup(client: AsyncClient, service_headers: dict, slug: str = "pc-tenant"):
    r = await client.post(
        "/api/tenants",
        json={"slug": slug, "name": f"{slug} Tenant"},
        headers=service_headers,
    )
    assert r.status_code == 201, r.text
    tenant = r.json()

    r = await client.post(
        f"/api/tenants/{tenant['id']}/users",
        json={
            "email": f"{slug}@test.com",
            "display_name": "PC User",
            "role": "editor",
            "external_id": f"ext-{slug}",
        },
        headers=service_headers,
    )
    assert r.status_code == 201, r.text
    user = r.json()

    headers = _headers(tenant["id"], user["id"], "editor")
    r = await client.post(
        "/api/projects",
        json={"name": f"{slug} Project", "description": "x", "is_shared": False},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    project = r.json()
    return tenant, user, project, headers


async def test_get_context_returns_empty_defaults(client, service_headers):
    _, _, project, headers = await _setup(client, service_headers)
    r = await client.get(f"/api/projects/{project['id']}/context", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["settings"] is None
    assert body["goals"] == []
    assert body["metrics"] == []
    assert body["risks"] == []
    assert body["permissions"]["can_edit"] is True


async def test_update_settings_and_returns_in_context(client, service_headers):
    _, _, project, headers = await _setup(client, service_headers)
    r = await client.put(
        f"/api/projects/{project['id']}/context/settings",
        json={
            "business_function": "Finance",
            "industry": "Manufacturing",
            "purpose": "Test purpose",
            "timezone": "America/Los_Angeles",
            "currency": "USD",
            "reporting_cadence": "monthly",
            "fiscal_year_start_month": 1,
            "ai_context_enabled": True,
            "ai_instructions": "always compare to prior month",
            "interpretation_notes": "notes",
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    settings = r.json()
    assert settings["business_function"] == "Finance"
    assert settings["ai_context_enabled"] is True
    assert settings["version"] == 1

    r = await client.get(f"/api/projects/{project['id']}/context", headers=headers)
    assert r.json()["settings"]["industry"] == "Manufacturing"
    assert r.json()["version"] == 1


async def test_settings_optimistic_concurrency(client, service_headers):
    _, _, project, headers = await _setup(client, service_headers)
    await client.put(
        f"/api/projects/{project['id']}/context/settings",
        json={"purpose": "first"},
        headers=headers,
    )
    r = await client.put(
        f"/api/projects/{project['id']}/context/settings",
        json={"purpose": "stale", "expected_version": 0},
        headers=headers,
    )
    assert r.status_code == 409, r.text
    data = r.json()
    assert data["current_version"] == 1


async def test_goal_lifecycle(client, service_headers):
    _, _, project, headers = await _setup(client, service_headers)
    pid = project["id"]

    r = await client.post(
        f"/api/projects/{pid}/goals",
        json={
            "title": "Reduce churn",
            "priority": "high",
            "status": "in_progress",
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    goal = r.json()
    assert goal["title"] == "Reduce churn"
    assert goal["position"] == 1

    r = await client.get(f"/api/projects/{pid}/goals", headers=headers)
    assert r.status_code == 200, r.text
    assert len(r.json()) == 1

    r = await client.patch(
        f"/api/projects/{pid}/goals/{goal['id']}",
        json={"title": "Reduce churn significantly", "expected_version": goal["version"]},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "Reduce churn significantly"

    r = await client.delete(
        f"/api/projects/{pid}/goals/{goal['id']}", headers=headers
    )
    assert r.status_code == 204

    r = await client.get(f"/api/projects/{pid}/goals", headers=headers)
    assert r.json() == []


async def test_metric_and_target_lifecycle(client, service_headers):
    _, _, project, headers = await _setup(client, service_headers)
    pid = project["id"]

    r = await client.post(
        f"/api/projects/{pid}/metrics",
        json={
            "name": "Revenue",
            "directionality": "higher_is_better",
            "aggregation": "sum",
            "targets": [
                {
                    "target_type": "single_value",
                    "target_value": 100000,
                    "comparison_operator": ">=",
                    "warning_threshold": 90000,
                    "critical_threshold": 80000,
                    "status": "active",
                }
            ],
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    metric = r.json()
    assert metric["name"] == "Revenue"
    assert len(metric["targets"]) == 1
    target = metric["targets"][0]
    assert target["target_value"] == 100000

    r = await client.patch(
        f"/api/projects/{pid}/metrics/{metric['id']}/targets/{target['id']}",
        json={"target_value": 120000, "expected_version": target["version"]},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["target_value"] == 120000

    r = await client.delete(
        f"/api/projects/{pid}/metrics/{metric['id']}/targets/{target['id']}",
        headers=headers,
    )
    assert r.status_code == 204

    r = await client.get(f"/api/projects/{pid}/metrics", headers=headers)
    assert r.json()[0]["targets"] == []


async def test_risk_lifecycle(client, service_headers):
    _, _, project, headers = await _setup(client, service_headers)
    pid = project["id"]

    r = await client.post(
        f"/api/projects/{pid}/risks",
        json={
            "title": "Supplier delay",
            "likelihood": "possible",
            "impact": "major",
            "status": "open",
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    risk = r.json()
    # Server computes severity from likelihood x impact.
    assert risk["severity"] == "medium"

    r = await client.patch(
        f"/api/projects/{pid}/risks/{risk['id']}",
        json={"status": "mitigating", "expected_version": risk["version"]},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "mitigating"

    r = await client.delete(
        f"/api/projects/{pid}/risks/{risk['id']}", headers=headers
    )
    assert r.status_code == 204


async def test_context_audit_records_mutations(client, service_headers):
    _, _, project, headers = await _setup(client, service_headers)
    pid = project["id"]
    await client.put(
        f"/api/projects/{pid}/context/settings",
        json={"purpose": "audit test"},
        headers=headers,
    )
    r = await client.get(f"/api/projects/{pid}/context/audit", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] >= 1
    assert any(e["event_type"] == "project_context.settings_updated" for e in body["items"])


async def test_viewer_cannot_modify_context(client, service_headers):
    tenant, _user, project, _ = await _setup(client, service_headers, slug="ro-tenant")
    # create a viewer user
    r = await client.post(
        f"/api/tenants/{tenant['id']}/users",
        json={
            "email": "viewer@test.com",
            "display_name": "Viewer",
            "role": "viewer",
            "external_id": "ext-viewer",
        },
        headers=service_headers,
    )
    assert r.status_code == 201, r.text
    viewer = r.json()
    vheaders = _headers(tenant["id"], viewer["id"], "viewer")

    r = await client.post(
        f"/api/projects/{project['id']}/goals",
        json={"title": "Viewer goal", "priority": "low"},
        headers=vheaders,
    )
    assert r.status_code == 403


async def test_context_service_orders_goals_and_applies_links(db_session: AsyncSession):
    from app.models.project import Project

    ctx = RequestContext(
        claims=TokenClaims(sub="u", tenant_id=1, user_id=1, role="editor")
    )
    svc = ProjectContextService(db_session, context=ctx)

    project = Project(tenant_id=1, name="SVC", owner_id=1)
    db_session.add(project)
    await db_session.flush()

    g1 = await svc.create_goal(
        project.id,
        ProjectGoalCreate(title="Goal 1", priority="low", status="not_started"),
    )
    g2 = await svc.create_goal(
        project.id,
        ProjectGoalCreate(title="Goal 2", priority="low", status="not_started"),
    )
    assert g1.position < g2.position

    await svc.reorder_goals(project.id, ReorderRequest(ids=[g2.id, g1.id]))
    goals = await svc.list_goals(project.id)
    assert [g.id for g in goals] == [g2.id, g1.id]
