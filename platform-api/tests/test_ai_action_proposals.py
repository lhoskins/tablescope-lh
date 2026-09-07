"""Tests for automatic insight-to-action proposal synchronization."""

from __future__ import annotations

from sqlalchemy import select

from app.models.project import Project
from app.models.project_action import ProjectAction
from app.models.tenant import Tenant
from app.models.user import User
from app.services.ai_action_proposals import sync_ai_action_proposals


async def test_sync_creates_one_deduplicated_pending_proposal(db_session, monkeypatch):
    tenant = Tenant(slug="proposal-sync", name="Proposal Sync")
    db_session.add(tenant)
    await db_session.flush()
    user = User(tenant_id=tenant.id, email="owner@example.com", role="editor")
    db_session.add(user)
    await db_session.flush()
    project = Project(tenant_id=tenant.id, owner_id=user.id, name="Supplier Quality")
    db_session.add(project)
    await db_session.commit()

    async def fake_draft(**_kwargs):
        return {
            "title": "Escalate chronic late deliveries",
            "description": "Work the grounded late-delivery cohort.",
            "priority": "high",
            "subtasks": [{"title": "Validate late orders"}],
            "success_criteria": [
                {
                    "name": "On-time delivery",
                    "target_value": 95,
                    "unit": "%",
                    "cadence": "weekly",
                }
            ],
        }

    monkeypatch.setattr(
        "app.services.ai_action_proposals.generate_action_draft", fake_draft
    )
    cards = [
        {
            "insightId": "risk-late-shipments",
            "insightType": "risk",
            "title": "Late deliveries exceed SLA",
            "summary": "Late deliveries reached 18%.",
            "recommendedAction": "Escalate chronic late deliveries.",
            "severity": "critical",
            "sources": {"tables": ["shipments"]},
        }
    ]

    first = await sync_ai_action_proposals(
        db_session,
        tenant_id=tenant.id,
        project_id=project.id,
        user_id=user.id,
        cards=cards,
        source_surface="business_insight",
        kg_version_id=4,
    )
    second = await sync_ai_action_proposals(
        db_session,
        tenant_id=tenant.id,
        project_id=project.id,
        user_id=user.id,
        cards=cards,
        source_surface="business_insight",
        kg_version_id=4,
    )

    assert first == 1
    assert second == 0
    actions = (await db_session.scalars(select(ProjectAction))).all()
    assert len(actions) == 1
    assert actions[0].status == "pending_review"
    assert actions[0].reviewer_user_id == user.id
    assert actions[0].source_insight_id == "risk-late-shipments"
    assert actions[0].proposal_metadata["kgVersionId"] == 4


async def test_refresh_grounding_keeps_both_insight_surfaces(db_session, monkeypatch):
    tenant = Tenant(slug="proposal-outcome", name="Proposal Outcome")
    db_session.add(tenant)
    await db_session.flush()
    user = User(tenant_id=tenant.id, email="owner2@example.com", role="editor")
    db_session.add(user)
    await db_session.flush()
    project = Project(tenant_id=tenant.id, owner_id=user.id, name="Delivery")
    db_session.add(project)
    await db_session.flush()
    action = ProjectAction(
        tenant_id=tenant.id,
        project_id=project.id,
        title="Improve SLA",
        status="completed",
        source_type="ai_proposal",
        source_insight_id="sla-risk",
        source_insight_title="SLA risk",
        outcome_status="awaiting_refresh",
    )
    db_session.add(action)
    await db_session.commit()

    card = {
        "insightId": "sla-risk",
        "title": "SLA risk reduced",
        "summary": "Late deliveries fell to 4%.",
    }
    for surface in ("business_insight", "project_insight"):
        await sync_ai_action_proposals(
            db_session,
            tenant_id=tenant.id,
            project_id=project.id,
            user_id=user.id,
            cards=[card],
            source_surface=surface,
        )

    await db_session.refresh(action)
    assert action.outcome_status == "grounded"
    assert set(action.outcome_snapshot["surfaces"]) == {
        "business_insight",
        "project_insight",
    }

