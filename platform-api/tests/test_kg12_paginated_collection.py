"""KG-12: structural graph collection must index every matching row for a
project, not silently and permanently drop everything past the first
``_MAX_PER_KIND`` (40). That cap now serves only as the per-round-trip
batch size for keyset pagination (``_fetch_all_in_batches``); a safety
ceiling (``_MAX_TOTAL_PER_KIND``) still guards against a genuinely
pathological project.

Run from `platform-api`: `pytest -q tests/test_kg12_paginated_collection.py`.
"""

from __future__ import annotations

import pytest

from app.models.file_source_meta import FileSourceMeta
from app.models.project import Project
from app.models.reference_library import TIER_PROJECT, ReferenceDocument
from app.services.knowledge_graph_context.collectors import (
    _fetch_all_in_batches,
    collect_structural_graph,
)
from app.services.knowledge_graph_context.graph_primitives import _MAX_PER_KIND

pytestmark = pytest.mark.anyio


async def _seed_project(db_session, *, tenant_id: int = 1) -> int:
    project = Project(tenant_id=tenant_id, owner_id=1, name="Large Project", is_shared=False)
    db_session.add(project)
    await db_session.flush()
    return project.id


async def test_file_sources_beyond_max_per_kind_are_all_still_included(db_session):
    tenant_id = 1101
    project_id = await _seed_project(db_session, tenant_id=tenant_id)
    count = _MAX_PER_KIND + 5

    db_session.add_all([
        FileSourceMeta(
            tenant_id=tenant_id, owner_id=1, project_id=project_id,
            view_name=f"table_{i}", file_name=f"file_{i}.csv", archived=False,
        )
        for i in range(count)
    ])
    await db_session.flush()

    nodes, _edges, _hub_key = await collect_structural_graph(
        db_session, tenant_id=tenant_id, project_id=project_id,
    )
    file_nodes = [n for n in nodes if n["source_type"] == "file_source"]
    assert len(file_nodes) == count


async def test_reference_documents_beyond_max_per_kind_are_all_still_included(db_session):
    tenant_id = 1102
    project_id = await _seed_project(db_session, tenant_id=tenant_id)
    count = _MAX_PER_KIND + 5

    db_session.add_all([
        ReferenceDocument(
            tier=TIER_PROJECT, project_id=project_id, tenant_id=tenant_id,
            title=f"Project Procedure {i}", status="active",
        )
        for i in range(count)
    ])
    await db_session.flush()

    nodes, _edges, _hub_key = await collect_structural_graph(
        db_session, tenant_id=tenant_id, project_id=project_id,
    )
    ref_nodes = [n for n in nodes if n["source_type"] == "reference_document"]
    assert len(ref_nodes) == count


async def test_fetch_all_in_batches_respects_the_safety_ceiling(db_session):
    tenant_id = 1103
    project_id = await _seed_project(db_session, tenant_id=tenant_id)

    db_session.add_all([
        FileSourceMeta(
            tenant_id=tenant_id, owner_id=1, project_id=project_id,
            view_name=f"ceiling_table_{i}", file_name=f"ceiling_{i}.csv", archived=False,
        )
        for i in range(20)
    ])
    await db_session.flush()

    rows = await _fetch_all_in_batches(
        db_session, FileSourceMeta,
        FileSourceMeta.project_id == project_id,
        FileSourceMeta.tenant_id == tenant_id,
        batch_size=5, max_total=10,
    )
    assert len(rows) == 10
