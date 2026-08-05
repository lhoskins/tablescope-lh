
from __future__ import annotations

import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .graph_primitives import _as_dict, log_family_event, normalize_family_key

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
