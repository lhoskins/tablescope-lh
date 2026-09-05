"""KG-20: obsolete authoritative guidance must never silently outrank the
current standard. ``ReferenceDocument`` already had ``superseded_by_id`` and
``status``, but ``collect_structural_graph`` only filtered on ``status`` --
a document whose successor was recorded but whose own status was never
flipped to "superseded" (a process gap, not a missing column) would still
show as an active, authoritative source alongside its replacement. A new
``expiration_date`` column closes the other half: a version can now stop
being authoritative on a known date with no successor recorded at all.

Run from `platform-api`: `pytest -q tests/test_kg20_versioned_references.py`.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.models.project import Project
from app.models.reference_library import TIER_PROJECT, ReferenceDocument
from app.services.knowledge_graph_context.collectors import collect_structural_graph

pytestmark = pytest.mark.anyio


async def _seed_project(db_session, *, tenant_id: int = 1) -> int:
    project = Project(tenant_id=tenant_id, owner_id=1, name="Versioned Refs Project", is_shared=False)
    db_session.add(project)
    await db_session.flush()
    return project.id


def _titles(nodes: list[dict]) -> set[str]:
    return {n["name"] for n in nodes if n["source_type"] == "reference_document"}


async def test_document_with_a_recorded_successor_is_excluded_even_if_its_own_status_is_stale(
    db_session,
):
    tenant_id = 1201
    project_id = await _seed_project(db_session, tenant_id=tenant_id)

    new_version = ReferenceDocument(
        tier=TIER_PROJECT, project_id=project_id, tenant_id=tenant_id,
        title="CAPA Procedure v2", status="active",
    )
    db_session.add(new_version)
    await db_session.flush()

    # The old version's own status was never flipped -- still "active" -- but
    # it now points at the document that replaced it.
    old_version = ReferenceDocument(
        tier=TIER_PROJECT, project_id=project_id, tenant_id=tenant_id,
        title="CAPA Procedure v1", status="active",
        superseded_by_id=new_version.id,
    )
    db_session.add(old_version)
    await db_session.flush()

    nodes, _edges, _hub_key = await collect_structural_graph(
        db_session, tenant_id=tenant_id, project_id=project_id,
    )
    titles = _titles(nodes)
    assert "CAPA Procedure v2" in titles
    assert "CAPA Procedure v1" not in titles


async def test_expired_document_is_excluded(db_session):
    tenant_id = 1202
    project_id = await _seed_project(db_session, tenant_id=tenant_id)

    db_session.add(
        ReferenceDocument(
            tier=TIER_PROJECT, project_id=project_id, tenant_id=tenant_id,
            title="Expired Policy", status="active",
            expiration_date=date.today() - timedelta(days=1),
        )
    )
    await db_session.flush()

    nodes, _edges, _hub_key = await collect_structural_graph(
        db_session, tenant_id=tenant_id, project_id=project_id,
    )
    assert "Expired Policy" not in _titles(nodes)


async def test_document_expiring_in_the_future_is_still_included(db_session):
    tenant_id = 1203
    project_id = await _seed_project(db_session, tenant_id=tenant_id)

    db_session.add(
        ReferenceDocument(
            tier=TIER_PROJECT, project_id=project_id, tenant_id=tenant_id,
            title="Current Policy", status="active",
            expiration_date=date.today() + timedelta(days=365),
        )
    )
    await db_session.flush()

    nodes, _edges, _hub_key = await collect_structural_graph(
        db_session, tenant_id=tenant_id, project_id=project_id,
    )
    assert "Current Policy" in _titles(nodes)


async def test_document_with_no_expiration_is_still_included(db_session):
    tenant_id = 1204
    project_id = await _seed_project(db_session, tenant_id=tenant_id)

    db_session.add(
        ReferenceDocument(
            tier=TIER_PROJECT, project_id=project_id, tenant_id=tenant_id,
            title="Evergreen Policy", status="active",
        )
    )
    await db_session.flush()

    nodes, _edges, _hub_key = await collect_structural_graph(
        db_session, tenant_id=tenant_id, project_id=project_id,
    )
    assert "Evergreen Policy" in _titles(nodes)
