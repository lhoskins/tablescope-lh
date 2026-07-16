"""Tests for knowledge graph health checks."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.jwt import TokenClaims
from app.models import (
    AIProjectGraphEdge,
    AIProjectGraphNode,
    KnowledgeGraphVersion,
    Project,
    ProjectBusinessContext,
)
from app.services.knowledge_graph_health import KnowledgeGraphHealthService
from app.services.knowledge_graph_lifecycle import KnowledgeGraphLifecycleManager

pytestmark = pytest.mark.anyio


def _manager(session: AsyncSession, tenant_id: int, user_id: int):
    return KnowledgeGraphLifecycleManager(
        session,
        RequestContext(
            claims=TokenClaims(
                sub=str(user_id), tenant_id=tenant_id, user_id=user_id, role="editor"
            )
        ),
    )


async def _project(session: AsyncSession, tenant_id: int, user_id: int, slug: str):
    project = Project(
        tenant_id=tenant_id,
        name=f"{slug} Project",
        owner_id=user_id,
        is_shared=False,
    )
    session.add(project)
    await session.flush()

    context = ProjectBusinessContext(
        tenant_id=tenant_id,
        project_id=project.id,
        ai_context_enabled=True,
        version=0,
    )
    session.add(context)
    await session.flush()
    return project


async def _seed_minimal_graph(session, tenant_id, user_id, project):
    project_node = AIProjectGraphNode(
        tenant_id=tenant_id,
        project_id=project.id,
        node_type="project",
        source_type="project",
        source_id=project.id,
        name=project.name,
        properties={"project_id": project.id},
        is_active=True,
        created_by=user_id,
    )
    metric_node = AIProjectGraphNode(
        tenant_id=tenant_id,
        project_id=project.id,
        node_type="metric",
        source_type="metric",
        source_id=1,
        name="KPI 1",
        is_active=True,
        created_by=user_id,
    )
    risk_node = AIProjectGraphNode(
        tenant_id=tenant_id,
        project_id=project.id,
        node_type="risk",
        source_type="risk",
        source_id=1,
        name="Risk 1",
        is_active=True,
        created_by=user_id,
    )
    session.add_all([project_node, metric_node, risk_node])
    await session.flush()

    session.add_all(
        [
            AIProjectGraphEdge(
                tenant_id=tenant_id,
                project_id=project.id,
                from_node_id=project_node.id,
                to_node_id=metric_node.id,
                relationship_type="measures",
                is_active=True,
                created_by=user_id,
            ),
            AIProjectGraphEdge(
                tenant_id=tenant_id,
                project_id=project.id,
                from_node_id=project_node.id,
                to_node_id=risk_node.id,
                relationship_type="threatens",
                is_active=True,
                created_by=user_id,
            ),
        ]
    )
    await session.flush()
    return project_node, metric_node, risk_node


async def test_health_check_unavailable_without_graph(db_session):
    tenant_id = 1
    user_id = 1
    project = await _project(db_session, tenant_id, user_id, "health")
    health = KnowledgeGraphHealthService(db_session)
    hc = await health.run_health_check(project.id, check_type="on_demand")
    assert hc.status == "unavailable"
    assert hc.errors == ["No active knowledge graph version"]


async def test_health_check_healthy_after_build(db_session):
    tenant_id = 1
    user_id = 1
    project = await _project(db_session, tenant_id, user_id, "healthy")
    await _seed_minimal_graph(db_session, tenant_id, user_id, project)

    manager = _manager(db_session, tenant_id, user_id)
    build, _ = await manager.request_full_rebuild(project.id)
    await manager.run_full_rebuild(build.id)
    await db_session.commit()

    health = KnowledgeGraphHealthService(db_session)
    hc = await health.run_health_check(project.id, check_type="on_demand")
    assert hc.status == "healthy"
    assert hc.node_count > 0


async def test_health_check_source_drift_marks_stale(db_session):
    tenant_id = 1
    user_id = 1
    project = await _project(db_session, tenant_id, user_id, "drift")
    await _seed_minimal_graph(db_session, tenant_id, user_id, project)

    manager = _manager(db_session, tenant_id, user_id)
    build, _ = await manager.request_full_rebuild(project.id)
    await manager.run_full_rebuild(build.id)
    await db_session.commit()

    # Simulate a source fingerprint drift on the active version.
    graph = await manager.ensure_graph(project.id)
    version = await db_session.get(KnowledgeGraphVersion, graph.active_version_id)
    version.source_fingerprint = "stale-fingerprint"
    await db_session.commit()

    health = KnowledgeGraphHealthService(db_session)
    hc = await health.run_health_check(project.id, check_type="on_demand")
    assert hc.status == "stale"
    assert hc.warnings and any("fingerprint drift" in w for w in hc.warnings)
