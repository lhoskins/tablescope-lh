"""Human feedback API for AI-generated insights.

Every endpoint is strictly scoped to the authenticated tenant and user.
Feedback is returned only for the current user; it is never aggregated or
shown to other users, and it is never used to automatically retrain the model.
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
from app.models.insight_feedback import InsightFeedback, InsightFeedbackReviewEvent
from app.models.project import Project
from app.models.user import User
from app.routes.home_pins import _require_project_access
from app.services.project_ai_context import invalidate_project_ai_context
from app.services.project_insight_service import mark_project_insight_stale

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


class InsightFeedbackAdminReviewItem(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    id: int
    insight_id: str
    project_id: int | None
    project_name: str | None
    user_id: int
    user_email: str
    sentiment: str
    reason_codes: list[str] = Field(default_factory=list)
    comment: str | None
    insight_type: str | None
    card_title: str | None
    created_at: str


class InsightFeedbackAdminReviewResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    items: list[InsightFeedbackAdminReviewItem]
    total: int


@router.get("/review", response_model=InsightFeedbackAdminReviewResponse)
async def review_insight_feedback(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    sentiment: str | None = Query(None),
    project_id: int | None = Query(None),
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> InsightFeedbackAdminReviewResponse:
    """Return tenant-scoped insight feedback for review by administrators."""
    base = (
        select(InsightFeedback, User.email.label("user_email"), Project.name.label("project_name"))
        .join(User, InsightFeedback.user_id == User.id)
        .join(Project, InsightFeedback.project_id == Project.id, isouter=True)
        .where(
            InsightFeedback.tenant_id == context.tenant_id,
            InsightFeedback.status == _STATUS_ACTIVE,
        )
    )
    if sentiment:
        base = base.where(InsightFeedback.sentiment == sentiment)
    if project_id is not None:
        base = base.where(InsightFeedback.project_id == project_id)

    total = (
        await session.scalar(select(func.count()).select_from(base.subquery()))
    ) or 0

    rows = (
        await session.execute(
            base.order_by(InsightFeedback.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()

    def _card_title(card: dict[str, Any] | None) -> str | None:
        if not card:
            return None
        return card.get("title") or card.get("summary") or None

    items = [
        InsightFeedbackAdminReviewItem(
            id=row.InsightFeedback.id,
            insight_id=row.InsightFeedback.insight_id,
            project_id=row.InsightFeedback.project_id,
            project_name=row.project_name,
            user_id=row.InsightFeedback.user_id,
            user_email=row.user_email,
            sentiment=row.InsightFeedback.sentiment,
            reason_codes=row.InsightFeedback.reason_codes or [],
            comment=row.InsightFeedback.comment,
            insight_type=row.InsightFeedback.insight_type,
            card_title=_card_title(row.InsightFeedback.card_snapshot),
            created_at=row.InsightFeedback.created_at.isoformat()
            if row.InsightFeedback.created_at
            else "",
        )
        for row in rows
    ]
    return InsightFeedbackAdminReviewResponse(items=items, total=total)


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


# ───────────────────────────── reviewer workflow ─────────────────────────────


def _can_review_feedback(context: RequestContext) -> bool:
    """True when the caller is an explicit reviewer or an admin."""
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


async def _get_review_feedback(
    session: AsyncSession,
    context: RequestContext,
    feedback_id: int,
) -> InsightFeedback:
    row = await session.get(InsightFeedback, feedback_id)
    if row is None or row.tenant_id != context.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Feedback not found",
        )
    await _require_project_access_for_review(session, context, row.project_id)
    return row


def _ensure_claimant_or_admin(
    row: InsightFeedback,
    context: RequestContext,
    action: str = "perform this action",
) -> None:
    is_claimant = row.reviewer_user_id == context.user_id
    is_admin = has_role(context.role, Role.ADMIN)
    if not (is_claimant or is_admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Only the claimant or a tenant admin can {action}",
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
    response: str | None
    reviewed_at: str | None
    acknowledged_at: str | None
    feedback_revision: int
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
        response=row.response,
        reviewed_at=row.reviewed_at.isoformat() if row.reviewed_at else None,
        acknowledged_at=row.acknowledged_at.isoformat() if row.acknowledged_at else None,
        feedback_revision=row.feedback_revision,
        created_at=row.created_at.isoformat() if row.created_at else "",
        updated_at=row.updated_at.isoformat() if row.updated_at else "",
        card_snapshot=row.card_snapshot,
        explanation_snapshot=row.explanation_snapshot,
    )


class InsightFeedbackReviewQueueParams:
    def __init__(
        self,
        review_status: str | None = Query("pending,in_review,needs_more_information"),
        project_id: int | None = Query(None),
        sentiment: str | None = Query("disagree"),
        limit: int = Query(100, ge=1, le=500),
        offset: int = Query(0, ge=0),
    ) -> None:
        self.review_status = review_status if review_status else None
        self.project_id = project_id
        self.sentiment = sentiment if sentiment else None
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


class InsightFeedbackInfoRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    reviewer_comment: str

    @field_validator("reviewer_comment")
    @classmethod
    def _validate_reviewer_comment(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("reviewer_comment is required")
        if len(v) > 4000:
            raise ValueError("reviewer_comment must not exceed 4000 characters")
        return v


class InsightFeedbackUserResponseRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    response: str

    @field_validator("response")
    @classmethod
    def _validate_response(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("response is required and cannot be whitespace")
        if len(v) > 4000:
            raise ValueError("response must not exceed 4000 characters")
        return v


class InsightFeedbackGovernanceRequest(BaseModel):
    insight_ids: list[str] = Field(..., min_length=1, max_length=200)
    project_id: int | None = None

    @field_validator("insight_ids")
    @classmethod
    def _dedupe_and_trim(cls, v: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for insight_id in v:
            tid = insight_id.strip()
            if tid and tid not in seen:
                seen.add(tid)
                out.append(tid)
        if not out:
            raise ValueError("insight_ids must not be empty")
        return out


class InsightFeedbackGovernanceItem(BaseModel):
    insight_id: str
    governance_status: str
    last_status_changed_at: str | None


class InsightFeedbackGovernanceResponse(BaseModel):
    items: list[InsightFeedbackGovernanceItem]


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
        InsightFeedback.status == _STATUS_ACTIVE,
    ]
    if params.review_status:
        statuses = [s.strip().lower() for s in params.review_status.split(",") if s.strip()]
        if statuses:
            where.append(InsightFeedback.review_status.in_(statuses))
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
    row = await _get_review_feedback(session, context, feedback_id)
    return _to_review_response(row)


@router.post("/review/{feedback_id}/claim", response_model=InsightFeedbackReviewResponse)
async def claim_review_feedback(
    feedback_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> InsightFeedbackReviewResponse:
    """Acknowledge a feedback item for review by the current user."""
    _require_insight_reviewer(context)

    row = await _get_review_feedback(session, context, feedback_id)
    if row.review_status != _REVIEW_STATUS_PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Feedback is already under review or dispositioned",
        )

    previous = row.review_status
    row.review_status = _REVIEW_STATUS_IN_REVIEW
    row.reviewer_user_id = context.user_id
    row.acknowledged_at = datetime.now(UTC)
    _log_review_event(
        session,
        row,
        _EVENT_ACKNOWLEDGED,
        previous,
        row.review_status,
        context.user_id,
    )
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

    row = await _get_review_feedback(session, context, feedback_id)
    _ensure_claimant_or_admin(row, context, "release this item")

    previous = row.review_status
    row.review_status = _REVIEW_STATUS_PENDING
    row.reviewer_user_id = None
    row.acknowledged_at = None
    row.reviewed_at = None
    row.reviewer_comment = None
    row.response = None
    _log_review_event(
        session,
        row,
        _EVENT_RELEASED,
        previous,
        row.review_status,
        context.user_id,
    )
    await session.commit()
    await session.refresh(row)
    return _to_review_response(row)


@router.post(
    "/review/{feedback_id}/request-info",
    response_model=InsightFeedbackReviewResponse,
)
async def request_more_information(
    feedback_id: int,
    body: InsightFeedbackInfoRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> InsightFeedbackReviewResponse:
    """Request more information from the submitter while reviewing a feedback item."""
    _require_insight_reviewer(context)

    row = await _get_review_feedback(session, context, feedback_id)
    _ensure_claimant_or_admin(row, context, "request more information")

    if row.review_status != _REVIEW_STATUS_IN_REVIEW:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Information can only be requested while the feedback is in review",
        )

    previous = row.review_status
    row.review_status = _REVIEW_STATUS_NEEDS_MORE_INFO
    row.reviewer_comment = body.reviewer_comment
    _log_review_event(
        session,
        row,
        _EVENT_INFO_REQUESTED,
        previous,
        row.review_status,
        context.user_id,
        comment=body.reviewer_comment,
    )
    await session.commit()
    await session.refresh(row)
    return _to_review_response(row)


@router.post(
    "/{insight_id}/review-response",
    response_model=InsightFeedbackResponse,
)
async def respond_to_review_request(
    insight_id: str,
    body: InsightFeedbackUserResponseRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> InsightFeedbackResponse:
    """Allow a submitter to respond to a request for more information."""
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

    if row.review_status != _REVIEW_STATUS_NEEDS_MORE_INFO:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A response can only be submitted when more information is requested",
        )

    previous = row.review_status
    row.review_status = _REVIEW_STATUS_IN_REVIEW
    row.response = body.response
    _log_review_event(
        session,
        row,
        _EVENT_USER_RESPONDED,
        previous,
        row.review_status,
        context.user_id,
        response=body.response,
    )
    await session.commit()
    await session.refresh(row)
    return _to_response(row)


@router.post("/review/{feedback_id}/disposition", response_model=InsightFeedbackReviewResponse)
async def disposition_review_feedback(
    feedback_id: int,
    body: InsightFeedbackDispositionRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> InsightFeedbackReviewResponse:
    """Set the final reviewer disposition for a feedback item.

    Final dispositions (``accepted``/``rejected``) require a reviewer comment.
    ``needs_more_information`` is a non-terminal request-for-info action.
    """
    _require_insight_reviewer(context)

    row = await _get_review_feedback(session, context, feedback_id)
    _ensure_claimant_or_admin(row, context, "set a disposition")

    requested_status = body.review_status
    if requested_status not in _VALID_REVIEW_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"review_status must be one of: {', '.join(_VALID_REVIEW_STATUSES)}",
        )

    if requested_status == _REVIEW_STATUS_NEEDS_MORE_INFO:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Use the request-info endpoint to ask for more information",
        )

    if requested_status in _FINAL_REVIEW_STATUSES:
        if not body.reviewer_comment or not body.reviewer_comment.strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="reviewer_comment is required for final dispositions",
            )

    # Final disposition must come from in_review. If the status is
    # needs_more_information the caller should first receive a response.
    if requested_status in _FINAL_REVIEW_STATUSES and row.review_status != _REVIEW_STATUS_IN_REVIEW:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Final disposition is only allowed while the feedback is in review",
        )

    previous = row.review_status
    row.review_status = requested_status
    row.reviewer_user_id = context.user_id
    row.reviewed_at = datetime.now(UTC)
    row.reviewer_comment = (
        body.reviewer_comment.strip() if body.reviewer_comment else None
    )

    if row.project_id is not None:
        await mark_project_insight_stale(
            session, tenant_id=row.tenant_id, project_id=row.project_id
        )
        invalidate_project_ai_context(row.tenant_id, row.project_id)

    event_type = (
        _EVENT_FEEDBACK_ACCEPTED
        if requested_status == _REVIEW_STATUS_ACCEPTED
        else _EVENT_INSIGHT_UPHELD
    )
    _log_review_event(
        session,
        row,
        event_type,
        previous,
        row.review_status,
        context.user_id,
        comment=row.reviewer_comment,
    )
    await session.commit()
    await session.refresh(row)
    return _to_review_response(row)


@router.post("/governance", response_model=InsightFeedbackGovernanceResponse)
async def governance_batch(
    body: InsightFeedbackGovernanceRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> InsightFeedbackGovernanceResponse:
    """Return a safe, privacy-preserving governance summary for a list of insights.

    This endpoint returns only the governance status and the latest status-change
    timestamp. It never exposes submitter/reviewer identity, comments, or reasons.
    """
    if body.project_id is not None:
        await _require_project_access(session, context, body.project_id)

    where = [
        InsightFeedback.tenant_id == context.tenant_id,
        InsightFeedback.insight_id.in_(body.insight_ids),
        InsightFeedback.status == _STATUS_ACTIVE,
    ]
    if body.project_id is not None:
        where.append(InsightFeedback.project_id == body.project_id)

    rows = (
        await session.execute(
            select(
                InsightFeedback.insight_id,
                InsightFeedback.review_status,
                InsightFeedback.updated_at,
            ).where(*where)
        )
    ).all()

    # Precedence: Under Review > Disputed > Validated > None
    governance: dict[str, tuple[str, datetime | None]] = {}
    for insight_id, review_status, updated_at in rows:
        existing = governance.get(insight_id)
        existing_status = existing[0] if existing else None
        existing_ts = existing[1] if existing else None

        if review_status in (
            _REVIEW_STATUS_PENDING,
            _REVIEW_STATUS_IN_REVIEW,
            _REVIEW_STATUS_NEEDS_MORE_INFO,
        ):
            new_status = "Under Review"
        elif review_status == _REVIEW_STATUS_ACCEPTED:
            new_status = "Disputed"
        elif review_status == _REVIEW_STATUS_REJECTED:
            new_status = "Validated"
        else:
            new_status = "None"

        # Keep the most severe status; update timestamp if changed.
        if existing_status is None:
            governance[insight_id] = (new_status, updated_at)
        else:
            precedence = ["Under Review", "Disputed", "Validated", "None"]
            # Lower index = more severe (Under Review beats Disputed beats Validated).
            if existing_status == "None" or precedence.index(new_status) < precedence.index(existing_status):
                governance[insight_id] = (new_status, updated_at)
            elif new_status == existing_status:
                latest_ts = max(filter(None, [existing_ts, updated_at]), default=None)
                governance[insight_id] = (new_status, latest_ts)

    items: list[InsightFeedbackGovernanceItem] = []
    for insight_id in body.insight_ids:
        status, ts = governance.get(insight_id, ("None", None))
        items.append(
            InsightFeedbackGovernanceItem(
                insight_id=insight_id,
                governance_status=status,
                last_status_changed_at=ts.isoformat() if ts else None,
            )
        )

    return InsightFeedbackGovernanceResponse(items=items)
