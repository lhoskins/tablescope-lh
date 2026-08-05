
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.database_data_source import DatabaseDataSource
from app.models.file_source_meta import FileSourceMeta
from app.models.saved_query import SavedQuery

from .terms import _tokens
from .types import _Source

# ---------------------------------------------------------------------------
# Source gathering (tenant + project scoped)
# ---------------------------------------------------------------------------

async def _gather_sources(
    session: AsyncSession, *, tenant_id: int, project_id: int
) -> list[_Source]:
    """Collect the project's authorized file + database sources with columns."""
    sources: list[_Source] = []

    files = (
        await session.scalars(
            select(FileSourceMeta).where(
                FileSourceMeta.tenant_id == tenant_id,
                FileSourceMeta.project_id == project_id,
                FileSourceMeta.archived.is_(False),
            )
        )
    ).all()
    for f in files:
        cols = [
            str(c.get("name"))
            for c in (f.column_types or [])
            if isinstance(c, dict) and c.get("name")
        ]
        description = ""
        if isinstance(f.ai_metadata, dict):
            description = str(f.ai_metadata.get("summary") or "")
        sources.append(
            _Source(name=f.view_name, columns=cols, kind="table",
                    description=description)
        )

    db_rows = (
        await session.scalars(
            select(DatabaseDataSource)
            .where(
                DatabaseDataSource.tenant_id == tenant_id,
                DatabaseDataSource.project_id == project_id,
                DatabaseDataSource.archived.is_(False),
            )
            .options(selectinload(DatabaseDataSource.columns))
        )
    ).all()
    for ds in db_rows:
        cols = [c.column_name for c in ds.columns if c.column_name]
        sources.append(
            _Source(name=ds.teiid_view_name, columns=cols, kind="db")
        )

    return sources


async def _saved_query_terms(
    session: AsyncSession, project_id: int
) -> set[str]:
    """Terms drawn from the project's saved query names/descriptions."""
    rows = (
        await session.scalars(
            select(SavedQuery).where(SavedQuery.project_id == project_id)
        )
    ).all()
    terms: set[str] = set()
    for q in rows:
        for t in _tokens(f"{q.name or ''} {q.description or ''}"):
            terms.add(t)
    return terms
