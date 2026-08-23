"""Resolve the project workspace's active resource for AI Assistant grounding.

The project workspace lets a user keep several resources (tables, dashboards,
documents, data sources) open as tabs. Whichever tab is active is passed to
the workspace AI Assistant conversation as a resource_type/resource_id pair;
this module turns that pair into a short, authorized description the model
can use to ground its answer, without ever executing a query.

Authorization is scope-only: the caller (see ``append_canonical_turn`` /
``submit_canonical_turn``) has already verified the requesting user can
access ``project_id``. Resolution here only has to confirm the resource
itself belongs to that same project — a resource id from a different
project must resolve to ``None`` rather than leak that project's metadata.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Dashboard, DatabaseDataSource, ProjectAsset, SavedQuery

#: Resource types the project workspace tab strip can open.
ACTIVE_RESOURCE_TYPES = frozenset({"table", "dashboard", "document", "data_source"})


@dataclass(frozen=True)
class ActiveResourceContext:
    resource_type: str
    resource_id: int
    label: str
    summary: str


async def resolve_active_resource_context(
    session: AsyncSession,
    *,
    project_id: int,
    resource_type: str | None,
    resource_id: int | None,
) -> ActiveResourceContext | None:
    """Return a short grounding summary for the active workspace tab.

    Returns ``None`` for an unrecognized type, a missing id, or a resource
    that does not belong to ``project_id`` — callers should treat ``None``
    as "no extra grounding available" and proceed without it, not as an
    error.
    """
    if resource_type not in ACTIVE_RESOURCE_TYPES or resource_id is None:
        return None

    if resource_type == "table":
        row = await session.get(SavedQuery, resource_id)
        if row is None or row.project_id != project_id:
            return None
        parts = [f"a saved table/query named '{row.name}'"]
        if row.description:
            parts.append(f"described as: {row.description}")
        if row.sql_text:
            parts.append(f"backed by this SQL: {row.sql_text[:500]}")
        return ActiveResourceContext(
            resource_type=resource_type,
            resource_id=resource_id,
            label=row.name,
            summary="; ".join(parts),
        )

    if resource_type == "dashboard":
        row = await session.get(Dashboard, resource_id)
        if row is None or row.project_id != project_id:
            return None
        widget_count = len((row.config or {}).get("widgets") or [])
        summary = f"a dashboard named '{row.name}' with {widget_count} widget(s)"
        if row.description:
            summary += f", described as: {row.description}"
        return ActiveResourceContext(
            resource_type=resource_type,
            resource_id=resource_id,
            label=row.name,
            summary=summary,
        )

    if resource_type == "document":
        row = await session.get(ProjectAsset, resource_id)
        if row is None or row.project_id != project_id:
            return None
        summary = f"a project document titled '{row.title}' ({row.asset_type})"
        if row.ai_summary:
            summary += f", summarized as: {row.ai_summary[:500]}"
        return ActiveResourceContext(
            resource_type=resource_type,
            resource_id=resource_id,
            label=row.title,
            summary=summary,
        )

    # resource_type == "data_source"
    row = await session.get(DatabaseDataSource, resource_id)
    if row is None or row.project_id != project_id:
        return None
    summary = (
        f"a data source named '{row.display_name}' "
        f"(table '{row.table_name}' in database '{row.database_name}')"
    )
    return ActiveResourceContext(
        resource_type=resource_type,
        resource_id=resource_id,
        label=row.display_name,
        summary=summary,
    )
