"""Workspaces — named, multi-card canvases inside a project.

A workspace is private to its creator until they publish it to the project.
Sharing follows the ``project_assets`` pattern: a ``visibility`` column plus
``owner_user_id``, with the read check mirroring ``_check_asset_read_access``.
Every mutation beyond creation is owner-only, matching publish/unpublish.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, has_role, require_role
from app.database import get_db
from app.models import Dashboard, DatabaseDataSource, ProjectAsset, SavedQuery
from app.models.project import Project
from app.models.workspace import Workspace, WorkspaceCard
from app.routes.ai_proxy_shared import _check_project_access

router = APIRouter(prefix="/projects/{project_id}/workspaces", tags=["workspaces"])

VIEW_MODES = frozenset({"card", "row", "full"})

#: Where a card's display name comes from, per resource type — the same
#: per-type mapping ``workspace_context`` grounds the assistant with.
_LABEL_SOURCES: dict[str, tuple[type[Any], Any]] = {
    "table": (SavedQuery, SavedQuery.name),
    "dashboard": (Dashboard, Dashboard.name),
    "document": (ProjectAsset, ProjectAsset.title),
    "data_source": (DatabaseDataSource, DatabaseDataSource.display_name),
}


# ── Schemas ──────────────────────────────────────────────────────────

class WorkspaceCardRead(BaseModel):
    id: int
    resource_type: str
    resource_id: str
    view_mode: str
    position: int
    added_at: datetime | None = None
    #: Resolved display name for the pinned resource, or None when the
    #: resource no longer exists (or never belonged to this project).
    label: str | None = None


class WorkspaceRead(BaseModel):
    id: int
    tenant_id: int
    project_id: int
    owner_user_id: int | None
    name: str
    visibility: str
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime
    cards: list[WorkspaceCardRead]


class WorkspaceCardCreate(BaseModel):
    resource_type: str = Field(..., max_length=50)
    resource_id: str = Field(..., max_length=255)


class WorkspaceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    cards: list[WorkspaceCardCreate] | None = None


class WorkspaceCardPatch(BaseModel):
    resource_type: str = Field(..., max_length=50)
    resource_id: str = Field(..., max_length=255)
    view_mode: str = Field(default="card", max_length=20)
    position: int | None = None


class WorkspacePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    #: Full replacement of the card list — add, remove, reorder, and
    #: view_mode changes are all expressed as the new desired list.
    cards: list[WorkspaceCardPatch] | None = None


# ── Helpers ──────────────────────────────────────────────────────────

async def _require_project_access(
    project_id: int,
    session: AsyncSession,
    context: RequestContext,
) -> Project:
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.tenant_id != context.tenant_id:
        raise HTTPException(status_code=403, detail="Not in this tenant")
    return project


def _check_workspace_read_access(workspace: Workspace, context: RequestContext) -> None:
    """Private-workspace authorization, independent of general project
    access: a workspace with visibility="private" is readable only by its
    owner (or a tenant admin)."""
    if workspace.visibility == "private" and workspace.owner_user_id != context.user_id:
        if not has_role(context.role, Role.TENANT_ADMIN):
            raise HTTPException(status_code=403, detail="This workspace is private")


def _check_workspace_owner(workspace: Workspace, context: RequestContext) -> None:
    """Publish/unpublish and every card edit are gated on ownership of this
    specific workspace, not on a project-level role — each member owns their
    own workspaces and decides what to share."""
    if workspace.owner_user_id != context.user_id:
        raise HTTPException(status_code=403, detail="Only the workspace owner can modify it")


async def _get_workspace(
    project_id: int,
    workspace_id: int,
    session: AsyncSession,
    context: RequestContext,
) -> Workspace:
    workspace = await session.get(Workspace, workspace_id)
    if (
        workspace is None
        or workspace.project_id != project_id
        or workspace.tenant_id != context.tenant_id
    ):
        raise HTTPException(status_code=404, detail="Workspace not found")
    return workspace


async def _load_cards(session: AsyncSession, workspace_id: int) -> list[WorkspaceCard]:
    result = await session.execute(
        select(WorkspaceCard)
        .where(WorkspaceCard.workspace_id == workspace_id)
        .order_by(WorkspaceCard.position, WorkspaceCard.id)
    )
    return list(result.scalars().all())


def _numeric_resource_id(resource_id: str) -> int | None:
    """Card ids are stored as strings (matching the frontend WorkspaceTab id
    shape); resolution against the project's tables/dashboards/documents/data
    sources needs the numeric form, which not every id has."""
    try:
        return int(resource_id)
    except (TypeError, ValueError):
        return None


async def _resolve_labels(
    session: AsyncSession,
    project_id: int,
    cards: list[WorkspaceCard],
) -> dict[tuple[str, str], str]:
    """Display names for every pinned resource, one query per resource type.

    The Workspace page lists all of a caller's workspaces at once, so per-card
    lookups would scale the round trips with the total number of cards.
    Resources outside ``project_id`` are simply absent from the result.
    """
    wanted: dict[str, set[int]] = {}
    for card in cards:
        numeric = _numeric_resource_id(card.resource_id)
        if numeric is not None and card.resource_type in _LABEL_SOURCES:
            wanted.setdefault(card.resource_type, set()).add(numeric)

    labels: dict[tuple[str, str], str] = {}
    for resource_type, ids in wanted.items():
        model, name_column = _LABEL_SOURCES[resource_type]
        result = await session.execute(
            select(model.id, name_column).where(
                model.id.in_(ids), model.project_id == project_id,
            )
        )
        for row_id, label in result.all():
            labels[(resource_type, str(row_id))] = label
    return labels


async def _card_reads(
    session: AsyncSession,
    project_id: int,
    cards: list[WorkspaceCard],
) -> list[WorkspaceCardRead]:
    labels = await _resolve_labels(session, project_id, cards)
    return [
        WorkspaceCardRead(
            id=card.id,
            resource_type=card.resource_type,
            resource_id=card.resource_id,
            view_mode=card.view_mode,
            position=card.position,
            added_at=card.added_at,
            label=labels.get((card.resource_type, card.resource_id)),
        )
        for card in cards
    ]


def _workspace_read_from(
    workspace: Workspace,
    cards: list[WorkspaceCardRead],
) -> WorkspaceRead:
    return WorkspaceRead(
        id=workspace.id,
        tenant_id=workspace.tenant_id,
        project_id=workspace.project_id,
        owner_user_id=workspace.owner_user_id,
        name=workspace.name,
        visibility=workspace.visibility,
        published_at=workspace.published_at,
        created_at=workspace.created_at,
        updated_at=workspace.updated_at,
        cards=cards,
    )


async def _workspace_read(
    session: AsyncSession,
    workspace: Workspace,
) -> WorkspaceRead:
    cards = await _load_cards(session, workspace.id)
    return _workspace_read_from(
        workspace, await _card_reads(session, workspace.project_id, cards),
    )


async def _workspace_reads(
    session: AsyncSession,
    project_id: int,
    workspaces: list[Workspace],
) -> list[WorkspaceRead]:
    """Read models for a whole list of workspaces in a fixed number of
    queries: one for every card, plus one per resource type for labels."""
    if not workspaces:
        return []
    result = await session.execute(
        select(WorkspaceCard)
        .where(WorkspaceCard.workspace_id.in_([w.id for w in workspaces]))
        .order_by(WorkspaceCard.position, WorkspaceCard.id)
    )
    all_cards = list(result.scalars().all())
    labels = await _resolve_labels(session, project_id, all_cards)

    by_workspace: dict[int, list[WorkspaceCardRead]] = {w.id: [] for w in workspaces}
    for card in all_cards:
        by_workspace[card.workspace_id].append(
            WorkspaceCardRead(
                id=card.id,
                resource_type=card.resource_type,
                resource_id=card.resource_id,
                view_mode=card.view_mode,
                position=card.position,
                added_at=card.added_at,
                label=labels.get((card.resource_type, card.resource_id)),
            )
        )
    return [_workspace_read_from(w, by_workspace[w.id]) for w in workspaces]


# ── Endpoints ────────────────────────────────────────────────────────

@router.post("", response_model=WorkspaceRead, status_code=201)
async def create_workspace(
    project_id: int,
    body: WorkspaceCreate,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> WorkspaceRead:
    await _require_project_access(project_id, session, context)
    await _check_project_access(session, context, project_id)

    workspace = Workspace(
        tenant_id=context.tenant_id,
        project_id=project_id,
        owner_user_id=context.user_id,
        name=body.name,
        visibility="private",
    )
    session.add(workspace)
    await session.flush()

    for position, card in enumerate(body.cards or []):
        session.add(
            WorkspaceCard(
                workspace_id=workspace.id,
                resource_type=card.resource_type,
                resource_id=card.resource_id,
                view_mode="card",
                position=position,
            )
        )
    await session.flush()
    await session.refresh(workspace)
    return await _workspace_read(session, workspace)


@router.get("", response_model=list[WorkspaceRead])
async def list_workspaces(
    project_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> list[WorkspaceRead]:
    await _require_project_access(project_id, session, context)
    await _check_project_access(session, context, project_id)

    result = await session.execute(
        select(Workspace)
        .where(
            Workspace.project_id == project_id,
            Workspace.tenant_id == context.tenant_id,
            or_(
                Workspace.visibility == "shared_project",
                Workspace.owner_user_id == context.user_id,
            ),
        )
        .order_by(Workspace.created_at)
    )
    return await _workspace_reads(session, project_id, list(result.scalars().all()))


@router.get("/{workspace_id}", response_model=WorkspaceRead)
async def get_workspace(
    project_id: int,
    workspace_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> WorkspaceRead:
    await _require_project_access(project_id, session, context)
    await _check_project_access(session, context, project_id)
    workspace = await _get_workspace(project_id, workspace_id, session, context)
    _check_workspace_read_access(workspace, context)
    return await _workspace_read(session, workspace)


@router.patch("/{workspace_id}", response_model=WorkspaceRead)
async def update_workspace(
    project_id: int,
    workspace_id: int,
    body: WorkspacePatch,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> WorkspaceRead:
    await _require_project_access(project_id, session, context)
    await _check_project_access(session, context, project_id)
    workspace = await _get_workspace(project_id, workspace_id, session, context)
    _check_workspace_owner(workspace, context)

    if body.name is not None:
        workspace.name = body.name

    if body.cards is not None:
        for card in body.cards:
            if card.view_mode not in VIEW_MODES:
                raise HTTPException(
                    status_code=400, detail=f"Unsupported view_mode: {card.view_mode}",
                )
        # Full-array replace: adds, removes, reorders and view_mode changes
        # all arrive as the new desired list, so there is no partial-op
        # ordering to reconcile.
        existing = {
            (c.resource_type, c.resource_id): c
            for c in await _load_cards(session, workspace.id)
        }
        keep_ids: list[int] = []
        for position, card in enumerate(body.cards):
            key = (card.resource_type, card.resource_id)
            row = existing.get(key)
            if row is None:
                row = WorkspaceCard(
                    workspace_id=workspace.id,
                    resource_type=card.resource_type,
                    resource_id=card.resource_id,
                )
                session.add(row)
            row.view_mode = card.view_mode
            row.position = card.position if card.position is not None else position
            await session.flush()
            keep_ids.append(row.id)
        stmt = delete(WorkspaceCard).where(WorkspaceCard.workspace_id == workspace.id)
        if keep_ids:
            stmt = stmt.where(WorkspaceCard.id.notin_(keep_ids))
        await session.execute(stmt)

    workspace.updated_at = datetime.now(UTC)
    await session.flush()
    return await _workspace_read(session, workspace)


@router.post("/{workspace_id}/publish", response_model=WorkspaceRead)
async def publish_workspace(
    project_id: int,
    workspace_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> WorkspaceRead:
    await _require_project_access(project_id, session, context)
    await _check_project_access(session, context, project_id)
    workspace = await _get_workspace(project_id, workspace_id, session, context)
    _check_workspace_owner(workspace, context)

    workspace.visibility = "shared_project"
    workspace.published_at = datetime.now(UTC)
    workspace.updated_at = datetime.now(UTC)
    await session.flush()
    return await _workspace_read(session, workspace)


@router.post("/{workspace_id}/unpublish", response_model=WorkspaceRead)
async def unpublish_workspace(
    project_id: int,
    workspace_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> WorkspaceRead:
    await _require_project_access(project_id, session, context)
    await _check_project_access(session, context, project_id)
    workspace = await _get_workspace(project_id, workspace_id, session, context)
    _check_workspace_owner(workspace, context)

    workspace.visibility = "private"
    workspace.published_at = None
    workspace.updated_at = datetime.now(UTC)
    await session.flush()
    return await _workspace_read(session, workspace)


@router.delete("/{workspace_id}")
async def delete_workspace(
    project_id: int,
    workspace_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict:
    await _require_project_access(project_id, session, context)
    await _check_project_access(session, context, project_id)
    workspace = await _get_workspace(project_id, workspace_id, session, context)
    _check_workspace_owner(workspace, context)

    await session.execute(
        delete(WorkspaceCard).where(WorkspaceCard.workspace_id == workspace.id)
    )
    await session.delete(workspace)
    await session.flush()
    return {"status": "deleted", "workspace_id": workspace_id}
