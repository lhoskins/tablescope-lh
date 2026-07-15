"""Aggregate repository scan profiles."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.repository import RepositoryConnection, RepositoryItem, RepositoryProfile


class RepositoryProfiler:
    """Build an aggregate profile from the current item snapshot of a repository."""

    SIZE_BUCKETS: ClassVar[list[tuple[int | float, str]]] = [
        (0, "0 B"),
        (1024, "0 B - 1 KB"),
        (10 * 1024, "1 KB - 10 KB"),
        (100 * 1024, "10 KB - 100 KB"),
        (1024 * 1024, "100 KB - 1 MB"),
        (10 * 1024 * 1024, "1 MB - 10 MB"),
        (100 * 1024 * 1024, "10 MB - 100 MB"),
        (1024 * 1024 * 1024, "100 MB - 1 GB"),
        (float("inf"), "> 1 GB"),
    ]

    AGE_BUCKETS: ClassVar[list[tuple[timedelta, str]]] = [
        (timedelta(days=7), "last_7_days"),
        (timedelta(days=30), "last_30_days"),
        (timedelta(days=90), "last_90_days"),
        (timedelta(days=365), "last_year"),
        (timedelta(days=365 * 5), "last_5_years"),
    ]

    @classmethod
    async def build_profile(
        cls,
        session: AsyncSession,
        connection_id: int,
        scan_id: int | None,
        tenant_id: int,
    ) -> dict[str, Any]:
        result = await session.execute(
            select(RepositoryConnection).where(
                RepositoryConnection.id == connection_id,
                RepositoryConnection.tenant_id == tenant_id,
            )
        )
        connection = result.scalar_one_or_none()
        if connection is None:
            raise ValueError("Repository connection not found")

        # Load only live, non-deleted items.
        items_result = await session.execute(
            select(RepositoryItem).where(
                RepositoryItem.connection_id == connection_id,
                RepositoryItem.tenant_id == tenant_id,
                RepositoryItem.is_deleted.is_(False),
            )
        )
        items = items_result.scalars().all()

        total_files = 0
        total_directories = 0
        total_bytes = 0
        extension_counter: Counter[str] = Counter()
        mime_counter: Counter[str] = Counter()
        age_counter: Counter[str] = Counter()
        size_bucket_counter: Counter[str] = Counter()
        extraction_supported = 0
        extraction_skipped = 0
        extraction_pending = 0
        extraction_completed = 0
        extraction_failed = 0
        extraction_governance_blocked = 0
        duplicate_candidates = 0

        now = datetime.now(UTC)
        seen_sizes: Counter[tuple[str, int | None]] = Counter()

        for item in items:
            if item.item_type == "file":
                total_files += 1
                size = item.size or 0
                total_bytes += size
                bucket = cls._size_bucket(size)
                size_bucket_counter[bucket] += 1

                ext = (item.extension or "none").lower()
                extension_counter[ext] += 1

                mime = item.mime_type or "unknown"
                mime_counter[mime] += 1

                if item.size is not None:
                    seen_sizes[(item.name.lower(), item.size)] += 1

                if item.extraction_status == "pending":
                    extraction_pending += 1
                elif item.extraction_status == "completed":
                    extraction_completed += 1
                elif item.extraction_status == "failed":
                    extraction_failed += 1
                elif item.extraction_status == "skipped":
                    extraction_skipped += 1
                elif item.extraction_status == "governance_blocked":
                    extraction_governance_blocked += 1
                else:
                    if cls._extraction_supported(item):
                        extraction_supported += 1
                    else:
                        extraction_skipped += 1

                if item.source_modified_at:
                    age_counter[cls._age_bucket(item.source_modified_at, now)] += 1
            elif item.item_type == "directory":
                total_directories += 1

        for count in seen_sizes.values():
            if count > 1:
                duplicate_candidates += count - 1

        oldest = None
        newest = None
        if items:
            modified_dates = [
                i.source_modified_at for i in items if i.source_modified_at is not None
            ]
            if modified_dates:
                oldest = min(modified_dates).isoformat()
                newest = max(modified_dates).isoformat()

        profile_json = {
            "generated_at": datetime.now(UTC).isoformat(),
            "connection_id": connection_id,
            "scan_id": scan_id,
            "total_items": len(items),
            "total_files": total_files,
            "total_directories": total_directories,
            "total_bytes": total_bytes,
            "extensions": dict(extension_counter.most_common(25)),
            "mime_types": dict(mime_counter.most_common(25)),
            "size_buckets": dict(size_bucket_counter),
            "age_buckets": {k: age_counter[k] for _, k in cls.AGE_BUCKETS},
            "extraction": {
                "supported": extraction_supported,
                "pending": extraction_pending,
                "queued": extraction_pending,
                "completed": extraction_completed,
                "failed": extraction_failed,
                "skipped": extraction_skipped,
                "governance_blocked": extraction_governance_blocked,
            },
            "duplicate_candidates": duplicate_candidates,
            "oldest_modified_at": oldest,
            "newest_modified_at": newest,
        }

        # Mark prior profiles stale and store current one.
        await session.execute(
            select(RepositoryProfile)
            .where(
                RepositoryProfile.connection_id == connection_id,
                RepositoryProfile.is_current.is_(True),
            )
        )
        stmt = select(RepositoryProfile).where(
            RepositoryProfile.connection_id == connection_id,
            RepositoryProfile.is_current.is_(True),
        )
        prior_result = await session.execute(stmt)
        for prior in prior_result.scalars().all():
            prior.is_current = False

        profile = RepositoryProfile(
            tenant_id=tenant_id,
            connection_id=connection_id,
            scan_id=scan_id,
            profile_json=profile_json,
            is_current=True,
        )
        session.add(profile)
        await session.flush()
        return profile.to_dict()

    @classmethod
    def _size_bucket(cls, size: int) -> str:
        for upper, label in cls.SIZE_BUCKETS:
            if size < upper:
                return label
        return "unknown"

    @classmethod
    def _age_bucket(cls, modified_at: datetime, now: datetime) -> str:
        if modified_at.tzinfo is None:
            modified_at = modified_at.replace(tzinfo=UTC)
        for td, label in cls.AGE_BUCKETS:
            if now - modified_at <= td:
                return label
        return "older"

    @classmethod
    def _extraction_supported(cls, item: RepositoryItem) -> bool:
        supported_exts = {
            "pdf",
            "txt",
            "md",
            "docx",
            "pptx",
            "xlsx",
            "csv",
            "json",
            "html",
        }
        ext = (item.extension or "").lower()
        return ext in supported_exts
