"""KG-13: the source fingerprint must change when a graph-relevant source
changes, so the graph is correctly marked stale and rebuilt. Confirmed gap:
uploaded file sources (``FileSourceMeta``) and the Reference Library
(``ReferenceDocument``, all three tiers) were entirely absent from
``compute_source_fingerprint`` -- adding, editing, or removing one left the
fingerprint (and therefore staleness detection) unchanged.

Run from ``platform-api``: ``pytest -q tests/test_kg13_source_fingerprint.py``.
"""

from __future__ import annotations

import pytest

from app.auth.context import RequestContext
from app.auth.jwt import TokenClaims
from app.models.file_source_meta import FileSourceMeta
from app.models.project import Project
from app.models.reference_library import TIER_COMPANY, TIER_INDUSTRY, TIER_PROJECT, ReferenceDocument
from app.services.knowledge_graph_lifecycle import KnowledgeGraphLifecycleManager

pytestmark = pytest.mark.anyio


def _manager(session, tenant_id: int, user_id: int) -> KnowledgeGraphLifecycleManager:
    return KnowledgeGraphLifecycleManager(
        session,
        RequestContext(
            claims=TokenClaims(sub=str(user_id), tenant_id=tenant_id, user_id=user_id, role="editor")
        ),
    )


async def _seed_project(db_session, *, tenant_id: int = 1) -> int:
    project = Project(tenant_id=tenant_id, owner_id=1, name="Boeing Supplier QA")
    db_session.add(project)
    await db_session.flush()
    return project.id


async def test_fingerprint_changes_when_a_file_source_is_added(db_session):
    tenant_id = 1
    project_id = await _seed_project(db_session, tenant_id=tenant_id)
    mgr = _manager(db_session, tenant_id, 1)

    before = await mgr.compute_source_fingerprint(project_id)

    db_session.add(
        FileSourceMeta(
            tenant_id=tenant_id, owner_id=1, project_id=project_id,
            view_name="supplier_quality", file_name="supplier_quality.csv",
        )
    )
    await db_session.flush()

    after = await mgr.compute_source_fingerprint(project_id)
    assert before != after


async def test_fingerprint_changes_when_a_project_reference_document_is_added(db_session):
    tenant_id = 1
    project_id = await _seed_project(db_session, tenant_id=tenant_id)
    mgr = _manager(db_session, tenant_id, 1)

    before = await mgr.compute_source_fingerprint(project_id)

    db_session.add(
        ReferenceDocument(
            tier=TIER_PROJECT, project_id=project_id, tenant_id=tenant_id,
            title="Boeing CAPA Procedure", status="active",
        )
    )
    await db_session.flush()

    after = await mgr.compute_source_fingerprint(project_id)
    assert before != after


async def test_fingerprint_changes_when_a_company_reference_document_is_added(db_session):
    """Company-tier references apply tenant-wide -- adding one anywhere in
    the tenant must mark every project in it stale, matching what
    collect_structural_graph actually pulls into the graph."""
    tenant_id = 1
    project_id = await _seed_project(db_session, tenant_id=tenant_id)
    mgr = _manager(db_session, tenant_id, 1)

    before = await mgr.compute_source_fingerprint(project_id)

    db_session.add(
        ReferenceDocument(
            tier=TIER_COMPANY, tenant_id=tenant_id,
            title="Acme Supplier Code of Conduct", status="active",
        )
    )
    await db_session.flush()

    after = await mgr.compute_source_fingerprint(project_id)
    assert before != after


async def test_fingerprint_changes_when_an_industry_standard_is_added(db_session):
    """Industry-tier references are global -- collect_structural_graph pulls
    them into every project's graph regardless of tenant."""
    tenant_id = 1
    project_id = await _seed_project(db_session, tenant_id=tenant_id)
    mgr = _manager(db_session, tenant_id, 1)

    before = await mgr.compute_source_fingerprint(project_id)

    db_session.add(
        ReferenceDocument(tier=TIER_INDUSTRY, title="AS9100D", status="active")
    )
    await db_session.flush()

    after = await mgr.compute_source_fingerprint(project_id)
    assert before != after


async def test_fingerprint_ignores_a_different_tenants_company_reference(db_session):
    tenant_id = 1
    other_tenant_id = 2
    project_id = await _seed_project(db_session, tenant_id=tenant_id)
    mgr = _manager(db_session, tenant_id, 1)

    before = await mgr.compute_source_fingerprint(project_id)

    db_session.add(
        ReferenceDocument(
            tier=TIER_COMPANY, tenant_id=other_tenant_id,
            title="Other Tenant's Policy", status="active",
        )
    )
    await db_session.flush()

    after = await mgr.compute_source_fingerprint(project_id)
    assert before == after
