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
        saved_query = await session.get(SavedQuery, resource_id)
        if saved_query is None or saved_query.project_id != project_id:
            return None
        parts = [f"a saved table/query named '{saved_query.name}'"]
        if saved_query.description:
            parts.append(f"described as: {saved_query.description}")
        if saved_query.sql_text:
            parts.append(f"backed by this SQL: {saved_query.sql_text[:500]}")
        return ActiveResourceContext(
            resource_type=resource_type,
            resource_id=resource_id,
            label=saved_query.name,
            summary="; ".join(parts),
        )

    if resource_type == "dashboard":
        dashboard = await session.get(Dashboard, resource_id)
        if dashboard is None or dashboard.project_id != project_id:
            return None
        widget_count = len((dashboard.config or {}).get("widgets") or [])
        summary = f"a dashboard named '{dashboard.name}' with {widget_count} widget(s)"
        if dashboard.description:
            summary += f", described as: {dashboard.description}"
        return ActiveResourceContext(
            resource_type=resource_type,
            resource_id=resource_id,
            label=dashboard.name,
            summary=summary,
        )

    if resource_type == "document":
        document = await session.get(ProjectAsset, resource_id)
        if document is None or document.project_id != project_id:
            return None
        summary = f"a project document titled '{document.title}' ({document.asset_type})"
        if document.ai_summary:
            summary += f", summarized as: {document.ai_summary[:500]}"
        return ActiveResourceContext(
            resource_type=resource_type,
            resource_id=resource_id,
            label=document.title,
            summary=summary,
        )

    # resource_type == "data_source"
    data_source = await session.get(DatabaseDataSource, resource_id)
    if data_source is None or data_source.project_id != project_id:
        return None
    summary = (
        f"a data source named '{data_source.display_name}' "
        f"(table '{data_source.table_name}' in database '{data_source.database_name}')"
    )
    return ActiveResourceContext(
        resource_type=resource_type,
        resource_id=resource_id,
        label=data_source.display_name,
        summary=summary,
    )
