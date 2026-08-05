
from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    RepositoryItem,
    RepositoryScan,
)

from .scan import RepositoryScannerError


async def create_scan(
    session: AsyncSession,
    tenant_id: int,
    connection_id: int,
    trigger_type: str = "manual",
) -> RepositoryScan:
    scan = RepositoryScan(
        tenant_id=tenant_id,
        connection_id=connection_id,
        trigger_type=trigger_type,
        status="queued",
    )
    session.add(scan)
    await session.flush()
    return scan


async def list_scans(
    session: AsyncSession,
    tenant_id: int,
    connection_id: int,
) -> list[dict[str, Any]]:
    result = await session.execute(
        select(RepositoryScan)
        .where(
            RepositoryScan.tenant_id == tenant_id,
            RepositoryScan.connection_id == connection_id,
        )
        .order_by(RepositoryScan.created_at.desc())
    )
    return [s.to_summary_dict() for s in result.scalars().all()]


async def get_scan(
    session: AsyncSession,
    tenant_id: int,
    connection_id: int,
    scan_id: int,
) -> dict[str, Any]:
    result = await session.execute(
        select(RepositoryScan).where(
            RepositoryScan.id == scan_id,
            RepositoryScan.connection_id == connection_id,
            RepositoryScan.tenant_id == tenant_id,
        )
    )
    scan = result.scalar_one_or_none()
    if scan is None:
        raise RepositoryScannerError("Scan not found")
    return scan.to_summary_dict()


async def list_items(
    session: AsyncSession,
    tenant_id: int,
    connection_id: int,
    *,
    item_type: str | None = None,
    is_deleted: bool | None = False,
    extraction_status: str | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    where = [
        RepositoryItem.tenant_id == tenant_id,
        RepositoryItem.connection_id == connection_id,
    ]
    if item_type is not None:
        where.append(RepositoryItem.item_type == item_type)
    if is_deleted is not None:
        where.append(RepositoryItem.is_deleted.is_(is_deleted))
    if extraction_status:
        where.append(RepositoryItem.extraction_status == extraction_status)
    if search:
        like = f"%{search}%"
        where.append(
            (RepositoryItem.name.ilike(like))
            | (RepositoryItem.relative_path.ilike(like))
        )

    count_result = await session.execute(
        select(func.count(RepositoryItem.id)).where(*where)
    )
    total = count_result.scalar() or 0

    result = await session.execute(
        select(RepositoryItem)
        .where(*where)
        .order_by(RepositoryItem.relative_path)
        .limit(limit)
        .offset(offset)
    )
    items = result.scalars().all()
    return [i.to_dict() for i in items], total
