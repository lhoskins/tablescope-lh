"""KG-30: semantic coverage scoring.

Validated gaps: the existing coverage manifest
(``app.services.knowledge_graph_context.coverage.compute_source_coverage``,
built for KG-11/KG-15) reported only raw counts, never a percentage, and
covered only 6 of the review's 9 listed dimensions (missing goals, KPIs/
metrics, risks -- despite all three already being graph-relevant sources
hashed by ``compute_source_fingerprint``). The health-check endpoint never
called it at all -- coverage lived only inside a build version's untyped
``validation_summary`` blob, never alongside the structural-validity report
a caller would actually check first.

Run from ``platform-api``: ``pytest -q tests/test_kg30_coverage_scoring.py``.
"""

from __future__ import annotations

import pytest

from app.auth.context import RequestContext
from app.auth.jwt import TokenClaims
from app.models import (
    AIProjectGraphEdge,
    AIProjectGraphNode,
    Project,
    ProjectBusinessContext,
)
from app.models.project_context.goals import ProjectGoal
from app.services.knowledge_graph_context.coverage import (
    compute_source_coverage,
    summarize_coverage_gaps,
)
from app.services.knowledge_graph_health import KnowledgeGraphHealthService
from app.services.knowledge_graph_lifecycle import KnowledgeGraphLifecycleManager

pytestmark = pytest.mark.anyio


def _manager(session, tenant_id: int, user_id: int):
    return KnowledgeGraphLifecycleManager(
        session,
        RequestContext(
            claims=TokenClaims(sub=str(user_id), tenant_id=tenant_id, user_id=user_id, role="editor")
        ),
    )


async def _project(session, tenant_id: int, user_id: int, slug: str):
    project = Project(tenant_id=tenant_id, name=f"{slug} Project", owner_id=user_id, is_shared=False)
    session.add(project)
    await session.flush()
    session.add(ProjectBusinessContext(
        tenant_id=tenant_id, project_id=project.id, ai_context_enabled=True, version=0,
    ))
    await session.flush()
    return project


def test_bucket_reports_full_coverage_and_a_named_gap_when_nothing_exists():
    from app.services.knowledge_graph_context.coverage import _bucket
    result = _bucket([], pending=set(), failed=set())
    assert result["coverage_percent"] == 100.0
    assert summarize_coverage_gaps({"file_sources": result}) == [
        "No file data sources found for this project"
    ]


def test_bucket_names_a_gap_for_failed_rows_even_when_all_are_included():
    from app.services.knowledge_graph_context.coverage import _bucket
    result = _bucket(["failed", "success", "success"], pending=set(), failed={"failed"})
    assert result["coverage_percent"] == 100.0  # all 3 are still "included" (under the cap)
    gaps = summarize_coverage_gaps({"data_sources": result})
    assert len(gaps) == 1
    assert "1 failed" in gaps[0]


async def test_compute_source_coverage_includes_goals_metrics_risks(db_session):
    tenant_id = 3001
    project = await _project(db_session, tenant_id, 1, "coverage")

    db_session.add(ProjectGoal(tenant_id=tenant_id, project_id=project.id, title="Reduce cycle time"))
    await db_session.flush()

    coverage = await compute_source_coverage(db_session, tenant_id=tenant_id, project_id=project.id)
    assert "goals" in coverage
    assert "metrics" in coverage
    assert "risks" in coverage
    assert coverage["goals"]["total"] == 1
    assert coverage["goals"]["coverage_percent"] == 100.0
    assert coverage["risks"]["total"] == 0
    assert coverage["risks"]["coverage_percent"] == 100.0


async def test_health_check_carries_source_coverage_and_named_gaps(db_session):
    tenant_id = 3002
    user_id = 1
    project = await _project(db_session, tenant_id, user_id, "health-coverage")

    project_node = AIProjectGraphNode(
        tenant_id=tenant_id, project_id=project.id, node_type="project",
        source_type="project", source_id=project.id, name=project.name,
        properties={"project_id": project.id}, is_active=True, created_by=user_id,
    )
    metric_node = AIProjectGraphNode(
        tenant_id=tenant_id, project_id=project.id, node_type="metric",
        source_type="metric", source_id=1, name="KPI 1", is_active=True, created_by=user_id,
    )
    risk_node = AIProjectGraphNode(
        tenant_id=tenant_id, project_id=project.id, node_type="risk",
        source_type="risk", source_id=1, name="Risk 1", is_active=True, created_by=user_id,
    )
    db_session.add_all([project_node, metric_node, risk_node])
    await db_session.flush()
    db_session.add_all([
        AIProjectGraphEdge(
            tenant_id=tenant_id, project_id=project.id,
            from_node_id=project_node.id, to_node_id=metric_node.id,
            relationship_type="measures", is_active=True, created_by=user_id,
        ),
        AIProjectGraphEdge(
            tenant_id=tenant_id, project_id=project.id,
            from_node_id=project_node.id, to_node_id=risk_node.id,
            relationship_type="threatens", is_active=True, created_by=user_id,
        ),
    ])
    await db_session.flush()

    manager = _manager(db_session, tenant_id, user_id)
    build, _ = await manager.request_full_rebuild(project.id)
    await manager.run_full_rebuild(build.id)
    await db_session.commit()

    health = KnowledgeGraphHealthService(db_session)
    hc = await health.run_health_check(project.id, check_type="on_demand")

    assert hc.status == "healthy"
    assert hc.source_coverage is not None
    assert "file_sources" in hc.source_coverage
    assert "goals" in hc.source_coverage
    # This project has no saved queries/dashboards/goals/etc -- the gap
    # summary must name that, without demoting an otherwise-healthy graph.
    assert hc.warnings
    assert any("No saved queries found" in w for w in hc.warnings)
