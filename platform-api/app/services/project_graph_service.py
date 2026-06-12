"""Document-family helpers over the project knowledge graph.

Families reuse the existing ``ai_project_graph_nodes`` / ``ai_project_graph_edges``
tables (node_type='document_family', edge_type='belongs_to_family' plus typed
relationship edges). No dedicated family table is created.

Auto-link thresholds (per plan):
    confidence >= 0.90  → auto-link the document to its family
    0.70 .. 0.89        → store as a suggestion (no belongs_to_family edge)
    < 0.70              → ignore
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

AUTO_LINK_THRESHOLD = 0.90
SUGGEST_THRESHOLD = 0.70

# Relationship edge types a family relationship may use (allow-list keeps the
# graph clean; unknown types fall back to ``related_family_member``).
FAMILY_RELATIONSHIP_TYPES = {
    "references", "supersedes", "superseded_by", "depends_on", "implements",
    "governs", "exception_to", "procedure_for", "policy_for", "evidence_for",
    "supports", "contradicts", "updates", "appendix_to", "template_for",
    "meeting_notes_for", "postmortem_for", "remediation_for", "audit_evidence_for",
    "related_family_member", "measures_process", "incident_impact",
    "related_to_datasource",
}


def _as_dict(value: Any) -> dict:
    """Coerce a JSON column value into a dict.

    Raw ``text()`` reads return the stored JSON as a ``str`` on SQLite (and,
    depending on the driver, on Postgres too), while ORM reads decode to a
    ``dict``. Normalize both here.
    """
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (ValueError, TypeError):
            return {}
    return {}


def normalize_family_key(name: str) -> str:
    """Normalize a family name into a stable snake_case key."""
    return re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")


def log_family_event(event: str, **payload: Any) -> None:
    """Emit a structured audit event for a family lifecycle action."""
    logger.info("family_audit %s %s", event, json.dumps(payload, default=str, sort_keys=True))


# ── Node / edge primitives (is_active aware) ─────────────────────────

async def upsert_document_family_node(
    session: AsyncSession,
    tenant_id: int,
    project_id: int,
    family_name: str,
    family_key: str,
    family_type: str,
    business_domain: str,
    confidence: float,
    reason: str,
    created_by: int,
) -> int | None:
    """Create or reuse the document_family node, dedup by family_key/domain.

    Reuse rule: same tenant, project, node_type='document_family', family_key,
    and (when present) business_domain.
    """
    family_key = family_key or normalize_family_key(family_name)

    # Dedup in Python (JSON operators differ across Postgres/SQLite). The number
    # of families per project is small, so scanning candidates is cheap.
    result = await session.execute(
        text(
            """
            SELECT id, properties FROM ai_project_graph_nodes
            WHERE tenant_id=:tid AND project_id=:pid AND node_type='document_family'
            ORDER BY id
            """
        ),
        {"tid": tenant_id, "pid": project_id},
    )
    for nid, props in result.fetchall():
        p = _as_dict(props)
        if p.get("family_key") != family_key:
            continue
        if business_domain and (p.get("business_domain") or "") != business_domain:
            continue
        await session.execute(
            text("UPDATE ai_project_graph_nodes SET is_active=true, name=:nm WHERE id=:id"),
            {"id": nid, "nm": family_name},
        )
        return nid

    props = {
        "family_key": family_key,
        "family_type": family_type or "general_knowledge_group",
        "business_domain": business_domain or "",
        "description": reason or "",
        "ai_generated": True,
        "confidence": round(float(confidence or 0), 4),
    }
    ins = await session.execute(
        text(
            """
            INSERT INTO ai_project_graph_nodes
                (tenant_id, project_id, node_type, source_type, source_id, name,
                 properties, visibility, is_active, created_by)
            VALUES (:tid, :pid, 'document_family', 'ai_generated', NULL, :nm,
                    :props, 'shared_project', true, :uid)
            RETURNING id
            """
        ),
        {
            "tid": tenant_id, "pid": project_id, "nm": family_name,
            "props": json.dumps(props), "uid": created_by,
        },
    )
    out = ins.fetchone()
    return out[0] if out else None


async def _upsert_typed_node(
    session: AsyncSession,
    tenant_id: int,
    project_id: int,
    created_by: int,
    node_type: str,
    name: str,
    properties: dict | None = None,
    source_type: str | None = None,
    source_id: int | None = None,
) -> int | None:
    where = "tenant_id=:tid AND project_id=:pid AND node_type=:nt AND name=:nm"
    params: dict[str, Any] = {"tid": tenant_id, "pid": project_id, "nt": node_type, "nm": name}
    if source_type and source_id:
        where += " AND source_type=:st AND source_id=:sid"
        params["st"] = source_type
        params["sid"] = source_id

    result = await session.execute(
        text(f"SELECT id FROM ai_project_graph_nodes WHERE {where} ORDER BY id LIMIT 1"),
        params,
    )
    row = result.fetchone()
    if row:
        await session.execute(
            text("UPDATE ai_project_graph_nodes SET is_active=true WHERE id=:id"),
            {"id": row[0]},
        )
        return row[0]

    ins = await session.execute(
        text(
            """
            INSERT INTO ai_project_graph_nodes
                (tenant_id, project_id, node_type, source_type, source_id, name,
                 properties, visibility, is_active, created_by)
            VALUES (:tid, :pid, :nt, :st, :sid, :nm, :props, 'shared_project', true, :uid)
            RETURNING id
            """
        ),
        {
            "tid": tenant_id, "pid": project_id, "nt": node_type,
            "st": source_type, "sid": source_id, "nm": name,
            "props": json.dumps(properties or {}), "uid": created_by,
        },
    )
    out = ins.fetchone()
    return out[0] if out else None


async def _upsert_edge(
    session: AsyncSession,
    tenant_id: int,
    project_id: int,
    created_by: int,
    from_node_id: int,
    to_node_id: int,
    edge_type: str,
    confidence: float = 0.8,
    evidence: str = "",
) -> int | None:
    result = await session.execute(
        text(
            """
            SELECT id FROM ai_project_graph_edges
            WHERE tenant_id=:tid AND project_id=:pid
              AND from_node_id=:fid AND to_node_id=:toid AND relationship_type=:et
            ORDER BY id LIMIT 1
            """
        ),
        {"tid": tenant_id, "pid": project_id, "fid": from_node_id, "toid": to_node_id, "et": edge_type},
    )
    row = result.fetchone()
    ev_json = json.dumps({"text": evidence}) if isinstance(evidence, str) else json.dumps(evidence or {})
    if row:
        await session.execute(
            text(
                "UPDATE ai_project_graph_edges SET is_active=true, confidence=:c, evidence=:ev WHERE id=:id"
            ),
            {"id": row[0], "c": confidence, "ev": ev_json},
        )
        return row[0]

    ins = await session.execute(
        text(
            """
            INSERT INTO ai_project_graph_edges
                (tenant_id, project_id, from_node_id, to_node_id, relationship_type,
                 confidence, evidence, visibility, is_active, created_by)
            VALUES (:tid, :pid, :fid, :toid, :et, :conf, :ev, 'shared_project', true, :uid)
            RETURNING id
            """
        ),
        {
            "tid": tenant_id, "pid": project_id, "fid": from_node_id, "toid": to_node_id,
            "et": edge_type, "conf": confidence, "ev": ev_json, "uid": created_by,
        },
    )
    out = ins.fetchone()
    return out[0] if out else None


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


# ── Reads ────────────────────────────────────────────────────────────

async def get_family_members(
    session: AsyncSession,
    tenant_id: int,
    project_id: int,
    family_node_id: int,
) -> dict[str, list[dict[str, Any]]]:
    """Return active family members grouped by kind.

    Documents come from belongs_to_family edges; datasources/kpis/entities/tags
    are aggregated from the active edges of those member documents.
    """
    members: dict[str, list[dict[str, Any]]] = {
        "documents": [], "datasources": [], "queries": [],
        "dashboards": [], "kpis": [], "entities": [],
    }

    doc_rows = await session.execute(
        text(
            """
            SELECT n.id, n.name, n.source_id, n.properties, e.confidence, e.evidence
            FROM ai_project_graph_edges e
            JOIN ai_project_graph_nodes n ON n.id = e.from_node_id
            WHERE e.tenant_id=:tid AND e.project_id=:pid
              AND e.to_node_id=:famid AND e.relationship_type='belongs_to_family'
              AND e.is_active=true AND n.is_active=true
            ORDER BY e.confidence DESC NULLS LAST, n.id
            """
        ),
        {"tid": tenant_id, "pid": project_id, "famid": family_node_id},
    )
    doc_ids: list[int] = []
    for nid, name, sid, props, conf, ev in doc_rows.fetchall():
        doc_ids.append(nid)
        p = _as_dict(props)
        members["documents"].append({
            "node_id": nid, "name": name, "source_id": sid,
            "summary": p.get("summary", ""), "role": _edge_role(ev),
            "confidence": float(conf or 0),
        })

    if not doc_ids:
        return members

    # Aggregate the documents' connected nodes into typed member buckets.
    id_placeholders = ", ".join(f":d{i}" for i in range(len(doc_ids)))
    rel_params: dict[str, Any] = {"tid": tenant_id, "pid": project_id}
    for i, did in enumerate(doc_ids):
        rel_params[f"d{i}"] = did
    rel_rows = await session.execute(
        text(
            f"""
            SELECT DISTINCT n.id, n.node_type, n.name, n.source_id
            FROM ai_project_graph_edges e
            JOIN ai_project_graph_nodes n ON n.id = e.to_node_id
            WHERE e.tenant_id=:tid AND e.project_id=:pid
              AND e.from_node_id IN ({id_placeholders})
              AND e.relationship_type<>'belongs_to_family'
              AND e.is_active=true AND n.is_active=true
            """
        ),
        rel_params,
    )
    seen: set[tuple[str, str]] = set()
    for nid, ntype, name, sid in rel_rows.fetchall():
        bucket = {
            "datasource": "datasources", "kpi": "kpis",
        }.get(ntype)
        if bucket is None:
            # Treat tags + named entities as entity-like members.
            if ntype in ("document_family", "tag"):
                continue
            bucket = "entities"
        key = (bucket, name)
        if key in seen:
            continue
        seen.add(key)
        members[bucket].append({"node_id": nid, "name": name, "source_id": sid, "type": ntype})

    return members


def _edge_role(evidence: Any) -> str:
    if isinstance(evidence, dict):
        return str(evidence.get("role", ""))
    if isinstance(evidence, str) and evidence:
        try:
            return str(json.loads(evidence).get("role", ""))
        except (ValueError, TypeError):
            return ""
    return ""


async def get_family_node(
    session: AsyncSession,
    tenant_id: int,
    project_id: int,
    family_node_id: int,
) -> dict[str, Any] | None:
    result = await session.execute(
        text(
            """
            SELECT id, name, properties FROM ai_project_graph_nodes
            WHERE id=:id AND tenant_id=:tid AND project_id=:pid
              AND node_type='document_family'
            """
        ),
        {"id": family_node_id, "tid": tenant_id, "pid": project_id},
    )
    row = result.fetchone()
    if not row:
        return None
    nid, name, props = row
    return {"id": nid, "name": name, "properties": _as_dict(props)}


async def deactivate_document_edges(
    session: AsyncSession,
    tenant_id: int,
    project_id: int,
    document_node_id: int,
) -> list[int]:
    """Deactivate a document's family edges; return affected family node ids."""
    fam_rows = await session.execute(
        text(
            """
            SELECT DISTINCT to_node_id FROM ai_project_graph_edges
            WHERE tenant_id=:tid AND project_id=:pid AND from_node_id=:fid
              AND relationship_type='belongs_to_family' AND is_active=true
            """
        ),
        {"tid": tenant_id, "pid": project_id, "fid": document_node_id},
    )
    family_ids = [r[0] for r in fam_rows.fetchall()]
    await session.execute(
        text(
            """
            UPDATE ai_project_graph_edges SET is_active=false
            WHERE tenant_id=:tid AND project_id=:pid AND from_node_id=:fid
              AND relationship_type='belongs_to_family'
            """
        ),
        {"tid": tenant_id, "pid": project_id, "fid": document_node_id},
    )
    return family_ids


async def archive_empty_family(
    session: AsyncSession,
    tenant_id: int,
    project_id: int,
    family_node_id: int,
) -> bool:
    """Mark a family node inactive when it has no active member documents."""
    result = await session.execute(
        text(
            """
            SELECT COUNT(*) FROM ai_project_graph_edges
            WHERE tenant_id=:tid AND project_id=:pid AND to_node_id=:famid
              AND relationship_type='belongs_to_family' AND is_active=true
            """
        ),
        {"tid": tenant_id, "pid": project_id, "famid": family_node_id},
    )
    count = result.scalar() or 0
    if count == 0:
        await session.execute(
            text("UPDATE ai_project_graph_nodes SET is_active=false WHERE id=:id"),
            {"id": family_node_id},
        )
        log_family_event(
            "document_family_archived",
            tenant_id=tenant_id, project_id=project_id, family_node_id=family_node_id,
        )
        return True
    return False
