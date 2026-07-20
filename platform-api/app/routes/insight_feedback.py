"""Human feedback API for AI-generated insights.

Every endpoint is strictly scoped to the authenticated tenant and user.
Feedback is returned only for the current user; it is never aggregated or
exposed to other users, and it is never used to automatically retrain the model.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, has_role, require_role
from app.database import get_db
from app.models.insight_feedback import InsightFeedback
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

# Reviewer workflow states. User-submitted feedback always starts as ``pending``.
_REVIEW_STATUS_PENDING = "pending"
_REVIEW_STATUS_ACCEPTED = "accepted"
_REVIEW_STATUS_REJECTED = "rejected"
_REVIEW_STATUS_NEEDS_MORE_INFO = "needs_more_information"
_VALID_REVIEW_STATUSES = {
    _REVIEW_STATUS_PENDING,
    _REVIEW_STATUS_ACCEPTED,
    _REVIEW_STATUS_REJECTED,
    _REVIEW_STATUS_NEEDS_MORE_INFO,
}
_FINAL_REVIEW_STATUSES = {_REVIEW_STATUS_ACCEPTED, _REVIEW_STATUS_REJECTED, _REVIEW_STATUS_NEEDS_MORE_INFO}

_PERMISSION_REVIEW = "insight_feedback.review"


class InsightFeedbackResponse(BaseModel):
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
    reviewed_at: str | None
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
        reviewed_at=row.reviewed_at.isoformat() if row.reviewed_at else None,
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
    if row is None:
        row = InsightFeedback(
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            project_id=body.project_id,
            insight_id=insight_id,
        )
        session.add(row)

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
    # User edits reset the review workflow so the new submission is re-examined.
    row.review_status = _REVIEW_STATUS_PENDING
    row.reviewer_user_id = None
    row.reviewer_comment = None
    row.reviewed_at = None

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

    # Re-validate project access using the stored project_id when the client
    # did not supply one; either way the user must still be able to reach it.
    check_project_id = project_id if project_id is not None else row.project_id
    await _require_project_access(session, context, check_project_id)

    # Soft-delete by status; the unique constraint stays valid and the user can
    # later re-submit feedback. Preserve the review audit trail.
    row.status = _STATUS_WITHDRAWN
    row.review_status = _REVIEW_STATUS_PENDING
    row.reviewer_user_id = None
    row.reviewer_comment = None
    row.reviewed_at = None
    await session.commit()


# ───────────────────────────── reviewer workflow ─────────────────────────────


def _can_review_feedback(context: RequestContext) -> bool:
    """True when the caller is an explicit reviewer or an admin.

    The permission list is the preferred gate; the role fallback is a safe
    initial mapping until a dedicated permission-assignment UI exists.
    """
    return context.has_permission(_PERMISSION_REVIEW) or has_role(
        context.role, Role.ADMIN
    )


async def _require_project_access_for_review(
    session: AsyncSession,
    context: RequestContext,
    project_id: int | None,
) -> None:
    """Enforce project access for reviewers.

    Tenant admins may review feedback for any project in the tenant; other
    reviewers must be members of the specific project.
    """
    if has_role(context.role, Role.ADMIN):
        return
    await _require_project_access(session, context, project_id)


def _require_insight_reviewer(context: RequestContext) -> None:
    if not _can_review_feedback(context):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insight feedback reviewer access required",
        )


class InsightFeedbackReviewResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    id: int
    user_id: int
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
    reviewed_at: str | None
    created_at: str
    updated_at: str
    card_snapshot: dict[str, Any] | None = None
    explanation_snapshot: dict[str, Any] | None = None


def _to_review_response(row: InsightFeedback) -> InsightFeedbackReviewResponse:
    return InsightFeedbackReviewResponse(
        id=row.id,
        user_id=row.user_id,
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
        reviewed_at=row.reviewed_at.isoformat() if row.reviewed_at else None,
        created_at=row.created_at.isoformat() if row.created_at else "",
        updated_at=row.updated_at.isoformat() if row.updated_at else "",
        card_snapshot=row.card_snapshot,
        explanation_snapshot=row.explanation_snapshot,
    )


class InsightFeedbackReviewQueueParams:
    def __init__(
        self,
        review_status: str | None = Query(None),
        project_id: int | None = Query(None),
        sentiment: str | None = Query(None),
        limit: int = Query(100, ge=1, le=500),
        offset: int = Query(0, ge=0),
    ) -> None:
        self.review_status = review_status
        self.project_id = project_id
        self.sentiment = sentiment
        self.limit = limit
        self.offset = offset


class InsightFeedbackReviewQueueResponse(BaseModel):
    items: list[InsightFeedbackReviewResponse]
    total: int


class InsightFeedbackDispositionRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    review_status: str
    reviewer_comment: str | None = None

    @field_validator("review_status")
    @classmethod
    def _validate_review_status(cls, v: str) -> str:
        s = (v or "").strip().lower()
        if s not in _VALID_REVIEW_STATUSES:
            raise ValueError(
                f"review_status must be one of: {', '.join(_VALID_REVIEW_STATUSES)}"
            )
        return s

    @field_validator("reviewer_comment")
    @classmethod
    def _validate_reviewer_comment(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            if len(v) > 4000:
                raise ValueError("reviewer_comment must not exceed 4000 characters")
        return v


@router.get("/review/queue", response_model=InsightFeedbackReviewQueueResponse)
async def get_review_queue(
    params: InsightFeedbackReviewQueueParams = Depends(),
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> InsightFeedbackReviewQueueResponse:
    """List feedback submitted by users in the current tenant.

    Filterable by review status, project, and sentiment. Tenant and project
    access are enforced; reviewers only see feedback from tenants they belong to.
    """
    _require_insight_reviewer(context)

    where = [
        InsightFeedback.tenant_id == context.tenant_id,
    ]
    if params.review_status:
        where.append(InsightFeedback.review_status == params.review_status.lower())
    if params.project_id is not None:
        await _require_project_access_for_review(session, context, params.project_id)
        where.append(InsightFeedback.project_id == params.project_id)
    if params.sentiment:
        where.append(InsightFeedback.sentiment == params.sentiment.lower())

    total = await session.scalar(
        select(func.count(InsightFeedback.id)).where(*where)
    ) or 0

    rows = (
        await session.execute(
            select(InsightFeedback)
            .where(*where)
            .order_by(InsightFeedback.created_at.desc())
            .offset(params.offset)
            .limit(params.limit)
        )
    ).scalars().all()

    return InsightFeedbackReviewQueueResponse(
        items=[_to_review_response(row) for row in rows],
        total=total,
    )


@router.get("/review/{feedback_id}", response_model=InsightFeedbackReviewResponse)
async def get_review_feedback(
    feedback_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> InsightFeedbackReviewResponse:
    """Retrieve a single feedback record for review, including frozen snapshots."""
    _require_insight_reviewer(context)

    row = await session.get(InsightFeedback, feedback_id)
    if row is None or row.tenant_id != context.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Feedback not found",
        )
    await _require_project_access_for_review(session, context, row.project_id)
    return _to_review_response(row)


@router.post("/review/{feedback_id}/claim", response_model=InsightFeedbackReviewResponse)
async def claim_review_feedback(
    feedback_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> InsightFeedbackReviewResponse:
    """Claim a feedback item for review by the current user."""
    _require_insight_reviewer(context)

    row = await session.get(InsightFeedback, feedback_id)
    if row is None or row.tenant_id != context.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Feedback not found",
        )
    await _require_project_access_for_review(session, context, row.project_id)

    if row.review_status != _REVIEW_STATUS_PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Feedback is already under review or dispositioned",
        )

    row.reviewer_user_id = context.user_id
    await session.commit()
    await session.refresh(row)
    return _to_review_response(row)


@router.post("/review/{feedback_id}/release", response_model=InsightFeedbackReviewResponse)
async def release_review_feedback(
    feedback_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> InsightFeedbackReviewResponse:
    """Release a claimed feedback item back to the pending queue."""
    _require_insight_reviewer(context)

    row = await session.get(InsightFeedback, feedback_id)
    if row is None or row.tenant_id != context.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Feedback not found",
        )
    await _require_project_access_for_review(session, context, row.project_id)

    is_claimant = row.reviewer_user_id == context.user_id
    is_admin = has_role(context.role, Role.ADMIN)
    if not (is_claimant or is_admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the claimant or a tenant admin can release this item",
        )

    row.reviewer_user_id = None
    # Return to pending only if it was not already dispositioned.
    if row.review_status == _REVIEW_STATUS_PENDING or row.review_status is None:
        row.review_status = _REVIEW_STATUS_PENDING
    row.reviewed_at = None
    row.reviewer_comment = None
    await session.commit()
    await session.refresh(row)
    return _to_review_response(row)


@router.post("/review/{feedback_id}/disposition", response_model=InsightFeedbackReviewResponse)
async def disposition_review_feedback(
    feedback_id: int,
    body: InsightFeedbackDispositionRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> InsightFeedbackReviewResponse:
    """Set the final reviewer disposition for a feedback item.

    A reviewer comment is required for final dispositions
    (``accepted``, ``rejected``, ``needs_more_information``).
    """
    _require_insight_reviewer(context)

    row = await session.get(InsightFeedback, feedback_id)
    if row is None or row.tenant_id != context.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Feedback not found",
        )
    await _require_project_access_for_review(session, context, row.project_id)

    is_claimant = row.reviewer_user_id == context.user_id
    is_admin = has_role(context.role, Role.ADMIN)
    if row.reviewer_user_id is not None and not (is_claimant or is_admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the claimant or a tenant admin can disposition this item",
        )

    if body.review_status in _FINAL_REVIEW_STATUSES:
        if not body.reviewer_comment or not body.reviewer_comment.strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="reviewer_comment is required for final dispositions",
            )

    row.review_status = body.review_status
    row.reviewer_comment = body.reviewer_comment.strip() if body.reviewer_comment else None
    row.reviewer_user_id = context.user_id
    row.reviewed_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(row)
    return _to_review_response(row)
