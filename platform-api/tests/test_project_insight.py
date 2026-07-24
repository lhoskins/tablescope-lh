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
    _tenant, user, project, headers = await _setup(
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
    _, _user, project, headers = await _setup(client, service_headers, "pi-idem")
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


async def test_acknowledge_persists_snapshot_and_lists_reviewed(
    client, service_headers, _mock_ai
) -> None:
    _, user, project, headers = await _setup(client, service_headers, "pi-snap")
    pid = project["id"]

    r = await client.post(
        f"/api/projects/{pid}/insights/i1/acknowledge",
        json={
            "note": "looks right",
            "title": "Supplier A risk",
            "summary": "Lead time breached SLA",
            "category": "risk",
            "severity": "high",
        },
        headers=headers,
    )
    assert r.status_code == 200

    r = await client.get(
        f"/api/projects/{pid}/insights/reviewed", headers=headers
    )
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    item = items[0]
    assert item["insightId"] == "i1"
    assert item["title"] == "Supplier A risk"
    assert item["summary"] == "Lead time breached SLA"
    assert item["category"] == "risk"
    assert item["severity"] == "high"
    assert item["note"] == "looks right"
    assert item["reviewedByName"]
    assert item["reviewedByUserId"] == user["id"]
    assert item["reviewedAt"]


async def test_reopen_removes_from_reviewed_and_audits(
    client, service_headers, _mock_ai, db_session
) -> None:
    _, user, project, headers = await _setup(client, service_headers, "pi-reopen")
    pid = project["id"]

    await client.post(
        f"/api/projects/{pid}/insights/i1/acknowledge",
        json={"note": None, "title": "Supplier A risk"},
        headers=headers,
    )
    reviewed = (
        await client.get(
            f"/api/projects/{pid}/insights/reviewed", headers=headers
        )
    ).json()["items"]
    assert len(reviewed) == 1

    r = await client.post(
        f"/api/projects/{pid}/insights/i1/reopen", headers=headers
    )
    assert r.status_code == 200
    assert r.json()["status"] == "reopened"

    reviewed = (
        await client.get(
            f"/api/projects/{pid}/insights/reviewed", headers=headers
        )
    ).json()["items"]
    assert reviewed == []

    # The reopened insight is back in the Open workflow (not 'reviewed').
    body = (
        await client.get(f"/api/projects/{pid}/insight", headers=headers)
    ).json()
    workflow = {w["id"]: w for w in body["insightValidationWorkflow"]}
    assert workflow["i1"]["status"] != "reviewed"

    audit = (
        await db_session.execute(
            select(AuditEvent).where(
                AuditEvent.project_id == pid,
                AuditEvent.event_type == "project_insight_reopened",
            )
        )
    ).scalar_one()
    assert audit.user_id == user["id"]
    assert audit.prompt_type == "i1"


async def test_reopen_unknown_insight_returns_404(
    client, service_headers, _mock_ai
) -> None:
    _, _, project, headers = await _setup(client, service_headers, "pi-reopen404")
    r = await client.post(
        f"/api/projects/{project['id']}/insights/nope/reopen", headers=headers
    )
    assert r.status_code == 404


async def test_reviewed_list_rejects_other_tenant(
    client, service_headers, _mock_ai
) -> None:
    _, _, project, _ = await _setup(client, service_headers, "pi-rev-iso-a")
    _, _, _, other_headers = await _setup(
        client, service_headers, "pi-rev-iso-b"
    )
    r = await client.get(
        f"/api/projects/{project['id']}/insights/reviewed",
        headers=other_headers,
    )
    assert r.status_code == 404


async def test_project_insight_exposes_card_groups(
    client, service_headers, _mock_ai
) -> None:
    _, _, project, headers = await _setup(client, service_headers, "pi-cards")
    body = (
        await client.get(
            f"/api/projects/{project['id']}/insight", headers=headers
        )
    ).json()
    for key in ("risks", "trends", "opportunities"):
        assert key in body
        assert isinstance(body[key], list)


def test_normalize_severity_coerces_to_allowed_values() -> None:
    from app.services import project_insight_service as pis

    # risks keep their value when allowed, else fall back to watch.
    assert pis._normalize_severity("critical", "risks") == "critical"
    assert pis._normalize_severity("bogus", "risks") == "watch"
    # trends never carry critical/urgent (mapped to warning).
    assert pis._normalize_severity("urgent", "trends") == "warning"
    assert pis._normalize_severity("critical", "trends") == "warning"
    assert pis._normalize_severity("watch", "trends") == "watch"
    assert pis._normalize_severity("", "trends") == "informational"
    # opportunities only opportunity/recommendation.
    assert pis._normalize_severity("recommendation", "opportunities") == (
        "recommendation"
    )
    assert pis._normalize_severity("critical", "opportunities") == "opportunity"


def test_card_group_maps_insight_type() -> None:
    from app.services import project_insight_service as pis

    assert pis._card_group("risk_sla") == "risks"
    assert pis._card_group("trend_spend") == "trends"
    assert pis._card_group("opportunity_supplier") == "opportunities"
    assert pis._card_group("shape_scatter") == "analysis"
    assert pis._card_group("something_else") == "analysis"


async def test_grouped_intelligence_cards_groups_and_maps(monkeypatch) -> None:
    from app.services import home_intelligence as hi
    from app.services import project_insight_service as pis

    sample = [
        {
            "id": "c1",
            "insightType": "risk_sla",
            "severity": "critical",
            "title": "Delivery lead time exceeds SLA threshold",
            "summary": "**High** lead time.",
            "callout": {"type": "risk", "text": "Escalate with supplier."},
            "sources": {"tables": ["SUP_Quality_CSV"], "documents": []},
            "sourceContext": {
                "metric": "lead_time_days",
                "periodColumn": "month",
                "sourceColumns": ["lead_time_days", "month", "supplier"],
            },
        },
        {
            "id": "c2",
            "insightType": "trend_spend",
            "severity": "urgent",
            "title": "Spend tracking over budget",
            "summary": "Spend up.",
            "sources": {"tables": ["FIN_Spend_CSV"]},
        },
        {
            "id": "c3",
            "insightType": "opportunity_supplier",
            "severity": "opportunity",
            "title": "Top-performing suppliers identified",
            "summary": "Great performers.",
            "sources": {},
        },
    ]

    async def fake_suite(project, ctx, prompt_types, runner):
        return sample

    monkeypatch.setattr(hi, "run_intelligence_suite", fake_suite)

    class _P:
        id = 1

    grouped = await pis._grouped_intelligence_cards(_P(), None, None)

    assert len(grouped["risks"]) == 1
    risk = grouped["risks"][0]
    assert risk["severity"] == "critical"
    assert risk["recommendedAction"] == "Escalate with supplier."
    assert risk["question"] == pis._INVESTIGATION_QUESTIONS["risk_sla"]
    assert risk["supportingSources"] == ["SUP_Quality_CSV"]
    # Source context (Business Insight source of truth) flows onto the card so
    # Investigate can ground the resolver in the exact source/columns.
    assert risk["sourceTables"] == ["SUP_Quality_CSV"]
    assert risk["metric"] == "lead_time_days"
    assert risk["periodColumn"] == "month"
    assert risk["sourceColumns"] == ["lead_time_days", "month", "supplier"]

    # trend urgent is normalized down to warning (allowed for trends).
    assert grouped["trends"][0]["severity"] == "warning"
    assert grouped["opportunities"][0]["severity"] == "opportunity"


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
