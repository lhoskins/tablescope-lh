"""KG-16: the knowledge graph must surface chunk/passage-level evidence for
project-asset documents that have already been chunked by the
document-processing pipeline (``ai_document_chunks``/``ai_documents``),
not only a single document-level node. A claim grounded in one paragraph of
a 50-page document should be traceable to that passage, not "somewhere in
this document."

``ai_documents``/``ai_document_chunks`` have no ORM model (see
``app.services.ai_grounding``, which queries them the same raw-SQL way), so
the test DB's ``Base.metadata.create_all`` never creates them -- the
fixture below creates minimal versions directly, mirroring the pattern
already used in ``tests/test_project_insight_rebuild.py``.

Run from `platform-api`: `pytest -q tests/test_kg16_document_passages.py`.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.models.project import Project
from app.models.project_asset import ProjectAsset
from app.services.knowledge_graph_context.collectors import (
    _MAX_PASSAGES_PER_DOCUMENT,
    collect_structural_graph,
)
from app.services.knowledge_graph_context.graph_primitives import _REL_HAS_PASSAGE

pytestmark = pytest.mark.anyio


@pytest_asyncio.fixture
async def ai_chunk_tables(db_session):
    await db_session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS ai_documents (
                id INTEGER PRIMARY KEY,
                source_type TEXT,
                source_id INTEGER
            )
            """
        )
    )
    await db_session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS ai_document_chunks (
                id INTEGER PRIMARY KEY,
                tenant_id INTEGER,
                project_id INTEGER,
                document_id INTEGER,
                chunk_index INTEGER,
                chunk_text TEXT
            )
            """
        )
    )
    await db_session.commit()


async def _seed_project(db_session, *, tenant_id: int) -> int:
    project = Project(tenant_id=tenant_id, owner_id=1, name="Passage Project", is_shared=False)
    db_session.add(project)
    await db_session.flush()
    return project.id


async def _seed_asset(db_session, *, tenant_id: int, project_id: int, title: str) -> int:
    asset = ProjectAsset(
        tenant_id=tenant_id, project_id=project_id, created_by=1,
        asset_type="pdf", source_type="uploaded_file", title=title, filename=f"{title}.pdf",
        original_filename=f"{title}.pdf", storage_provider="local",
        storage_location=f"/tmp/{title}.pdf", status="uploaded",
    )
    db_session.add(asset)
    await db_session.flush()
    return asset.id


async def _seed_document(db_session, *, asset_id: int) -> int:
    result = await db_session.execute(
        text("INSERT INTO ai_documents (source_type, source_id) VALUES ('project_asset', :sid)"),
        {"sid": asset_id},
    )
    await db_session.commit()
    return result.lastrowid


async def _seed_chunks(
    db_session, *, tenant_id: int, project_id: int, document_id: int, count: int,
) -> None:
    for i in range(count):
        await db_session.execute(
            text(
                """
                INSERT INTO ai_document_chunks
                    (tenant_id, project_id, document_id, chunk_index, chunk_text)
                VALUES (:tenant_id, :project_id, :document_id, :idx, :text)
                """
            ),
            {
                "tenant_id": tenant_id, "project_id": project_id,
                "document_id": document_id, "idx": i, "text": f"chunk {i} text",
            },
        )
    await db_session.commit()


async def test_document_chunks_produce_passage_nodes_and_has_passage_edges(
    db_session, ai_chunk_tables,
):
    tenant_id = 1601
    project_id = await _seed_project(db_session, tenant_id=tenant_id)
    asset_id = await _seed_asset(db_session, tenant_id=tenant_id, project_id=project_id, title="Handbook")
    document_id = await _seed_document(db_session, asset_id=asset_id)
    await _seed_chunks(db_session, tenant_id=tenant_id, project_id=project_id, document_id=document_id, count=2)

    nodes, edges, _hub_key = await collect_structural_graph(
        db_session, tenant_id=tenant_id, project_id=project_id,
    )
    passage_nodes = [n for n in nodes if n["source_type"] == "ai_document_chunk"]
    assert len(passage_nodes) == 2

    passage_edges = [e for e in edges if e["relationship_type"] == _REL_HAS_PASSAGE]
    assert len(passage_edges) == 2
    for e in passage_edges:
        assert e["from_node_id"] == f"s:asset:{asset_id}"


async def test_document_with_no_chunks_produces_no_passage_nodes(db_session, ai_chunk_tables):
    tenant_id = 1602
    project_id = await _seed_project(db_session, tenant_id=tenant_id)
    await _seed_asset(db_session, tenant_id=tenant_id, project_id=project_id, title="Unchunked")

    nodes, edges, _hub_key = await collect_structural_graph(
        db_session, tenant_id=tenant_id, project_id=project_id,
    )
    assert [n for n in nodes if n["source_type"] == "ai_document_chunk"] == []
    assert [e for e in edges if e["relationship_type"] == _REL_HAS_PASSAGE] == []


async def test_passages_beyond_the_per_document_cap_are_truncated(db_session, ai_chunk_tables):
    tenant_id = 1603
    project_id = await _seed_project(db_session, tenant_id=tenant_id)
    asset_id = await _seed_asset(db_session, tenant_id=tenant_id, project_id=project_id, title="Long Doc")
    document_id = await _seed_document(db_session, asset_id=asset_id)
    await _seed_chunks(
        db_session, tenant_id=tenant_id, project_id=project_id, document_id=document_id,
        count=_MAX_PASSAGES_PER_DOCUMENT + 5,
    )

    nodes, _edges, _hub_key = await collect_structural_graph(
        db_session, tenant_id=tenant_id, project_id=project_id,
    )
    passage_nodes = [n for n in nodes if n["source_type"] == "ai_document_chunk"]
    assert len(passage_nodes) == _MAX_PASSAGES_PER_DOCUMENT


async def test_chunks_from_another_tenant_or_project_are_excluded(db_session, ai_chunk_tables):
    tenant_id = 1604
    project_id = await _seed_project(db_session, tenant_id=tenant_id)
    asset_id = await _seed_asset(db_session, tenant_id=tenant_id, project_id=project_id, title="Doc")
    document_id = await _seed_document(db_session, asset_id=asset_id)
    # Chunk rows carrying the wrong tenant/project must never surface here,
    # even though they point at the same ai_documents row via document_id.
    await _seed_chunks(
        db_session, tenant_id=tenant_id + 1, project_id=project_id,
        document_id=document_id, count=1,
    )
    await _seed_chunks(
        db_session, tenant_id=tenant_id, project_id=project_id + 1,
        document_id=document_id, count=1,
    )

    nodes, _edges, _hub_key = await collect_structural_graph(
        db_session, tenant_id=tenant_id, project_id=project_id,
    )
    assert [n for n in nodes if n["source_type"] == "ai_document_chunk"] == []
