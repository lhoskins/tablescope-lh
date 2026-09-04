"""Knowledge graph snapshot persistence and read entrypoints."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .cards import _card_bundle
from .constants import (
    DEFAULT_MIN_CONFIDENCE,
    MAX_PRECACHE_CENTERS,
    PRECACHE_CONCURRENCY,
    SNAPSHOT_PIPELINE_VERSION,
    _json_safe,
)
from .loader import _is_canvas_hidden, _load_stored_graph, enrich_node
from .renderer import build_graph_payload, build_node_centric_graph_from_snapshot
from .visibility import filter_payload_for_viewer

logger = logging.getLogger(__name__)

def _center_eligible_keys(
    raw_nodes: list[dict[str, Any]],
) -> list[str]:
    """Return the graphKeys of every node that can be a canvas centre.

    The project hub (and any ``hidden_on_canvas`` node) is the data boundary and
    is never a centre, so it is excluded. The list is capped to keep rebuild
    cost bounded on very large graphs (highest-confidence centres first).
    """
    eligible = [
        n for n in (enrich_node(n) for n in raw_nodes)
        if not _is_canvas_hidden(n) and n.get("isCenterEligible")
    ]
    eligible.sort(key=lambda n: n.get("confidence") or 0.0, reverse=True)
    keys: list[str] = []
    seen: set[str] = set()
    for n in eligible:
        key = n.get("graphKey")
        if key and key not in seen:
            seen.add(key)
            keys.append(key)
        if len(keys) >= MAX_PRECACHE_CENTERS:
            break
    return keys


async def _precache_center_cards(
    raw_nodes: list[dict[str, Any]],
    raw_edges: list[dict[str, Any]],
    *,
    tenant_id: int,
    user_id: int,
    project_id: int,
) -> dict[str, Any]:
    """Run AI enrichment for every centre-eligible node and return the bundles.

    Returns a ``{graphKey: cardBundle}`` map. Each bundle holds the AI-generated
    insight cards (and gaps / recommended actions / trace paths) for that centre.
    Enrichment runs with bounded concurrency. Centres are AI-only: a centre
    whose AI enrichment yields no grounded card is still cached (with an empty
    card list) so the read path serves it from cache without re-calling the AI.
    """
    from app.services.knowledge_graph_ai import enrich_payload_with_ai

    center_keys = _center_eligible_keys(raw_nodes)
    if not center_keys:
        return {}

    semaphore = asyncio.Semaphore(PRECACHE_CONCURRENCY)

    async def _one(center_key: str) -> tuple[str, dict[str, Any]] | None:
        payload = build_graph_payload(raw_nodes, raw_edges, center_node=center_key)
        center = payload.get("centerNode")
        if not center or not payload.get("nodes"):
            return None
        resolved_key = center.get("graphKey") or center_key
        async with semaphore:
            try:
                await enrich_payload_with_ai(
                    payload, tenant_id=tenant_id, user_id=user_id,
                    project_id=project_id,
                )
            except Exception:
                logger.exception(
                    "KG pre-cache enrichment failed for centre %s", resolved_key
                )
                return None
        return resolved_key, _card_bundle(payload)

    results = await asyncio.gather(*(_one(k) for k in center_keys))
    bundles: dict[str, Any] = {}
    for res in results:
        if res is not None:
            key, bundle = res
            bundles[key] = bundle
    return bundles


async def rebuild_project_graph_snapshot(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: int,
    user_id: int | None = None,
    enrich_with_ai: bool = True,
) -> dict[str, Any]:
    """Rebuild and persist the full project Knowledge Graph snapshot.

    Collects the stored graph rows + structural Evidence graph, pre-generates
    the AI insight cards for every centre-eligible node, and upserts the
    snapshot row. Both the canvas (full graph) and the per-centre cards are
    cached so every node click reads from the snapshot — no rebuild and no AI
    call until the user hits Refresh. Returns the in-memory snapshot dict.
    """
    from app.models.knowledge_graph_snapshot import (
        SNAPSHOT_KEY_FULL,
        AIProjectGraphSnapshot,
    )

    raw_nodes, raw_edges = await _load_stored_graph(
        session, tenant_id=tenant_id, project_id=project_id,
    )

    # Pre-cache the AI insight cards for EVERY centre-eligible node so that a
    # node click reads its business-insight cards instantly from cache (no
    # rebuild, no AI call until the user hits Refresh). Cards are keyed by the
    # centre's graphKey.
    ai_cards_by_center: dict[str, Any] = {}
    if enrich_with_ai and user_id is not None:
        ai_cards_by_center = await _precache_center_cards(
            raw_nodes, raw_edges,
            tenant_id=tenant_id, user_id=user_id, project_id=project_id,
        )

    generated_at = datetime.now(UTC).isoformat()
    payload = _json_safe({
        "fullGraph": {"nodes": raw_nodes, "edges": raw_edges},
        "sourceCounts": _snapshot_source_counts(raw_nodes),
        "aiCardsByCenter": ai_cards_by_center,
        "pipelineVersion": SNAPSHOT_PIPELINE_VERSION,
        "generatedAt": generated_at,
    })

    gen_dt = datetime.now(UTC)
    try:
        row = await session.scalar(
            select(AIProjectGraphSnapshot).where(
                AIProjectGraphSnapshot.tenant_id == tenant_id,
                AIProjectGraphSnapshot.project_id == project_id,
                AIProjectGraphSnapshot.snapshot_key == SNAPSHOT_KEY_FULL,
            )
        )
        if row is None:
            row = AIProjectGraphSnapshot(
                tenant_id=tenant_id,
                project_id=project_id,
                snapshot_key=SNAPSHOT_KEY_FULL,
                payload=payload,
                pipeline_version=SNAPSHOT_PIPELINE_VERSION,
                generated_at=gen_dt,
                created_by=user_id,
            )
            session.add(row)
        else:
            row.payload = payload
            row.pipeline_version = SNAPSHOT_PIPELINE_VERSION
            row.generated_at = gen_dt
        await session.flush()
        await session.commit()
        snapshot_id: int | None = row.id
    except Exception:
        # Never let a persistence failure break the graph: roll back and serve
        # the freshly-computed payload from memory (uncached).
        logger.exception("Failed to persist Knowledge Graph snapshot")
        await session.rollback()
        snapshot_id = None

    return {"id": snapshot_id, **payload}


def _snapshot_source_counts(raw_nodes: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for n in raw_nodes:
        t = str(n.get("node_type") or "unknown")
        counts[t] = counts.get(t, 0) + 1
    return counts


async def get_project_graph_snapshot(
    session: AsyncSession, *, tenant_id: int, project_id: int,
) -> dict[str, Any] | None:
    """Return the cached full-graph snapshot for a project.

    Prefers the active knowledge-graph version (produced by the lifecycle
    manager), then falls back to the legacy ``full_project_graph`` snapshot.
    This keeps the Insight-First Knowledge Graph canvas in sync with the
    lifecycle-managed rebuild.
    """
    from app.models.knowledge_graph_lifecycle import KnowledgeGraphVersion
    from app.models.knowledge_graph_snapshot import (
        SNAPSHOT_KEY_FULL,
        AIProjectGraphSnapshot,
    )

    # Prefer the active lifecycle version so the graph UI shows the latest
    # validated rebuild.
    active_version = await session.scalar(
        select(KnowledgeGraphVersion).where(
            KnowledgeGraphVersion.tenant_id == tenant_id,
            KnowledgeGraphVersion.project_id == project_id,
            KnowledgeGraphVersion.status == "active",
        ).order_by(KnowledgeGraphVersion.version_number.desc())
    )
    row: AIProjectGraphSnapshot | None = None
    if active_version and active_version.storage_reference:
        row = await session.scalar(
            select(AIProjectGraphSnapshot).where(
                AIProjectGraphSnapshot.tenant_id == tenant_id,
                AIProjectGraphSnapshot.project_id == project_id,
                AIProjectGraphSnapshot.snapshot_key == active_version.storage_reference,
            )
        )
    if row is None:
        row = await session.scalar(
            select(AIProjectGraphSnapshot).where(
                AIProjectGraphSnapshot.tenant_id == tenant_id,
                AIProjectGraphSnapshot.project_id == project_id,
                AIProjectGraphSnapshot.snapshot_key == SNAPSHOT_KEY_FULL,
            )
        )
    if row is None:
        return None
    payload = dict(row.payload or {})
    payload.setdefault("fullGraph", {"nodes": [], "edges": []})
    # Normalize legacy single-centre cache (aiCenterKey/aiCards) into the
    # per-centre map so node clicks can look up cards by graph key.
    if "aiCardsByCenter" not in payload:
        legacy_key = payload.get("aiCenterKey")
        legacy_cards = payload.get("aiCards")
        payload["aiCardsByCenter"] = (
            {legacy_key: legacy_cards} if legacy_key and legacy_cards else {}
        )
    generated_at = payload.get("generatedAt") or (
        row.generated_at.isoformat() if row.generated_at else ""
    )
    return {"id": row.id, **payload, "generatedAt": generated_at}


async def build_node_centric_graph(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: int,
    user_id: int | None = None,
    role: str | None = None,
    center_node: str | None = None,
    lens: str = "insight-first",
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    include_inferred: bool = False,
    severity: str = "all",
    refresh: bool = False,
) -> dict[str, Any]:
    """Return the node-centric Knowledge Graph payload from the cached snapshot.

    Default load and node clicks read the persisted full-graph snapshot and
    recenter/filter from its cached nodes/edges, overlaying the centre's
    pre-cached AI insight cards. No rebuild and no AI call happen on a read —
    both canvas and cards are served from the snapshot until ``refresh=True``
    rebuilds and re-persists it (regenerating the cards for every centre).
    """
    snapshot: dict[str, Any] | None = None
    if not refresh:
        snapshot = await get_project_graph_snapshot(
            session, tenant_id=tenant_id, project_id=project_id,
        )
        # A snapshot built under an older pipeline version (e.g. before the
        # connector-style policy) is rebuilt automatically so the new policy
        # takes effect without a manual refresh.
        if snapshot is not None and (
            str(snapshot.get("pipelineVersion") or "") != SNAPSHOT_PIPELINE_VERSION
        ):
            logger.info(
                "KG snapshot stale (have=%s want=%s) — rebuilding project %s",
                snapshot.get("pipelineVersion"), SNAPSHOT_PIPELINE_VERSION,
                project_id,
            )
            snapshot = None
    if snapshot is None:
        snapshot = await rebuild_project_graph_snapshot(
            session, tenant_id=tenant_id, project_id=project_id, user_id=user_id,
        )

    payload = build_node_centric_graph_from_snapshot(
        snapshot,
        center_node=center_node,
        lens=lens,
        min_confidence=min_confidence,
        include_inferred=include_inferred,
        severity=severity,
    )

    payload["lastUpdated"] = snapshot.get("generatedAt", "")
    payload["snapshotId"] = snapshot.get("id")
    payload["pipelineVersion"] = snapshot.get("pipelineVersion", "")
    payload["isCached"] = not refresh

    # The cached snapshot is shared by every project member, but a private
    # document is only for its owner (and tenant admins) -- filter per the
    # actual requesting viewer on every read, not just at build time (KG-04).
    payload = await filter_payload_for_viewer(
        session, payload, tenant_id=tenant_id, user_id=user_id, role=role,
    )
    return payload
