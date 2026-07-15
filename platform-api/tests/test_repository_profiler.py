"""Tests for repository profile aggregation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RepositoryConnection, RepositoryItem, Tenant
from app.services.repository_profiler import RepositoryProfiler

pytestmark = pytest.mark.anyio


async def _seed_tenant(db_session: AsyncSession) -> Tenant:
    tenant = Tenant(slug="repo-tenant", name="Repo Tenant")
    db_session.add(tenant)
    await db_session.flush()
    return tenant


async def _seed_connection(db_session: AsyncSession, tenant: Tenant) -> RepositoryConnection:
    conn = RepositoryConnection(
        tenant_id=tenant.id,
        name="UNC Share",
        connector_type="unc",
        config_json={"rootPath": r"\\server\share"},
    )
    db_session.add(conn)
    await db_session.flush()
    return conn


async def test_build_profile_from_items(db_session: AsyncSession) -> None:
    tenant = await _seed_tenant(db_session)
    conn = await _seed_connection(db_session, tenant)

    now = datetime.now(UTC)
    items = [
        RepositoryItem(
            tenant_id=tenant.id,
            connection_id=conn.id,
            external_id="pdf-1",
            relative_path="a.pdf",
            name="a.pdf",
            parent_path="/",
            item_type="file",
            extension="pdf",
            mime_type="application/pdf",
            size=2048,
            source_modified_at=now - timedelta(days=2),
            extraction_status="pending",
        ),
        RepositoryItem(
            tenant_id=tenant.id,
            connection_id=conn.id,
            external_id="pdf-2",
            relative_path="archive/a.pdf",
            name="a.pdf",
            parent_path="/archive",
            item_type="file",
            extension="pdf",
            mime_type="application/pdf",
            size=2048,
            source_modified_at=now - timedelta(days=2),
            extraction_status="pending",
        ),
        RepositoryItem(
            tenant_id=tenant.id,
            connection_id=conn.id,
            external_id="txt-1",
            relative_path="notes.txt",
            name="notes.txt",
            parent_path="/",
            item_type="file",
            extension="txt",
            mime_type="text/plain",
            size=512,
            source_modified_at=now - timedelta(days=40),
            extraction_status="completed",
        ),
        RepositoryItem(
            tenant_id=tenant.id,
            connection_id=conn.id,
            external_id="dir-1",
            relative_path="archive",
            name="archive",
            parent_path="/",
            item_type="directory",
        ),
    ]
    for item in items:
        db_session.add(item)
    await db_session.flush()

    result = await RepositoryProfiler.build_profile(
        db_session, conn.id, scan_id=None, tenant_id=tenant.id
    )

    profile = result["profile"]
    assert profile["total_files"] == 3
    assert profile["total_directories"] == 1
    assert profile["total_bytes"] == 2048 + 2048 + 512
    assert profile["extensions"]["pdf"] == 2
    assert profile["extensions"]["txt"] == 1
    assert profile["mime_types"]["application/pdf"] == 2
    assert profile["duplicate_candidates"] == 1
    assert profile["extraction"]["pending"] == 2
    assert profile["extraction"]["completed"] == 1
    assert profile["age_buckets"]["last_7_days"] == 2
    assert profile["age_buckets"]["last_30_days"] == 0
    assert profile["age_buckets"]["last_90_days"] == 1
    assert profile["age_buckets"]["last_year"] == 0


async def test_deleted_items_are_excluded(db_session: AsyncSession) -> None:
    tenant = await _seed_tenant(db_session)
    conn = await _seed_connection(db_session, tenant)

    live = RepositoryItem(
        tenant_id=tenant.id,
        connection_id=conn.id,
        external_id="live-1",
        relative_path="live.pdf",
        name="live.pdf",
        parent_path="/",
        item_type="file",
        extension="pdf",
        size=100,
        source_modified_at=datetime.now(UTC),
        extraction_status="pending",
    )
    deleted = RepositoryItem(
        tenant_id=tenant.id,
        connection_id=conn.id,
        external_id="deleted-1",
        relative_path="old.pdf",
        name="old.pdf",
        parent_path="/",
        item_type="file",
        extension="pdf",
        size=100,
        source_modified_at=datetime.now(UTC),
        is_deleted=True,
        extraction_status="pending",
    )
    db_session.add_all([live, deleted])
    await db_session.flush()

    result = await RepositoryProfiler.build_profile(
        db_session, conn.id, scan_id=None, tenant_id=tenant.id
    )
    assert result["profile"]["total_files"] == 1
