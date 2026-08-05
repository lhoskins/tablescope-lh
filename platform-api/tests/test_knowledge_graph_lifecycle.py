"""Tests for knowledge graph lifecycle manager and routes."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.jwt import TokenClaims, create_access_token
from app.services.knowledge_graph_lifecycle import GraphImpactAnalyzer, KnowledgeGraphLifecycleManager
from app.services.supabase_auth_service import SupabaseAuthService, SupabaseUser

pytestmark = pytest.mark.anyio


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
        self, *, to, template, variables, subject=None, reply_to=None, tenant_id=None, **kwargs
    ) -> bool:
        return True


@pytest.fixture(autouse=True)
def _mock_supabase(monkeypatch):
    import app.routes.tenants_users as tenants_module

    monkeypatch.setattr(tenants_module, "SupabaseAuthService", _FakeSupabase)
    monkeypatch.setattr(tenants_module, "EmailService", _FakeEmail)


def _headers(tenant_id: int, user_id: int, role: str = "editor") -> dict:
    token = create_access_token(
        sub="u", tenant_id=tenant_id, user_id=user_id, role=role
    )
    return {"Authorization": f"Bearer {token}"}


async def _setup(client: AsyncClient, service_headers: dict, slug: str = "kg-tenant"):
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
            "display_name": "KG User",
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


def _manager(session: AsyncSession, tenant_id: int, user_id: int, role: str = "editor"):
    return KnowledgeGraphLifecycleManager(
        session,
        RequestContext(
            claims=TokenClaims(
                sub=str(user_id), tenant_id=tenant_id, user_id=user_id, role=role
            )
        ),
    )


async def test_ensure_graph_creates_row(client, service_headers, db_session):
    tenant, user, project, _ = await _setup(client, service_headers)
    manager = _manager(db_session, tenant["id"], user["id"])
    graph = await manager.ensure_graph(project["id"])
    assert graph.project_id == project["id"]
    assert graph.lifecycle_status == "missing"


async def test_request_full_rebuild_creates_build(client, service_headers):
    _, _, project, headers = await _setup(client, service_headers)
    r = await client.post(
        f"/api/projects/{project['id']}/knowledge-graph/rebuild",
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["build_type"] == "full"
    assert body["build"]["project_id"] == project["id"]
    assert body["build"]["status"] == "queued"

    # Duplicate full rebuild request is idempotent.
    r2 = await client.post(
        f"/api/projects/{project['id']}/knowledge-graph/rebuild",
        headers=headers,
    )
    assert r2.status_code == 200
    assert r2.json()["build"]["id"] == body["build"]["id"]


async def test_request_incremental_rebuild_analyzes_change_set(client, service_headers, db_session):
    tenant, user, project, headers = await _setup(client, service_headers)

    # Activate the graph so the incremental analyzer can patch safely.
    manager = _manager(db_session, tenant["id"], user["id"])
    build, _ = await manager.request_full_rebuild(project["id"])
    await manager.run_full_rebuild(build.id)
    await db_session.commit()

    r = await client.post(
        f"/api/projects/{project['id']}/knowledge-graph/rebuild/incremental",
        json={
            "change_set": [
                {
                    "entity_type": "goal",
                    "entity_id": 1,
                    "action": "updated",
                    "change_scope": "local",
                }
            ]
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["build_type"] == "incremental"


async def test_schema_change_falls_back_to_full(client, service_headers):
    _, _, project, headers = await _setup(client, service_headers)
    r = await client.post(
        f"/api/projects/{project['id']}/knowledge-graph/rebuild/incremental",
        json={
            "change_set": [
                {
                    "entity_type": "data_source",
                    "action": "updated",
                    "change_scope": "schema",
                }
            ]
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["build_type"] == "full"


async def test_status_endpoint_returns_graph_and_builds(client, service_headers):
    _, _, project, headers = await _setup(client, service_headers)
    await client.post(
        f"/api/projects/{project['id']}/knowledge-graph/rebuild",
        headers=headers,
    )
    r = await client.get(
        f"/api/projects/{project['id']}/knowledge-graph/status",
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["project_id"] == project["id"]
    assert len(body["builds"]) == 1
    assert body["lifecycle_status"] == "requested"


async def test_mark_stale(client, service_headers, db_session):
    tenant, user, project, _ = await _setup(client, service_headers)
    manager = _manager(db_session, tenant["id"], user["id"])
    graph = await manager.mark_stale(project["id"], "Source drift")
    assert graph.lifecycle_status == "stale"


async def test_recover_stale_builds(client, service_headers, db_session):
    tenant, user, project, _ = await _setup(client, service_headers)
    manager = _manager(db_session, tenant["id"], user["id"])
    build = (await manager.request_full_rebuild(project["id"]))[0]
    from datetime import UTC, datetime, timedelta
    build.heartbeat_at = datetime.now(UTC) - timedelta(seconds=1000)
    await db_session.flush()

    recovered = await manager.recover_stale_builds()
    assert build.id in recovered
    assert build.status == "failed"


async def test_evaluate_stale_graphs_detects_fingerprint_drift(client, service_headers, db_session):
    tenant, user, project, _ = await _setup(client, service_headers)
    manager = _manager(db_session, tenant["id"], user["id"])
    graph = await manager.ensure_graph(project["id"])
    graph.current_source_fingerprint = "old-fingerprint"
    await db_session.flush()

    marked = await manager.evaluate_stale_graphs()
    assert project["id"] in marked
    assert graph.lifecycle_status == "stale"


async def test_graph_impact_analyzer_empty_change_set():
    analyzer = GraphImpactAnalyzer()
    result = await analyzer.analyze([])
    assert result["safe_incremental"] is False
    assert result["scope"] == "none"
