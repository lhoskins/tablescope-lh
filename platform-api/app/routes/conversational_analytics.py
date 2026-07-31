"""Conversational analytics routes for project-scoped natural-language queries.

Endpoints mirror the Sprint-04 contract: create/list/read conversations,
submit a turn, retry, rename, and archive. Tenant, user, and project
authorization are enforced on every call.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models import AnalyticsConversation, AnalyticsConversationTurn, Project, ProjectMember
from app.services.business_insight_project_resolver import (
    resolve_business_insight_project,
)
from app.services.conversational_analytics import execute_turn

router = APIRouter(prefix="/conversational-analytics", tags=["Conversational Analytics"])


class CreateConversationRequest(BaseModel):
    project_id: int | None = Field(default=None, description="Project to scope the conversation to.")
    title: str | None = Field(default=None, max_length=255)
    surface: str = Field(default="ai_assistant", max_length=32)
    initial_message: str | None = Field(default=None)
    data_source_id: int | None = Field(default=None)
    client_request_id: str | None = Field(default=None, max_length=64)


class RenameConversationRequest(BaseModel):
    title: str = Field(..., max_length=255)


class SubmitTurnRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    data_source_id: int | None = Field(default=None)
    client_request_id: str | None = Field(default=None, max_length=64)


class ConversationSummary(BaseModel):
    id: int
    project_id: int | None
    surface: str
    title: str
    status: str
    updated_at: datetime


class TurnResponse(BaseModel):
    id: int
    sequence: int
    user_message: str
    intent_type: str | None
    status: str
    assistant_message: str | None
    sql: str | None
    result: dict[str, Any] | None
    chart_config: dict[str, Any] | None
    explanation: dict[str, Any] | None
    error_code: str | None


class ConversationResponse(BaseModel):
    id: int
    project_id: int | None
    surface: str
    title: str
    status: str
    active_datasource_id: int | None
    turns: list[TurnResponse]
    updated_at: datetime


class TurnSubmissionResponse(BaseModel):
    conversation_id: int
    turn: TurnResponse


async def _check_project_access(session: AsyncSession, context: RequestContext, project_id: int | None) -> None:
    if project_id is None:
        return
    project = await session.get(Project, project_id)
    if project is None or project.tenant_id != context.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if context.role in (Role.ROOT_ADMIN.value, Role.TENANT_ADMIN.value, Role.ADMIN.value):
        return
    owner = await session.scalar(
        select(Project.owner_id).where(Project.id == project_id)
    )
    if owner == context.user_id:
        return
    member = await session.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == context.user_id,
        )
    )
    if member is not None:
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")


async def _load_conversation(
    session: AsyncSession,
    context: RequestContext,
    conversation_id: int,
    *,
    with_turns: bool = False,
) -> AnalyticsConversation:
    if with_turns:
        result = await session.execute(
            select(AnalyticsConversation)
            .options(selectinload(AnalyticsConversation.turns))
            .where(AnalyticsConversation.id == conversation_id)
        )
        conversation = result.scalar_one_or_none()
    else:
        conversation = await session.get(AnalyticsConversation, conversation_id)
    if conversation is None or conversation.tenant_id != context.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    if conversation.user_id != context.user_id and context.role not in (
        Role.ROOT_ADMIN.value,
        Role.TENANT_ADMIN.value,
        Role.ADMIN.value,
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    return conversation


def _turn_to_response(turn: AnalyticsConversationTurn) -> TurnResponse:
    return TurnResponse(
        id=turn.id,
        sequence=turn.sequence,
        user_message=turn.user_message,
        intent_type=turn.intent_type,
        status=turn.status,
        assistant_message=turn.assistant_message,
        sql=turn.sql,
        result=turn.result_cache,
        chart_config=turn.chart_config,
        explanation=turn.explanation,
        error_code=turn.error_code,
    )


def _conversation_to_response(conversation: AnalyticsConversation) -> ConversationResponse:
    return ConversationResponse(
        id=conversation.id,
        project_id=conversation.project_id,
        surface=conversation.surface,
        title=conversation.title,
        status=conversation.status,
        active_datasource_id=conversation.active_datasource_id,
        turns=[_turn_to_response(t) for t in conversation.turns],
        updated_at=conversation.updated_at,
    )


@router.post("/conversations", response_model=ConversationResponse)
async def create_conversation(
    req: CreateConversationRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> ConversationResponse:
    """Create or resume a canonical conversation by (surface, project_id).

    Business/Project Insights use a dedicated surface so repeated asks stay in
    one thread instead of creating a new conversation per question.
    """
    if req.project_id is not None:
        await _check_project_access(session, context, req.project_id)

    surface = req.surface or "ai_assistant"
    # Only auto-resolve a project for the generic AI assistant surface.
    resolved_project_id = req.project_id
    if surface == "ai_assistant" and resolved_project_id is None and req.initial_message:
        resolved = await resolve_business_insight_project(
            session, context, req.initial_message
        )
        if resolved.status == "resolved":
            resolved_project_id = resolved.project_id

    if resolved_project_id is not None:
        await _check_project_access(session, context, resolved_project_id)

    # Canonical lookup by (user, surface, project).
    existing = await session.scalar(
        select(AnalyticsConversation).where(
            AnalyticsConversation.tenant_id == context.tenant_id,
            AnalyticsConversation.user_id == context.user_id,
            AnalyticsConversation.surface == surface,
            AnalyticsConversation.project_id == resolved_project_id,
            AnalyticsConversation.status == "active",
        )
    )
    if existing is not None:
        conversation = existing
    else:
        title = req.title or "New conversation"
        if req.initial_message and not req.title:
            title = req.initial_message[:80] + ("…" if len(req.initial_message) > 80 else "")

        conversation = AnalyticsConversation(
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            project_id=resolved_project_id,
            surface=surface,
            active_datasource_id=req.data_source_id,
            title=title,
            status="active",
        )
        session.add(conversation)
        await session.flush()

    if req.initial_message:
        turn = AnalyticsConversationTurn(
            conversation_id=conversation.id,
            sequence=1,
            user_message=req.initial_message,
            client_request_id=req.client_request_id,
            status="pending",
        )
        session.add(turn)
        await session.flush()
        await execute_turn(
            session, context, conversation, turn, datasource_id=req.data_source_id
        )
        if turn.status == "success":
            conversation.last_successful_turn_id = turn.id
        await session.flush()

    result = await session.execute(
        select(AnalyticsConversation)
        .options(selectinload(AnalyticsConversation.turns))
        .where(AnalyticsConversation.id == conversation.id)
    )
    conversation = result.scalar_one()
    return _conversation_to_response(conversation)


@router.get("/conversations", response_model=list[ConversationSummary])
async def list_conversations(
    project_id: int | None = None,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> list[ConversationSummary]:
    """List the current user's conversations, optionally filtered by project."""
    stmt = select(AnalyticsConversation).where(
        AnalyticsConversation.tenant_id == context.tenant_id,
        AnalyticsConversation.user_id == context.user_id,
    )
    if project_id is not None:
        await _check_project_access(session, context, project_id)
        stmt = stmt.where(AnalyticsConversation.project_id == project_id)
    stmt = stmt.order_by(AnalyticsConversation.updated_at.desc())
    result = await session.execute(stmt)
    conversations = result.scalars().all()
    return [
        ConversationSummary(
            id=c.id,
            project_id=c.project_id,
            surface=c.surface,
            title=c.title,
            status=c.status,
            updated_at=c.updated_at,
        )
        for c in conversations
    ]


@router.get("/conversations/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(
    conversation_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> ConversationResponse:
    """Return a conversation with its ordered turns and bounded result caches."""
    conversation = await _load_conversation(session, context, conversation_id, with_turns=True)
    return _conversation_to_response(conversation)


@router.post("/conversations/{conversation_id}/turns", response_model=TurnSubmissionResponse)
async def submit_turn(
    conversation_id: int,
    req: SubmitTurnRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> TurnSubmissionResponse:
    """Submit a new turn to an existing conversation."""
    conversation = await _load_conversation(session, context, conversation_id)
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
                AnalyticsConversationTurn.conversation_id == conversation_id,
                AnalyticsConversationTurn.client_request_id == req.client_request_id,
            )
        )
        if existing:
            return TurnSubmissionResponse(
                conversation_id=conversation_id,
                turn=_turn_to_response(existing),
            )

    max_sequence = await session.scalar(
        select(AnalyticsConversationTurn.sequence)
        .where(AnalyticsConversationTurn.conversation_id == conversation_id)
        .order_by(AnalyticsConversationTurn.sequence.desc())
        .limit(1)
    ) or 0

    turn = AnalyticsConversationTurn(
        conversation_id=conversation_id,
        sequence=max_sequence + 1,
        user_message=req.message,
        client_request_id=req.client_request_id,
        parent_turn_id=conversation.last_successful_turn_id,
        status="pending",
    )
    session.add(turn)
    await session.flush()

    await execute_turn(
        session, context, conversation, turn, datasource_id=req.data_source_id
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


@router.post("/conversations/{conversation_id}/turns/{turn_id}/retry", response_model=TurnSubmissionResponse)
async def retry_turn(
    conversation_id: int,
    turn_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> TurnSubmissionResponse:
    """Re-run a failed turn and update it in place."""
    conversation = await _load_conversation(session, context, conversation_id)
    turn = await session.get(AnalyticsConversationTurn, turn_id)
    if turn is None or turn.conversation_id != conversation_id:
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


@router.patch("/conversations/{conversation_id}", response_model=ConversationResponse)
async def update_conversation(
    conversation_id: int,
    req: RenameConversationRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> ConversationResponse:
    """Rename or archive a conversation."""
    conversation = await _load_conversation(session, context, conversation_id, with_turns=True)
    conversation.title = req.title
    conversation.updated_at = datetime.now(UTC)
    await session.flush()
    return _conversation_to_response(conversation)


@router.delete(
    "/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_conversation(
    conversation_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> None:
    """Delete a conversation and all its turns.

    Uses raw DML to avoid SQLAlchemy ORM circular-dependency ordering when
    ``last_successful_turn_id`` and ``conversation_id`` reference each other.
    """
    conversation = await _load_conversation(session, context, conversation_id)
    cid = conversation.id
    tid = context.tenant_id
    uid = context.user_id
    is_admin = context.role in (
        Role.ROOT_ADMIN.value,
        Role.TENANT_ADMIN.value,
        Role.ADMIN.value,
    )
    where_sql = "id = :id AND tenant_id = :tid"
    params: dict[str, Any] = {"id": cid, "tid": tid}
    if not is_admin:
        where_sql += " AND user_id = :uid"
        params["uid"] = uid

    await session.execute(
        text(
            "UPDATE analytics_conversations SET last_successful_turn_id = NULL "
            f"WHERE {where_sql}"
        ),
        params,
    )
    await session.execute(
        text("DELETE FROM analytics_conversation_turns WHERE conversation_id = :id"),
        {"id": cid},
    )
    await session.execute(
        text(
            "DELETE FROM analytics_conversations "
            f"WHERE {where_sql}"
        ),
        params,
    )
    await session.commit()
