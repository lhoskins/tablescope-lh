"""Conversation lifecycle routes for project-scoped natural-language analytics.

Create/resume, list, read, rename and delete conversations, plus the recent
project conversation feed. Also hosts the schemas, access checks and response
builders shared with the turn routes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models import AnalyticsConversation, AnalyticsConversationTurn, Project, ProjectMember
from app.services.business_insight_project_resolver import (
    resolve_business_insight_project,
)
from app.services.canonical_conversations import (
    CanonicalConversationSurface,
    CanonicalProjectError,
    CanonicalSurfaceError,
    append_canonical_turn,
    load_canonical_conversation,
)
from app.services.conversation_previews import (
    question_preview,
    result_preview,
    result_type,
)
from app.services.conversational_analytics import execute_turn

router = APIRouter(prefix="/conversational-analytics", tags=["Conversational Analytics"])

#: Surfaces whose conversations belong to a project's own AI Assistant history.
#: Business Insight conversations resolve to a ``project_id`` too, so filtering
#: on the project alone would leak them into project-scoped history.
PROJECT_CONVERSATION_SURFACES = ("project_insights", "ai_assistant")

RECENT_CONVERSATIONS_DEFAULT_LIMIT = 4
RECENT_CONVERSATIONS_MAX_LIMIT = 20


class CreateConversationRequest(BaseModel):
    project_id: int | None = Field(default=None, description="Project to scope the conversation to.")
    title: str | None = Field(default=None, max_length=255)
    surface: str = Field(default="ai_assistant", max_length=32)
    initial_message: str | None = Field(default=None)
    data_source_id: int | None = Field(default=None)
    client_request_id: str | None = Field(default=None, max_length=64)


class RenameConversationRequest(BaseModel):
    title: str = Field(..., max_length=255)


class ConversationSummary(BaseModel):
    id: int
    project_id: int | None
    surface: str
    title: str
    status: str
    canonical_key: str | None
    merged_into_conversation_id: int | None
    updated_at: datetime


class RecentConversationItem(BaseModel):
    conversation_id: int
    turn_id: int
    surface: str
    question_preview: str
    result_preview: str
    result_type: str
    completed_at: datetime


class RecentConversationsResponse(BaseModel):
    project_id: int
    items: list[RecentConversationItem]


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
    canonical_key: str | None
    merged_into_conversation_id: int | None
    turns: list[TurnResponse]
    updated_at: datetime


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
    conversation = await load_canonical_conversation(
        session, context, conversation_id, with_turns=with_turns
    )
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
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
        canonical_key=conversation.canonical_key,
        merged_into_conversation_id=conversation.merged_into_conversation_id,
        turns=[_turn_to_response(t) for t in conversation.turns],
        updated_at=conversation.updated_at,
    )


@router.post("/conversations", response_model=ConversationResponse)
async def create_conversation(
    req: CreateConversationRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> ConversationResponse:
    """Create a new manual AI Assistant conversation.

    Insight surfaces with an ``initial_message`` delegate to the canonical
    append service during the compatibility window. This lets older clients
    continue to post to the conversation-create route without creating
    duplicate Insight threads.
    """
    surface = req.surface or "ai_assistant"

    # Compatibility delegation for Insight surfaces.
    if surface in (
        CanonicalConversationSurface.BUSINESS_INSIGHTS.value,
        CanonicalConversationSurface.PROJECT_INSIGHTS.value,
    ):
        if not req.initial_message:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{surface} conversations require an initial message; use /canonical-turns instead",
            )
        # Business Insights are tenant/user scoped; any supplied project_id is ignored.
        canonical_project_id = (
            None
            if surface == CanonicalConversationSurface.BUSINESS_INSIGHTS.value
            else req.project_id
        )
        if canonical_project_id is not None:
            await _check_project_access(session, context, canonical_project_id)
        try:
            canonical = await append_canonical_turn(
                session,
                context,
                surface=CanonicalConversationSurface(surface),
                project_id=canonical_project_id,
                message=req.initial_message,
                client_request_id=req.client_request_id or "",
                data_source_id=req.data_source_id,
            )
        except CanonicalProjectError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from exc
        except CanonicalSurfaceError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from exc

        conversation = await _load_conversation(
            session, context, canonical.conversation_id, with_turns=True
        )
        return _conversation_to_response(conversation)

    # Manual AI Assistant chat: always create a fresh conversation.
    resolved_project_id = req.project_id
    if resolved_project_id is not None:
        await _check_project_access(session, context, resolved_project_id)
    if surface == "ai_assistant" and resolved_project_id is None and req.initial_message:
        resolved = await resolve_business_insight_project(
            session, context, req.initial_message
        )
        if resolved.status == "resolved":
            resolved_project_id = resolved.project_id
            await _check_project_access(session, context, resolved_project_id)

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

    conversation = await _load_conversation(
        session, context, conversation.id, with_turns=True
    )
    return _conversation_to_response(conversation)


def _visible_conversations_stmt(context: RequestContext):
    """Conversations the caller may read.

    Ownership is the only visibility rule: there is no conversation sharing
    model, so a conversation is never exposed to another user.
    """
    return select(AnalyticsConversation).where(
        AnalyticsConversation.tenant_id == context.tenant_id,
        AnalyticsConversation.user_id == context.user_id,
    )


@router.get("/conversations", response_model=list[ConversationSummary])
async def list_conversations(
    project_id: int | None = None,
    limit: int | None = None,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> list[ConversationSummary]:
    """List the current user's active conversations, optionally filtered by project."""
    stmt = _visible_conversations_stmt(context).where(
        AnalyticsConversation.status != "merged"
    )
    if project_id is not None:
        await _check_project_access(session, context, project_id)
        stmt = stmt.where(AnalyticsConversation.project_id == project_id)
    stmt = stmt.order_by(AnalyticsConversation.updated_at.desc())
    if limit is not None:
        stmt = stmt.limit(max(1, limit))
    result = await session.execute(stmt)
    conversations = result.scalars().all()
    return [
        ConversationSummary(
            id=c.id,
            project_id=c.project_id,
            surface=c.surface,
            title=c.title,
            status=c.status,
            canonical_key=c.canonical_key,
            merged_into_conversation_id=c.merged_into_conversation_id,
            updated_at=c.updated_at,
        )
        for c in conversations
    ]


@router.get(
    "/projects/{project_id}/recent-conversations",
    response_model=RecentConversationsResponse,
)
async def recent_project_conversations(
    project_id: int,
    limit: int = RECENT_CONVERSATIONS_DEFAULT_LIMIT,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> RecentConversationsResponse:
    """Most recent successfully completed question/result pairs for a project.

    Scoped to the caller's own conversations on project surfaces; system
    activity, pending/failed turns, and archived conversations never appear.
    """
    await _check_project_access(session, context, project_id)
    bounded_limit = max(1, min(limit, RECENT_CONVERSATIONS_MAX_LIMIT))

    conversation_ids = (
        _visible_conversations_stmt(context)
        .with_only_columns(AnalyticsConversation.id)
        .where(
            AnalyticsConversation.project_id == project_id,
            AnalyticsConversation.surface.in_(PROJECT_CONVERSATION_SURFACES),
            AnalyticsConversation.status == "active",
        )
        .subquery()
    )

    stmt = (
        select(AnalyticsConversationTurn, AnalyticsConversation.surface)
        .join(
            AnalyticsConversation,
            AnalyticsConversation.id == AnalyticsConversationTurn.conversation_id,
        )
        .where(
            AnalyticsConversationTurn.conversation_id.in_(select(conversation_ids)),
            AnalyticsConversationTurn.status == "success",
        )
        .order_by(
            AnalyticsConversationTurn.updated_at.desc(),
            AnalyticsConversationTurn.id.desc(),
        )
        # Over-fetch so retry/stream duplicates can be collapsed and still fill
        # the requested window.
        .limit(bounded_limit * 4)
    )
    rows = (await session.execute(stmt)).all()

    items: list[RecentConversationItem] = []
    seen: set[tuple[int, str]] = set()
    for turn, surface in rows:
        question = question_preview(turn.user_message)
        if not question:
            continue
        dedupe_key = (turn.conversation_id, question.casefold())
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        items.append(
            RecentConversationItem(
                conversation_id=turn.conversation_id,
                turn_id=turn.id,
                surface=surface,
                question_preview=question,
                result_preview=result_preview(
                    turn.assistant_message, turn.explanation, turn.chart_config
                ),
                result_type=result_type(turn.chart_config, turn.result_cache),
                completed_at=turn.updated_at,
            )
        )
        if len(items) >= bounded_limit:
            break

    return RecentConversationsResponse(project_id=project_id, items=items)


@router.get("/conversations/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(
    conversation_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> ConversationResponse:
    """Return a conversation with its ordered turns and bounded result caches."""
    conversation = await _load_conversation(session, context, conversation_id, with_turns=True)
    return _conversation_to_response(conversation)


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
