
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.project_asset import ProjectAsset
from app.services.document_chunking_service import chunk_document
from app.services.document_extraction_service import extract_text
from app.services.project_insight_service import mark_project_insight_stale

from .graph import _build_graph, _link_to_datasources
from .graph import _upsert_edge as _upsert_edge
from .graph import _upsert_node as _upsert_node
from .indexing import _index_document_vectors
from .profiling import DocumentProfileError, _call_ai_profile, _hash_stored_file, logger
from .profiling import call_document_profiler as call_document_profiler

"""Orchestrate document processing: extraction → chunking → AI profile → graph.

Called as a background task after document upload.
"""


async def process_document_asset(
    session: AsyncSession,
    asset: ProjectAsset,
    tenant_id: int,
    project_id: int,
    user_id: int,
    *,
    force: bool = False,
    trigger_graph_rebuild: bool = True,
) -> str:
    """Full pipeline: extract → chunk → persist chunks → AI profile → graph.

    Returns a status string: ``"processed"``, ``"skipped_unchanged"``, or
    ``"failed"``. A document whose bytes match the stored ``file_hash`` and
    that is already profiled is skipped so reprocessing only does work on real
    file changes; ``force=True`` (a user's explicit Reprocess) bypasses the
    gate. ``trigger_graph_rebuild=False`` lets a project-wide cascade suppress
    per-document rebuild events in favor of one terminal rebuild.
    """

    # ── Step 0: File-hash gate ───────────────────────────────────────
    current_hash = _hash_stored_file(asset.storage_location)
    if (
        not force
        and current_hash is not None
        and current_hash == asset.file_hash
        and asset.ai_status == "profiled"
    ):
        logger.info(
            "Skipping reprocess of asset %d: file unchanged and already profiled",
            asset.id,
        )
        return "skipped_unchanged"
    if current_hash is not None and current_hash != asset.file_hash:
        # The stored bytes changed (file replaced on disk); persist the new
        # hash so the gate and source fingerprinting see the change.
        asset.file_hash = current_hash
        try:
            await session.execute(
                text(
                    "UPDATE ai_documents SET file_hash=:fh "
                    "WHERE source_type='project_asset' AND source_id=:sid"
                ),
                {"fh": current_hash, "sid": asset.id},
            )
        except Exception:
            logger.exception("Failed to update ai_documents hash for asset %d", asset.id)

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
        return "failed"

    doc_text = extraction.get("document_text", "")
    if not doc_text.strip():
        asset.ai_status = "failed"
        asset.ai_error_message = "No text could be extracted from this document"
        await session.commit()
        return "failed"

    # ── Step 2: Chunk text ───────────────────────────────────────────
    asset.ai_status = "chunking"
    await session.commit()

    chunks = chunk_document(extraction)
    if not chunks:
        asset.ai_status = "failed"
        asset.ai_error_message = "Chunking produced no chunks"
        await session.commit()
        return "failed"

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
        return "failed"

    # ── Step 5: Persist profile ──────────────────────────────────────
    asset.ai_summary = profile.get("summary", asset.ai_summary or "")
    # Merge the new profile on top of existing metadata so upstream values
    # (e.g. document_family set during upload or a previous run) are never
    # silently dropped by a partial AI payload.
    existing = asset.ai_metadata or {}
    asset.ai_metadata = {**existing, **profile}
    asset.ai_status = "profiled"
    asset.ai_error_message = None

    if ai_doc_id:
        await session.execute(
            text("UPDATE ai_documents SET status='profiled' WHERE id=:did"),
            {"did": ai_doc_id},
        )

    await session.commit()

    # Document metadata changed, so any cached project insights/opportunities
    # for this project are now stale. Mark them for background rebuild.
    try:
        await mark_project_insight_stale(
            session, tenant_id=tenant_id, project_id=project_id
        )
        await session.commit()
        if get_settings().project_insight_event_rebuild_enabled:
            from app.tasks.workflows import enqueue_rebuild_project_insight

            await enqueue_rebuild_project_insight(
                tenant_id=tenant_id, project_id=project_id
            )
    except Exception:
        logger.exception("Failed to invalidate project intelligence snapshots")

    # ── Step 6: Build graph nodes/edges ──────────────────────────────
    # Capture a checkpoint right before the staging rows are written so the
    # rebuild worker can verify the rows are visible before reading them.
    source_checkpoint = datetime.now(UTC)
    try:
        await _build_graph(session, asset, profile, tenant_id, project_id, user_id)
        await session.commit()
    except Exception:
        logger.exception("Graph building failed for asset %d", asset.id)
        await session.rollback()

    # ── Step 7: Link to existing datasources ─────────────────────────
    try:
        await _link_to_datasources(session, asset, profile, tenant_id, project_id, user_id)
        await session.commit()
    except Exception:
        logger.exception("Datasource linking failed for asset %d", asset.id)
        await session.rollback()

    # ── Step 8: Index document text into the vector store for AI Ask ──
    try:
        await _index_document_vectors(
            tenant_id=tenant_id,
            user_id=user_id,
            project_id=project_id,
            document_id=ai_doc_id or asset.id,
            source_id=asset.id,
            visibility=asset.visibility,
            content=doc_text,
        )
    except Exception:
        logger.exception("Vector indexing failed for asset %d", asset.id)

    # ── Step 9: Trigger a knowledge-graph snapshot rebuild ───────────
    # The graph rows written above (Steps 6-7) are committed, so a rebuild now
    # observes the fresh document/relationship/family edges. Best-effort and
    # last: the graph is a downstream consumer and must never fail the pipeline.
    if trigger_graph_rebuild:
        from app.services.knowledge_graph_lifecycle import (
            request_event_driven_rebuild,
        )

        await request_event_driven_rebuild(
            session,
            project_id=project_id,
            change_set=[
                {
                    "entity_type": "document",
                    "entity_id": asset.id,
                    "action": "processed",
                    "change_scope": "content",
                }
            ],
            trigger="document_processed",
            requested_by=user_id,
            source_checkpoint=source_checkpoint,
        )

    return "processed"
