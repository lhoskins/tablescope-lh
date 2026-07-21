"""Tests for Project Actions routes and progress rollup."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.auth.jwt import create_access_token

pytestmark = pytest.mark.anyio


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


def _headers(tenant_id: int, user_id: int, role: str = "editor") -> dict:
    token = create_access_token(
        sub="u", tenant_id=tenant_id, user_id=user_id, role=role
    )
    return {"Authorization": f"Bearer {token}"}


async def _setup(client: AsyncClient, service_headers: dict, slug: str = "actions-test"):
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
            "display_name": "Action User",
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


async def _create_action(
    client,
    project_id,
    headers,
    title,
    subtasks=None,
    priority="high",
    snapshot=None,
):
    body = {
        "title": title,
        "priority": priority,
        "status": "not_started",
        "source_type": "insight",
        "source_insight_id": "ins-1",
        "source_insight_type": "risk",
        "source_insight_title": title,
        "source_insight_snapshot": snapshot,
        "initial_subtasks": subtasks or [],
    }
    r = await client.post(f"/api/projects/{project_id}/actions", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


async def test_create_action_computes_fingerprint_and_progress(client, service_headers):
    _, _, project, headers = await _setup(client, service_headers)
    pid = project["id"]
    action = await _create_action(
        client,
        pid,
        headers,
        "Fix defect spike",
        subtasks=[{"title": "Identify root cause"}, {"title": "Apply fix"}],
    )
    assert action["status"] == "not_started"
    assert action["percent_complete"] == 0
    assert action["source_insight_fingerprint"] is not None
    assert action["source_insight_fingerprint"] != action["source_insight_id"]
    assert len(action["subtasks"]) == 2


async def test_progress_rollups_and_autocomplete(client, service_headers):
    _, _, project, headers = await _setup(client, service_headers)
    pid = project["id"]
    action = await _create_action(
        client, pid, headers, "Rollup test", subtasks=[{"title": "A"}, {"title": "B"}]
    )
    sid = action["subtasks"][0]["id"]
    r = await client.patch(
        f"/api/projects/{pid}/actions/{action['id']}/subtasks/{sid}",
        json={"status": "completed"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["percent_complete"] == 100

    # 50% when only one of two required subtasks is completed
    action_r = await client.get(f"/api/projects/{pid}/actions/{action['id']}", headers=headers)
    assert action_r.json()["percent_complete"] == 50

    # Complete the second subtask -> parent auto-completes
    sid2 = action["subtasks"][1]["id"]
    r = await client.patch(
        f"/api/projects/{pid}/actions/{action['id']}/subtasks/{sid2}",
        json={"status": "completed"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    action_r = await client.get(f"/api/projects/{pid}/actions/{action['id']}", headers=headers)
    action_body = action_r.json()
    assert action_body["status"] == "completed"
    assert action_body["percent_complete"] == 100
    assert action_body["completed_at"] is not None


async def test_reopen_parent_when_subtask_reopens(client, service_headers):
    _, _, project, headers = await _setup(client, service_headers)
    pid = project["id"]
    action = await _create_action(client, pid, headers, "Reopen test", subtasks=[{"title": "A"}])
    sid = action["subtasks"][0]["id"]
    await client.patch(
        f"/api/projects/{pid}/actions/{action['id']}/subtasks/{sid}",
        json={"status": "completed"},
        headers=headers,
    )
    r = await client.patch(
        f"/api/projects/{pid}/actions/{action['id']}/subtasks/{sid}",
        json={"status": "in_progress"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    action_r = await client.get(f"/api/projects/{pid}/actions/{action['id']}", headers=headers)
    assert action_r.json()["status"] == "in_progress"
    assert action_r.json()["completed_at"] is None


async def test_cannot_complete_parent_with_incomplete_required_subtasks(client, service_headers):
    _, _, project, headers = await _setup(client, service_headers)
    pid = project["id"]
    action = await _create_action(
        client, pid, headers, "Block test", subtasks=[{"title": "A"}]
    )
    r = await client.patch(
        f"/api/projects/{pid}/actions/{action['id']}",
        json={"status": "completed"},
        headers=headers,
    )
    assert r.status_code == 409, r.text


async def test_archive_soft_deletes_action_and_subtasks(client, service_headers):
    _, _, project, headers = await _setup(client, service_headers)
    pid = project["id"]
    action = await _create_action(client, pid, headers, "Archive test", subtasks=[{"title": "A"}])
    r = await client.delete(f"/api/projects/{pid}/actions/{action['id']}", headers=headers)
    assert r.status_code == 200, r.text
    r = await client.get(f"/api/projects/{pid}/actions/{action['id']}", headers=headers)
    assert r.status_code == 404


async def test_list_filters_and_search(client, service_headers):
    _, _, project, headers = await _setup(client, service_headers)
    pid = project["id"]
    await _create_action(client, pid, headers, "Alpha critical", subtasks=[], priority="critical")
    await _create_action(client, pid, headers, "Beta low", subtasks=[], priority="low")
    r = await client.get(f"/api/projects/{pid}/actions?priority=critical", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["title"] == "Alpha critical"

    r = await client.get(f"/api/projects/{pid}/actions?q=beta", headers=headers)
    assert r.json()["items"][0]["title"] == "Beta low"


async def test_viewer_cannot_create_action(client, service_headers):
    _, user, project, _ = await _setup(client, service_headers)
    headers = _headers(project["tenant_id"], user["id"], "viewer")
    r = await client.post(
        f"/api/projects/{project['id']}/actions",
        json={"title": "x", "priority": "medium"},
        headers=headers,
    )
    assert r.status_code == 403


async def test_tenant_isolation(client, service_headers):
    _, _, project1, headers1 = await _setup(client, service_headers, slug="iso-a")
    _, _, project2, headers2 = await _setup(client, service_headers, slug="iso-b")
    action = await _create_action(client, project1["id"], headers1, "Iso", subtasks=[])
    r = await client.get(
        f"/api/projects/{project2['id']}/actions/{action['id']}", headers=headers2
    )
    assert r.status_code == 404


async def test_count_for_insight_dedupes_by_fingerprint(client, service_headers):
    _, _, project, headers = await _setup(client, service_headers)
    pid = project["id"]
    snapshot = {"sources": {"tables": ["t1"], "documents": []}}
    await _create_action(client, pid, headers, "Dedup", subtasks=[], snapshot=snapshot)
    r = await client.post(
        f"/api/projects/{pid}/actions:count-for-insight",
        json={
            "source_insight_id": "ins-2",
            "source_insight_type": "risk",
            "source_insight_title": "Dedup",
            "source_insight_snapshot": snapshot,
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 1
    assert len(body["action_ids"]) == 1


async def test_project_summary_includes_action_count(client, service_headers):
    _, _, project, headers = await _setup(client, service_headers)
    pid = project["id"]
    await _create_action(client, pid, headers, "Summary", subtasks=[])
    r = await client.get("/api/projects/summaries", headers=headers)
    assert r.status_code == 200, r.text
    summary = next((s for s in r.json() if s["id"] == pid), None)
    assert summary is not None
    assert summary["action_count"] == 1


async def test_build_ai_context_includes_actions(client, service_headers, db_session):
    _, _, project, headers = await _setup(client, service_headers)
    pid = project["id"]
    await _create_action(
        client, pid, headers, "AI context", subtasks=[{"title": "Step 1"}]
    )
    from app.services.project_ai_context import build_project_ai_context

    ctx = await build_project_ai_context(
        db_session,
        tenant_id=project["tenant_id"],
        project_id=pid,
    )
    assert "actions" in ctx
    assert len(ctx["actions"]) == 1
    assert ctx["actions"][0]["title"] == "AI context"
    assert "actions_guidance" in ctx
    assert "actions_summary" in ctx
