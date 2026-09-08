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

from sqlalchemy import select
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


async def resolve_active_resource_contexts(
    session: AsyncSession,
    *,
    project_id: int,
    resources: list[tuple[str | None, int | None]],
) -> list[ActiveResourceContext]:
    """Resolve several active resources at once, skipping unresolvable ones.

    A workspace grounds the assistant on every card pinned to it, so the
    turn-submission path passes a list. Each pair resolves independently:
    an unknown type, missing id, or out-of-project resource is dropped
    rather than failing the whole turn.
    """
    resolved: list[ActiveResourceContext] = []
    for resource_type, resource_id in resources:
        context = await resolve_active_resource_context(
            session,
            project_id=project_id,
            resource_type=resource_type,
            resource_id=resource_id,
        )
        if context is not None:
            resolved.append(context)
    return resolved


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


@dataclass(frozen=True)
class ProjectResourceCandidate:
    """One of the project's tables/dashboards/documents/data sources.

    Unlike ``ActiveResourceContext`` this isn't authorized against a
    resource_type/resource_id the caller already asked for -- it's a row
    pulled while scanning the whole project, so ``searchable_text`` exists
    purely for scoring a candidate against a question, never shown to the
    model directly. ``summary`` is what actually reaches a prompt, in the
    same voice as ``resolve_active_resource_context``'s summaries.
    """

    resource_type: str
    resource_id: int
    label: str
    searchable_text: str
    summary: str


async def list_project_resource_candidates(
    session: AsyncSession,
    *,
    project_id: int,
    exclude: set[tuple[str, int]],
    limit_per_type: int = 200,
) -> list[ProjectResourceCandidate]:
    """Every table/dashboard/document/data source in the project, minus
    whichever are already pinned to the requesting workspace.

    Lets the assistant notice a question is probably about something the
    user hasn't dragged into the workspace yet, instead of only ever seeing
    what's already pinned. Capped per type so a very large project can't
    turn this into an unbounded scan on every turn; scoring and filtering
    happen in the caller, this just returns the field.
    """
    candidates: list[ProjectResourceCandidate] = []

    tables = await session.scalars(
        select(SavedQuery).where(SavedQuery.project_id == project_id).limit(limit_per_type)
    )
    for t in tables:
        if ("table", t.id) in exclude:
            continue
        text = " ".join(part for part in (t.name, t.description) if part)
        summary = f"a saved table/query named '{t.name}'"
        if t.description:
            summary += f", described as: {t.description}"
        candidates.append(
            ProjectResourceCandidate("table", t.id, t.name, text, summary)
        )

    dashboards = await session.scalars(
        select(Dashboard).where(Dashboard.project_id == project_id).limit(limit_per_type)
    )
    for d in dashboards:
        if ("dashboard", d.id) in exclude:
            continue
        text = " ".join(part for part in (d.name, d.description) if part)
        summary = f"a dashboard named '{d.name}'"
        if d.description:
            summary += f", described as: {d.description}"
        candidates.append(
            ProjectResourceCandidate("dashboard", d.id, d.name, text, summary)
        )

    documents = await session.scalars(
        select(ProjectAsset).where(ProjectAsset.project_id == project_id).limit(limit_per_type)
    )
    for doc in documents:
        if ("document", doc.id) in exclude:
            continue
        text = " ".join(part for part in (doc.title, doc.ai_summary) if part)
        summary = f"a project document titled '{doc.title}' ({doc.asset_type})"
        if doc.ai_summary:
            summary += f", summarized as: {doc.ai_summary[:300]}"
        candidates.append(
            ProjectResourceCandidate("document", doc.id, doc.title, text, summary)
        )

    sources = await session.scalars(
        select(DatabaseDataSource)
        .where(DatabaseDataSource.project_id == project_id)
        .limit(limit_per_type)
    )
    for ds in sources:
        if ("data_source", ds.id) in exclude:
            continue
        text = " ".join(
            part for part in (ds.display_name, ds.table_name, ds.database_name) if part
        )
        summary = (
            f"a data source named '{ds.display_name}' "
            f"(table '{ds.table_name}' in database '{ds.database_name}')"
        )
        candidates.append(
            ProjectResourceCandidate("data_source", ds.id, ds.display_name, text, summary)
        )

    return candidates
