"""Cross-project aggregate reads for the home page (summaries, all-*, mine).

Split from ``projects.py``; see ``projects_shared.py`` for the helper cluster.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models.dashboard import Dashboard
from app.models.database_data_source import DatabaseDataSource
from app.models.file_source_meta import FileSourceMeta
from app.models.project import Project, ProjectMember
from app.models.project_action import ProjectAction
from app.models.project_asset import ProjectAsset
from app.models.saved_query import SavedQuery
from app.routes.projects_shared import (
    _derive_ai_status,
    _home_context,
    _owner,
    _shared_by,
)
from app.schemas.project import (
    ProjectSummaryRead,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/projects", tags=["projects"])


def _action_home_item(action: ProjectAction, project: Project) -> dict:
    """Serialize the compact action shape used by the personalized Home page."""
    return {
        "id": action.id,
        "project_id": action.project_id,
        "project_name": project.name,
        "title": action.title,
        "status": action.status,
        "priority": action.priority,
        "percent_complete": action.percent_complete,
        "due_date": action.due_date.isoformat() if action.due_date else None,
        "completed_at": (
            action.completed_at.isoformat() if action.completed_at else None
        ),
        "updated_at": action.updated_at.isoformat() if action.updated_at else None,
    }


@router.get("/actions-home")
async def get_home_action_summary(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> dict:
    """Return one tenant-safe action rollup for the personalized Home page.

    Keeping this aggregation server-side avoids loading every visible project
    and issuing an actions request for each one whenever Home opens.
    """
    projects, _ = await _home_context(session, context)
    if not projects:
        return {
            "highlights": {
                "needs_attention": 0,
                "due_this_week": 0,
                "recently_completed": 0,
            },
            "assigned": [],
            "updates": [],
        }

    now = datetime.now(UTC)
    week_end = now + timedelta(days=7)
    recent_start = now - timedelta(days=7)
    project_ids = list(projects.keys())
    visible = (
        ProjectAction.tenant_id == context.tenant_id,
        ProjectAction.project_id.in_(project_ids),
        ProjectAction.archived_at.is_(None),
        ProjectAction.deleted_at.is_(None),
    )
    active = ProjectAction.status.notin_(["completed", "cancelled"])

    needs_attention = await session.scalar(
        select(func.count(ProjectAction.id)).where(
            *visible,
            active,
            or_(
                ProjectAction.status == "blocked",
                ProjectAction.due_date < now,
            ),
        )
    )
    due_this_week = await session.scalar(
        select(func.count(ProjectAction.id)).where(
            *visible,
            active,
            ProjectAction.due_date >= now,
            ProjectAction.due_date <= week_end,
        )
    )
    recently_completed = await session.scalar(
        select(func.count(ProjectAction.id)).where(
            *visible,
            ProjectAction.status == "completed",
            ProjectAction.completed_at >= recent_start,
        )
    )

    assigned_rows = list(
        await session.scalars(
            select(ProjectAction)
            .where(
                *visible,
                active,
                ProjectAction.owner_user_id == context.user_id,
            )
            .order_by(
                ProjectAction.due_date.asc().nullslast(),
                ProjectAction.updated_at.desc(),
            )
            .limit(6)
        )
    )
    update_rows = list(
        await session.scalars(
            select(ProjectAction)
            .where(*visible)
            .order_by(ProjectAction.updated_at.desc())
            .limit(5)
        )
    )

    return {
        "highlights": {
            "needs_attention": int(needs_attention or 0),
            "due_this_week": int(due_this_week or 0),
            "recently_completed": int(recently_completed or 0),
        },
        "assigned": [
            _action_home_item(action, projects[action.project_id])
            for action in assigned_rows
        ],
        "updates": [
            _action_home_item(action, projects[action.project_id])
            for action in update_rows
        ],
    }


@router.get("/summaries", response_model=list[ProjectSummaryRead])
async def list_project_summaries(
    recent: bool = Query(default=False),
    limit: int | None = Query(default=None, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> list[ProjectSummaryRead]:
    """List visible projects with rollup counts and an AI status badge.

    Used by the Home and Projects screens to render project cards without N+1
    round-trips. Counts are computed with grouped aggregates over the set of
    projects the caller can see.
    """
    member_sub = select(ProjectMember.project_id).where(
        ProjectMember.user_id == context.user_id,
        ProjectMember.is_active.is_(True),
    )
    project_query = (
        select(Project)
        .where(
            Project.tenant_id == context.tenant_id,
            or_(
                Project.owner_id == context.user_id,
                Project.id.in_(member_sub),
            ),
        )
        .order_by(
            Project.updated_at.desc() if recent else Project.created_at.desc()
        )
    )
    if limit is not None:
        project_query = project_query.limit(limit)
    projects = list(await session.scalars(project_query))
    if not projects:
        return []

    ids = [p.id for p in projects]

    async def _grouped_counts(model) -> dict[int, int]:
        result = await session.execute(
            select(model.project_id, func.count())
            .where(model.project_id.in_(ids))
            .group_by(model.project_id)
        )
        return {pid: count for pid, count in result.all()}

    query_result = await session.execute(
        select(SavedQuery.project_id, func.count())
        .where(
            SavedQuery.project_id.in_(ids),
            SavedQuery.is_archived.is_(False),
        )
        .group_by(SavedQuery.project_id)
    )
    query_counts = {pid: count for pid, count in query_result.all()}
    dashboard_counts = await _grouped_counts(Dashboard)
    asset_counts = await _grouped_counts(ProjectAsset)
    member_counts = await _grouped_counts(ProjectMember)

    action_result = await session.execute(
        select(ProjectAction.project_id, func.count())
        .where(
            ProjectAction.project_id.in_(ids),
            ProjectAction.archived_at.is_(None),
        )
        .group_by(ProjectAction.project_id)
    )
    action_counts = {pid: count for pid, count in action_result.all()}

    indexing_states = ("processing", "indexing", "pending")
    ready_states = ("ready", "completed", "indexed", "complete")

    async def _asset_status_counts(states: tuple[str, ...]) -> dict[int, int]:
        result = await session.execute(
            select(ProjectAsset.project_id, func.count())
            .where(
                ProjectAsset.project_id.in_(ids),
                ProjectAsset.ai_status.in_(states),
            )
            .group_by(ProjectAsset.project_id)
        )
        return {pid: count for pid, count in result.all()}

    indexing_counts = await _asset_status_counts(indexing_states)
    ready_counts = await _asset_status_counts(ready_states)

    summaries: list[ProjectSummaryRead] = []
    for p in projects:
        q_count = query_counts.get(p.id, 0)
        d_count = dashboard_counts.get(p.id, 0)
        doc_count = asset_counts.get(p.id, 0)
        ai_status = _derive_ai_status(
            doc_total=doc_count,
            doc_indexing=indexing_counts.get(p.id, 0),
            doc_ready=ready_counts.get(p.id, 0),
            has_activity=(q_count > 0 or d_count > 0),
        )
        summaries.append(
            ProjectSummaryRead(
                id=p.id,
                name=p.name,
                is_shared=p.is_shared,
                updated_at=p.updated_at,
                document_count=doc_count,
                query_count=q_count,
                dashboard_count=d_count,
                action_count=action_counts.get(p.id, 0),
                member_count=member_counts.get(p.id, 0),
                data_source_count=0,
                ai_status=ai_status,
            )
        )
    return summaries


@router.get("/dashboards-all")
async def list_all_dashboards(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> list[dict]:
    """All dashboards across the caller's visible projects (Home view)."""
    projects, user_names = await _home_context(session, context)
    if not projects:
        return []
    rows = list(
        await session.scalars(
            select(Dashboard)
            .where(Dashboard.project_id.in_(list(projects.keys())))
            .order_by(Dashboard.created_at.desc())
        )
    )
    return [
        {
            "id": d.id,
            "name": d.name,
            "projectId": d.project_id,
            "projectName": (
                projects[d.project_id].name if d.project_id in projects else "—"
            ),
            "status": d.status,
            "sharedBy": _shared_by(
                projects.get(d.project_id), d.owner_id, user_names
            ),
            "ownerId": _owner(
                projects.get(d.project_id), d.owner_id, user_names
            )[0],
            "ownerName": _owner(
                projects.get(d.project_id), d.owner_id, user_names
            )[1],
            "createdAt": d.created_at.isoformat() if d.created_at else None,
        }
        for d in rows
    ]


@router.get("/datasources-all")
async def list_all_datasources(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> list[dict]:
    """All data sources (file + database) across visible projects (Home view)."""
    projects, user_names = await _home_context(session, context)
    if not projects:
        return []
    pids = list(projects.keys())

    file_rows = list(
        await session.scalars(
            select(FileSourceMeta)
            .where(
                FileSourceMeta.project_id.in_(pids),
                FileSourceMeta.archived.is_(False),
            )
            .order_by(FileSourceMeta.created_at.desc())
        )
    )
    db_rows = list(
        await session.scalars(
            select(DatabaseDataSource)
            .where(
                DatabaseDataSource.project_id.in_(pids),
                DatabaseDataSource.archived.is_(False),
            )
            .order_by(DatabaseDataSource.created_at.desc())
        )
    )

    out: list[dict] = []
    for f in file_rows:
        out.append(
            {
                "id": f.id,
                "name": f.file_name,
                "viewName": f.view_name,
                "kind": "file",
                "projectId": f.project_id,
                "projectName": (
                    projects[f.project_id].name
                    if f.project_id in projects
                    else "—"
                ),
                "sharedBy": _shared_by(
                    projects.get(f.project_id) if f.project_id is not None else None,
                    f.owner_id,
                    user_names,
                ),
                "createdAt": f.created_at.isoformat() if f.created_at else None,
            }
        )
    for d in db_rows:
        out.append(
            {
                "id": d.id,
                "name": d.display_name,
                "viewName": d.teiid_view_name,
                "kind": "database",
                "projectId": d.project_id,
                "projectName": (
                    projects[d.project_id].name
                    if d.project_id in projects
                    else "—"
                ),
                "sharedBy": _shared_by(
                    projects.get(d.project_id) if d.project_id is not None else None,
                    d.created_by,
                    user_names,
                ),
                "createdAt": d.created_at.isoformat() if d.created_at else None,
            }
        )
    out.sort(key=lambda r: r["createdAt"] or "", reverse=True)
    return out


@router.get("/my-datasources")
async def list_my_datasources(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> list[dict]:
    """All data sources the caller has created, irrespective of project.

    Powers the Data Source Builder's "Active Data Sources" list so previously
    created sources (files + database tables) show up after a refresh and can
    be reviewed / reassigned. Scoped to the caller's own sources.
    """
    projects, _ = await _home_context(session, context)

    file_rows = list(
        await session.scalars(
            select(FileSourceMeta)
            .where(
                FileSourceMeta.tenant_id == context.tenant_id,
                FileSourceMeta.owner_id == context.user_id,
                FileSourceMeta.archived.is_(False),
            )
            .order_by(FileSourceMeta.created_at.desc())
        )
    )
    db_rows = list(
        await session.scalars(
            select(DatabaseDataSource)
            .where(
                DatabaseDataSource.tenant_id == context.tenant_id,
                DatabaseDataSource.created_by == context.user_id,
                DatabaseDataSource.status == "active",
                DatabaseDataSource.archived.is_(False),
            )
            .options(selectinload(DatabaseDataSource.columns))
            .order_by(DatabaseDataSource.created_at.desc())
        )
    )

    def _project_name(pid: int | None) -> str | None:
        if pid is None:
            return None
        meta = projects.get(pid)
        return meta.name if meta else None

    out: list[dict] = []
    for f in file_rows:
        out.append(
            {
                "id": f.id,
                "kind": "file",
                "name": f.file_name,
                "viewName": f.view_name,
                "projectId": f.project_id,
                "projectName": _project_name(f.project_id),
                "columns": len(f.column_types or []),
                "sourceFormat": f.source_format,
                "createdAt": f.created_at.isoformat() if f.created_at else None,
            }
        )
    for d in db_rows:
        out.append(
            {
                "id": d.id,
                "kind": "database",
                "name": d.display_name,
                "viewName": d.teiid_view_name,
                "projectId": d.project_id,
                "projectName": _project_name(d.project_id),
                "columns": len(d.columns or []),
                "dbType": d.db_type,
                "schemaName": d.schema_name,
                "tableName": d.table_name,
                "sourceType": d.source_type,
                "connectorType": d.connector_type,
                "createdAt": d.created_at.isoformat() if d.created_at else None,
            }
        )
    out.sort(key=lambda r: r["createdAt"] or "", reverse=True)
    return out


@router.get("/documents-all")
async def list_all_documents(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> list[dict]:
    """All documents across the caller's visible projects (Home view)."""
    projects, user_names = await _home_context(session, context)
    names = {pid: meta.name for pid, meta in projects.items()}
    if not names:
        return []
    rows = list(
        await session.scalars(
            select(ProjectAsset)
            .where(ProjectAsset.project_id.in_(list(names.keys())))
            .order_by(ProjectAsset.created_at.desc())
        )
    )
    return [
        {
            "id": a.id,
            "name": a.title or a.original_filename or a.filename,
            "projectId": a.project_id,
            "projectName": names.get(a.project_id, "—"),
            "aiStatus": a.ai_status,
            "sharedBy": _shared_by(
                projects.get(a.project_id), a.owner_user_id, user_names
            ),
            "ownerId": _owner(
                projects.get(a.project_id), a.owner_user_id, user_names
            )[0],
            "ownerName": _owner(
                projects.get(a.project_id), a.owner_user_id, user_names
            )[1],
            "createdAt": a.created_at.isoformat() if a.created_at else None,
        }
        for a in rows
    ]
