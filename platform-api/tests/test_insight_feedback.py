"""Tests for Sprint-03: explainable insight cards and persisted human feedback."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import create_access_token
from app.models.insight_feedback import InsightFeedback
from app.services import home_intelligence as hi
from app.services.insight_explanation import build_explanation
from app.services.insight_feedback_learning import build_feedback_training_record
from app.services.supabase_auth_service import SupabaseAuthService, SupabaseUser

pytestmark = pytest.mark.anyio


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
    import app.routes.tenants_users as tenants_module

    monkeypatch.setattr(tenants_module, "SupabaseAuthService", _FakeSupabase)
    monkeypatch.setattr(tenants_module, "EmailService", _FakeEmail)


def _headers(tenant_id: int, user_id: int, role: str = "editor") -> dict:
    token = create_access_token(
        sub="u", tenant_id=tenant_id, user_id=user_id, role=role
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
            "display_name": "Feedback User",
            "role": "editor",
            "external_id": f"ext-{slug}",
        },
        headers=service_headers,
    )
    assert r.status_code == 201
    user = r.json()
    headers = _headers(tenant["id"], user["id"])

    r = await client.post(
        "/api/projects",
        json={"name": "Feedback Project", "description": "x", "is_shared": False},
        headers=headers,
    )
    assert r.status_code == 201
    project = r.json()
    return tenant, user, project, headers


# ─────────────────────────── explainability service ─────────────────────────


def test_build_explanation_infers_method_and_includes_required_fields():
    explanation = build_explanation(
        project_id=1,
        project_name="Supply Chain",
        insight_type="trend_spend",
        summary="Spend increased 20% month over month.",
        chart_type="kpi_grid",
        metric="amount",
        aggregation="sum",
        sql='SELECT "month", SUM("amount") FROM "spend" GROUP BY "month"',
        result={"columns": ["month", "sum_amount"], "rows": [{"month": "2024-01", "sum_amount": 100.0}]},
    )
    assert explanation is not None
    assert explanation["summary"] == "Spend increased 20% month over month."
    assert explanation["method"] == "period_over_period_comparison"
    assert explanation["methodLabel"] == "Period-over-period comparison"
    assert "steps" in explanation
    assert explanation["source"]["projectId"] == 1
    assert explanation["source"]["projectName"] == "Supply Chain"
    assert explanation["sql"] == 'SELECT "month", SUM("amount") FROM "spend" GROUP BY "month"'
    assert explanation["confidence"]["level"] in {"low", "medium", "high"}
    assert "assumptions" in explanation
    assert "limitations" in explanation


def test_build_explanation_returns_none_for_document_only_without_documents():
    explanation = build_explanation(
        project_id=1,
        project_name="Contracts",
        insight_type="document_summary",
        summary="A document-only insight.",
        method="document_synthesis",
    )
    assert explanation is None


async def test_card_builder_adds_stable_insight_id_and_explanation():
    project = SimpleNamespace(id=42, name="Demo")
    card = hi._card(
        project,
        "risk_sla",
        "critical",
        "SLA breach",
        "Average lead time exceeds threshold.",
        sql='SELECT "month", AVG("lead_time") FROM "shipments"',
        chart_type="bar",
        label_column="month",
        value_column="avg_lead",
    )
    assert "insightId" in card
    assert len(card["insightId"]) == 32
    assert card["insightId"] != card["id"]
    assert "explanation" in card
    assert card["explanation"]["method"] == "rule_based_detection"
    assert card["explanation"]["source"]["projectId"] == 42


# ───────────────────────────── feedback model ───────────────────────────────


async def test_feedback_model_enforces_unique_constraint(db_session: AsyncSession):
    fb1 = InsightFeedback(
        tenant_id=1,
        user_id=2,
        project_id=10,
        insight_id="insight-abc",
        insight_type="risk_sla",
        sentiment="disagree",
        reason_codes=["incorrect_data", "too_confident"],
        comment="The numbers look off.",
        status="active",
    )
    db_session.add(fb1)
    await db_session.commit()

    # A second active row for the same (tenant, user, insight) violates the unique constraint.
    fb2 = InsightFeedback(
        tenant_id=1,
        user_id=2,
        project_id=10,
        insight_id="insight-abc",
        insight_type="risk_sla",
        sentiment="agree",
        reason_codes=[],
        status="active",
    )
    db_session.add(fb2)
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        await db_session.flush()

    await db_session.rollback()


async def test_feedback_model_soft_delete_allows_resubmit(db_session: AsyncSession):
    fb = InsightFeedback(
        tenant_id=1,
        user_id=2,
        project_id=10,
        insight_id="insight-xyz",
        insight_type="risk_sla",
        sentiment="disagree",
        reason_codes=["incorrect_data"],
        comment="The numbers look off.",
        status="active",
    )
    db_session.add(fb)
    await db_session.commit()

    # Soft-delete (withdraw) the feedback.
    fb.status = "withdrawn"
    fb.comment = None
    await db_session.commit()

    # Re-submit by reactivating the same row, which preserves the unique constraint.
    fb.status = "active"
    fb.sentiment = "agree"
    fb.reason_codes = []
    await db_session.commit()

    row = await db_session.scalar(
        select(InsightFeedback).where(
            InsightFeedback.tenant_id == 1,
            InsightFeedback.user_id == 2,
            InsightFeedback.insight_id == "insight-xyz",
            InsightFeedback.status == "active",
        )
    )
    assert row is not None
    assert row.sentiment == "agree"
    assert row.comment is None


# ───────────────────────────── feedback API ─────────────────────────────────


async def test_feedback_api_upsert_get_batch_delete(client, service_headers):
    _, _, project, headers = await _setup(client, service_headers, "fb-api")

    insight_id = "insight-test-123"

    # Initially there is no feedback.
    r = await client.get(f"/api/insight-feedback/{insight_id}", headers=headers)
    assert r.status_code == 200
    assert r.json() is None

    # Upsert active feedback.
    r = await client.put(
        f"/api/insight-feedback/{insight_id}",
        json={
            "project_id": project["id"],
            "sentiment": "disagree",
            "reason_codes": ["incorrect_data"],
            "comment": "Looks wrong",
            "insight_type": "risk_sla",
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sentiment"] == "disagree"
    assert body["reason_codes"] == ["incorrect_data"]
    assert body["comment"] == "Looks wrong"
    assert body["status"] == "active"

    # GET returns the record.
    r = await client.get(f"/api/insight-feedback/{insight_id}", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["insight_id"] == insight_id
    assert body["project_id"] == project["id"]

    # Batch returns the same record.
    r = await client.post(
        "/api/insight-feedback/batch",
        json={"insight_ids": [insight_id, "missing-insight"]},
        headers=headers,
    )
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["insight_id"] == insight_id

    # Update to agree; comment is now required for all feedback.
    r = await client.put(
        f"/api/insight-feedback/{insight_id}",
        json={
            "project_id": project["id"],
            "sentiment": "agree",
            "reason_codes": [],
            "comment": "After review, the numbers look correct.",
            "insight_type": "risk_sla",
        },
        headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["sentiment"] == "agree"
    assert body["review_status"] == "not_required"

    # Delete withdraws the feedback.
    r = await client.delete(
        f"/api/insight-feedback/{insight_id}",
        params={"project_id": project["id"]},
        headers=headers,
    )
    assert r.status_code == 204

    r = await client.get(f"/api/insight-feedback/{insight_id}", headers=headers)
    assert r.json() is None


async def test_feedback_api_rejects_invalid_sentiment_and_reasons(client, service_headers):
    _, _, project, headers = await _setup(client, service_headers, "fb-invalid")

    r = await client.put(
        "/api/insight-feedback/bad-insight",
        json={
            "project_id": project["id"],
            "sentiment": "maybe",
            "reason_codes": ["invalid_code"],
            "comment": "Some comment.",
        },
        headers=headers,
    )
    assert r.status_code == 422


async def test_feedback_api_is_isolated_by_tenant_and_user(client, service_headers):
    _, _, _project_a, headers_a = await _setup(client, service_headers, "fb-iso-a")
    _, _, _project_b, headers_b = await _setup(client, service_headers, "fb-iso-b")

    insight_id = "shared-insight"
    await client.put(
        f"/api/insight-feedback/{insight_id}",
        json={
            "project_id": _project_a["id"],
            "sentiment": "agree",
            "reason_codes": [],
            "comment": "Agree.",
        },
        headers=headers_a,
    )

    r = await client.get(f"/api/insight-feedback/{insight_id}", headers=headers_b)
    assert r.status_code == 200
    assert r.json() is None


async def test_feedback_api_cannot_write_to_missing_project(client, service_headers):
    _, _, _, headers = await _setup(client, service_headers, "fb-proj")
    r = await client.put(
        "/api/insight-feedback/no-project-insight",
        json={
            "project_id": 999999,
            "sentiment": "agree",
            "reason_codes": [],
            "comment": "Looks correct.",
        },
        headers=headers,
    )
    assert r.status_code == 404


async def test_feedback_batch_enforces_max_ids(client, service_headers):
    _, _, _, headers = await _setup(client, service_headers, "fb-batch")
    r = await client.post(
        "/api/insight-feedback/batch",
        json={"insight_ids": [str(i) for i in range(201)]},
        headers=headers,
    )
    assert r.status_code == 422


# ───────────────────────────── review endpoint ───────────────────────────────


async def _create_user(client, service_headers, tenant_id: int, email: str, role: str):
    r = await client.post(
        f"/api/tenants/{tenant_id}/users",
        json={
            "email": email,
            "display_name": email.split("@")[0],
            "role": role,
            "external_id": f"ext-{email}",
        },
        headers=service_headers,
    )
    assert r.status_code == 201
    return r.json()


async def test_feedback_review_lists_other_users_feedback_for_admin(client, service_headers):
    tenant, editor, project, editor_headers = await _setup(client, service_headers, "fb-review")
    admin = await _create_user(client, service_headers, tenant["id"], "admin@fb-review.com", "admin")
    admin_headers = _headers(tenant["id"], admin["id"], "admin")

    # Editor leaves feedback.
    r = await client.put(
        "/api/insight-feedback/insight-1",
        json={
            "project_id": project["id"],
            "sentiment": "disagree",
            "reason_codes": ["incorrect_data"],
            "comment": "Numbers look off.",
            "card_snapshot": {"title": "Test insight"},
        },
        headers=editor_headers,
    )
    assert r.status_code == 200

    r = await client.get("/api/insight-feedback/review", headers=admin_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert item["sentiment"] == "disagree"
    assert item["user_id"] == editor["id"]
    assert item["project_id"] == project["id"]
    assert item["card_title"] == "Test insight"
    assert item["project_name"] == "Feedback Project"


async def test_feedback_review_forbidden_for_non_admin(client, service_headers):
    _, _, _, headers = await _setup(client, service_headers, "fb-review-editor")
    r = await client.get("/api/insight-feedback/review", headers=headers)
    assert r.status_code == 403


async def test_feedback_review_is_tenant_isolated(client, service_headers):
    tenant_a, _, _project_a, _ = await _setup(client, service_headers, "fb-review-a")
    tenant_b, user_b, project_b, _ = await _setup(client, service_headers, "fb-review-b")

    admin_a = await _create_user(client, service_headers, tenant_a["id"], "admin@a.com", "admin")
    admin_a_headers = _headers(tenant_a["id"], admin_a["id"], "admin")

    # Feedback in tenant B.
    headers_b = _headers(tenant_b["id"], user_b["id"], "editor")
    r = await client.put(
        "/api/insight-feedback/insight-b",
        json={
            "project_id": project_b["id"],
            "sentiment": "agree",
            "reason_codes": [],
            "comment": "Looks good.",
            "card_snapshot": {"title": "B insight"},
        },
        headers=headers_b,
    )
    assert r.status_code == 200

    r = await client.get("/api/insight-feedback/review", headers=admin_a_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 0
    assert data["items"] == []


# ───────────────────────────── learning export ──────────────────────────────


def test_build_feedback_training_record_is_privacy_safe():
    feedback = InsightFeedback(
        id=1,
        tenant_id=10,
        user_id=20,
        project_id=30,
        insight_id="insight-xyz",
        insight_type="risk_sla",
        sentiment="disagree",
        reason_codes=["incorrect_data"],
        comment="Bad numbers.",
        insight_fingerprint="fp-1",
        card_snapshot={
            "id": "card-1",
            "insightId": "insight-xyz",
            "title": "SLA breach",
            "summary": "Bad.",
            "secretField": "should-be-removed",
            "prompt": "hidden-prompt",
            "sql": 'SELECT "x" FROM "y"',
        },
        explanation_snapshot={
            "method": "anomaly_detection",
            "sql": 'SELECT "x" FROM "y"',
            "assumptions": ["a"],
            "limitations": ["l"],
            "chainOfThought": "hidden",
        },
        model_metadata={"model": "gpt-4", "temperature": 0.0},
        status="active",
    )
    record = build_feedback_training_record(feedback)
    assert record["record_type"] == "insight_feedback"
    assert record["tenant_id"] == 10
    assert record["user_id"] == 20
    assert record["project_id"] == 30
    assert record["insight_id"] == "insight-xyz"
    assert record["sentiment"] == "disagree"
    assert record["reason_codes"] == ["incorrect_data"]
    assert record["comment"] == "Bad numbers."
    assert record["status"] == "active"
    assert record["method"] == "anomaly_detection"
    assert "card" in record
    assert "explanation" in record
    assert record["model_name"] == "gpt-4"
    assert "secretField" not in record["card"]
    assert "prompt" not in record["card"]
    assert "chainOfThought" not in record["explanation"]
    assert record["card"]["sql"] == 'SELECT "x" FROM "y"'
    assert record["privacy_safe"] is True


# ──────────────────────────── reviewer workflow ───────────────────────────


async def _setup_reviewer(client, service_headers, slug: str):
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
            "email": f"{slug}-reviewer@test.com",
            "display_name": "Reviewer User",
            "role": "admin",
            "external_id": f"ext-{slug}-reviewer",
        },
        headers=service_headers,
    )
    assert r.status_code == 201
    reviewer = r.json()
    reviewer_headers = _headers(tenant["id"], reviewer["id"], "admin")

    r = await client.post(
        f"/api/tenants/{tenant['id']}/users",
        json={
            "email": f"{slug}-user@test.com",
            "display_name": "Feedback User",
            "role": "editor",
            "external_id": f"ext-{slug}-user",
        },
        headers=service_headers,
    )
    assert r.status_code == 201
    user = r.json()
    user_headers = _headers(tenant["id"], user["id"], "editor")

    r = await client.post(
        "/api/projects",
        json={"name": "Feedback Project", "description": "x", "is_shared": False},
        headers=user_headers,
    )
    assert r.status_code == 201
    project = r.json()
    return tenant, reviewer, reviewer_headers, user, user_headers, project


async def test_review_queue_requires_reviewer_role(client, service_headers):
    _, _, _, _, user_headers, _ = await _setup_reviewer(client, service_headers, "fb-req")
    r = await client.get("/api/insight-feedback/review/queue", headers=user_headers)
    assert r.status_code == 403


async def test_review_queue_lists_feedback_for_review(client, service_headers):
    _, _, reviewer_headers, _, user_headers, project = await _setup_reviewer(
        client, service_headers, "fb-queue"
    )

    insight_id = "insight-review-1"
    r = await client.put(
        f"/api/insight-feedback/{insight_id}",
        json={
            "project_id": project["id"],
            "sentiment": "disagree",
            "reason_codes": ["incorrect_data"],
            "comment": "The numbers look wrong.",
            "insight_type": "risk_sla",
        },
        headers=user_headers,
    )
    assert r.status_code == 200

    r = await client.get("/api/insight-feedback/review/queue", headers=reviewer_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["insight_id"] == insight_id
    assert body["items"][0]["review_status"] == "pending"


async def test_review_claim_and_disposition_requires_comment(client, service_headers):
    _, _, reviewer_headers, _, user_headers, project = await _setup_reviewer(
        client, service_headers, "fb-disp"
    )

    insight_id = "insight-review-2"
    r = await client.put(
        f"/api/insight-feedback/{insight_id}",
        json={
            "project_id": project["id"],
            "sentiment": "disagree",
            "reason_codes": [],
            "comment": "Disagree.",
            "insight_type": "risk_sla",
        },
        headers=user_headers,
    )
    assert r.status_code == 200
    feedback_id = r.json()["id"]

    r = await client.post(
        f"/api/insight-feedback/review/{feedback_id}/claim",
        headers=reviewer_headers,
    )
    assert r.status_code == 200
    assert r.json()["reviewer_user_id"] is not None

    # Final disposition without reviewer comment is rejected.
    r = await client.post(
        f"/api/insight-feedback/review/{feedback_id}/disposition",
        json={"review_status": "accepted"},
        headers=reviewer_headers,
    )
    assert r.status_code == 422

    r = await client.post(
        f"/api/insight-feedback/review/{feedback_id}/disposition",
        json={"review_status": "accepted", "reviewer_comment": "Approved."},
        headers=reviewer_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["review_status"] == "accepted"
    assert body["reviewer_comment"] == "Approved."
    assert body["reviewed_at"] is not None


# ─────────────────────────── state-machine / lifecycle ───────────────────────


async def test_agree_feedback_is_not_required_and_absent_from_queue(client, service_headers):
    _, _reviewer, reviewer_headers, _user, user_headers, project = await _setup_reviewer(
        client, service_headers, "fb-agree"
    )
    insight_id = "insight-agree-1"
    r = await client.put(
        f"/api/insight-feedback/{insight_id}",
        json={
            "project_id": project["id"],
            "sentiment": "agree",
            "reason_codes": [],
            "comment": "Looks right.",
            "insight_type": "risk_sla",
        },
        headers=user_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["review_status"] == "not_required"

    r = await client.get("/api/insight-feedback/review/queue", headers=reviewer_headers)
    assert r.status_code == 200
    assert r.json()["total"] == 0


async def test_disagree_creates_pending_review(client, service_headers):
    _, _, reviewer_headers, _, user_headers, project = await _setup_reviewer(
        client, service_headers, "fb-dis"
    )
    insight_id = "insight-dis-1"
    r = await client.put(
        f"/api/insight-feedback/{insight_id}",
        json={
            "project_id": project["id"],
            "sentiment": "disagree",
            "reason_codes": ["incorrect_data"],
            "comment": "Wrong.",
            "insight_type": "risk_sla",
        },
        headers=user_headers,
    )
    assert r.status_code == 200
    assert r.json()["review_status"] == "pending"

    r = await client.get("/api/insight-feedback/review/queue", headers=reviewer_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["review_status"] == "pending"


async def test_claim_acknowledges_and_sets_reviewer(client, service_headers):
    _, _, reviewer_headers, _, user_headers, project = await _setup_reviewer(
        client, service_headers, "fb-claim"
    )
    insight_id = "insight-claim-1"
    r = await client.put(
        f"/api/insight-feedback/{insight_id}",
        json={
            "project_id": project["id"],
            "sentiment": "disagree",
            "reason_codes": ["incorrect_data"],
            "comment": "Wrong.",
            "insight_type": "risk_sla",
        },
        headers=user_headers,
    )
    feedback_id = r.json()["id"]
    r = await client.post(f"/api/insight-feedback/review/{feedback_id}/claim", headers=reviewer_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["review_status"] == "in_review"
    assert body["reviewer_user_id"] is not None
    assert body["acknowledged_at"] is not None


async def test_concurrent_claim_returns_409(client, service_headers):
    _, _reviewer, reviewer_headers, _, user_headers, project = await _setup_reviewer(
        client, service_headers, "fb-conc"
    )
    other = await client.post(
        f"/api/tenants/{project['tenant_id']}/users",
        json={
            "email": "fb-conc-other@test.com",
            "display_name": "Other Reviewer",
            "role": "admin",
            "external_id": "ext-fb-conc-other",
        },
        headers=service_headers,
    )
    assert other.status_code == 201
    other_headers = _headers(project["tenant_id"], other.json()["id"], "admin")

    insight_id = "insight-conc-1"
    r = await client.put(
        f"/api/insight-feedback/{insight_id}",
        json={
            "project_id": project["id"],
            "sentiment": "disagree",
            "reason_codes": ["incorrect_data"],
            "comment": "Wrong.",
            "insight_type": "risk_sla",
        },
        headers=user_headers,
    )
    feedback_id = r.json()["id"]
    r = await client.post(f"/api/insight-feedback/review/{feedback_id}/claim", headers=reviewer_headers)
    assert r.status_code == 200
    r = await client.post(f"/api/insight-feedback/review/{feedback_id}/claim", headers=other_headers)
    assert r.status_code == 409


async def test_release_returns_to_pending(client, service_headers):
    _, _, reviewer_headers, _, user_headers, project = await _setup_reviewer(
        client, service_headers, "fb-rel"
    )
    insight_id = "insight-rel-1"
    r = await client.put(
        f"/api/insight-feedback/{insight_id}",
        json={
            "project_id": project["id"],
            "sentiment": "disagree",
            "reason_codes": ["incorrect_data"],
            "comment": "Wrong.",
            "insight_type": "risk_sla",
        },
        headers=user_headers,
    )
    feedback_id = r.json()["id"]
    await client.post(f"/api/insight-feedback/review/{feedback_id}/claim", headers=reviewer_headers)
    r = await client.post(f"/api/insight-feedback/review/{feedback_id}/release", headers=reviewer_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["review_status"] == "pending"
    assert body["reviewer_user_id"] is None
    assert body["acknowledged_at"] is None


async def test_request_info_and_user_response(client, service_headers):
    _, _, reviewer_headers, _, user_headers, project = await _setup_reviewer(
        client, service_headers, "fb-info"
    )
    insight_id = "insight-info-1"
    r = await client.put(
        f"/api/insight-feedback/{insight_id}",
        json={
            "project_id": project["id"],
            "sentiment": "disagree",
            "reason_codes": ["incorrect_data"],
            "comment": "Wrong.",
            "insight_type": "risk_sla",
        },
        headers=user_headers,
    )
    feedback_id = r.json()["id"]
    await client.post(f"/api/insight-feedback/review/{feedback_id}/claim", headers=reviewer_headers)

    r = await client.post(
        f"/api/insight-feedback/review/{feedback_id}/request-info",
        json={},
        headers=reviewer_headers,
    )
    assert r.status_code == 422

    r = await client.post(
        f"/api/insight-feedback/review/{feedback_id}/request-info",
        json={"reviewer_comment": "Can you provide the source row?"},
        headers=reviewer_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["review_status"] == "needs_more_information"

    r = await client.post(
        f"/api/insight-feedback/{insight_id}/review-response",
        json={"response": ""},
        headers=user_headers,
    )
    assert r.status_code == 422

    r = await client.post(
        f"/api/insight-feedback/{insight_id}/review-response",
        json={"response": "Row 42 shows the correct value."},
        headers=user_headers,
    )
    assert r.status_code == 200
    assert r.json()["review_status"] == "in_review"


async def test_disposition_only_from_in_review(client, service_headers):
    _, _, reviewer_headers, _, user_headers, project = await _setup_reviewer(
        client, service_headers, "fb-disp-sm"
    )
    insight_id = "insight-disp-1"
    r = await client.put(
        f"/api/insight-feedback/{insight_id}",
        json={
            "project_id": project["id"],
            "sentiment": "disagree",
            "reason_codes": ["incorrect_data"],
            "comment": "Wrong.",
            "insight_type": "risk_sla",
        },
        headers=user_headers,
    )
    feedback_id = r.json()["id"]
    r = await client.post(
        f"/api/insight-feedback/review/{feedback_id}/disposition",
        json={"review_status": "accepted", "reviewer_comment": "Approved."},
        headers=reviewer_headers,
    )
    assert r.status_code == 409

    await client.post(f"/api/insight-feedback/review/{feedback_id}/claim", headers=reviewer_headers)
    r = await client.post(
        f"/api/insight-feedback/review/{feedback_id}/disposition",
        json={"review_status": "accepted", "reviewer_comment": "Feedback accepted."},
        headers=reviewer_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["review_status"] == "accepted"
    assert body["reviewed_at"] is not None
    assert body["reviewer_comment"] == "Feedback accepted."


async def test_review_event_audit_trail_is_recorded(client, service_headers, db_session: AsyncSession):
    _, _, reviewer_headers, _, user_headers, project = await _setup_reviewer(
        client, service_headers, "fb-audit"
    )
    insight_id = "insight-audit-1"
    r = await client.put(
        f"/api/insight-feedback/{insight_id}",
        json={
            "project_id": project["id"],
            "sentiment": "disagree",
            "reason_codes": ["incorrect_data"],
            "comment": "Wrong.",
            "insight_type": "risk_sla",
        },
        headers=user_headers,
    )
    feedback_id = r.json()["id"]
    await client.post(f"/api/insight-feedback/review/{feedback_id}/claim", headers=reviewer_headers)
    await client.post(
        f"/api/insight-feedback/review/{feedback_id}/disposition",
        json={"review_status": "rejected", "reviewer_comment": "Numbers verified."},
        headers=reviewer_headers,
    )

    from app.models.insight_feedback import InsightFeedbackReviewEvent

    events = (await db_session.execute(
        select(InsightFeedbackReviewEvent).where(InsightFeedbackReviewEvent.feedback_id == feedback_id)
    )).scalars().all()
    types = {e.event_type for e in events}
    assert "acknowledged" in types
    assert "insight_upheld" in types


async def test_governance_batch_no_private_comments(client, service_headers):
    _, _, reviewer_headers, _, user_headers, project = await _setup_reviewer(
        client, service_headers, "fb-gov"
    )
    insight_id = "insight-gov-1"
    r = await client.put(
        f"/api/insight-feedback/{insight_id}",
        json={
            "project_id": project["id"],
            "sentiment": "disagree",
            "reason_codes": ["incorrect_data"],
            "comment": "Private user comment.",
            "insight_type": "risk_sla",
        },
        headers=user_headers,
    )
    feedback_id = r.json()["id"]
    await client.post(f"/api/insight-feedback/review/{feedback_id}/claim", headers=reviewer_headers)
    await client.post(
        f"/api/insight-feedback/review/{feedback_id}/disposition",
        json={"review_status": "accepted", "reviewer_comment": "Private reviewer note."},
        headers=reviewer_headers,
    )

    r = await client.post(
        "/api/insight-feedback/governance",
        json={"insight_ids": [insight_id], "project_id": project["id"]},
        headers=user_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["governance_status"] in {"Disputed", "Under Review", "Validated", "None"}
    assert "comment" not in item
    assert "reviewer_comment" not in item
