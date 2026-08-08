
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.insight_feedback import InsightFeedback
from app.models.project_action import ProjectAction
from app.models.project_context import (
    ProjectBusinessContext,
    ProjectGoal,
    ProjectMetric,
    ProjectMetricTarget,
    ProjectRisk,
)

logger = logging.getLogger(__name__)

_CHAR_PER_TOKEN = 4
_DEFAULT_TOKEN_BUDGET = 4000
_MAX_TEXT_LENGTH = 4000

_PRIORITY_ORDER = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
}


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // _CHAR_PER_TOKEN)


def _truncate(text: str | None, length: int = _MAX_TEXT_LENGTH) -> str | None:
    if text is None:
        return None
    if len(text) <= length:
        return text
    return text[: length - 3] + "..."


def _format_value(value: float | None) -> str | None:
    if value is None:
        return None
    if value == int(value):
        return str(int(value))
    return f"{value:.4f}"


def _is_target_effective(target: ProjectMetricTarget, now: datetime) -> bool:
    if not target.active or target.status != "active":
        return False
    if target.effective_start and now < target.effective_start:
        return False
    if target.effective_end and now > target.effective_end:
        return False
    return True


async def load_project_context(
    session: AsyncSession, *, tenant_id: int, project_id: int
) -> dict[str, Any]:
    """Load all project context entities needed to build an AI package."""
    settings = await session.scalar(
        select(ProjectBusinessContext).where(
            ProjectBusinessContext.tenant_id == tenant_id,
            ProjectBusinessContext.project_id == project_id,
        )
    )

    goals = (
        await session.scalars(
            select(ProjectGoal)
            .options(
                selectinload(ProjectGoal.metric_links),
                selectinload(ProjectGoal.risk_links),
            )
            .where(
                ProjectGoal.tenant_id == tenant_id,
                ProjectGoal.project_id == project_id,
                ProjectGoal.active.is_(True),
            )
        )
    ).all()

    metrics = (
        await session.scalars(
            select(ProjectMetric)
            .options(selectinload(ProjectMetric.targets))
            .where(
                ProjectMetric.tenant_id == tenant_id,
                ProjectMetric.project_id == project_id,
                ProjectMetric.active.is_(True),
            )
        )
    ).all()

    risks = (
        await session.scalars(
            select(ProjectRisk)
            .options(
                selectinload(ProjectRisk.goal_links),
                selectinload(ProjectRisk.metric_links),
            )
            .where(
                ProjectRisk.tenant_id == tenant_id,
                ProjectRisk.project_id == project_id,
                ProjectRisk.active.is_(True),
            )
        )
    ).all()

    return {
        "settings": settings,
        "goals": goals,
        "metrics": metrics,
        "risks": risks,
    }


_ACTION_PRIORITY_ORDER = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
}

_ACTION_STATUS_ORDER = {
    "blocked": 0,
    "in_progress": 1,
    "not_started": 2,
    "completed": 3,
    "cancelled": 4,
}

_MAX_ACTIONS_IN_CONTEXT = 8
_MAX_SUBTASKS_IN_CONTEXT = 5


async def _load_actions_package(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: int,
    now: datetime,
) -> dict[str, Any]:
    """Load a bounded, fresh actions block for AI context.

    Always loaded from the DB even when the rest of the project context is
    cached, so action/subtask changes are reflected immediately.
    """
    actions = (
        await session.scalars(
            select(ProjectAction)
            .options(selectinload(ProjectAction.subtasks))
            .where(
                ProjectAction.tenant_id == tenant_id,
                ProjectAction.project_id == project_id,
                ProjectAction.archived_at.is_(None),
            )
        )
    ).all()

    sorted_actions = sorted(
        actions,
        key=lambda a: (
            _ACTION_STATUS_ORDER.get(a.status, 99),
            _ACTION_PRIORITY_ORDER.get(a.priority, 99),
            a.due_date is None,
            a.due_date or now,
            a.updated_at,
        ),
    )[:_MAX_ACTIONS_IN_CONTEXT]

    action_packages: list[dict[str, Any]] = []
    blocked_count = 0
    overdue_count = 0
    completed_count = 0

    for a in sorted_actions:
        if a.status == "blocked":
            blocked_count += 1
        if a.due_date and a.due_date < now and a.status not in ("completed", "cancelled"):
            overdue_count += 1
        if a.status == "completed":
            completed_count += 1

        active_required = sorted(
            [s for s in a.subtasks if s.archived_at is None and s.is_required],
            key=lambda s: (
                0 if s.status == "blocked" else 1,
                0 if s.status == "in_progress" else 1,
                s.position,
                s.id,
            ),
        )

        subtask_summaries = []
        for s in active_required[:_MAX_SUBTASKS_IN_CONTEXT]:
            subtask_summaries.append(
                {
                    "id": s.id,
                    "title": _truncate(s.title, 200),
                    "status": s.status,
                    "percent": s.percent_complete,
                    "is_required": s.is_required,
                    "due_overdue": bool(
                        s.due_date and s.due_date < now and s.status not in ("completed", "cancelled")
                    ),
                }
            )

        blocked_subtasks = [s for s in active_required if s.status == "blocked"]
        incomplete_subtasks = [s for s in active_required if s.status != "completed"]

        action_packages.append(
            {
                "id": a.id,
                "title": _truncate(a.title, 200),
                "description": _truncate(a.description),
                "status": a.status,
                "priority": a.priority,
                "percent": a.percent_complete,
                "due_overdue": bool(
                    a.due_date and a.due_date < now and a.status not in ("completed", "cancelled")
                ),
                "source_insight_id": a.source_insight_id,
                "source_insight_type": a.source_insight_type,
                "source_insight_title": _truncate(a.source_insight_title, 200),
                "required_subtasks": subtask_summaries,
                "blocked_subtask_titles": [_truncate(s.title, 200) for s in blocked_subtasks[:5]],
                "incomplete_subtask_count": len(incomplete_subtasks),
                "active_required_subtask_count": len(active_required),
                "subtasks_omitted": max(0, len(active_required) - _MAX_SUBTASKS_IN_CONTEXT),
            }
        )

    omitted = max(0, len(actions) - _MAX_ACTIONS_IN_CONTEXT)

    return {
        "actions": action_packages,
        "actions_omitted": omitted,
        "actions_summary": {
            "total_active": len(actions),
            "blocked": blocked_count,
            "overdue": overdue_count,
            "completed": completed_count,
        },
        "actions_guidance": (
            "Project Actions are user-reported mitigation activity. They are evidence of "
            "planned or ongoing work, not automatic proof that a risk is eliminated. "
            "Blocked, overdue, or low-progress actions may increase concern. Completed "
            "actions may be cited as mitigating evidence, but the model must still weigh "
            "current source data before lowering a risk. Registered risks and AI-detected "
            "Insight cards are distinct concepts; do not invent linkages between them."
        ),
        "actions_provenance": f"Loaded from Project Actions for project {project_id} at {now.isoformat()}",
    }


async def _load_feedback_context(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: int,
    limit: int = 50,
) -> dict[str, Any]:
    """Load governed insight feedback results for the project AI context.

    Only terminal reviewer dispositions are included, with no private submitter
    identity or raw comments. The insight snapshot is identified by insight_id so
    the AI can treat accepted feedback as disputed and upheld feedback as validated.
    """
    rows = (
        await session.execute(
            select(
                InsightFeedback.insight_id,
                InsightFeedback.review_status,
                InsightFeedback.reviewed_at,
            )
            .where(
                InsightFeedback.tenant_id == tenant_id,
                InsightFeedback.project_id == project_id,
                InsightFeedback.status == "active",
                InsightFeedback.review_status.in_(
                    ["accepted", "rejected", "pending", "in_review", "needs_more_information"]
                ),
            )
            .order_by(InsightFeedback.updated_at.desc())
            .limit(limit)
        )
    ).all()

    items = []
    for insight_id, review_status, reviewed_at in rows:
        label = {
            "accepted": "disputed",
            "rejected": "validated",
            "pending": "under_review",
            "in_review": "under_review",
            "needs_more_information": "under_review",
        }.get(review_status, review_status)
        items.append(
            {
                "insight_id": insight_id,
                "governance_label": label,
                "reviewed_at": reviewed_at.isoformat() if reviewed_at else None,
            }
        )

    return {
        "count": len(items),
        "items": items,
        "instruction": (
            "Insight feedback is governed human review. Accepted feedback means the "
            "insight is disputed and should be regenerated before being relied upon. "
            "Upheld feedback means the insight was validated by a reviewer. "
            "Pending or in-review feedback means the insight is under review."
        ),
    }
