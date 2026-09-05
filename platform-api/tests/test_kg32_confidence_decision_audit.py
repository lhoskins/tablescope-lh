"""KG-32: durable capture of AI confidence vs. the human decision made on it.

Validated gap: ``document_families_curation.py``'s accept/change/remove
routes only ever reported the (AI confidence, human decision) pair through
``log_family_event`` -- a log line, not a queryable table -- and the
original AI-suggested confidence was overwritten/discarded on ``ai_metadata``
the instant the decision was applied, with nothing durable left to calibrate
against later. This is groundwork only: it makes those pairs queryable; it
does not itself compute a calibration report.

Run from ``platform-api``:
``pytest -q tests/test_kg32_confidence_decision_audit.py``.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.auth.context import RequestContext
from app.auth.jwt import TokenClaims
from app.models import AiConfidenceDecision, Project, ProjectAsset
from app.routes.document_families_curation import (
    AcceptFamilyRequest,
    ChangeFamilyRequest,
    accept_family,
    change_family,
    remove_family,
)

pytestmark = pytest.mark.anyio


def _context(tenant_id: int, user_id: int) -> RequestContext:
    return RequestContext(
        claims=TokenClaims(sub=str(user_id), tenant_id=tenant_id, user_id=user_id, role="editor")
    )


async def _project_and_asset(db_session, *, tenant_id: int, user_id: int, ai_metadata=None):
    project = Project(tenant_id=tenant_id, name="kg32 Project", owner_id=user_id, is_shared=False)
    db_session.add(project)
    await db_session.flush()
    asset = ProjectAsset(
        tenant_id=tenant_id, project_id=project.id, owner_user_id=user_id,
        asset_type="document", source_type="uploaded_file",
        title="Doc", filename="doc.pdf", storage_location="doc.pdf",
        ai_metadata=ai_metadata,
    )
    db_session.add(asset)
    await db_session.flush()
    return project, asset


async def _decisions(db_session, project_id: int) -> list[AiConfidenceDecision]:
    rows = (
        await db_session.execute(
            select(AiConfidenceDecision).where(AiConfidenceDecision.project_id == project_id)
        )
    ).scalars().all()
    return list(rows)


async def test_accept_records_the_ai_suggested_confidence(db_session):
    tenant_id, user_id = 301, 1
    project, asset = await _project_and_asset(
        db_session, tenant_id=tenant_id, user_id=user_id,
        ai_metadata={
            "document_family": {
                "family_name": "Quality Manual", "family_key": "quality_manual",
                "family_type": "policy", "confidence": 0.82, "role": "governing",
                "reason": "AI suggestion.",
            },
        },
    )
    context = _context(tenant_id, user_id)
    await accept_family(
        project.id, asset.id, AcceptFamilyRequest(), db_session, context,
    )
    decisions = await _decisions(db_session, project.id)
    assert len(decisions) == 1
    assert decisions[0].human_decision == "accepted"
    assert decisions[0].source_pipeline == "document_family"
    assert decisions[0].ai_confidence_at_decision == pytest.approx(0.82)
    assert decisions[0].asset_id == asset.id
    assert decisions[0].decided_by == user_id


async def test_change_records_the_prior_ai_confidence_not_the_new_one(db_session):
    tenant_id, user_id = 302, 1
    project, asset = await _project_and_asset(
        db_session, tenant_id=tenant_id, user_id=user_id,
        ai_metadata={
            "document_family": {
                "family_name": "Old Family", "family_key": "old_family",
                "family_type": "policy", "confidence": 0.55, "role": "governing",
                "reason": "AI suggestion.",
            },
        },
    )
    context = _context(tenant_id, user_id)
    await change_family(
        project.id, asset.id,
        ChangeFamilyRequest(family_name="New Family", confidence=1.0),
        db_session, context,
    )
    decisions = await _decisions(db_session, project.id)
    assert len(decisions) == 1
    assert decisions[0].human_decision == "changed"
    # The AI's *original* confidence is recorded, not the human's override.
    assert decisions[0].ai_confidence_at_decision == pytest.approx(0.55)


async def test_remove_with_no_prior_ai_suggestion_records_null_confidence(db_session):
    tenant_id, user_id = 303, 1
    project, asset = await _project_and_asset(
        db_session, tenant_id=tenant_id, user_id=user_id, ai_metadata=None,
    )
    context = _context(tenant_id, user_id)
    await remove_family(project.id, asset.id, db_session, context)
    decisions = await _decisions(db_session, project.id)
    assert len(decisions) == 1
    assert decisions[0].human_decision == "removed"
    assert decisions[0].ai_confidence_at_decision is None
