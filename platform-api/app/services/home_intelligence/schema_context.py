from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.database_data_source import DatabaseDataSource
from app.models.file_source_meta import FileSourceMeta
from app.models.project import Project
from app.models.project_asset import ProjectAsset
from app.models.query_scope import QueryScope
from app.models.reference_library import (
    TIER_COMPANY,
    TIER_INDUSTRY,
    TIER_PROJECT,
    ReferenceDocument,
)
from app.models.saved_query import SavedQuery

from .query_helpers import _detect_view_strict, _norm, logger

_PROJECT_COLORS = [
    "#185FA5", "#0F6E56", "#7A4FB5", "#B5642F", "#2F7DB5", "#9A2F5E",
]


def project_color(project_id: int) -> str:
    return _PROJECT_COLORS[project_id % len(_PROJECT_COLORS)]


# ─────────────────────────────────────────────────────────────────────────────
# Project context
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TableInfo:
    view_name: str
    columns: list[tuple[str, str]] = field(default_factory=list)  # (name, type)
    kind: str = "file"  # "file" | "db"

    @property
    def column_names(self) -> list[str]:
        return [c[0] for c in self.columns]


@dataclass
class DocInfo:
    title: str
    ai_summary: str | None
    ai_metadata: dict[str, Any]


@dataclass
class ScopeLink:
    """A user/AI-curated drill-down relationship resolved to view names.

    Sourced from enabled ``QueryScope`` rows and mapped from saved-query ids
    onto the concrete Teiid view names the planner reasons about, so a curated
    relationship becomes strong join evidence.
    """

    left_table: str
    right_table: str
    left_column: str
    right_column: str
    created_by_ai: bool


@dataclass
class ProjectContext:
    tables: list[TableInfo]
    documents: list[DocInfo]
    scope_links: list[ScopeLink] = field(default_factory=list)


async def gather_project_context(
    session: AsyncSession, project: Project
) -> ProjectContext:
    """Collect a project's real tables (with columns) and documents."""
    tables: list[TableInfo] = []

    files = (
        await session.scalars(
            select(FileSourceMeta).where(
                FileSourceMeta.project_id == project.id,
                FileSourceMeta.archived.is_(False),
            )
        )
    ).all()
    for f in files:
        cols: list[tuple[str, str]] = []
        for c in f.column_types or []:
            name = c.get("name") or c.get("column") or c.get("field_name")
            if name:
                cols.append((str(name), str(c.get("type", "string"))))
        tables.append(TableInfo(view_name=f.view_name, columns=cols, kind="file"))

    db_sources = (
        await session.scalars(
            select(DatabaseDataSource)
            .where(
                DatabaseDataSource.project_id == project.id,
                DatabaseDataSource.archived.is_(False),
            )
            .options(selectinload(DatabaseDataSource.columns))
        )
    ).all()
    for ds in db_sources:
        cols = [
            (c.column_name, str(c.teiid_type_override or c.data_type or "string"))
            for c in ds.columns
        ]
        tables.append(
            TableInfo(view_name=ds.teiid_view_name, columns=cols, kind="db")
        )

    assets = (
        await session.scalars(
            select(ProjectAsset).where(ProjectAsset.project_id == project.id)
        )
    ).all()
    documents = [
        DocInfo(
            title=a.title or a.original_filename or a.filename,
            ai_summary=a.ai_summary,
            ai_metadata=a.ai_metadata or {},
        )
        for a in assets
    ]

    # Reference Library docs in scope (industry = global, company = this tenant,
    # project = this project) so Home analyses can ground in governed standards
    # and policies, not just the project's own uploads.
    ref_docs = (
        await session.scalars(
            select(ReferenceDocument)
            .where(
                ReferenceDocument.status == "active",
                ReferenceDocument.ai_summary.isnot(None),
                or_(
                    ReferenceDocument.tier == TIER_INDUSTRY,
                    and_(
                        ReferenceDocument.tier == TIER_COMPANY,
                        ReferenceDocument.tenant_id == project.tenant_id,
                    ),
                    and_(
                        ReferenceDocument.tier == TIER_PROJECT,
                        ReferenceDocument.project_id == project.id,
                    ),
                ),
            )
            .order_by(ReferenceDocument.updated_at.desc())
            .limit(40)
        )
    ).all()
    for r in ref_docs:
        documents.append(
            DocInfo(
                title=r.title,
                ai_summary=r.ai_summary,
                ai_metadata={
                    "reference_tier": r.tier,
                    "issuing_body": r.issuing_body or "",
                    "domain_tag": r.domain_tag or "",
                },
            )
        )

    scope_links: list[ScopeLink] = []
    try:
        scope_links = await _resolve_scope_links(
            session,
            project_id=project.id,
            allowed_tables=[t.view_name for t in tables],
        )
    except Exception as exc:  # fail-open: enrichment must never break context
        logger.warning(
            "Scope-link enrichment skipped for project %s: %s", project.id, exc
        )

    return ProjectContext(
        tables=tables,
        documents=documents,
        scope_links=scope_links,
    )


async def _resolve_scope_links(
    session: AsyncSession,
    *,
    project_id: int,
    allowed_tables: list[str],
) -> list[ScopeLink]:
    """Map this project's enabled ``QueryScope`` rows onto view-to-view links.

    Only enabled scopes for *this* project are read (never crossing project
    boundaries). Each scope's source and target saved query is resolved to a
    single allowed view via :func:`_detect_view_strict`; scopes whose SQL is
    missing, matches zero or multiple views, or self-references are skipped.
    Links are de-duplicated by (sorted view pair, normalized source field).
    """
    scopes = (
        await session.scalars(
            select(QueryScope).where(
                QueryScope.project_id == project_id,
                QueryScope.enabled.is_(True),
            )
        )
    ).all()
    if not scopes:
        return []

    query_ids = {s.query_id for s in scopes} | {
        s.target_query_id for s in scopes
    }
    queries = (
        await session.scalars(
            select(SavedQuery).where(SavedQuery.id.in_(query_ids))
        )
    ).all()
    sql_by_id = {q.id: q.sql_text for q in queries}

    links: list[ScopeLink] = []
    seen: set[tuple[str, str, str]] = set()
    for s in scopes:
        left = _detect_view_strict(sql_by_id.get(s.query_id), allowed_tables)
        right = _detect_view_strict(
            sql_by_id.get(s.target_query_id), allowed_tables
        )
        if not left or not right or left == right:
            continue
        lo, hi_ = sorted([left, right])
        key = (lo, hi_, _norm(s.source_field))
        if key in seen:
            continue
        seen.add(key)
        links.append(
            ScopeLink(
                left_table=left,
                right_table=right,
                left_column=s.source_field.strip('"'),
                right_column=s.target_field.strip('"'),
                created_by_ai=bool(s.created_by_ai),
            )
        )
    return links
