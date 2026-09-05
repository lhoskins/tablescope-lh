"""Per-viewer document visibility filtering for Knowledge Graph reads (KG-04).

The graph is built once (by whichever project member last triggered a
rebuild) and cached in a shared snapshot; every subsequent read of that
cached snapshot must still respect each individual viewer's own document
permissions, not just the tenant/project boundary already checked before
reaching this module. A private ``ProjectAsset`` document -- and every card,
gap, recommended action, and trace path that cites it as evidence -- must
never reach a user who is neither its owner nor a tenant admin, even though
that user is an authorized member of the project as a whole.

Mirrors the existing per-document policy in
``app/routes/project_assets.py::_check_asset_read_access`` rather than
inventing a second one.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.rbac import Role, has_role
from app.models.project_asset import ProjectAsset

_EMPTY_STATS: dict[str, Any] = {
    "nodeCount": 0, "edgeCount": 0, "cardCount": 0, "gapCount": 0, "byDisplayGroup": {},
}


async def _hidden_project_asset_ids(
    session: AsyncSession,
    nodes: list[dict[str, Any]],
    *,
    tenant_id: int,
    user_id: int | None,
    role: str | None,
) -> set[int]:
    if role is not None and has_role(role, Role.TENANT_ADMIN):
        return set()
    asset_ids = {
        n.get("source_id")
        for n in nodes
        if n.get("source_type") == "project_asset" and n.get("source_id") is not None
    }
    if not asset_ids:
        return set()
    rows = (
        await session.execute(
            select(ProjectAsset.id, ProjectAsset.visibility, ProjectAsset.owner_user_id)
            .where(
                ProjectAsset.id.in_(asset_ids),
                ProjectAsset.tenant_id == tenant_id,
            )
        )
    ).all()
    return {
        asset_id
        for asset_id, visibility, owner_user_id in rows
        if visibility == "private" and owner_user_id != user_id
    }


def _hidden_node_ids(nodes: list[dict[str, Any]], hidden_asset_ids: set[int]) -> set[int]:
    """Node ids to hide given a set of hidden ``ProjectAsset`` ids.

    Covers both the document node itself (``source_type == "project_asset"``)
    and any chunk/passage node derived from it (KG-08/KG-16:
    ``source_type == "ai_document_chunk"``, tagged with its parent's id at
    ``properties.asset_id`` in ``collect_structural_graph``) -- a passage IS
    its parent document's evidence, so it can never be visible to a viewer
    the parent itself is hidden from. Shared by both filter functions below
    so this can't drift between the pre-enrichment and post-build paths.
    """
    if not hidden_asset_ids:
        return set()
    ids: set[int] = set()
    for n in nodes:
        source_type = n.get("source_type")
        if source_type == "project_asset" and n.get("source_id") in hidden_asset_ids:
            ids.add(n["id"])
        elif source_type == "ai_document_chunk":
            if (n.get("properties") or {}).get("asset_id") in hidden_asset_ids:
                ids.add(n["id"])
    return ids


async def filter_raw_graph_for_user(
    session: AsyncSession,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    *,
    tenant_id: int,
    user_id: int | None,
    role: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Strip private-document nodes/edges the given user can't read from a
    raw (pre-enrichment) node/edge list (KG-06).

    Used before the AI-enrichment payload is built, so a document private to
    one project member never reaches the AI server as context for another
    member's cached cards -- not just hidden from the response afterwards
    (see ``filter_payload_for_viewer``), but never sent in the first place.
    """
    hidden_asset_ids = await _hidden_project_asset_ids(
        session, nodes, tenant_id=tenant_id, user_id=user_id, role=role
    )
    if not hidden_asset_ids:
        return nodes, edges

    hidden_node_ids = _hidden_node_ids(nodes, hidden_asset_ids)
    visible_nodes = [n for n in nodes if n["id"] not in hidden_node_ids]
    visible_edges = [
        e for e in edges
        if e.get("from_node_id") not in hidden_node_ids
        and e.get("to_node_id") not in hidden_node_ids
    ]
    return visible_nodes, visible_edges


async def filter_payload_for_viewer(
    session: AsyncSession,
    payload: dict[str, Any],
    *,
    tenant_id: int,
    user_id: int | None,
    role: str | None,
) -> dict[str, Any]:
    """Strip nodes/edges/cards/gaps/actions/trace-paths backed by a private
    document the viewer doesn't own. A no-op fast path when nothing in the
    payload is private, which is the overwhelmingly common case.
    """
    nodes = payload.get("nodes") or []
    hidden_asset_ids = await _hidden_project_asset_ids(
        session, nodes, tenant_id=tenant_id, user_id=user_id, role=role
    )
    if not hidden_asset_ids:
        return payload

    hidden_node_ids = _hidden_node_ids(nodes, hidden_asset_ids)
    hidden_graph_keys = {
        n.get("graphKey") for n in nodes if n["id"] in hidden_node_ids and n.get("graphKey")
    }

    center = payload.get("centerNode")
    if center is not None and center.get("id") in hidden_node_ids:
        # The requested center itself is a private document the viewer can't
        # open -- never echo its label/summary back. Shaped like "nothing
        # found" rather than a 403 so a stale bookmark/link degrades quietly.
        return {
            **payload,
            "centerNode": None,
            "nodes": [],
            "edges": [],
            "insightCards": [],
            "gaps": [],
            "recommendedActions": [],
            "tracePaths": [],
            "stats": dict(_EMPTY_STATS),
            "visibilityRestricted": True,
        }

    visible_nodes = [n for n in nodes if n["id"] not in hidden_node_ids]
    visible_node_ids = {n["id"] for n in visible_nodes}

    edges = payload.get("edges") or []
    visible_edges = [
        e for e in edges
        if e.get("source") in visible_node_ids and e.get("target") in visible_node_ids
    ]

    def _cites_hidden_node(node_ids: list[Any]) -> bool:
        return any(nid in hidden_node_ids for nid in node_ids)

    cards = [
        c for c in (payload.get("insightCards") or [])
        if not _cites_hidden_node((c.get("traceToEvidence") or {}).get("nodeIds") or [])
    ]
    trace_paths = [
        t for t in (payload.get("tracePaths") or [])
        if not _cites_hidden_node(t.get("nodeIds") or [])
    ]
    gaps = [
        g for g in (payload.get("gaps") or [])
        if g.get("nodeKey") not in hidden_graph_keys
    ]
    recommended_actions = [
        a for a in (payload.get("recommendedActions") or [])
        if a.get("nodeKey") not in hidden_graph_keys
    ]

    by_group: dict[str, int] = {}
    for n in visible_nodes:
        group = n.get("displayGroup", "")
        by_group[group] = by_group.get(group, 0) + 1
    stats = {
        **(payload.get("stats") or {}),
        "nodeCount": len(visible_nodes),
        "edgeCount": len(visible_edges),
        "cardCount": len(cards),
        "gapCount": len(gaps),
        "byDisplayGroup": by_group,
    }

    return {
        **payload,
        "nodes": visible_nodes,
        "edges": visible_edges,
        "insightCards": cards,
        "gaps": gaps,
        "recommendedActions": recommended_actions,
        "tracePaths": trace_paths,
        "stats": stats,
    }
