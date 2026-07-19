"""Reference Library document processing pipeline.

Shared by manual single uploads and the bulk URL importer. Runs:

1. Text extraction (PDF / DOCX / PPTX / TXT / MD / HTML)
2. AI summary generation (via the signed AI server endpoint)
3. Indexing for citation — the extracted text is persisted, the AI summary is
   stored on the document, and the full text is embedded into the shared,
   tier-scoped reference vector store so the AI assistant can retrieve passages
   and the Home planner can ground analyses in it.
4. Status update — ``active`` on success, ``draft`` with an error on failure so a
   manual summary can be entered as a fallback.

The pipeline is identical regardless of tier — only the storage path and
visibility scope differ, and those are set at upload time.
"""

from __future__ import annotations

import logging
import os
import re
import uuid
from html.parser import HTMLParser
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from app.models.reference_library import ReferenceDocument

from app.config import get_settings
from app.services import reference_library_ai_client as ai_client
from app.services.document_extraction_service import extract_text
from app.services.document_processing_service import (
    DocumentProfileError,
    call_document_profiler,
)
from app.services.project_insight_service import mark_project_insight_stale
from app.services.reference_library_service import domain_storage_key

logger = logging.getLogger(__name__)

LOCAL_STORAGE_BASE = os.environ.get("ASSET_STORAGE_PATH", "/opt/wildfly/teiidfiles/customers")

# Extensions whose text we can extract natively.
EXTRACTABLE_EXTENSIONS = {".pdf", ".docx", ".pptx", ".txt", ".md", ".html", ".htm"}

EXT_TO_FILE_TYPE = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".doc": "doc",
    ".pptx": "pptx",
    ".txt": "txt",
    ".md": "md",
    ".html": "html",
    ".htm": "html",
}


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip = False

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in ("script", "style"):
            self._skip = True

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._skip = False

    def handle_data(self, data: str) -> None:
        if not self._skip and data.strip():
            self._parts.append(data.strip())

    def text(self) -> str:
        return re.sub(r"\n{3,}", "\n\n", "\n".join(self._parts))


def reference_storage_dir(
    tier: str, domain_tag: str | None, tenant_id: int | None, project_id: int | None
) -> Path:
    """Storage directory following the path convention from the spec.

    industry/{domain}/...  ·  company/{tenant_id}/...  ·  project/{project_id}/...
    """
    base = Path(LOCAL_STORAGE_BASE) / "reference_library"
    if tier == "industry":
        return base / "industry" / domain_storage_key(domain_tag)
    if tier == "company":
        return base / "company" / str(tenant_id or 0)
    return base / "project" / str(project_id or 0)


def store_reference_file(
    *,
    tier: str,
    domain_tag: str | None,
    tenant_id: int | None,
    project_id: int | None,
    document_id: int,
    ext: str,
    data: bytes,
) -> str:
    """Persist file bytes to reference-library storage; return the absolute path."""
    dir_path = reference_storage_dir(tier, domain_tag, tenant_id, project_id)
    dir_path.mkdir(parents=True, exist_ok=True)
    clean_ext = ext if ext.startswith(".") else f".{ext}"
    file_path = dir_path / f"{document_id}{clean_ext}"
    file_path.write_bytes(data)
    return str(file_path)


def _extract_reference_text(file_path: str, ext: str) -> str:
    """Extract plain text from a reference file. Raises on unsupported/failed."""
    ext = ext.lower()
    if ext in (".html", ".htm"):
        raw = Path(file_path).read_text(encoding="utf-8", errors="ignore")
        parser = _HTMLTextExtractor()
        parser.feed(raw)
        return parser.text()
    if ext == ".doc":
        # Legacy binary .doc is not natively extractable here.
        raise ValueError("Legacy .doc format is not supported — convert to .docx or .pdf")
    extraction = extract_text(file_path, ext)
    return str(extraction.get("document_text", ""))


def _chunk_previews(doc_text: str, size: int = 1000, limit: int = 5) -> list[dict]:
    """Lightweight chunk previews for the profiler prompt (no persistence)."""
    previews: list[dict] = []
    for i in range(0, min(len(doc_text), size * limit), size):
        previews.append({"chunk_index": i // size, "text": doc_text[i : i + size]})
    return previews


async def _reference_tags_and_kpis(session: AsyncSession) -> tuple[list[str], list[str]]:
    tags: list[str] = []
    kpis: list[str] = []
    try:
        rows = await session.execute(
            sql_text("SELECT tag_key FROM ai_reference_tags WHERE is_active=true LIMIT 200")
        )
        tags = [r[0] for r in rows.fetchall()]
        rows = await session.execute(
            sql_text("SELECT kpi_key FROM ai_reference_kpis WHERE is_active=true LIMIT 200")
        )
        kpis = [r[0] for r in rows.fetchall()]
    except Exception:
        logger.debug("Could not fetch reference tags/KPIs for profiling")
    return tags, kpis


async def _profile_reference_document(
    session: AsyncSession, doc: ReferenceDocument, doc_text: str
) -> dict | None:
    """Run the shared AI profiler for a reference doc (no family step).

    Returns the profile dict, or ``None`` if the profiler is unavailable/failed
    so the caller can fall back to a summary-only path.
    """
    ref_tags, ref_kpis = await _reference_tags_and_kpis(session)
    try:
        return await call_document_profiler(
            tenant_id=doc.tenant_id or 0,
            user_id=doc.uploaded_by or 0,
            project_id=doc.project_id or 0,
            asset_id=doc.id,
            document_id=doc.id,
            filename=doc.original_filename or doc.title,
            asset_type=doc.file_type or "document",
            content_type="",
            text_preview=doc_text[:4000],
            chunks=_chunk_previews(doc_text),
            ref_tags=ref_tags,
            ref_kpis=ref_kpis,
            include_family=False,
        )
    except DocumentProfileError as exc:
        logger.warning("Reference profiling unavailable for doc %s: %s", doc.id, exc)
        return None
    except Exception:
        logger.exception("Reference profiling failed for doc %s", doc.id)
        return None


async def process_reference_document(document_id: int) -> None:
    """Run extraction → summary → status for a single reference document.

    Loads its own session so it can run as a background task. Safe to call after
    a manual upload or a bulk-import fetch.
    """
    from app.database import SessionLocal
    from app.models.reference_library import ReferenceDocument

    async with SessionLocal() as session:
        doc = await session.get(ReferenceDocument, document_id)
        if doc is None:
            logger.warning("process_reference_document: doc %s not found", document_id)
            return
        if not doc.file_path:
            logger.warning("process_reference_document: doc %s has no file", document_id)
            return

        doc.status = "processing"
        doc.ai_error_message = None
        await session.commit()

        ext = Path(doc.file_path).suffix.lower()

        # ── Step 1: text extraction ──
        try:
            doc_text = _extract_reference_text(doc.file_path, ext)
        except Exception as exc:
            logger.warning("Reference extraction failed for doc %s: %s", document_id, exc)
            doc.status = "draft"
            doc.ai_error_message = (
                f"Could not extract text ({exc}). Try re-uploading or enter a manual summary."
            )
            await session.commit()
            return

        if not doc_text.strip():
            doc.status = "draft"
            doc.ai_error_message = (
                "Could not extract text (empty or scanned-image document). "
                "Enter a manual summary as a fallback."
            )
            await session.commit()
            return

        # Persist extracted text alongside the source file for citation lookups.
        try:
            text_path = str(Path(doc.file_path).with_suffix(".extracted.txt"))
            Path(text_path).write_text(doc_text, encoding="utf-8")
            doc.extracted_text_path = text_path
        except Exception:
            logger.exception("Failed to persist extracted text for doc %s", document_id)

        # ── Step 2: AI profile (summary + tags/kpis/entities/questions) ──
        # Reference libraries are tenant-wide, so profiling runs with
        # include_family=False — the project-scoped document-family step never
        # runs here. Falls back to a summary-only call if the profiler is
        # unavailable so a doc still lands with at least a summary.
        profile = await _profile_reference_document(session, doc, doc_text)
        summary: str | None = None
        if profile is not None:
            # Merge so values previously set by the upload/parser or another step
            # (e.g. document_family) are preserved when the AI returns a partial
            # metadata payload.
            existing = doc.ai_metadata or {}
            doc.ai_metadata = {**existing, **profile}
            summary = profile.get("summary") or None
        if not summary:
            try:
                summary = await ai_client.summarize_reference_document(
                    tenant_id=doc.tenant_id or 0,
                    user_id=doc.uploaded_by or 0,
                    document_id=doc.id,
                    title=doc.title,
                    issuing_body=doc.issuing_body or "",
                    domain_tag=doc.domain_tag or "",
                    extracted_text=doc_text,
                )
            except Exception:
                logger.exception("AI summary call failed for doc %s", document_id)

        if summary:
            doc.ai_summary = summary

        # Reference metadata changed; cached insights/opportunities that depend on
        # this tenant/project are now stale. Mark them for background rebuild.
        try:
            await mark_project_insight_stale(
                session, tenant_id=doc.tenant_id, project_id=doc.project_id
            )
            if get_settings().project_insight_event_rebuild_enabled and doc.project_id:
                from app.tasks.workflows import enqueue_rebuild_project_insight

                await enqueue_rebuild_project_insight(
                    tenant_id=doc.tenant_id, project_id=doc.project_id
                )
        except Exception:
            logger.exception("Failed to invalidate project intelligence snapshots")

        # ── Step 3: embed into the shared reference vector store ──
        indexed = False
        try:
            indexed = await ai_client.index_reference_document(
                tier=doc.tier,
                tenant_id=doc.tenant_id,
                project_id=doc.project_id,
                user_id=doc.uploaded_by,
                document_id=doc.id,
                title=doc.title,
                extracted_text=doc_text,
            )
        except Exception:
            logger.exception("Vector indexing failed for reference doc %s", document_id)

        # ── Step 4: mark active ──
        doc.status = "active"
        await session.commit()
        logger.info(
            "Reference document %s processed (summary=%s, indexed=%s)",
            document_id, bool(summary), indexed,
        )


async def reindex_reference_documents() -> dict[str, int]:
    """Backfill the reference vector store from already-processed docs.

    One-off/maintenance helper: embeds every reference doc that has a file but
    was processed before vector indexing existed. Returns a small status tally.
    """
    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models.reference_library import ReferenceDocument

    tally = {"indexed": 0, "skipped": 0, "failed": 0}
    async with SessionLocal() as session:
        docs = (
            await session.scalars(
                select(ReferenceDocument).where(ReferenceDocument.file_path.isnot(None))
            )
        ).all()

        for doc in docs:
            text = ""
            if doc.extracted_text_path and Path(doc.extracted_text_path).exists():
                text = Path(doc.extracted_text_path).read_text(
                    encoding="utf-8", errors="ignore"
                )
            elif doc.file_path:
                try:
                    text = _extract_reference_text(
                        doc.file_path, Path(doc.file_path).suffix
                    )
                except Exception:
                    logger.warning("Backfill: extraction failed for doc %s", doc.id)

            if not text.strip():
                tally["skipped"] += 1
                continue

            try:
                ok = await ai_client.index_reference_document(
                    tier=doc.tier,
                    tenant_id=doc.tenant_id,
                    project_id=doc.project_id,
                    user_id=doc.uploaded_by,
                    document_id=doc.id,
                    title=doc.title,
                    extracted_text=text,
                )
                tally["indexed" if ok else "failed"] += 1
            except Exception:
                logger.exception("Backfill: indexing failed for doc %s", doc.id)
                tally["failed"] += 1

    logger.info("Reference reindex backfill complete: %s", tally)
    return tally


def new_storage_id() -> str:
    """Short opaque id for storage filenames when a DB id is not yet available."""
    return uuid.uuid4().hex[:12]
