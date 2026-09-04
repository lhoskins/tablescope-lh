"""KG-11 / KG-15: compute_source_coverage must report an explicit
total/included/excluded/failed/pending manifest per source type, so a
successful KG build cannot silently conceal truncated, failed, or
still-processing sources.

Run from ``platform-api``: ``pytest -q tests/test_kg15_source_coverage.py``.
"""

from __future__ import annotations

import pytest

from app.models.database_data_source import DatabaseDataSource
from app.models.file_source_meta import FileSourceMeta
from app.models.project import Project
from app.models.project_asset import ProjectAsset
from app.models.reference_library import TIER_COMPANY, TIER_INDUSTRY, TIER_PROJECT, ReferenceDocument
from app.services.knowledge_graph_context.coverage import compute_source_coverage

pytestmark = pytest.mark.anyio


async def _seed_project(db_session, *, tenant_id: int = 1) -> int:
    project = Project(tenant_id=tenant_id, owner_id=1, name="Boeing Supplier QA")
    db_session.add(project)
    await db_session.flush()
    return project.id


async def test_file_sources_report_pending_when_never_profiled(db_session):
    tenant_id = 1
    project_id = await _seed_project(db_session, tenant_id=tenant_id)
    db_session.add_all([
        FileSourceMeta(
            tenant_id=tenant_id, owner_id=1, project_id=project_id,
            view_name="profiled_one", file_name="a.csv", ai_profile_status="profiled",
        ),
        FileSourceMeta(
            tenant_id=tenant_id, owner_id=1, project_id=project_id,
            view_name="stuck_one", file_name="b.csv", ai_profile_status="pending",
        ),
    ])
    await db_session.flush()

    coverage = await compute_source_coverage(db_session, tenant_id=tenant_id, project_id=project_id)
    bucket = coverage["file_sources"]
    assert bucket == {"total": 2, "included": 2, "excluded": 0, "failed": 0, "pending": 1}


async def test_assets_report_failed_and_pending_separately(db_session):
    tenant_id = 1
    project_id = await _seed_project(db_session, tenant_id=tenant_id)
    db_session.add_all([
        ProjectAsset(
            tenant_id=tenant_id, project_id=project_id, asset_type="document",
            title="Good doc", filename="good.pdf", storage_location="good.pdf",
            ai_status="profiled",
        ),
        ProjectAsset(
            tenant_id=tenant_id, project_id=project_id, asset_type="document",
            title="Failed doc", filename="bad.pdf", storage_location="bad.pdf",
            ai_status="failed",
        ),
        ProjectAsset(
            tenant_id=tenant_id, project_id=project_id, asset_type="document",
            title="Still extracting", filename="wip.pdf", storage_location="wip.pdf",
            ai_status="extracting",
        ),
    ])
    await db_session.flush()

    coverage = await compute_source_coverage(db_session, tenant_id=tenant_id, project_id=project_id)
    bucket = coverage["assets"]
    assert bucket == {"total": 3, "included": 3, "excluded": 0, "failed": 1, "pending": 1}


async def test_data_sources_untested_are_pending_failed_test_is_failed(db_session):
    tenant_id = 1
    project_id = await _seed_project(db_session, tenant_id=tenant_id)

    def _ds(name: str, test_status):
        return DatabaseDataSource(
            tenant_id=tenant_id, project_id=project_id, display_name=name,
            source_type="database_table", db_type="mysql", host="db.example.com",
            port=3306, database_name="quality", table_name=name, username="svc",
            teiid_model_name=f"m_{name}", teiid_table_name=name,
            teiid_view_name=f"v_{name}", teiid_jndi_name=f"java:/{name}",
            status="active", last_test_status=test_status,
        )

    db_session.add_all([
        _ds("ok_table", "success"),
        _ds("broken_table", "failed"),
        _ds("untested_table", None),
    ])
    await db_session.flush()

    coverage = await compute_source_coverage(db_session, tenant_id=tenant_id, project_id=project_id)
    bucket = coverage["data_sources"]
    assert bucket == {"total": 3, "included": 3, "excluded": 0, "failed": 1, "pending": 1}


async def test_reference_documents_scoped_by_tier_like_the_collector(db_session):
    tenant_id = 1
    other_tenant_id = 2
    project_id = await _seed_project(db_session, tenant_id=tenant_id)
    db_session.add_all([
        ReferenceDocument(
            tier=TIER_PROJECT, project_id=project_id, tenant_id=tenant_id,
            title="Project doc", status="active",
        ),
        ReferenceDocument(
            tier=TIER_COMPANY, tenant_id=tenant_id, title="Company doc", status="active",
        ),
        ReferenceDocument(tier=TIER_INDUSTRY, title="AS9100D", status="active"),
        ReferenceDocument(tier=TIER_INDUSTRY, title="Still processing", status="processing"),
        # Not visible to this project at all: another tenant's company doc.
        ReferenceDocument(
            tier=TIER_COMPANY, tenant_id=other_tenant_id, title="Other tenant doc", status="active",
        ),
        # Excluded by status filter, not counted at all (matches the collector).
        ReferenceDocument(tier=TIER_INDUSTRY, title="Superseded standard", status="superseded"),
    ])
    await db_session.flush()

    coverage = await compute_source_coverage(db_session, tenant_id=tenant_id, project_id=project_id)
    bucket = coverage["reference_documents"]
    assert bucket == {"total": 4, "included": 4, "excluded": 0, "failed": 0, "pending": 1}


async def test_truncation_cap_is_reported_when_a_source_type_exceeds_it(db_session, monkeypatch):
    """Exercise the real cap semantics without seeding 41 rows."""
    from app.services.knowledge_graph_context import coverage as cov

    monkeypatch.setattr(cov, "_MAX_PER_KIND", 2)

    tenant_id = 1
    project_id = await _seed_project(db_session, tenant_id=tenant_id)
    db_session.add_all([
        FileSourceMeta(
            tenant_id=tenant_id, owner_id=1, project_id=project_id,
            view_name=f"file_{i}", file_name=f"file_{i}.csv", ai_profile_status="profiled",
        )
        for i in range(5)
    ])
    await db_session.flush()

    coverage = await compute_source_coverage(db_session, tenant_id=tenant_id, project_id=project_id)
    bucket = coverage["file_sources"]
    assert bucket["total"] == 5
    assert bucket["included"] == 2
    assert bucket["excluded"] == 3
