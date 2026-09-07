"""Closed-loop AI action proposals grounded in refreshed insight cards."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_event import AuditEvent
from app.models.project import Project
from app.models.project_action import ProjectAction, ProjectActionSubtask
from app.models.project_context.goals import ProjectGoal
from app.models.project_context.metrics import ProjectMetric
from app.routes.project_actions_shared import _insight_fingerprint
from app.services.ai_intelligence_client import AIUnavailableError, generate_action_draft

logger = logging.getLogger(__name__)
_CARD_KEYS = ("risks", "trends", "opportunities", "analysis")


def project_insight_cards(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract only canonical project-insight cards from a report payload."""
    cards: list[dict[str, Any]] = []
    for key in _CARD_KEYS:
        value = payload.get(key)
        if isinstance(value, list):
            cards.extend(card for card in value if isinstance(card, dict))
    return cards


def _action_text(card: dict[str, Any]) -> str:
    recommended = card.get("recommendedAction") or card.get("recommended_action")
    if isinstance(recommended, str) and recommended.strip():
        return recommended.strip()
    callout = card.get("callout")
    if isinstance(callout, dict) and isinstance(callout.get("text"), str):
        return callout["text"].strip()
    return ""


def _card_id(card: dict[str, Any]) -> str | None:
    value = card.get("insightId") or card.get("id")
    return str(value) if value not in (None, "") else None


def _snapshot(card: dict[str, Any], action_text: str) -> dict[str, Any]:
    return {
        **card,
        "recommended_action": action_text,
        "captured_at": datetime.now(UTC).isoformat(),
    }


async def sync_ai_action_proposals(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: int,
    user_id: int,
    cards: list[dict[str, Any]],
    source_surface: str,
    kg_version_id: int | None = None,
    max_new_proposals: int = 3,
) -> int:
    """Ground completed actions, then create deduplicated human-review proposals."""
    project = await session.get(Project, project_id)
    if project is None or project.tenant_id != tenant_id:
        return 0

    now = datetime.now(UTC)
    actions = (
        await session.scalars(
            select(ProjectAction).where(
                ProjectAction.tenant_id == tenant_id,
                ProjectAction.project_id == project_id,
                ProjectAction.deleted_at.is_(None),
            )
        )
    ).all()
    goals = (
        await session.scalars(
            select(ProjectGoal).where(
                ProjectGoal.tenant_id == tenant_id,
                ProjectGoal.project_id == project_id,
                ProjectGoal.active.is_(True),
            )
        )
    ).all()
    metrics = (
        await session.scalars(
            select(ProjectMetric).where(
                ProjectMetric.tenant_id == tenant_id,
                ProjectMetric.project_id == project_id,
                ProjectMetric.active.is_(True),
            )
        )
    ).all()

    by_id = {_card_id(card): card for card in cards if _card_id(card)}
    for action in actions:
        if action.status != "completed" or action.outcome_status not in {"awaiting_refresh", "grounded"}:
            continue
        card = by_id.get(action.source_insight_id)
        if card is None:
            for candidate in cards:
                fingerprint = _insight_fingerprint(
                    project_id,
                    candidate.get("insightType") or candidate.get("insight_type"),
                    candidate.get("title"),
                    candidate,
                )
                if fingerprint and fingerprint == action.source_insight_fingerprint:
                    card = candidate
                    break
        if card is not None:
            previous = action.outcome_snapshot or {}
            surfaces = dict(previous.get("surfaces") or {})
            surfaces[source_surface] = card
            action.outcome_snapshot = {
                "sourceSurface": source_surface,
                "kgVersionId": kg_version_id,
                "capturedAt": now.isoformat(),
                "updatedInsight": card,
                "surfaces": surfaces,
            }
            action.outcome_status = "grounded"
            action.outcome_refreshed_at = now
            action.lock_version += 1

    existing_ids = {a.source_insight_id for a in actions if a.source_insight_id}
    existing_fingerprints = {
        a.source_insight_fingerprint for a in actions if a.source_insight_fingerprint
    }
    created = 0
    for card in cards:
        if created >= max_new_proposals:
            break
        action_text = _action_text(card)
        title = str(card.get("title") or "").strip()
        if not title or not action_text:
            continue
        insight_id = _card_id(card)
        insight_type = str(card.get("insightType") or card.get("insight_type") or "insight")
        snapshot = _snapshot(card, action_text)
        fingerprint = _insight_fingerprint(project_id, insight_type, title, snapshot)
        if (insight_id and insight_id in existing_ids) or (
            fingerprint and fingerprint in existing_fingerprints
        ):
            continue
        try:
            draft = await generate_action_draft(
                tenant_id=tenant_id,
                user_id=user_id,
                project_id=project_id,
                insight={
                    "insight_type": insight_type,
                    "title": title,
                    "summary": str(card.get("summary") or ""),
                    "recommended_action": action_text,
                    "severity": str(card.get("severity") or "info"),
                    "sources": card.get("sources") or {},
                    "supporting_sources": card.get("supportingSources") or [],
                    "explanation": card.get("explanation"),
                },
            )
        except AIUnavailableError:
            logger.info("AI action proposal skipped: generator unavailable")
            break
        if not isinstance(draft, dict):
            continue

        criteria = draft.get("success_criteria") or draft.get("successCriteria") or []
        first_criterion = criteria[0] if criteria and isinstance(criteria[0], dict) else {}
        requested_goal = str(draft.get("goal_title") or draft.get("goalTitle") or "").strip().casefold()
        requested_metric = str(first_criterion.get("name") or "").strip().casefold()
        matched_metric = next(
            (metric for metric in metrics if metric.name.strip().casefold() == requested_metric),
            None,
        )
        matched_goal = next(
            (goal for goal in goals if requested_goal and goal.title.strip().casefold() == requested_goal),
            None,
        )
        if matched_goal is None and matched_metric is not None and matched_metric.success_criterion_id:
            matched_goal = next(
                (goal for goal in goals if goal.id == matched_metric.success_criterion_id),
                None,
            )
        proposal = ProjectAction(
            tenant_id=tenant_id,
            project_id=project_id,
            title=str(draft.get("title") or action_text)[:500],
            description=str(draft.get("description") or card.get("summary") or "") or None,
            status="pending_review",
            priority=str(draft.get("priority") or "medium").lower()
            if str(draft.get("priority") or "medium").lower() in {"low", "medium", "high", "critical"}
            else "medium",
            reviewer_user_id=project.owner_id,
            goal_id=matched_goal.id if matched_goal else None,
            primary_metric_id=matched_metric.id if matched_metric else None,
            source_type="ai_proposal",
            source_insight_id=insight_id,
            source_insight_fingerprint=fingerprint,
            source_insight_type=insight_type,
            source_insight_title=title,
            source_insight_snapshot=snapshot,
            source_surface=source_surface,
            proposal_metadata={
                "generatedAt": now.isoformat(),
                "kgVersionId": kg_version_id,
                "successCriteria": criteria,
                "goalTitle": matched_goal.title if matched_goal else draft.get("goal_title") or draft.get("goalTitle"),
                "metricName": matched_metric.name if matched_metric else first_criterion.get("name"),
                "hypothesis": draft.get("hypothesis"),
                "duplicateCheck": "No matching open or completed action",
            },
            outcome_status="awaiting_review",
            created_by_user_id=user_id,
            updated_by_user_id=user_id,
        )
        session.add(proposal)
        await session.flush()
        subtasks = draft.get("subtasks") or []
        for index, item in enumerate(subtasks[:10]):
            if not isinstance(item, dict) or not str(item.get("title") or "").strip():
                continue
            session.add(
                ProjectActionSubtask(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    action_id=proposal.id,
                    title=str(item["title"]).strip()[:500],
                    description=item.get("description"),
                    position=index,
                    is_required=bool(item.get("is_required", True)),
                    effort_points=item.get("effort_points"),
                    created_by_user_id=user_id,
                    updated_by_user_id=user_id,
                )
            )
        session.add(
            AuditEvent(
                tenant_id=tenant_id,
                project_id=project_id,
                user_id=user_id,
                event_type="project_action_ai_proposed",
                scope="project_action",
                prompt_type=str(proposal.id),
                title=proposal.title,
                tables_queried=[],
                documents_read=[],
                duration_ms=None,
            )
        )
        created += 1
        if insight_id:
            existing_ids.add(insight_id)
        if fingerprint:
            existing_fingerprints.add(fingerprint)

    await session.commit()
    return created
