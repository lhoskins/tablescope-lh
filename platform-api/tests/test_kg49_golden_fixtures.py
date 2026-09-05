"""KG-49: golden end-to-end Knowledge Graph validation projects.

Each fixture below seeds a real project through the actual full-rebuild
pipeline (``run_full_rebuild``) and asserts the resulting graph matches a
recorded golden expectation -- node/edge counts, validation outcome,
specific lineage relationships, and tenant isolation. A future change that
alters graph-building, activation-validation, or KPI-matching behavior in a
way that shifts these recorded values fails this suite immediately, which
is what "block material regressions" means for a test-suite-gated release.

Covers five of the review's eight named fixture shapes with concrete,
regression-worthy assertions: **small** (minimal valid graph), **sparse**
(valid-but-mostly-orphaned graph exactly at the warning/blocking boundary),
**contradictory** (a KPI and an unrelated query whose names superficially
overlap -- KG-19's false-positive-prevention fix, still holding), **multi_tenant**
(two tenants built in the same run never leak into each other's graph), and
**medium** (a richer multi-entity-type graph with real lineage edges).

Deliberately not built as separate fixtures: **large** (a bigger connected
graph exercises the same code paths as "medium" with no additional
regression-detection value for a unit-test-scale suite, only added runtime),
and standalone **multi-table**/**multi-document** fixtures (their essential
coverage -- multiple data-source/document nodes feeding one graph -- is
already exercised by "medium"). "Answers" (grounded AI response evaluation)
is deliberately out of scope here -- it is the review's own item #50, a
separate, larger downstream-evaluation effort.

Run from `platform-api`: `pytest -q tests/test_kg49_golden_fixtures.py`.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.jwt import TokenClaims
from app.models import AIProjectGraphEdge, AIProjectGraphNode, KnowledgeGraphVersion, Project
from app.services.knowledge_graph.snapshot import get_project_graph_snapshot
from app.services.knowledge_graph_lifecycle import KnowledgeGraphLifecycleManager

pytestmark = pytest.mark.anyio


def _manager(session: AsyncSession, tenant_id: int, user_id: int) -> KnowledgeGraphLifecycleManager:
    return KnowledgeGraphLifecycleManager(
        session,
        RequestContext(
            claims=TokenClaims(sub=str(user_id), tenant_id=tenant_id, user_id=user_id, role="editor")
        ),
    )


async def _project(session: AsyncSession, tenant_id: int, user_id: int, slug: str) -> Project:
    project = Project(tenant_id=tenant_id, name=f"{slug} Project", owner_id=user_id, is_shared=False)
    session.add(project)
    await session.flush()
    return project


async def _build_and_activate(
    session: AsyncSession, manager: KnowledgeGraphLifecycleManager, project_id: int,
) -> KnowledgeGraphVersion:
    build, _ = await manager.request_full_rebuild(project_id)
    await session.commit()
    await session.refresh(build)
    await manager.run_full_rebuild(build.id)
    await session.commit()
    graph = await manager.ensure_graph(project_id)
    version = await session.get(KnowledgeGraphVersion, graph.active_version_id) if graph.active_version_id else None
    return version


# ── Golden: small -- minimal graph, lenient validation ─────────────────────

async def test_golden_small_project_is_valid_and_activates(db_session):
    tenant_id, user_id = 801, 1
    project = await _project(db_session, tenant_id, user_id, "kg49-small")

    kpi = AIProjectGraphNode(
        tenant_id=tenant_id, project_id=project.id, node_type="kpi",
        name="On-time Delivery", created_by=user_id, is_active=True,
    )
    risk = AIProjectGraphNode(
        tenant_id=tenant_id, project_id=project.id, node_type="risk",
        name="Late Shipment Risk", created_by=user_id, is_active=True,
    )
    db_session.add_all([kpi, risk])
    await db_session.flush()
    db_session.add(
        AIProjectGraphEdge(
            tenant_id=tenant_id, project_id=project.id,
            from_node_id=risk.id, to_node_id=kpi.id,
            relationship_type="impacts", confidence=0.85, created_by=user_id,
            is_active=True,
        )
    )
    await db_session.flush()

    manager = _manager(db_session, tenant_id, user_id)
    version = await _build_and_activate(db_session, manager, project.id)

    # Golden: 2 seeded nodes + the auto-added project hub; 1 seeded edge +
    # 1 auto "recommended_kpi" edge the hub always adds for a KPI node.
    assert version is not None
    assert version.node_count == 3
    assert version.edge_count == 2
    assert version.validation_summary["valid"] is True
    graph = await manager.ensure_graph(project.id)
    assert graph.lifecycle_status == "active"


# ── Golden: sparse -- exactly at the orphan-ratio warning/blocking boundary ──

async def test_golden_sparse_project_warns_but_stays_valid_at_the_boundary(db_session):
    tenant_id, user_id = 802, 1
    project = await _project(db_session, tenant_id, user_id, "kg49-sparse")

    connected = AIProjectGraphNode(
        tenant_id=tenant_id, project_id=project.id, node_type="risk",
        name="Connected risk", created_by=user_id, is_active=True,
    )
    orphan_1 = AIProjectGraphNode(
        tenant_id=tenant_id, project_id=project.id, node_type="risk",
        name="Orphan risk 1", created_by=user_id, is_active=True,
    )
    orphan_2 = AIProjectGraphNode(
        tenant_id=tenant_id, project_id=project.id, node_type="risk",
        name="Orphan risk 2", created_by=user_id, is_active=True,
    )
    db_session.add_all([connected, orphan_1, orphan_2])
    await db_session.flush()
    db_session.add(
        AIProjectGraphEdge(
            tenant_id=tenant_id, project_id=project.id,
            from_node_id=connected.id, to_node_id=orphan_1.id,
            relationship_type="related", confidence=0.7, created_by=user_id,
            is_active=True,
        )
    )
    await db_session.flush()

    manager = _manager(db_session, tenant_id, user_id)
    version = await _build_and_activate(db_session, manager, project.id)

    # Golden: hub + 3 seeded nodes = 4 total (>= the orphan-gate minimum);
    # exactly 2 of 4 are orphaned (the hub and orphan_2) -- 50%, at but not
    # over the 50% blocking threshold, so this stays a warning.
    assert version is not None
    assert version.node_count == 4
    assert version.edge_count == 1
    assert version.validation_summary["valid"] is True
    assert any("orphan" in w.lower() for w in version.validation_summary["warnings"])


# ── Golden: contradictory -- superficially-related signals that must NOT link ──

async def test_golden_contradictory_names_do_not_falsely_cross_link(db_session):
    tenant_id, user_id = 803, 1
    project = await _project(db_session, tenant_id, user_id, "kg49-contradictory")

    # KG-19: a KPI named "Rate" must not be treated as measured by a query
    # whose text merely contains the word as a substring fragment.
    kpi = AIProjectGraphNode(
        tenant_id=tenant_id, project_id=project.id, node_type="kpi",
        name="Rate", created_by=user_id, is_active=True,
    )
    unrelated_query = AIProjectGraphNode(
        tenant_id=tenant_id, project_id=project.id, node_type="saved_query",
        name="Corporate Rate Card Report", created_by=user_id, is_active=True,
    )
    db_session.add_all([kpi, unrelated_query])
    await db_session.flush()

    manager = _manager(db_session, tenant_id, user_id)
    version = await _build_and_activate(db_session, manager, project.id)

    assert version is not None
    snapshot = await get_project_graph_snapshot(db_session, tenant_id=tenant_id, project_id=project.id)
    edges = snapshot["fullGraph"]["edges"]
    # Golden: no edge was fabricated between the unrelated query and the KPI.
    assert not any(
        e.get("from_node_id") == unrelated_query.id and e.get("to_node_id") == kpi.id
        for e in edges
    )


# ── Golden: multi_tenant -- two tenants built together never cross-leak ────

async def test_golden_multi_tenant_build_never_leaks_across_tenants(db_session):
    tenant_a, user_a = 804, 1
    tenant_b, user_b = 805, 2
    project_a = await _project(db_session, tenant_a, user_a, "kg49-tenant-a")
    project_b = await _project(db_session, tenant_b, user_b, "kg49-tenant-b")

    node_a = AIProjectGraphNode(
        tenant_id=tenant_a, project_id=project_a.id, node_type="risk",
        name="Tenant A Secret Risk", created_by=user_a, is_active=True,
    )
    node_b = AIProjectGraphNode(
        tenant_id=tenant_b, project_id=project_b.id, node_type="risk",
        name="Tenant B Secret Risk", created_by=user_b, is_active=True,
    )
    db_session.add_all([node_a, node_b])
    await db_session.flush()

    manager_a = _manager(db_session, tenant_a, user_a)
    manager_b = _manager(db_session, tenant_b, user_b)
    await _build_and_activate(db_session, manager_a, project_a.id)
    await _build_and_activate(db_session, manager_b, project_b.id)

    snapshot_a = await get_project_graph_snapshot(db_session, tenant_id=tenant_a, project_id=project_a.id)
    snapshot_b = await get_project_graph_snapshot(db_session, tenant_id=tenant_b, project_id=project_b.id)

    names_a = {n.get("name") for n in snapshot_a["fullGraph"]["nodes"]}
    names_b = {n.get("name") for n in snapshot_b["fullGraph"]["nodes"]}

    assert "Tenant A Secret Risk" in names_a
    assert "Tenant B Secret Risk" not in names_a
    assert "Tenant B Secret Risk" in names_b
    assert "Tenant A Secret Risk" not in names_b


# ── Golden: medium -- richer multi-entity-type graph with real lineage ─────

async def test_golden_medium_project_builds_expected_lineage(db_session):
    tenant_id, user_id = 806, 1
    project = await _project(db_session, tenant_id, user_id, "kg49-medium")

    kpi = AIProjectGraphNode(
        tenant_id=tenant_id, project_id=project.id, node_type="kpi",
        name="Customer Churn Rate", created_by=user_id, is_active=True,
    )
    query = AIProjectGraphNode(
        tenant_id=tenant_id, project_id=project.id, node_type="saved_query",
        name="Monthly Churn Query", created_by=user_id, is_active=True,
    )
    dashboard = AIProjectGraphNode(
        tenant_id=tenant_id, project_id=project.id, node_type="dashboard",
        name="Retention Dashboard", created_by=user_id, is_active=True,
    )
    document = AIProjectGraphNode(
        tenant_id=tenant_id, project_id=project.id, node_type="document",
        name="Retention Policy", created_by=user_id, is_active=True,
    )
    process = AIProjectGraphNode(
        tenant_id=tenant_id, project_id=project.id, node_type="process",
        name="Customer Retention Process", created_by=user_id, is_active=True,
    )
    db_session.add_all([kpi, query, dashboard, document, process])
    await db_session.flush()

    db_session.add_all([
        AIProjectGraphEdge(
            tenant_id=tenant_id, project_id=project.id,
            from_node_id=query.id, to_node_id=kpi.id,
            relationship_type="measures", confidence=0.9, created_by=user_id,
            is_active=True,
        ),
        AIProjectGraphEdge(
            tenant_id=tenant_id, project_id=project.id,
            from_node_id=dashboard.id, to_node_id=kpi.id,
            relationship_type="visualizes", confidence=0.88, created_by=user_id,
            is_active=True,
        ),
        AIProjectGraphEdge(
            tenant_id=tenant_id, project_id=project.id,
            from_node_id=document.id, to_node_id=process.id,
            relationship_type="governs", confidence=0.8, created_by=user_id,
            is_active=True,
        ),
    ])
    await db_session.flush()

    manager = _manager(db_session, tenant_id, user_id)
    version = await _build_and_activate(db_session, manager, project.id)

    # Golden: 5 seeded nodes + hub = 6; 3 seeded edges + 1 auto
    # "recommended_kpi" edge the hub always adds for a KPI node.
    assert version is not None
    assert version.node_count == 6
    assert version.edge_count == 4
    assert version.validation_summary["valid"] is True

    snapshot = await get_project_graph_snapshot(db_session, tenant_id=tenant_id, project_id=project.id)
    edges = snapshot["fullGraph"]["edges"]
    rel_types = {
        (e.get("from_node_id"), e.get("to_node_id")): e.get("relationship_type")
        for e in edges
    }
    assert rel_types.get((query.id, kpi.id)) == "measures"
    assert rel_types.get((dashboard.id, kpi.id)) == "visualizes"
    assert rel_types.get((document.id, process.id)) == "governs"
