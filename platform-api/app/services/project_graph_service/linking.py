
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .graph_primitives import (
    AUTO_LINK_THRESHOLD,
    FAMILY_RELATIONSHIP_TYPES,
    SUGGEST_THRESHOLD,
    _upsert_edge,
    _upsert_typed_node,
    log_family_event,
    normalize_family_key,
)
from .lifecycle import archive_empty_family, deactivate_document_edges, upsert_document_family_node


async def link_document_to_family(
    session: AsyncSession,
    tenant_id: int,
    project_id: int,
    document_node_id: int,
    family_node_id: int,
    confidence: float,
    reason: str,
    created_by: int,
    role: str = "",
) -> int | None:
    """Create (or reactivate) the document → belongs_to_family edge.

    A document belongs to at most one active family, so any other active
    belongs_to_family edges from this document are deactivated first.
    """
    await session.execute(
        text(
            """
            UPDATE ai_project_graph_edges SET is_active=false
            WHERE tenant_id=:tid AND project_id=:pid AND from_node_id=:fid
              AND relationship_type='belongs_to_family' AND to_node_id<>:famid
            """
        ),
        {"tid": tenant_id, "pid": project_id, "fid": document_node_id, "famid": family_node_id},
    )
    ev = {"reason": reason}
    if role:
        ev["role"] = role
    return await _upsert_edge(
        session, tenant_id, project_id, created_by,
        from_node_id=document_node_id, to_node_id=family_node_id,
        edge_type="belongs_to_family", confidence=confidence, evidence=json.dumps(ev),
    )


async def create_family_relationship_edges(
    session: AsyncSession,
    tenant_id: int,
    project_id: int,
    document_node_id: int,
    profile: dict[str, Any],
    created_by: int,
) -> int:
    """Materialize family_relationships from the profile as typed graph edges."""
    rels = profile.get("family_relationships", []) or []
    created = 0
    for rel in rels:
        if not isinstance(rel, dict):
            continue
        target_name = str(rel.get("target_name", "")).strip()
        if not target_name:
            continue
        rel_type = str(rel.get("relationship_type", "")).strip().lower()
        if rel_type not in FAMILY_RELATIONSHIP_TYPES:
            rel_type = "related_family_member"
        target_type = str(rel.get("target_type", "")).strip().lower() or "process"

        target_node_id = await _upsert_typed_node(
            session, tenant_id, project_id, created_by,
            node_type=target_type, name=target_name,
            properties={"node_type": target_type, "ai_generated": True},
        )
        if not target_node_id:
            continue
        try:
            conf = float(rel.get("confidence", 0.7))
        except (TypeError, ValueError):
            conf = 0.7
        await _upsert_edge(
            session, tenant_id, project_id, created_by,
            from_node_id=document_node_id, to_node_id=target_node_id,
            edge_type=rel_type, confidence=conf, evidence=str(rel.get("evidence", "")),
        )
        created += 1
    return created


# ── Orchestration (called during profiling) ──────────────────────────

async def apply_document_family(
    session: AsyncSession,
    tenant_id: int,
    project_id: int,
    document_node_id: int,
    asset_id: int,
    profile: dict[str, Any],
    created_by: int,
) -> dict[str, Any] | None:
    """Apply the family section of a profile to the graph using thresholds.

    Returns a small status dict for logging/UI, or None when no family applies.
    """
    fam = profile.get("document_family")

    def _conf(d: dict) -> float:
        try:
            return float(d.get("confidence", 0.0))
        except (TypeError, ValueError):
            return 0.0

    # No (or low-confidence) family: drop any stale links from a prior profile.
    if not isinstance(fam, dict) or _conf(fam) < SUGGEST_THRESHOLD or not str(fam.get("family_name", "")).strip():
        affected = await deactivate_document_edges(session, tenant_id, project_id, document_node_id)
        for fid in affected:
            await archive_empty_family(session, tenant_id, project_id, fid)
        return None

    confidence = _conf(fam)
    family_name = str(fam.get("family_name", "")).strip()
    family_key = str(fam.get("family_key", "")).strip().lower() or normalize_family_key(family_name)
    family_type = str(fam.get("family_type", "")).strip().lower()
    business_domain = str(profile.get("business_domain", "")).strip()
    role = str(fam.get("role", "")).strip().lower()
    reason = str(fam.get("reason", "")).strip()
    auto_link = confidence >= AUTO_LINK_THRESHOLD

    if not auto_link:
        # Suggestion only — stored in ai_metadata by the caller; no edges. Drop
        # any prior auto-link so a downgraded reprocess doesn't keep a stale edge.
        affected = await deactivate_document_edges(session, tenant_id, project_id, document_node_id)
        for fid in affected:
            await archive_empty_family(session, tenant_id, project_id, fid)
        log_family_event(
            "document_family_suggested",
            tenant_id=tenant_id, project_id=project_id, asset_id=asset_id,
            family_name=family_name, confidence=confidence, user_id=created_by,
        )
        return {"status": "suggested", "family_name": family_name, "confidence": confidence}

    family_node_id = await upsert_document_family_node(
        session, tenant_id, project_id, family_name, family_key, family_type,
        business_domain, confidence, reason, created_by,
    )
    if not family_node_id:
        return None

    await link_document_to_family(
        session, tenant_id, project_id, document_node_id, family_node_id,
        confidence, reason, created_by, role=role,
    )
    await create_family_relationship_edges(
        session, tenant_id, project_id, document_node_id, profile, created_by,
    )
    log_family_event(
        "document_family_auto_linked",
        tenant_id=tenant_id, project_id=project_id, asset_id=asset_id,
        family_node_id=family_node_id, family_name=family_name,
        confidence=confidence, action_source="ai_auto_link", user_id=created_by,
    )
    return {
        "status": "auto_linked",
        "family_node_id": family_node_id,
        "family_name": family_name,
        "confidence": confidence,
    }


def _edge_role(evidence: Any) -> str:
    if isinstance(evidence, dict):
        return str(evidence.get("role", ""))
    if isinstance(evidence, str) and evidence:
        try:
            return str(json.loads(evidence).get("role", ""))
        except (ValueError, TypeError):
            return ""
    return ""
