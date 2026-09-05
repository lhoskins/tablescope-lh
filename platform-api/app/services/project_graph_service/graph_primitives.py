
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
    # KG-27: case/whitespace-insensitive so an entity extracted as "CMX",
    # "cmx", or " CMX " resolves to the same node instead of creating a
    # near-duplicate that differs only by casing or incidental whitespace
    # -- exact identifier/alias/context-based resolution (the fuller ask)
    # is a materially larger, separate effort.
    where = (
        "tenant_id=:tid AND project_id=:pid AND node_type=:nt "
        "AND LOWER(TRIM(name))=LOWER(TRIM(:nm))"
    )
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
