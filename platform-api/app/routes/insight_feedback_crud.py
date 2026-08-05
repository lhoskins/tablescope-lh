"""Human feedback API for AI-generated insights — submitter-facing CRUD.

Every endpoint is strictly scoped to the authenticated tenant and user.
Feedback is returned only for the current user; it is never aggregated or
shown to other users, and it is never used to automatically retrain the model.

The reviewer workflow lives in ``insight_feedback_review.py``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models.insight_feedback import InsightFeedback, InsightFeedbackReviewEvent
from app.routes.home_pins import _require_project_access

router = APIRouter(prefix="/insight-feedback", tags=["Insight Feedback"])

# Sentiment vocabulary. Only ``agree`` and ``disagree`` are accepted for a
# concrete feedback record; a DELETE removes the record entirely.
SENTIMENT_AGREE = "agree"
SENTIMENT_DISAGREE = "disagree"
_VALID_SENTIMENTS = {SENTIMENT_AGREE, SENTIMENT_DISAGREE}

# Controlled reason codes users can attach to feedback. The UI owns the labels;
# the API only validates the code keys.
REASON_CODE_LABELS = {
    "incorrect_data": "The data looks incorrect or incomplete",
    "missing_context": "Important context is missing",
    "wrong_method": "The analytical method doesn't fit",
    "not_actionable": "The insight is not actionable",
    "disagree_conclusion": "I disagree with the conclusion",
    "too_confident": "The confidence is too high",
    "other": "Other",
}
_VALID_REASON_CODES = set(REASON_CODE_LABELS)

_STATUS_ACTIVE = "active"
_STATUS_WITHDRAWN = "withdrawn"

# Reviewer workflow states.
_REVIEW_STATUS_NOT_REQUIRED = "not_required"
_REVIEW_STATUS_PENDING = "pending"
_REVIEW_STATUS_IN_REVIEW = "in_review"
_REVIEW_STATUS_NEEDS_MORE_INFO = "needs_more_information"
_REVIEW_STATUS_ACCEPTED = "accepted"
_REVIEW_STATUS_REJECTED = "rejected"
_VALID_REVIEW_STATUSES = {
    _REVIEW_STATUS_NOT_REQUIRED,
    _REVIEW_STATUS_PENDING,
    _REVIEW_STATUS_IN_REVIEW,
    _REVIEW_STATUS_NEEDS_MORE_INFO,
    _REVIEW_STATUS_ACCEPTED,
    _REVIEW_STATUS_REJECTED,
}
_FINAL_REVIEW_STATUSES = {_REVIEW_STATUS_ACCEPTED, _REVIEW_STATUS_REJECTED}

# Review event types for the immutable audit trail.
_EVENT_AGREE_SAVED = "agree_saved"
_EVENT_DISAGREE_SUBMITTED = "disagree_submitted"
_EVENT_EDITED = "feedback_edited"
_EVENT_WITHDRAWN = "withdrawn"
_EVENT_ACKNOWLEDGED = "acknowledged"
_EVENT_RELEASED = "released"
_EVENT_INFO_REQUESTED = "information_requested"
_EVENT_USER_RESPONDED = "user_responded"
_EVENT_FEEDBACK_ACCEPTED = "feedback_accepted"
_EVENT_INSIGHT_UPHELD = "insight_upheld"
_EVENT_ADMIN_REOPEN = "admin_reopen"

_PERMISSION_REVIEW = "insight_feedback.review"


def _log_review_event(
    session: AsyncSession,
    row: InsightFeedback,
    event_type: str,
    from_status: str | None,
    to_status: str | None,
    actor_user_id: int,
    comment: str | None = None,
    response: str | None = None,
) -> None:
    session.add(
        InsightFeedbackReviewEvent(
            tenant_id=row.tenant_id,
            project_id=row.project_id,
            feedback_id=row.id,
            insight_id=row.insight_id,
            event_type=event_type,
            from_review_status=from_status,
            to_review_status=to_status,
            actor_user_id=actor_user_id,
            comment=comment,
            response=response,
            feedback_revision=row.feedback_revision,
        )
    )


class InsightFeedbackResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    id: int
    insight_id: str
    project_id: int | None
    insight_type: str | None
    sentiment: str
    reason_codes: list[str] = Field(default_factory=list)
    comment: str | None
    status: str
    review_status: str
    reviewer_user_id: int | None
    reviewer_comment: str | None
    response: str | None
    reviewed_at: str | None
    acknowledged_at: str | None
    feedback_revision: int
    created_at: str
    updated_at: str


class InsightFeedbackBatchRequest(BaseModel):
    insight_ids: list[str] = Field(..., min_length=1, max_length=200)

    @field_validator("insight_ids")
    @classmethod
    def _dedupe_and_trim(cls, v: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for insight_id in v:
            if not insight_id:
                raise ValueError("insight_ids must not contain empty strings")
            tid = insight_id.strip()
            if tid not in seen:
                seen.add(tid)
                out.append(tid)
        if not out:
            raise ValueError("insight_ids must not be empty")
        return out


class InsightFeedbackBatchResponse(BaseModel):
    items: list[InsightFeedbackResponse]


class InsightFeedbackUpsertRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    project_id: int
    sentiment: str
    reason_codes: list[str] = Field(default_factory=list)
    comment: str
    snapshot_id: str | None = None
    run_id: str | None = None
    insight_type: str | None = None
    insight_fingerprint: str | None = None
    card_snapshot: dict[str, Any] | None = None
    explanation_snapshot: dict[str, Any] | None = None
    model_metadata: dict[str, Any] | None = None

    @field_validator("sentiment")
    @classmethod
    def _validate_sentiment(cls, v: str) -> str:
        s = (v or "").strip().lower()
        if s not in _VALID_SENTIMENTS:
            raise ValueError(f"sentiment must be one of: {', '.join(_VALID_SENTIMENTS)}")
        return s

    @field_validator("reason_codes")
    @classmethod
    def _validate_reason_codes(cls, v: list[str]) -> list[str]:
        for code in v:
            if code not in _VALID_REASON_CODES:
                raise ValueError(f"invalid reason_code: {code}")
        return v

    @field_validator("comment")
    @classmethod
    def _validate_comment(cls, v: str) -> str:
        if not isinstance(v, str):
            raise ValueError("comment is required")
        v = v.strip()
        if not v:
            raise ValueError("comment is required and cannot be whitespace")
        if len(v) > 4000:
            raise ValueError("comment must not exceed 4000 characters")
        return v


def _to_response(row: InsightFeedback) -> InsightFeedbackResponse:
    return InsightFeedbackResponse(
        id=row.id,
        insight_id=row.insight_id,
        project_id=row.project_id,
        insight_type=row.insight_type,
        sentiment=row.sentiment,
        reason_codes=row.reason_codes or [],
        comment=row.comment,
        status=row.status,
        review_status=row.review_status,
        reviewer_user_id=row.reviewer_user_id,
        reviewer_comment=row.reviewer_comment,
        response=row.response,
        reviewed_at=row.reviewed_at.isoformat() if row.reviewed_at else None,
        acknowledged_at=row.acknowledged_at.isoformat() if row.acknowledged_at else None,
        feedback_revision=row.feedback_revision,
        created_at=row.created_at.isoformat() if row.created_at else "",
        updated_at=row.updated_at.isoformat() if row.updated_at else "",
    )


@router.get("/{insight_id}", response_model=InsightFeedbackResponse | None)
async def get_insight_feedback(
    insight_id: str,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> InsightFeedbackResponse | None:
    """Return the current user's feedback for a single insight."""
    row = await session.scalar(
        select(InsightFeedback).where(
            InsightFeedback.tenant_id == context.tenant_id,
            InsightFeedback.user_id == context.user_id,
            InsightFeedback.insight_id == insight_id,
            InsightFeedback.status == _STATUS_ACTIVE,
        )
    )
    if row is None:
        return None
    return _to_response(row)


@router.post("/batch", response_model=InsightFeedbackBatchResponse)
async def batch_get_insight_feedback(
    body: InsightFeedbackBatchRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> InsightFeedbackBatchResponse:
    """Return the current user's active feedback for up to 200 insight IDs."""
    rows = (
        await session.execute(
            select(InsightFeedback).where(
                InsightFeedback.tenant_id == context.tenant_id,
                InsightFeedback.user_id == context.user_id,
                InsightFeedback.insight_id.in_(body.insight_ids),
                InsightFeedback.status == _STATUS_ACTIVE,
            )
        )
    ).scalars().all()
    return InsightFeedbackBatchResponse(items=[_to_response(row) for row in rows])


@router.put("/{insight_id}", response_model=InsightFeedbackResponse)
async def upsert_insight_feedback(
    insight_id: str,
    body: InsightFeedbackUpsertRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> InsightFeedbackResponse:
    """Create or update the current user's feedback for an insight."""
    await _require_project_access(session, context, body.project_id)

    row = await session.scalar(
        select(InsightFeedback).where(
            InsightFeedback.tenant_id == context.tenant_id,
            InsightFeedback.user_id == context.user_id,
            InsightFeedback.insight_id == insight_id,
        )
    )
    existing = row is not None
    if row is None:
        row = InsightFeedback(
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            project_id=body.project_id,
            insight_id=insight_id,
            feedback_revision=1,
        )
        session.add(row)

    is_material_edit = existing and row.status == _STATUS_ACTIVE
    previous_status = row.review_status

    row.project_id = body.project_id
    row.sentiment = body.sentiment
    row.reason_codes = list(body.reason_codes) if body.reason_codes else []
    row.comment = body.comment.strip()
    row.snapshot_id = body.snapshot_id
    row.run_id = body.run_id
    row.insight_type = body.insight_type
    row.insight_fingerprint = body.insight_fingerprint
    row.card_snapshot = body.card_snapshot
    row.explanation_snapshot = body.explanation_snapshot
    row.model_metadata = body.model_metadata
    row.status = _STATUS_ACTIVE
    row.response = None

    if body.sentiment == SENTIMENT_AGREE:
        row.review_status = _REVIEW_STATUS_NOT_REQUIRED
        row.reviewer_user_id = None
        row.reviewer_comment = None
        row.reviewed_at = None
        row.acknowledged_at = None
        event_type = _EVENT_AGREE_SAVED if not is_material_edit else _EVENT_EDITED
    else:
        # Disagreement enters the review workflow. A material edit to an
        # existing disagreement starts a new revision and requeues it.
        if is_material_edit:
            row.feedback_revision += 1
            event_type = _EVENT_EDITED
        else:
            event_type = _EVENT_DISAGREE_SUBMITTED
        row.review_status = _REVIEW_STATUS_PENDING
        row.reviewer_user_id = None
        row.reviewer_comment = None
        row.reviewed_at = None
        row.acknowledged_at = None

    await session.flush()
    _log_review_event(
        session,
        row,
        event_type,
        previous_status if is_material_edit else None,
        row.review_status,
        context.user_id,
    )

    await session.commit()
    await session.refresh(row)
    return _to_response(row)


@router.delete(
    "/{insight_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_insight_feedback(
    insight_id: str,
    project_id: int | None = None,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> None:
    """Withdraw the current user's feedback for an insight."""
    row = await session.scalar(
        select(InsightFeedback).where(
            InsightFeedback.tenant_id == context.tenant_id,
            InsightFeedback.user_id == context.user_id,
            InsightFeedback.insight_id == insight_id,
            InsightFeedback.status == _STATUS_ACTIVE,
        )
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Feedback not found",
        )

    check_project_id = project_id if project_id is not None else row.project_id
    await _require_project_access(session, context, check_project_id)

    previous_status = row.review_status
    row.status = _STATUS_WITHDRAWN
    row.review_status = _REVIEW_STATUS_PENDING
    row.reviewer_user_id = None
    row.reviewer_comment = None
    row.response = None
    row.reviewed_at = None
    row.acknowledged_at = None
    _log_review_event(
        session,
        row,
        _EVENT_WITHDRAWN,
        previous_status,
        row.review_status,
        context.user_id,
    )
    await session.commit()
