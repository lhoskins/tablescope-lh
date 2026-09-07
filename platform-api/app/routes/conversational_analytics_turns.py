"""Turn submission and retry routes for conversational analytics."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models import AnalyticsConversationTurn, Dashboard, FileSourceMeta, SavedQuery
from app.routes.ai_proxy_shared import _detect_datasource
from app.routes.conversational_analytics_conversations import (
    TurnResponse,
    _check_project_access,
    _load_conversation,
    _turn_to_response,
)
from app.services.canonical_conversations import (
    CanonicalConversationSurface,
    CanonicalProjectError,
    CanonicalSurfaceError,
    append_canonical_turn,
)
from app.services.conversational_analytics import execute_turn

router = APIRouter(prefix="/conversational-analytics", tags=["Conversational Analytics"])
logger = logging.getLogger(__name__)


class SubmitTurnRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    data_source_id: int | None = Field(default=None)
    attachment_ids: list[int] = Field(default_factory=list)
    client_request_id: str | None = Field(default=None, max_length=64)


class TurnSubmissionResponse(BaseModel):
    conversation_id: int
    turn: TurnResponse


class ArtifactDecisionRequest(BaseModel):
    decision: Literal["accept", "reject"]
    artifact_kind: Literal["query", "dashboard"]
    asset_id: int | None = None


@router.post("/conversations/{conversation_id}/turns", response_model=TurnSubmissionResponse)
async def submit_turn(
    conversation_id: int,
    req: SubmitTurnRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> TurnSubmissionResponse:
    """Submit a new turn to an existing conversation."""
    conversation = await _load_conversation(session, context, conversation_id)
    # Follow merge aliases so turns are appended to the canonical conversation.
    canonical_id = conversation.id
    if conversation.project_id is not None:
        await _check_project_access(session, context, conversation.project_id)
    if conversation.status != "active":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot add turns to an archived conversation",
        )

    # Idempotency: return existing turn for duplicate client_request_id.
    if req.client_request_id:
        existing = await session.scalar(
            select(AnalyticsConversationTurn).where(
                AnalyticsConversationTurn.conversation_id == canonical_id,
                AnalyticsConversationTurn.client_request_id == req.client_request_id,
            )
        )
        if existing:
            return TurnSubmissionResponse(
                conversation_id=canonical_id,
                turn=_turn_to_response(existing),
            )

    max_sequence = await session.scalar(
        select(AnalyticsConversationTurn.sequence)
        .where(AnalyticsConversationTurn.conversation_id == canonical_id)
        .order_by(AnalyticsConversationTurn.sequence.desc())
        .limit(1)
    ) or 0

    turn = AnalyticsConversationTurn(
        conversation_id=canonical_id,
        sequence=max_sequence + 1,
        user_message=req.message,
        client_request_id=req.client_request_id,
        parent_turn_id=conversation.last_successful_turn_id,
        status="pending",
    )
    session.add(turn)
    await session.flush()

    await execute_turn(
        session,
        context,
        conversation,
        turn,
        datasource_id=req.data_source_id,
        attachment_ids=req.attachment_ids,
    )
    if (
        turn.status == "success"
        and turn.id is not None
        and turn.intent_type != "create_dashboard"
    ):
        conversation.last_successful_turn_id = turn.id
    conversation.updated_at = datetime.now(UTC)
    await session.flush()
    await session.refresh(turn)

    return TurnSubmissionResponse(
        conversation_id=conversation_id,
        turn=_turn_to_response(turn),
    )


@router.post(
    "/conversations/{conversation_id}/turns/{turn_id}/artifact-decision",
    response_model=TurnSubmissionResponse,
)
async def decide_artifact_proposal(
    conversation_id: int,
    turn_id: int,
    req: ArtifactDecisionRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> TurnSubmissionResponse:
    """Accept or reject a chat artifact proposal.

    Query acceptance creates the SavedQuery here from SQL that was already
    validated and executed by the conversational pipeline. Dashboard
    acceptance is recorded only after the existing dashboard designer has
    applied its separately reviewed design and supplies the resulting id.
    """
    conversation = await _load_conversation(session, context, conversation_id)
    if conversation.project_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Artifact proposals require a project-scoped conversation",
        )
    await _check_project_access(session, context, conversation.project_id)

    turn = await session.scalar(
        select(AnalyticsConversationTurn)
        .where(
            AnalyticsConversationTurn.id == turn_id,
            AnalyticsConversationTurn.conversation_id == conversation.id,
        )
        .with_for_update()
    )
    if turn is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Turn not found")

    explanation = dict(turn.explanation or {})
    proposal = dict(explanation.get("artifactProposal") or {})
    if not proposal or proposal.get("kind") != req.artifact_kind:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This turn does not contain the requested artifact proposal",
        )

    current_status = proposal.get("status") or "pending"
    if current_status == "accepted" and req.decision == "accept":
        return TurnSubmissionResponse(
            conversation_id=conversation.id,
            turn=_turn_to_response(turn),
        )
    if current_status == "rejected" and req.decision == "reject":
        return TurnSubmissionResponse(
            conversation_id=conversation.id,
            turn=_turn_to_response(turn),
        )
    if current_status in {"accepted", "rejected"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This proposal was already {current_status}",
        )

    asset_id: int | None = None
    asset_url: str | None = None
    if req.decision == "accept" and req.artifact_kind == "query":
        if not turn.sql or turn.status != "success":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="The proposal has no validated SQL to save",
            )
        sources = list(
            await session.scalars(
                select(FileSourceMeta).where(
                    FileSourceMeta.project_id == conversation.project_id,
                    FileSourceMeta.tenant_id == context.tenant_id,
                    FileSourceMeta.archived.is_(False),
                )
            )
        )
        saved_query = SavedQuery(
            project_id=conversation.project_id,
            owner_id=context.user_id,
            name=str(proposal.get("title") or "AI Query")[:255],
            description=str(proposal.get("prompt") or turn.user_message),
            sql_text=turn.sql,
            left_datasource=_detect_datasource(
                turn.sql, [source.view_name for source in sources]
            ),
            ai_generated=True,
        )
        session.add(saved_query)
        await session.flush()
        asset_id = saved_query.id
        asset_url = f"/projects/{conversation.project_id}/queries"

    if req.decision == "accept" and req.artifact_kind == "dashboard":
        if req.asset_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="A created dashboard id is required",
            )
        dashboard = await session.get(Dashboard, req.asset_id)
        if (
            dashboard is None
            or dashboard.project_id != conversation.project_id
            or dashboard.tenant_id != context.tenant_id
        ):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dashboard not found")
        asset_id = dashboard.id
        asset_url = f"/projects/{conversation.project_id}/dashboards/{dashboard.id}"

    proposal.update(
        {
            "status": "accepted" if req.decision == "accept" else "rejected",
            "decidedAt": datetime.now(UTC).isoformat(),
            "decidedBy": context.user_id,
            "assetId": asset_id,
            "assetUrl": asset_url,
        }
    )
    explanation["artifactProposal"] = proposal
    turn.explanation = explanation
    await session.flush()
    await session.refresh(turn)
    logger.info(
        "Conversation artifact decision | conversation=%d turn=%d kind=%s decision=%s asset=%s tenant=%d user=%d",
        conversation.id,
        turn.id,
        req.artifact_kind,
        req.decision,
        asset_id,
        context.tenant_id,
        context.user_id,
    )
    return TurnSubmissionResponse(
        conversation_id=conversation.id,
        turn=_turn_to_response(turn),
    )


class ActiveResourceRef(BaseModel):
    resource_type: str = Field(..., max_length=32)
    resource_id: int


class SubmitCanonicalTurnRequest(BaseModel):
    surface: str = Field(..., max_length=32)
    project_id: int | None = Field(default=None)
    message: str = Field(..., min_length=1, max_length=4000)
    data_source_id: int | None = Field(default=None)
    attachment_ids: list[int] = Field(default_factory=list)
    client_request_id: str = Field(..., max_length=64)
    # Project workspace only: the resource type/id the user currently has open
    # in the workspace tab strip, used to ground the assistant's answer.
    active_resource_type: str | None = Field(default=None, max_length=32)
    active_resource_id: int | None = Field(default=None)
    # A named workspace pins several cards at once. When present this list
    # supersedes the single pair above, which stays for existing callers.
    active_resources: list[ActiveResourceRef] | None = Field(default=None)


class SubmitCanonicalTurnResponse(BaseModel):
    conversation_id: int
    conversation_created: bool
    surface: str
    project_id: int | None
    turn: TurnResponse


@router.post("/canonical-turns", response_model=SubmitCanonicalTurnResponse)
async def submit_canonical_turn(
    req: SubmitCanonicalTurnRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> SubmitCanonicalTurnResponse:
    """Atomically get or create a canonical Insight conversation and append a turn."""
    try:
        surface = CanonicalConversationSurface(req.surface)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported surface: {req.surface}",
        ) from exc

    if req.project_id is not None:
        await _check_project_access(session, context, req.project_id)

    try:
        result = await append_canonical_turn(
            session,
            context,
            surface=surface,
            project_id=req.project_id,
            message=req.message,
            data_source_id=req.data_source_id,
            attachment_ids=req.attachment_ids,
            client_request_id=req.client_request_id,
            active_resource_type=req.active_resource_type,
            active_resource_id=req.active_resource_id,
            active_resources=(
                [(r.resource_type, r.resource_id) for r in req.active_resources]
                if req.active_resources
                else None
            ),
        )
    except CanonicalProjectError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except CanonicalSurfaceError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    turn = await session.get(AnalyticsConversationTurn, result.turn_id)
    if turn is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Turn not found after creation",
        )
    return SubmitCanonicalTurnResponse(
        conversation_id=result.conversation_id,
        conversation_created=result.conversation_created,
        surface=result.surface,
        project_id=result.project_id,
        turn=_turn_to_response(turn),
    )


@router.post("/conversations/{conversation_id}/turns/{turn_id}/retry", response_model=TurnSubmissionResponse)
async def retry_turn(
    conversation_id: int,
    turn_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> TurnSubmissionResponse:
    """Re-run a failed turn and update it in place."""
    conversation = await _load_conversation(session, context, conversation_id)
    canonical_id = conversation.id
    turn = await session.get(AnalyticsConversationTurn, turn_id)
    if turn is None or turn.conversation_id != canonical_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Turn not found")

    await execute_turn(
        session, context, conversation, turn, datasource_id=conversation.active_datasource_id
    )
    if (
        turn.status == "success"
        and turn.id is not None
        and turn.intent_type != "create_dashboard"
    ):
        conversation.last_successful_turn_id = turn.id
    await session.flush()
    await session.refresh(turn)

    return TurnSubmissionResponse(
        conversation_id=conversation_id,
        turn=_turn_to_response(turn),
    )
