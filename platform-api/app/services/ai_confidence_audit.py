"""KG-32: write path for the AI-confidence-vs-human-decision audit trail.

Called once per human accept/change/remove decision on an AI-suggested
Knowledge Graph edge (document-family curation today), so the model's own
confidence at the moment of that decision survives the decision itself
instead of being discarded the instant it's applied. Groundwork only: a
future calibration pass would query this table, but nothing here computes
one -- there is no historical labeled dataset yet to calibrate against.

Best-effort by design: an audit-write failure must never break the curation
action it's auditing.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_confidence_decision import AiConfidenceDecision

logger = logging.getLogger(__name__)


async def record_ai_confidence_decision(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: int,
    asset_id: int | None,
    source_pipeline: str,
    ai_confidence_at_decision: float | None,
    human_decision: str,
    decided_by: int | None,
) -> None:
    """Persist one (AI confidence, human decision) pair.

    Best-effort: never raises into the caller.
    """
    try:
        session.add(
            AiConfidenceDecision(
                tenant_id=tenant_id,
                project_id=project_id,
                asset_id=asset_id,
                source_pipeline=source_pipeline,
                ai_confidence_at_decision=ai_confidence_at_decision,
                human_decision=human_decision,
                decided_by=decided_by,
            )
        )
        await session.flush()
    except Exception:
        logger.exception(
            "Failed to record AI confidence decision for project %s asset %s",
            project_id, asset_id,
        )
