"""Turn submission and retry routes for conversational analytics."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models import AnalyticsConversationTurn
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


class SubmitTurnRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    data_source_id: int | None = Field(default=None)
    attachment_ids: list[int] = Field(default_factory=list)
    client_request_id: str | None = Field(default=None, max_length=64)


class TurnSubmissionResponse(BaseModel):
    conversation_id: int
    turn: TurnResponse


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
    if turn.status == "success" and turn.id is not None:
        conversation.last_successful_turn_id = turn.id
    conversation.updated_at = datetime.now(UTC)
    await session.flush()
    await session.refresh(turn)

    return TurnSubmissionResponse(
        conversation_id=conversation_id,
        turn=_turn_to_response(turn),
    )


class SubmitCanonicalTurnRequest(BaseModel):
    surface: str = Field(..., max_length=32)
    project_id: int | None = Field(default=None)
    message: str = Field(..., min_length=1, max_length=4000)
    data_source_id: int | None = Field(default=None)
    attachment_ids: list[int] = Field(default_factory=list)
    client_request_id: str = Field(..., max_length=64)


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
    if turn.status == "success" and turn.id is not None:
        conversation.last_successful_turn_id = turn.id
    await session.flush()
    await session.refresh(turn)

    return TurnSubmissionResponse(
        conversation_id=conversation_id,
        turn=_turn_to_response(turn),
    )
