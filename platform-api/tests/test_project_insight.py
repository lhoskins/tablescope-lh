"""Tests for the Project Insight endpoints.

Covers: project-scoped output shape, executive-summary bullet categories,
recommendations as suggestions (not just saved assets), Reference Library not
used as a SQL datasource, acknowledgement audit trail, no Approve/Reject in the
V1 workflow, AI-unavailable degradation, and tenant/project isolation.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.auth.jwt import create_access_token
from app.models.audit_event import AuditEvent
from app.models.project_insight_acknowledgement import (
    ProjectInsightAcknowledgement,
)
from app.services.supabase_auth_service import SupabaseAuthService, SupabaseUser


class _FakeSupabase(SupabaseAuthService):
    def __init__(self) -> None:
        pass

    async def create_or_invite_user(
        self, email, *, first_name=None, last_name=None, redirect_to=None
    ) -> SupabaseUser:
        return SupabaseUser(
            id=f"supa-{email}",
            email=email,
            created=True,
            action_link=f"https://invite/{email}",
        )


class _FakeEmail:
    async def send_transactional_email(
        self, *, to, template, variables, subject=None, reply_to=None
    ) -> bool:
        return True


@pytest.fixture(autouse=True)
def _mock_supabase(monkeypatch):
    import app.routes.tenants as tenants_module

    monkeypatch.setattr(tenants_module, "SupabaseAuthService", _FakeSupabase)
    monkeypatch.setattr(tenants_module, "EmailService", _FakeEmail)


_AI_RESULT = {
    "executiveSummary": {
        "summary": "Project is on track with two supplier risks.",
        "critical": ["Supplier A lead time breached SLA"],
        "warnings": ["Budget variance trending up"],
        "opportunities": ["Consolidate spend with Supplier B"],
        "recommendations": ["Renegotiate Supplier A contract"],
    },
    "questionsToAsk": [
        {"id": "q1", "question": "Why did Supplier A slip?", "reason": "risk"}
    ],
    "trendDetection": [
        {"id": "t1", "label": "Spend up", "description": "MoM +12%"}
    ],
    "recommendedDashboards": [
        {"id": "d1", "title": "Supplier SLA", "status": "suggested"}
    ],
    "recommendedQueries": [
        {"id": "rq1", "title": "Late shipments", "status": "suggested"}
    ],
    "recommendedKpis": [
        {"id": "k1", "name": "On-time %", "status": "recommended", "currentValue": None}
    ],
    "insightValidationWorkflow": [
        {"id": "i1", "title": "Supplier A risk", "priority": "high", "status": "new"},
        {"id": "i2", "title": "Budget watch", "priority": "medium", "status": "new"},
    ],
    "request_id": "r1",
    "model_used": "test-model",
}


def _editor_headers(tenant_id: int, user_id: int) -> dict:
    token = create_access_token(
        sub="u", tenant_id=tenant_id, user_id=user_id, role="editor"
    )
    return {"Authorization": f"Bearer {token}"}


async def _setup(client, service_headers, slug: str):
    r = await client.post(
        "/api/tenants",
        json={"slug": slug, "name": f"{slug} tenant"},
        headers=service_headers,
    )
    assert r.status_code == 201
    tenant = r.json()

    r = await client.post(
        f"/api/tenants/{tenant['id']}/users",
        json={
            "email": f"{slug}@test.com",
            "display_name": "Insight User",
            "role": "editor",
            "external_id": f"ext-{slug}",
        },
        headers=service_headers,
    )
    assert r.status_code == 201
    user = r.json()

    headers = _editor_headers(tenant["id"], user["id"])
    r = await client.post(
        "/api/projects",
        json={"name": "Insight Project", "description": "x", "is_shared": False},
        headers=headers,
    )
    assert r.status_code == 201
    return tenant, user, r.json(), headers


@pytest.fixture()
def _mock_ai(monkeypatch):
    """Patch the AI client so no real AI server is required. Records call args."""
    calls: list[dict] = []

    async def fake(**kwargs):
        calls.append(kwargs)
        return _AI_RESULT

    monkeypatch.setattr(
        "app.services.ai_intelligence_client.project_insight", fake
    )
    return calls


async def test_project_insight_returns_project_scoped_output(
    client, service_headers, _mock_ai
) -> None:
    _, _, project, headers = await _setup(client, service_headers, "pi-scope")
    pid = project["id"]

    r = await client.get(f"/api/projects/{pid}/insight", headers=headers)
    assert r.status_code == 200
    body = r.json()

    # Scoped to exactly this project — the AI client was called with its id.
    assert body["project"]["id"] == pid
    assert len(_mock_ai) == 1
    assert _mock_ai[0]["project_id"] == pid
    assert body["aiAvailable"] is True


async def test_executive_summary_has_bullet_categories(
    client, service_headers, _mock_ai
) -> None:
    _, _, project, headers = await _setup(client, service_headers, "pi-exec")
    r = await client.get(
        f"/api/projects/{project['id']}/insight", headers=headers
    )
    es = r.json()["executiveSummary"]
    assert es["summary"]
    for key in ("critical", "warnings", "opportunities", "recommendations"):
        assert isinstance(es[key], list) and es[key]


async def test_recommendations_can_be_suggested_without_saved_assets(
    client, service_headers, _mock_ai
) -> None:
    _, _, project, headers = await _setup(client, service_headers, "pi-suggest")
    body = (
        await client.get(
            f"/api/projects/{project['id']}/insight", headers=headers
        )
    ).json()
    # No saved dashboards/queries/KPIs exist for this fresh project, yet the
    # report still surfaces suggestions.
    assert body["recommendedDashboards"][0]["status"] == "suggested"
    assert body["recommendedQueries"][0]["status"] == "suggested"
    assert body["recommendedKpis"][0]["status"] == "recommended"


async def test_reference_library_not_used_as_sql_datasource(
    client, service_headers, _mock_ai
) -> None:
    _, _, project, headers = await _setup(client, service_headers, "pi-ref")
    await client.get(f"/api/projects/{project['id']}/insight", headers=headers)
    # The context handed to the AI only carries data tables/documents/queries —
    # never a "reference library" datasource the model could query as SQL.
    ctx = _mock_ai[0]
    assert "reference" not in {t.get("kind") for t in ctx["tables"]}
    assert all(t.get("name") for t in ctx["tables"])


async def test_acknowledge_creates_audit_record(
    client, service_headers, _mock_ai, db_session
) -> None:
    tenant, user, project, headers = await _setup(
        client, service_headers, "pi-ack"
    )
    pid = project["id"]

    r = await client.post(
        f"/api/projects/{pid}/insights/i1/acknowledge",
        json={"note": None},
        headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["insightId"] == "i1"
    assert body["status"] == "reviewed"
    assert body["acknowledgedByUserId"] == user["id"]
    assert body["acknowledgedByName"]
    assert body["acknowledgedAt"]

    ack = (
        await db_session.execute(
            select(ProjectInsightAcknowledgement).where(
                ProjectInsightAcknowledgement.project_id == pid,
                ProjectInsightAcknowledgement.insight_id == "i1",
            )
        )
    ).scalar_one()
    assert ack.status == "reviewed"
    assert ack.user_id == user["id"]

    audit = (
        await db_session.execute(
            select(AuditEvent).where(
                AuditEvent.project_id == pid,
                AuditEvent.event_type == "project_insight_acknowledged",
            )
        )
    ).scalar_one()
    assert audit.user_id == user["id"]
    assert audit.prompt_type == "i1"


async def test_acknowledge_is_idempotent_and_surfaces_in_workflow(
    client, service_headers, _mock_ai
) -> None:
    _, user, project, headers = await _setup(client, service_headers, "pi-idem")
    pid = project["id"]

    for _ in range(2):
        r = await client.post(
            f"/api/projects/{pid}/insights/i1/acknowledge",
            json={"note": None},
            headers=headers,
        )
        assert r.status_code == 200

    body = (
        await client.get(f"/api/projects/{pid}/insight", headers=headers)
    ).json()
    workflow = {w["id"]: w for w in body["insightValidationWorkflow"]}
    assert workflow["i1"]["status"] == "reviewed"
    assert workflow["i1"]["acknowledgedBy"]
    assert workflow["i2"]["status"] == "new"


async def test_workflow_has_no_approve_or_reject(
    client, service_headers, _mock_ai
) -> None:
    _, _, project, headers = await _setup(client, service_headers, "pi-noapprove")
    body = (
        await client.get(
            f"/api/projects/{project['id']}/insight", headers=headers
        )
    ).json()
    statuses = {w["status"] for w in body["insightValidationWorkflow"]}
    assert statuses <= {"new", "reviewed"}
    assert "approved" not in statuses
    assert "rejected" not in statuses


async def test_project_insight_degrades_when_ai_unavailable(
    client, service_headers, monkeypatch
) -> None:
    async def fake(**kwargs):
        return None

    monkeypatch.setattr(
        "app.services.ai_intelligence_client.project_insight", fake
    )
    _, _, project, headers = await _setup(client, service_headers, "pi-down")
    body = (
        await client.get(
            f"/api/projects/{project['id']}/insight", headers=headers
        )
    ).json()
    assert body["aiAvailable"] is False
    assert "whatChangedSinceLastVisit" in body


async def test_project_insight_rejects_other_tenant(
    client, service_headers, _mock_ai
) -> None:
    _, _, project, _ = await _setup(client, service_headers, "pi-iso-a")
    _, _, _, other_headers = await _setup(client, service_headers, "pi-iso-b")

    r = await client.get(
        f"/api/projects/{project['id']}/insight", headers=other_headers
    )
    assert r.status_code == 404

    r = await client.post(
        f"/api/projects/{project['id']}/insights/i1/acknowledge",
        json={"note": None},
        headers=other_headers,
    )
    assert r.status_code == 404
