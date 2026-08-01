"""Server-side bulk URL import engine for Industry-tier references.

Fetches reference documents from their source URLs on the server (avoiding
browser CORS limits), then feeds each one through the same processing pipeline
as a manual upload. Designed for the Industry tier only for now.

Key behaviours (from spec):
- browser User-Agent, 30s timeout, max 5 redirects, 75MB cap
- accept only PDF / DOC / DOCX / HTML responses
- rate-limit 500ms between requests to the same domain
- max 3 concurrent fetches
- never auto-retry on failure — log and move on
"""

from __future__ import annotations

import asyncio
import csv
import io
import logging
import time
from datetime import UTC, datetime
from urllib.parse import urlparse

from sqlalchemy import select

from app.services.reference_library_processing import (
    process_reference_document,
    store_reference_file,
)
from app.services.reference_library_service import find_duplicate_in_tier, normalize_domain_tag
from app.services.safe_remote_fetch import (
    RemoteFetchError,
    fetch_remote_file,
    redact_url,
)

logger = logging.getLogger(__name__)

MAX_BYTES = 75 * 1024 * 1024
MAX_CONCURRENT = 3
DOMAIN_RATE_LIMIT_SEC = 0.5

REQUIRED_COLUMNS = ["title", "source_url"]

CONTENT_TYPE_TO_EXT = {
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "text/html": ".html",
}

SKIP_HINTS = {"paywalled", "manual_required"}


def _norm_header(name: str) -> str:
    return name.strip().lower().replace(" ", "_")


def parse_csv_rows(content: bytes) -> list[dict[str, str]]:
    """Parse CSV bytes into a list of normalized-key row dicts."""
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    rows: list[dict[str, str]] = []
    for raw in reader:
        row = {
            _norm_header(k): (v or "").strip()
            for k, v in raw.items()
            if k is not None
        }
        rows.append(row)
    return rows


def csv_columns(content: bytes) -> list[str]:
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        return []
    return [_norm_header(h) for h in header]


def _is_valid_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except ValueError:
        return False


async def validate_rows(session, rows: list[dict[str, str]]) -> list[dict]:
    """Validate parsed CSV rows for the Industry tier. Returns per-row results."""
    results: list[dict] = []
    for idx, row in enumerate(rows, start=1):
        title = row.get("title", "").strip()
        source_url = row.get("source_url", "").strip()
        raw_domain = row.get("domain_tag", "").strip()
        fetch_hint = row.get("fetch_method", row.get("fetch_method_hint", "")).strip().lower()

        warnings: list[str] = []
        status = "ready"
        failure_reason: str | None = None
        will_update_existing_id: int | None = None

        domain, remapped = normalize_domain_tag(raw_domain)
        if remapped and raw_domain:
            warnings.append("domain_remapped")

        if not title:
            status = "error"
            failure_reason = "Missing title"
        elif not source_url:
            status = "error"
            failure_reason = "Missing source_url"
        elif not _is_valid_url(source_url):
            status = "error"
            failure_reason = "Malformed source_url"
        elif fetch_hint in SKIP_HINTS:
            status = "skipped"
            failure_reason = f"fetch_method={fetch_hint}"
        else:
            dup = await find_duplicate_in_tier(
                session, tier="industry", title=title, tenant_id=None, project_id=None
            )
            if dup is not None:
                warnings.append("duplicate")
                will_update_existing_id = dup.id

        results.append(
            {
                "rowNumber": idx,
                "title": title,
                "issuingBody": row.get("issuing_body", ""),
                "domainTag": domain,
                "applicabilityTag": row.get("applicability_tag", ""),
                "sourceUrl": source_url,
                "versionLabel": row.get("version_label", ""),
                "fetchMethodHint": fetch_hint,
                "status": status,
                "failureReason": failure_reason,
                "warnings": warnings,
                "willUpdateExistingId": will_update_existing_id,
            }
        )
    return results


# ── fetch engine ─────────────────────────────────────────────────────────────


class _DomainRateLimiter:
    """Ensures >= DOMAIN_RATE_LIMIT_SEC between requests to the same domain."""

    def __init__(self) -> None:
        self._last: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock(self, domain: str) -> asyncio.Lock:
        if domain not in self._locks:
            self._locks[domain] = asyncio.Lock()
        return self._locks[domain]

    async def wait(self, domain: str) -> None:
        async with self._lock(domain):
            last = self._last.get(domain, 0.0)
            elapsed = time.monotonic() - last
            if elapsed < DOMAIN_RATE_LIMIT_SEC:
                await asyncio.sleep(DOMAIN_RATE_LIMIT_SEC - elapsed)
            self._last[domain] = time.monotonic()


async def _fetch_url(url: str) -> tuple[bytes, str]:
    """Fetch a reference document. Returns (data, ext); raises on any failure.

    Routed through the shared hardened fetcher so these operator-supplied CSV
    URLs get the same SSRF controls as Data Source Builder imports: internal
    and metadata addresses refused, credential-bearing URLs rejected, every
    redirect hop revalidated, and a hard byte cap.
    """
    chunks: list[bytes] = []

    try:
        _, metadata = await fetch_remote_file(
            url, max_bytes=MAX_BYTES, sink=chunks.append
        )
    except RemoteFetchError as exc:
        raise ValueError(exc.message) from exc

    ext = CONTENT_TYPE_TO_EXT.get(metadata.content_type or "")
    if ext is None:
        # Fall back to URL extension for servers with generic content-type.
        path = urlparse(url).path.lower()
        if path.endswith(".pdf"):
            ext = ".pdf"
        elif path.endswith(".docx"):
            ext = ".docx"
        elif path.endswith((".html", ".htm")):
            ext = ".html"
        else:
            raise ValueError(
                f"Unsupported content-type: {metadata.content_type or 'unknown'}"
            )
    return b"".join(chunks), ext


async def run_batch(batch_id: int, *, retry_only: bool = False) -> None:
    """Fetch + process all eligible rows in a batch. Updates DB as it goes."""
    from app.database import SessionLocal
    from app.models.reference_library import (
        ReferenceDocument,
        ReferenceLibraryImportBatch,
        ReferenceLibraryImportRow,
    )

    async with SessionLocal() as session:
        batch = await session.get(ReferenceLibraryImportBatch, batch_id)
        if batch is None:
            return
        batch.status = "running"
        await session.commit()
        uploaded_by = batch.uploaded_by

        stmt = select(ReferenceLibraryImportRow).where(
            ReferenceLibraryImportRow.batch_id == batch_id
        )
        rows = (await session.scalars(stmt)).all()

    eligible_statuses = {"failed"} if retry_only else {"pending", "ready"}
    eligible = [r for r in rows if r.status in eligible_statuses]

    limiter = _DomainRateLimiter()
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    started = time.monotonic()

    async def handle(
        row_id: int,
        url: str,
        title: str,
        domain: str,
        existing_id: int | None,
    ) -> None:
        domain_host = urlparse(url).netloc
        async with semaphore:
            await limiter.wait(domain_host)
            async with SessionLocal() as s:
                row = await s.get(ReferenceLibraryImportRow, row_id)
                if row is None:
                    return
                row.status = "fetching"
                row.failure_reason = None
                await s.commit()

            try:
                data, ext = await _fetch_url(url)
            except Exception as exc:
                async with SessionLocal() as s:
                    row = await s.get(ReferenceLibraryImportRow, row_id)
                    if row is not None:
                        row.status = "failed"
                        row.failure_reason = str(exc)[:500]
                        await s.commit()
                logger.info(
                    "bulk fetch failed row=%s url=%s: %s",
                    row_id,
                    redact_url(url),
                    exc,
                )
                return

            # Create the document + store file, then process.
            async with SessionLocal() as s:
                row = await s.get(ReferenceLibraryImportRow, row_id)
                if row is None:
                    return
                # Fill a matching metadata-only stub in place when one was
                # detected at validation, otherwise create a new document.
                doc = None
                if existing_id is not None:
                    candidate = await s.get(ReferenceDocument, existing_id)
                    if candidate is not None and not candidate.file_path:
                        doc = candidate
                        doc.issuing_body = doc.issuing_body or row.issuing_body
                        doc.domain_tag = domain
                        doc.applicability_tag = (
                            doc.applicability_tag or row.applicability_tag
                        )
                        doc.source_url = url
                        doc.version_label = doc.version_label or row.version_label
                        doc.status = "processing"
                if doc is None:
                    doc = ReferenceDocument(
                        tier="industry",
                        tenant_id=None,
                        project_id=None,
                        title=title,
                        issuing_body=row.issuing_body,
                        domain_tag=domain,
                        applicability_tag=row.applicability_tag,
                        source_url=url,
                        version_label=row.version_label,
                        status="processing",
                        uploaded_by=uploaded_by,
                    )
                    s.add(doc)
                await s.flush()
                path = store_reference_file(
                    tier="industry",
                    domain_tag=domain,
                    tenant_id=None,
                    project_id=None,
                    document_id=doc.id,
                    ext=ext,
                    data=data,
                )
                doc.file_path = path
                doc.file_type = ext.lstrip(".")
                doc.file_size_bytes = len(data)
                row.reference_document_id = doc.id
                row.status = "processing"
                await s.commit()
                doc_id = doc.id

            await process_reference_document(doc_id)

            async with SessionLocal() as s:
                row = await s.get(ReferenceLibraryImportRow, row_id)
                processed = await s.get(ReferenceDocument, doc_id)
                if row is not None and processed is not None:
                    if processed.status in ("active", "draft"):
                        row.status = "active"
                    else:
                        row.status = "failed"
                        row.failure_reason = (
                            processed.ai_error_message or "Processing failed"
                        )
                    await s.commit()

    await asyncio.gather(
        *[
            handle(
                r.id,
                r.source_url,
                r.title,
                r.domain_tag or "Other",
                r.will_update_existing_id,
            )
            for r in eligible
        ]
    )

    # Finalize batch counts.
    async with SessionLocal() as session:
        batch = await session.get(ReferenceLibraryImportBatch, batch_id)
        rows = (
            await session.scalars(
                select(ReferenceLibraryImportRow).where(
                    ReferenceLibraryImportRow.batch_id == batch_id
                )
            )
        ).all()
        if batch is not None:
            batch.succeeded_count = sum(1 for r in rows if r.status == "active")
            batch.failed_count = sum(1 for r in rows if r.status == "failed")
            batch.skipped_count = sum(1 for r in rows if r.status == "skipped")
            batch.status = (
                "complete_with_errors" if batch.failed_count else "complete"
            )
            # Column is TIMESTAMP WITHOUT TIME ZONE; store a naive UTC datetime.
            batch.completed_at = datetime.now(UTC).replace(tzinfo=None)
            await session.commit()
            logger.info(
                "bulk batch %s done in %.1fs: ok=%s failed=%s skipped=%s",
                batch_id,
                time.monotonic() - started,
                batch.succeeded_count,
                batch.failed_count,
                batch.skipped_count,
            )


def failures_csv(rows: list) -> str:
    """Build a failure-report CSV string from import rows."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(
        ["row_number", "title", "source_url", "domain_tag", "status", "failure_reason"]
    )
    for r in rows:
        if r.status in ("failed", "skipped"):
            writer.writerow(
                [
                    r.row_number,
                    r.title,
                    r.source_url,
                    r.domain_tag or "",
                    r.status,
                    r.failure_reason or "",
                ]
            )
    return out.getvalue()
