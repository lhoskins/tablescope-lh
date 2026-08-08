
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project_asset import ProjectAsset
from app.services.project_graph_service import apply_document_family

from .profiling import logger


async def _build_graph(
    session: AsyncSession,
    asset: ProjectAsset,
    profile: dict[str, Any],
    tenant_id: int,
    project_id: int,
    user_id: int,
) -> None:
    """Create graph nodes and edges from the AI profile."""

    # Create document node
    doc_node_id = await _upsert_node(
        session, tenant_id, project_id, user_id,
        node_type="document",
        source_type="project_asset",
        source_id=asset.id,
        name=asset.filename,
        properties={
            "summary": profile.get("summary", ""),
            "document_type": profile.get("document_type", ""),
            "filename": asset.filename,
            "asset_type": asset.asset_type,
        },
    )
    if not doc_node_id:
        return

    # Create tag nodes + edges
    for tag in profile.get("tags", []):
        tag_key = tag.get("tag_key") if isinstance(tag, dict) else str(tag)
        if not tag_key:
            continue
        tag_node_id = await _upsert_node(
            session, tenant_id, project_id, user_id,
            node_type="tag", name=tag_key,
            properties={"display_name": tag.get("display_name", tag_key) if isinstance(tag, dict) else tag_key},
        )
        if tag_node_id:
            await _upsert_edge(
                session, tenant_id, project_id, user_id,
                from_node_id=doc_node_id, to_node_id=tag_node_id,
                edge_type="has_tag",
                confidence=tag.get("confidence", 0.8) if isinstance(tag, dict) else 0.8,
            )

    # Create KPI nodes + edges
    for kpi in profile.get("recommended_kpis", []):
        kpi_key = kpi.get("kpi_key") if isinstance(kpi, dict) else str(kpi)
        if not kpi_key:
            continue
        kpi_node_id = await _upsert_node(
            session, tenant_id, project_id, user_id,
            node_type="kpi", name=kpi_key,
            properties={"display_name": kpi.get("display_name", kpi_key) if isinstance(kpi, dict) else kpi_key},
        )
        if kpi_node_id:
            await _upsert_edge(
                session, tenant_id, project_id, user_id,
                from_node_id=doc_node_id, to_node_id=kpi_node_id,
                edge_type="supports_kpi",
                confidence=kpi.get("confidence", 0.7) if isinstance(kpi, dict) else 0.7,
            )

    # Create entity nodes + edges
    for entity in profile.get("entities", []):
        if not isinstance(entity, dict):
            continue
        entity_type = entity.get("entity_type", "entity")
        entity_name = entity.get("name", "")
        if not entity_name:
            continue
        entity_node_id = await _upsert_node(
            session, tenant_id, project_id, user_id,
            node_type=entity_type, name=entity_name,
            properties={"entity_type": entity_type},
        )
        if entity_node_id:
            rel_type = f"references_{entity_type}" if entity_type in ("supplier", "customer", "product") else "contains_entity"
            await _upsert_edge(
                session, tenant_id, project_id, user_id,
                from_node_id=doc_node_id, to_node_id=entity_node_id,
                edge_type=rel_type,
                confidence=entity.get("confidence", 0.8),
                evidence=entity.get("evidence", ""),
            )

    # Document family: auto-link (confidence >= 0.90) or store suggestion.
    try:
        await apply_document_family(
            session, tenant_id, project_id,
            document_node_id=doc_node_id, asset_id=asset.id,
            profile=profile, created_by=user_id,
        )
    except Exception:
        logger.exception("Family linking failed for asset %d", asset.id)


async def _link_to_datasources(
    session: AsyncSession,
    asset: ProjectAsset,
    profile: dict[str, Any],
    tenant_id: int,
    project_id: int,
    user_id: int,
) -> None:
    """Link document to existing project datasources via matching."""

    # Get doc node
    result = await session.execute(
        text("""
            SELECT id FROM ai_project_graph_nodes
            WHERE tenant_id=:tid AND project_id=:pid AND source_type='project_asset' AND source_id=:sid
            LIMIT 1
        """),
        {"tid": tenant_id, "pid": project_id, "sid": asset.id},
    )
    row = result.fetchone()
    doc_node_id = row[0] if row else None
    if not doc_node_id:
        return

    # Get project datasources
    ds_result = await session.execute(
        text("SELECT id, view_name, file_name FROM file_source_meta WHERE project_id=:pid"),
        {"pid": project_id},
    )
    datasources = ds_result.fetchall()
    if not datasources:
        return

    # Collect entity names and tags from profile
    entity_names = set()
    for e in profile.get("entities", []):
        if isinstance(e, dict) and e.get("name"):
            entity_names.add(e["name"].lower())

    tags = set()
    for t in profile.get("tags", []):
        key = t.get("tag_key") if isinstance(t, dict) else str(t)
        if key:
            tags.add(key.lower())

    # Match datasources by name similarity
    for ds_id, view_name, file_name in datasources:
        view_lower = (view_name or "").lower()
        file_lower = (file_name or "").lower()

        matched = False
        for entity in entity_names:
            # Check if entity name appears in datasource name
            entity_words = entity.split()
            if any(w in view_lower or w in file_lower for w in entity_words if len(w) > 3):
                matched = True
                break

        if not matched:
            # Check tag overlap with datasource name
            for tag in tags:
                tag_words = tag.replace("_", " ").split()
                if any(w in view_lower or w in file_lower for w in tag_words if len(w) > 3):
                    matched = True
                    break

        if matched:
            # Create datasource node if needed
            ds_node_id = await _upsert_node(
                session, tenant_id, project_id, user_id,
                node_type="datasource",
                source_type="file_source",
                source_id=ds_id,
                name=view_name or file_name or str(ds_id),
                properties={"file_name": file_name, "view_name": view_name},
            )
            if ds_node_id:
                await _upsert_edge(
                    session, tenant_id, project_id, user_id,
                    from_node_id=doc_node_id, to_node_id=ds_node_id,
                    edge_type="related_to_datasource",
                    confidence=0.7,
                )


async def _upsert_node(
    session: AsyncSession,
    tenant_id: int,
    project_id: int,
    user_id: int,
    node_type: str,
    name: str,
    properties: dict | None = None,
    source_type: str | None = None,
    source_id: int | None = None,
) -> int | None:
    """Create or get a graph node, return its ID."""

    # Check if exists
    where_clause = "tenant_id=:tid AND project_id=:pid AND node_type=:nt AND name=:nm"
    params: dict[str, Any] = {"tid": tenant_id, "pid": project_id, "nt": node_type, "nm": name}
    if source_type and source_id:
        where_clause += " AND source_type=:st AND source_id=:sid"
        params["st"] = source_type
        params["sid"] = source_id

    result = await session.execute(
        text(f"SELECT id FROM ai_project_graph_nodes WHERE {where_clause} LIMIT 1"),
        params,
    )
    row = result.fetchone()
    if row:
        return row[0]

    ins = await session.execute(
        text("""
            INSERT INTO ai_project_graph_nodes
                (tenant_id, project_id, node_type, source_type, source_id, name, properties,
                 visibility, created_by)
            VALUES (:tid, :pid, :nt, :st, :sid, :nm, :props, 'shared_project', :uid)
            RETURNING id
        """),
        {
            "tid": tenant_id,
            "pid": project_id,
            "nt": node_type,
            "st": source_type,
            "sid": source_id,
            "nm": name,
            "props": json.dumps(properties or {}),
            "uid": user_id,
        },
    )
    row = ins.fetchone()
    return row[0] if row else None


async def _upsert_edge(
    session: AsyncSession,
    tenant_id: int,
    project_id: int,
    user_id: int,
    from_node_id: int,
    to_node_id: int,
    edge_type: str,
    confidence: float = 0.8,
    evidence: str = "",
) -> int | None:
    """Create or get a graph edge, return its ID."""

    result = await session.execute(
        text("""
            SELECT id FROM ai_project_graph_edges
            WHERE tenant_id=:tid AND project_id=:pid
              AND from_node_id=:fid AND to_node_id=:toid AND relationship_type=:et
            LIMIT 1
        """),
        {"tid": tenant_id, "pid": project_id, "fid": from_node_id, "toid": to_node_id, "et": edge_type},
    )
    row = result.fetchone()
    if row:
        return row[0]

    ev_json = json.dumps({"text": evidence}) if isinstance(evidence, str) else json.dumps(evidence or {})

    ins = await session.execute(
        text("""
            INSERT INTO ai_project_graph_edges
                (tenant_id, project_id, from_node_id, to_node_id, relationship_type,
                 confidence, evidence, visibility, created_by)
            VALUES (:tid, :pid, :fid, :toid, :et, :conf, :ev, 'shared_project', :uid)
            RETURNING id
        """),
        {
            "tid": tenant_id,
            "pid": project_id,
            "fid": from_node_id,
            "toid": to_node_id,
            "et": edge_type,
            "conf": confidence,
            "ev": ev_json,
            "uid": user_id,
        },
    )
    row = ins.fetchone()
    return row[0] if row else None
