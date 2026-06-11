"""Orchestrate document processing: extraction → chunking → AI profile → graph.

Called as a background task after document upload.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.project_asset import ProjectAsset
from app.services.document_chunking_service import chunk_document
from app.services.document_extraction_service import extract_text

logger = logging.getLogger(__name__)


class DocumentProfileError(Exception):
    """Raised when the AI document profiler cannot produce a profile."""


async def process_document_asset(
    session: AsyncSession,
    asset: ProjectAsset,
    tenant_id: int,
    project_id: int,
    user_id: int,
) -> None:
    """Full pipeline: extract → chunk → persist chunks → AI profile → graph."""

    # ── Step 1: Extract text ─────────────────────────────────────────
    asset.ai_status = "extracting"
    await session.commit()

    try:
        extraction = extract_text(asset.storage_location, asset.file_extension or ".txt")
    except Exception as exc:
        logger.exception("Text extraction failed for asset %d", asset.id)
        asset.ai_status = "failed"
        asset.ai_error_message = f"Extraction failed: {exc}"
        await session.commit()
        return

    doc_text = extraction.get("document_text", "")
    if not doc_text.strip():
        asset.ai_status = "failed"
        asset.ai_error_message = "No text could be extracted from this document"
        await session.commit()
        return

    # ── Step 2: Chunk text ───────────────────────────────────────────
    asset.ai_status = "chunking"
    await session.commit()

    chunks = chunk_document(extraction)
    if not chunks:
        asset.ai_status = "failed"
        asset.ai_error_message = "Chunking produced no chunks"
        await session.commit()
        return

    # ── Step 3: Persist chunks to ai_document_chunks ─────────────────
    # Find the ai_documents row for this asset
    result = await session.execute(
        text("SELECT id FROM ai_documents WHERE source_type='project_asset' AND source_id=:sid LIMIT 1"),
        {"sid": asset.id},
    )
    ai_doc_row = result.fetchone()
    ai_doc_id = ai_doc_row[0] if ai_doc_row else None

    if ai_doc_id:
        # Clear old chunks
        await session.execute(
            text("DELETE FROM ai_document_chunks WHERE document_id=:did"),
            {"did": ai_doc_id},
        )

        chunk_ids: list[int] = []
        for chunk in chunks:
            ins = await session.execute(
                text("""
                    INSERT INTO ai_document_chunks
                        (tenant_id, project_id, document_id, chunk_index, chunk_text,
                         content_hash, token_count, visibility, owner_user_id, created_by)
                    VALUES (:tid, :pid, :did, :ci, :ct, :ch, :tc, :vis, :uid, :uid)
                    RETURNING id
                """),
                {
                    "tid": tenant_id,
                    "pid": project_id,
                    "did": ai_doc_id,
                    "ci": chunk["chunk_index"],
                    "ct": chunk["chunk_text"],
                    "ch": chunk["content_hash"],
                    "tc": chunk["token_count"],
                    "vis": asset.visibility,
                    "uid": user_id,
                },
            )
            row = ins.fetchone()
            if row:
                chunk_ids.append(row[0])

        # Update ai_documents chunk_count + status
        await session.execute(
            text("UPDATE ai_documents SET chunk_count=:cc, status='chunked' WHERE id=:did"),
            {"cc": len(chunks), "did": ai_doc_id},
        )
        await session.commit()

    # ── Step 4: AI profile ───────────────────────────────────────────
    asset.ai_status = "profiling"
    await session.commit()

    # Get reference tags/KPIs for the prompt
    ref_tags: list[str] = []
    ref_kpis: list[str] = []
    try:
        tag_result = await session.execute(
            text("SELECT tag_key FROM ai_reference_tags WHERE is_active=true LIMIT 200")
        )
        ref_tags = [r[0] for r in tag_result.fetchall()]
        kpi_result = await session.execute(
            text("SELECT kpi_key FROM ai_reference_kpis WHERE is_active=true LIMIT 200")
        )
        ref_kpis = [r[0] for r in kpi_result.fetchall()]
    except Exception:
        logger.debug("Could not fetch reference tags/KPIs")

    text_preview = doc_text[:4000]
    chunk_previews = [{"chunk_index": c["chunk_index"], "text": c["chunk_text"][:1000]} for c in chunks[:5]]

    try:
        profile = await _call_ai_profile(
            tenant_id=tenant_id,
            user_id=user_id,
            project_id=project_id,
            asset_id=asset.id,
            document_id=ai_doc_id,
            filename=asset.filename,
            asset_type=asset.asset_type,
            content_type=asset.content_type or "",
            text_preview=text_preview,
            chunks=chunk_previews,
            ref_tags=ref_tags,
            ref_kpis=ref_kpis,
        )
    except DocumentProfileError as exc:
        logger.error("AI profiling failed for asset %d: %s", asset.id, exc)
        asset.ai_status = "failed"
        asset.ai_error_message = f"AI profiling failed: {exc}"
        if ai_doc_id:
            await session.execute(
                text("UPDATE ai_documents SET status='failed' WHERE id=:did"),
                {"did": ai_doc_id},
            )
        await session.commit()
        return

    # ── Step 5: Persist profile ──────────────────────────────────────
    asset.ai_summary = profile.get("summary", "")
    asset.ai_metadata = profile
    asset.ai_status = "profiled"
    asset.ai_error_message = None

    if ai_doc_id:
        await session.execute(
            text("UPDATE ai_documents SET status='profiled' WHERE id=:did"),
            {"did": ai_doc_id},
        )

    await session.commit()

    # ── Step 6: Build graph nodes/edges ──────────────────────────────
    try:
        await _build_graph(session, asset, profile, tenant_id, project_id, user_id)
        await session.commit()
    except Exception:
        logger.exception("Graph building failed for asset %d", asset.id)

    # ── Step 7: Link to existing datasources ─────────────────────────
    try:
        await _link_to_datasources(session, asset, profile, tenant_id, project_id, user_id)
        await session.commit()
    except Exception:
        logger.exception("Datasource linking failed for asset %d", asset.id)


async def _call_ai_profile(
    tenant_id: int,
    user_id: int,
    project_id: int,
    asset_id: int,
    document_id: int | None,
    filename: str,
    asset_type: str,
    content_type: str,
    text_preview: str,
    chunks: list[dict],
    ref_tags: list[str],
    ref_kpis: list[str],
) -> dict[str, Any]:
    """Call the AI server's dedicated document profiling endpoint.

    Raises DocumentProfileError on any failure. There is no /ai/ask fallback:
    the generic Q&A endpoint refuses extraction tasks, so a failure here must
    surface as a failed document rather than silently degrading.
    """
    settings = get_settings()
    if not settings.tablescope_ai_enabled or not settings.tablescope_ai_api_url:
        raise DocumentProfileError("AI is not configured (tablescope_ai_enabled / tablescope_ai_api_url)")

    ai_url = settings.tablescope_ai_api_url

    def _sign(p: dict[str, Any]) -> str:
        canonical = json.dumps(p, sort_keys=True, separators=(",", ":"))
        return hmac.new(
            settings.tablescope_ai_signing_secret.encode(),
            canonical.encode(),
            hashlib.sha256,
        ).hexdigest()

    payload: dict[str, Any] = {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "project_id": project_id,
        "asset_id": asset_id,
        "document_id": document_id,
        "filename": filename,
        "asset_type": asset_type,
        "content_type": content_type,
        "text_preview": text_preview,
        "chunks": chunks,
        "enabled_reference_tags": ref_tags,
        "enabled_reference_kpis": ref_kpis,
        "timestamp": time.time(),
    }
    payload["signature"] = _sign(payload)

    try:
        async with httpx.AsyncClient(timeout=180) as client:
            resp = await client.post(f"{ai_url}/ai/document/profile", json=payload)
    except Exception as exc:
        raise DocumentProfileError(f"Could not reach AI document profiler: {exc}") from exc

    if resp.status_code != 200:
        raise DocumentProfileError(
            f"AI document profiler returned HTTP {resp.status_code}: {resp.text[:300]}"
        )

    return resp.json()


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
    import json

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
    import json

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
            VALUES (:tid, :pid, :fid, :toid, :et, :conf, :ev::jsonb, 'shared_project', :uid)
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
