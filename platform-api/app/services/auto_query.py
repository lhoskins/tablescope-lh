"""Auto-create a saved query when a data source is created.

When a user uploads a file or registers a database table, we create a saved
query named after the data source (without its file extension) so it is
immediately available in the Queries list and the Scope Relationship Builder
draggable list.  The helper is idempotent: it never creates a second query for
a data source that already has one.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.saved_query import SavedQuery

logger = logging.getLogger(__name__)

# Extensions stripped from a data-source name when deriving the query name.
_EXTENSIONS = (
    ".csv",
    ".tsv",
    ".txt",
    ".xlsx",
    ".xlsm",
    ".xls",
    ".json",
    ".parquet",
    ".xml",
)


def strip_extension(name: str) -> str:
    """Return ``name`` without a trailing data-file extension."""
    lowered = name.lower()
    for ext in _EXTENSIONS:
        if lowered.endswith(ext):
            return name[: -len(ext)]
    return name


def default_sql(view_name: str, columns: Sequence[str] | None) -> str:
    """Build the default query SQL for a single data source.

    Uses explicit column names when available; falls back to ``SELECT *`` only
    when no column metadata exists yet.
    """
    cols = [c for c in (columns or []) if c]
    if cols:
        body = ",\n  ".join(f'"{c}"' for c in cols)
        return f'SELECT\n  {body}\nFROM "{view_name}"'
    return f'SELECT * FROM "{view_name}"'


async def _unique_name(
    session: AsyncSession, *, project_id: int, base_name: str
) -> str:
    existing = set(
        (
            await session.scalars(
                select(SavedQuery.name).where(
                    SavedQuery.project_id == project_id
                )
            )
        ).all()
    )
    if base_name not in existing:
        return base_name
    n = 2
    while f"{base_name} ({n})" in existing:
        n += 1
    return f"{base_name} ({n})"


async def ensure_datasource_query(
    session: AsyncSession,
    *,
    project_id: int | None,
    owner_id: int | None,
    display_name: str,
    view_name: str,
    columns: Sequence[str] | None = None,
) -> SavedQuery | None:
    """Create a saved query for a newly created data source.

    Returns the existing query (without creating a duplicate) when one already
    references ``view_name``.  Returns ``None`` when there is no project to
    attach the query to.  The caller is responsible for committing.
    """
    if project_id is None:
        return None

    existing = await session.scalar(
        select(SavedQuery).where(
            SavedQuery.project_id == project_id,
            SavedQuery.left_datasource == view_name,
        )
    )
    if existing is not None:
        return existing

    base_name = strip_extension(display_name).strip() or view_name
    name = await _unique_name(
        session, project_id=project_id, base_name=base_name
    )
    query = SavedQuery(
        project_id=project_id,
        owner_id=owner_id,
        name=name,
        description=f"Auto-created for data source {display_name}",
        left_datasource=view_name,
        sql_text=default_sql(view_name, columns),
        ai_generated=False,
        is_shared=False,
    )
    session.add(query)
    await session.flush()
    logger.info(
        "Auto-created saved query %r (id=%s) for view %s in project %s",
        name,
        query.id,
        view_name,
        project_id,
    )
    return query
