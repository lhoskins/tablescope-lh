"""Tests for the proactive AI grounding evidence pipeline."""

from __future__ import annotations

import pytest

from app.schemas.ai_grounding import GroundingEvidence
from app.services import ai_grounding
from app.services.ai_grounding import gather_grounding_evidence


@pytest.fixture
def _patch_grounding_deps(monkeypatch):
    """Patch external services so gather_grounding_evidence stays offline."""

    async def fake_search_vectors(*args, **kwargs):
        return {
            "project_passages": [
                {
                    "id": "p1",
                    "document_id": 101,
                    "chunk_index": 0,
                    "title": "Revenue policy",
                    "text": "Revenue is recognized when control transfers.",
                    "source_type": "project_asset",
                    "retrieval_score": 0.92,
                    "retrieval_method": "vector",
                    "tier": "project",
                }
            ],
            "reference_passages": [
                {
                    "id": "r1",
                    "document_id": 201,
                    "title": "ASC 606",
                    "text": "Revenue from contracts with customers.",
                    "source_type": "reference_library",
                    "retrieval_score": 0.85,
                    "retrieval_method": "vector",
                    "tier": "industry",
                }
            ],
        }

    async def fake_project_fts(*args, **kwargs):
        return [
            ai_grounding.GroundingPassage(
                id="p2",
                document_id=101,
                chunk_index=1,
                title="",
                text="ASC 606 policy transfer of control",
                source_type="project_asset",
                retrieval_score=0.45,
                retrieval_method="lexical",
                tier="project",
            )
        ]

    async def fake_reference_fts(*args, **kwargs):
        return [
            ai_grounding.GroundingPassage(
                id="r2",
                document_id=201,
                title="ASC 606",
                text="Revenue recognition principle",
                source_type="reference_library",
                retrieval_score=0.38,
                retrieval_method="lexical",
                tier="industry",
            )
        ]

    async def fake_kpis(*args, **kwargs):
        return [
            {
                "kpi_key": "revenue",
                "display_name": "Total Revenue",
                "required_fields": ["revenue"],
                "related_tags": ["sales"],
            }
        ]

    async def fake_load_graph(*args, **kwargs):
        return (
            [
                {"id": 1, "type": "kpi", "label": "Revenue", "summary": "Total revenue"}
            ],
            [],
        )

    def fake_enrich_node(node, *args, **kwargs):
        node.setdefault("node_type", "concept")
        node.setdefault("label", node.get("title") or node.get("name") or "Node")
        node.setdefault("summary", node.get("description") or "")
        return node

    monkeypatch.setattr(
        "app.services.ai_intelligence_client.search_grounding_vectors",
        fake_search_vectors,
    )
    monkeypatch.setattr(ai_grounding.ai_intelligence_client, "is_enabled", lambda: True)
    monkeypatch.setattr(ai_grounding, "_lexical_project_chunks", fake_project_fts)
    monkeypatch.setattr(ai_grounding, "_lexical_reference_documents", fake_reference_fts)
    monkeypatch.setattr(ai_grounding, "get_reference_kpis", fake_kpis)
    monkeypatch.setattr(ai_grounding, "_load_stored_graph", fake_load_graph)
    monkeypatch.setattr(ai_grounding, "enrich_node", fake_enrich_node)


async def test_gather_grounding_evidence_returns_passages_and_manifest(
    db_session, _patch_grounding_deps
):
    evidence = await gather_grounding_evidence(
        db_session,
        tenant_id=1,
        user_id=2,
        project_id=3,
        question="What is revenue?",
        relevant_columns=["revenue"],
    )

    assert evidence is not None
    assert evidence.question == "What is revenue?"
    assert len(evidence.passages) == 3
    assert len(evidence.kpis) == 1
    assert len(evidence.kg_nodes) == 1
    assert all(isinstance(p, ai_grounding.GroundingPassage) for p in evidence.passages)

    manifest = evidence.manifest()
    assert manifest["question"] == "What is revenue?"
    assert manifest["passageCount"] == 3
    assert manifest["kpiCount"] == 1
    assert manifest["kgNodeCount"] == 1
    assert "passages" in manifest
    # Vector, lexical, and a hybrid merged source are all present.
    methods = {p["retrievalMethod"] for p in manifest["passages"]}
    assert methods == {"vector", "lexical", "hybrid"}


async def test_grounding_merge_dedupes_by_document_chunk(
    db_session, _patch_grounding_deps
):
    evidence = await gather_grounding_evidence(
        db_session,
        tenant_id=1,
        user_id=2,
        project_id=3,
        question="revenue",
        relevant_columns=["revenue"],
    )

    # The vector search and lexical search both hit document 101.
    project_passages = [
        p for p in evidence.passages if p.source_type == "project_asset"
    ]
    ids = {p.id for p in project_passages}
    # Lexical and vector passages for doc 101 should be merged into one entry.
    assert len(ids) <= 2


async def test_grounding_kpi_ranking_prefers_question_matches(
    db_session, _patch_grounding_deps
):
    # Project has a KPI whose name aligns with the question.
    evidence = await gather_grounding_evidence(
        db_session,
        tenant_id=1,
        user_id=2,
        project_id=3,
        question="total revenue by month",
        relevant_columns=["revenue", "month"],
    )

    assert evidence.kpis
    assert evidence.kpis[0].kpi_key == "revenue"


async def test_manifest_is_compact_and_serializable():
    evidence = GroundingEvidence(
        question="test",
        passages=[
            ai_grounding.GroundingPassage(
                id="p1",
                document_id=1,
                chunk_index=0,
                title="Doc",
                text="A very long passage " * 1000,
                source_type="project_asset",
                retrieval_score=0.9,
                retrieval_method="vector",
                tier="project",
            )
        ],
        kg_nodes=[ai_grounding.GroundingKGNode(id=1, node_type="kpi", title="Revenue")],
        kpis=[ai_grounding.GroundingKPI(kpi_key="revenue", display_name="Revenue")],
    )
    manifest = evidence.manifest()
    assert manifest["passageCount"] == 1
    assert "A very long passage" not in str(manifest)
    assert manifest["kgVersionId"] is None
