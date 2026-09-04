"""KG-07: every Knowledge Graph context collection used to generate an
AI-powered answer must leave an audit trail an administrator can use to
reconstruct exactly what evidence informed it.

Exercises ``collect_knowledge_graph_ai_context`` directly against a real DB
session (not the stubbed loader used by test_knowledge_graph_ai_context.py)
so the resulting ``KnowledgeGraphEvidenceAccess`` row can be inspected.

Run from ``platform-api``: ``pytest -q tests/test_kg07_evidence_audit.py``.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models.ai_project_graph import AIProjectGraphEdge, AIProjectGraphNode
from app.models.knowledge_graph_evidence_access import KnowledgeGraphEvidenceAccess
from app.models.knowledge_graph_lifecycle import KnowledgeGraph, KnowledgeGraphVersion
from app.models.project import Project
from app.services.knowledge_graph_ai_context import collect_knowledge_graph_ai_context

pytestmark = pytest.mark.anyio


async def _seed_project(db_session, *, tenant_id: int = 1) -> int:
    project = Project(tenant_id=tenant_id, owner_id=1, name="Boeing Supplier QA")
    db_session.add(project)
    await db_session.flush()
    return project.id


async def _seed_active_kg_version(db_session, *, tenant_id: int, project_id: int) -> int:
    graph = KnowledgeGraph(tenant_id=tenant_id, project_id=project_id, lifecycle_status="active")
    db_session.add(graph)
    await db_session.flush()
    version = KnowledgeGraphVersion(
        graph_id=graph.id, tenant_id=tenant_id, project_id=project_id,
        version_number=1, status="active",
    )
    db_session.add(version)
    await db_session.flush()
    graph.active_version_id = version.id
    await db_session.flush()
    return version.id


async def _seed_graph(db_session, *, tenant_id: int, project_id: int) -> tuple[int, int]:
    """One risk node governed by a document, measured by a saved query."""
    risk = AIProjectGraphNode(
        tenant_id=tenant_id, project_id=project_id, node_type="risk",
        name="Overdue CAPAs", created_by=1, is_active=True,
        properties={"confidence": 0.9, "summary": "CAPA closures slipping."},
    )
    doc = AIProjectGraphNode(
        tenant_id=tenant_id, project_id=project_id, node_type="policy",
        name="Quality Manual", source_type="project_asset", source_id=555,
        created_by=1, is_active=True, properties={"confidence": 0.9},
    )
    query = AIProjectGraphNode(
        tenant_id=tenant_id, project_id=project_id, node_type="saved_query",
        name="Open CAPAs", source_type="saved_query", source_id=777,
        created_by=1, is_active=True, properties={"confidence": 0.9},
    )
    kpi = AIProjectGraphNode(
        tenant_id=tenant_id, project_id=project_id, node_type="kpi",
        name="On-time Closure", created_by=1, is_active=True,
        properties={"confidence": 0.9},
    )
    db_session.add_all([risk, doc, query, kpi])
    await db_session.flush()
    db_session.add_all([
        AIProjectGraphEdge(
            tenant_id=tenant_id, project_id=project_id,
            from_node_id=doc.id, to_node_id=risk.id,
            relationship_type="governs", confidence=0.9, is_active=True,
            created_by=1,
        ),
        # query "measures" kpi -- the lineage shape collect_knowledge_graph_ai_context
        # actually recognizes (see knowledge_graph_ai_context.py's query_lineage loop).
        AIProjectGraphEdge(
            tenant_id=tenant_id, project_id=project_id,
            from_node_id=query.id, to_node_id=kpi.id,
            relationship_type="measures", confidence=0.9, is_active=True,
            created_by=1,
        ),
    ])
    await db_session.flush()
    return doc.source_id, query.source_id


async def test_collecting_context_writes_an_evidence_access_row(db_session):
    tenant_id = 1
    project_id = await _seed_project(db_session, tenant_id=tenant_id)
    kg_version_id = await _seed_active_kg_version(
        db_session, tenant_id=tenant_id, project_id=project_id,
    )
    doc_source_id, query_source_id = await _seed_graph(
        db_session, tenant_id=tenant_id, project_id=project_id,
    )

    await collect_knowledge_graph_ai_context(
        db_session, tenant_id=tenant_id, project_id=project_id, user_id=42,
        surface="business_insights",
    )
    await db_session.flush()

    rows = (
        await db_session.scalars(
            select(KnowledgeGraphEvidenceAccess).where(
                KnowledgeGraphEvidenceAccess.project_id == project_id,
            )
        )
    ).all()
    assert len(rows) == 1
    row = rows[0]
    assert row.tenant_id == tenant_id
    assert row.user_id == 42
    assert row.surface == "business_insights"
    assert row.kg_version_id == kg_version_id
    assert doc_source_id in row.document_ids
    assert query_source_id in row.query_ids
    assert len(row.node_ids) >= 1


async def test_different_surfaces_are_recorded_separately(db_session):
    tenant_id = 1
    project_id = await _seed_project(db_session, tenant_id=tenant_id)
    await _seed_graph(db_session, tenant_id=tenant_id, project_id=project_id)

    await collect_knowledge_graph_ai_context(
        db_session, tenant_id=tenant_id, project_id=project_id, user_id=1,
        surface="dashboard_generation",
    )
    await collect_knowledge_graph_ai_context(
        db_session, tenant_id=tenant_id, project_id=project_id, user_id=1,
        surface="query_generation",
    )
    await db_session.flush()

    rows = (
        await db_session.scalars(
            select(KnowledgeGraphEvidenceAccess).where(
                KnowledgeGraphEvidenceAccess.project_id == project_id,
            )
        )
    ).all()
    surfaces = {r.surface for r in rows}
    assert surfaces == {"dashboard_generation", "query_generation"}


async def test_empty_graph_writes_no_audit_row(db_session):
    """An empty/no-evidence context is a no-op, not an empty audit row."""
    tenant_id = 1
    project_id = await _seed_project(db_session, tenant_id=tenant_id)

    await collect_knowledge_graph_ai_context(
        db_session, tenant_id=tenant_id, project_id=project_id, user_id=1,
        surface="business_insights",
    )
    await db_session.flush()

    rows = (
        await db_session.scalars(
            select(KnowledgeGraphEvidenceAccess).where(
                KnowledgeGraphEvidenceAccess.project_id == project_id,
            )
        )
    ).all()
    assert rows == []


async def test_external_response_schema_is_unchanged_by_the_audit_ids(db_session):
    """The internal _id/_ids tags used for auditing must never leak into the
    context block handed to the AI server."""
    tenant_id = 1
    project_id = await _seed_project(db_session, tenant_id=tenant_id)
    await _seed_graph(db_session, tenant_id=tenant_id, project_id=project_id)

    context = await collect_knowledge_graph_ai_context(
        db_session, tenant_id=tenant_id, project_id=project_id, user_id=1,
        surface="business_insights",
    )
    for bucket in ("risks", "governing_documents"):
        for item in context.get(bucket, []):
            assert "_id" not in item
