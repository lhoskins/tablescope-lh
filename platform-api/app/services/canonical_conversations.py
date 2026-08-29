"""Canonical Business and Project Insight conversation lifecycle.

A canonical conversation is one durable thread per (tenant, user, surface,
project). New questions from the same Insight surface append to the same
conversation instead of creating duplicates. Manual AI Assistant chats remain
independent because they have ``canonical_key = NULL``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.context import RequestContext
from app.auth.rbac import Role
from app.models import AnalyticsConversation, AnalyticsConversationTurn, Project
from app.services.conversational_analytics import execute_turn
from app.services.workspace_context import (
    ActiveResourceContext,
    resolve_active_resource_contexts,
)


def _is_conversation_reader(context: RequestContext, conversation: AnalyticsConversation) -> bool:
    if conversation.tenant_id != context.tenant_id:
        return False
    if conversation.user_id == context.user_id:
        return True
    return context.role in (Role.ROOT_ADMIN.value, Role.TENANT_ADMIN.value, Role.ADMIN.value)


class CanonicalConversationSurface(str, Enum):
    BUSINESS_INSIGHTS = "business_insights"
    PROJECT_INSIGHTS = "project_insights"
    PROJECT_WORKSPACE = "project_workspace"


class CanonicalSurfaceError(Exception):
    pass


class CanonicalProjectError(Exception):
    pass


def canonical_scope_key(surface: str, project_id: int | None) -> str:
    if surface == CanonicalConversationSurface.BUSINESS_INSIGHTS.value:
        return "business_insights"
    if surface == CanonicalConversationSurface.PROJECT_INSIGHTS.value:
        if project_id is None:
            raise CanonicalProjectError("project_id is required for project_insights")
        return f"project_insights:{project_id}"
    if surface == CanonicalConversationSurface.PROJECT_WORKSPACE.value:
        if project_id is None:
            raise CanonicalProjectError("project_id is required for project_workspace")
        return f"project_workspace:{project_id}"
    raise CanonicalSurfaceError(f"Unsupported canonical surface: {surface}")


async def _get_or_create_canonical_conversation(
    session: AsyncSession,
    context: RequestContext,
    *,
    surface: CanonicalConversationSurface,
    project_id: int | None,
    key: str,
    title: str,
) -> tuple[AnalyticsConversation, bool]:
    """Atomic get-or-create of a canonical conversation.

    Uses ``SELECT ... FOR UPDATE`` followed by a plain insert. If a concurrent
    request wins the race, the unique constraint raises an ``IntegrityError`` and
    the caller retries, loading the existing canonical row.
    """
    stmt = (
        select(AnalyticsConversation)
        .where(
            AnalyticsConversation.tenant_id == context.tenant_id,
            AnalyticsConversation.user_id == context.user_id,
            AnalyticsConversation.canonical_key == key,
            AnalyticsConversation.status == "active",
        )
        .with_for_update()
    )
    result = await session.execute(stmt)
    existing = result.scalar_one_or_none()
    if existing is not None:
        return existing, False

    conversation = AnalyticsConversation(
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        project_id=project_id,
        surface=surface.value,
        title=title,
        status="active",
        canonical_key=key,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    session.add(conversation)
    await session.flush()
    return conversation, True


class CanonicalTurnResult:
    def __init__(
        self,
        *,
        conversation_id: int,
        conversation_created: bool,
        surface: str,
        project_id: int | None,
        turn_id: int,
        sequence: int,
        status: str,
    ) -> None:
        self.conversation_id = conversation_id
        self.conversation_created = conversation_created
        self.surface = surface
        self.project_id = project_id
        self.turn_id = turn_id
        self.sequence = sequence
        self.status = status


async def append_canonical_turn(
    session: AsyncSession,
    context: RequestContext,
    *,
    surface: CanonicalConversationSurface,
    project_id: int | None,
    message: str,
    client_request_id: str,
    data_source_id: int | None = None,
    attachment_ids: list[int] | None = None,
    active_resource_type: str | None = None,
    active_resource_id: int | None = None,
    active_resources: list[tuple[str | None, int | None]] | None = None,
) -> CanonicalTurnResult:
    """Append one turn to the canonical Insight thread for this scope.

    Idempotent by ``client_request_id``; the same request ID returns the
    existing turn instead of creating a duplicate. The conversation is
    created atomically on first use, and turn sequences are contiguous within
    the thread.
    """
    if surface == CanonicalConversationSurface.BUSINESS_INSIGHTS:
        if project_id is not None:
            raise CanonicalProjectError(
                "business_insights cannot be scoped to a project_id"
            )
        title = "Business Insights"
    elif surface == CanonicalConversationSurface.PROJECT_INSIGHTS:
        if project_id is None:
            raise CanonicalProjectError("project_id is required for project_insights")
        project = await session.get(Project, project_id)
        if project is None or project.tenant_id != context.tenant_id:
            raise CanonicalProjectError("Project not found")
        title = f"Project Insights — {project.name}"
    elif surface == CanonicalConversationSurface.PROJECT_WORKSPACE:
        if project_id is None:
            raise CanonicalProjectError("project_id is required for project_workspace")
        project = await session.get(Project, project_id)
        if project is None or project.tenant_id != context.tenant_id:
            raise CanonicalProjectError("Project not found")
        title = f"Workspace — {project.name}"
    else:
        raise CanonicalSurfaceError(f"Unsupported canonical surface: {surface}")

    key = canonical_scope_key(surface.value, project_id)

    # Retry once on the rare race where two first requests hit simultaneously.
    conversation: AnalyticsConversation | None = None
    created = False
    last_error: Exception | None = None
    for _ in range(2):
        try:
            conversation, created = await _get_or_create_canonical_conversation(
                session,
                context,
                surface=surface,
                project_id=project_id,
                key=key,
                title=title,
            )
            break
        except IntegrityError as exc:
            last_error = exc
            await session.rollback()
    if conversation is None:
        raise last_error or RuntimeError("Could not resolve canonical conversation")

    # Idempotency: return an existing turn for this request id.
    if client_request_id:
        existing_turn = await session.scalar(
            select(AnalyticsConversationTurn).where(
                AnalyticsConversationTurn.conversation_id == conversation.id,
                AnalyticsConversationTurn.client_request_id == client_request_id,
            )
        )
        if existing_turn is not None:
            return CanonicalTurnResult(
                conversation_id=conversation.id,
                conversation_created=created,
                surface=surface.value,
                project_id=project_id,
                turn_id=existing_turn.id,
                sequence=existing_turn.sequence,
                status=existing_turn.status,
            )

    # Allocate the next sequence under the conversation lock.
    max_sequence = await session.scalar(
        select(func.coalesce(func.max(AnalyticsConversationTurn.sequence), 0)).where(
            AnalyticsConversationTurn.conversation_id == conversation.id
        )
    ) or 0

    turn = AnalyticsConversationTurn(
        conversation_id=conversation.id,
        sequence=int(max_sequence) + 1,
        user_message=message,
        client_request_id=client_request_id,
        parent_turn_id=conversation.last_successful_turn_id,
        status="pending",
    )
    session.add(turn)
    await session.flush()

    # A workspace grounds on every card pinned to it; the single
    # active_resource_type/id pair is the one-card case of that list.
    requested_resources = active_resources or [(active_resource_type, active_resource_id)]
    resolved_resources: list[ActiveResourceContext] = []
    if surface == CanonicalConversationSurface.PROJECT_WORKSPACE and project_id is not None:
        resolved_resources = await resolve_active_resource_contexts(
            session,
            project_id=project_id,
            resources=requested_resources,
        )

    await execute_turn(
        session,
        context,
        conversation,
        turn,
        datasource_id=data_source_id,
        attachment_ids=attachment_ids or [],
        active_resources=resolved_resources,
    )

    if turn.status == "success":
        conversation.last_successful_turn_id = turn.id
    conversation.updated_at = datetime.now(UTC)
    await session.flush()

    return CanonicalTurnResult(
        conversation_id=conversation.id,
        conversation_created=created,
        surface=surface.value,
        project_id=project_id,
        turn_id=turn.id,
        sequence=turn.sequence,
        status=turn.status,
    )


async def load_canonical_conversation(
    session: AsyncSession,
    context: RequestContext,
    conversation_id: int,
    *,
    with_turns: bool = False,
) -> AnalyticsConversation | None:
    """Load a conversation, following merge aliases up to a bounded depth.

    Tenant/user authorization is enforced at every hop. Returns ``None`` if
    the conversation is inaccessible.
    """
    for _ in range(4):
        if with_turns:
            result = await session.execute(
                select(AnalyticsConversation)
                .options(
                    selectinload(AnalyticsConversation.turns).selectinload(
                        AnalyticsConversationTurn.chat_attachments
                    )
                )
                .where(AnalyticsConversation.id == conversation_id)
            )
            conversation = result.scalar_one_or_none()
        else:
            conversation = await session.get(AnalyticsConversation, conversation_id)
        if conversation is None:
            return None
        if not _is_conversation_reader(context, conversation):
            return None
        if conversation.merged_into_conversation_id is None:
            return conversation
        conversation_id = conversation.merged_into_conversation_id
    return None
