"""KG-24: ``create_family_relationship_edges`` is the sole write path where
a free-form, LLM-supplied ``target_type`` string reaches
``ai_project_graph_nodes`` with no prior type-appropriateness check. A
target_type of "dashboard" (or any other reserved structural type) must
not be allowed to create a same-named node with no real source_id/
source_type backing it -- that node would be indistinguishable from, and
could graph_key-collide with, the real structural node for this project.

Run from ``platform-api``:
``pytest -q tests/test_kg24_reserved_type_coercion.py``.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import text

from app.services import project_graph_service as svc

T1, P1, U1 = 1, 10, 100


async def _make_document_node(session, tenant_id, project_id, name, *, source_id=None):
    res = await session.execute(
        text(
            """
            INSERT INTO ai_project_graph_nodes
                (tenant_id, project_id, node_type, source_type, source_id, name,
                 properties, visibility, is_active, created_by)
            VALUES (:tid, :pid, 'document', 'project_asset', :sid, :nm,
                    :props, 'shared_project', true, :uid)
            RETURNING id
            """
        ),
        {
            "tid": tenant_id, "pid": project_id, "sid": source_id, "nm": name,
            "props": json.dumps({"summary": f"summary for {name}"}), "uid": U1,
        },
    )
    return res.fetchone()[0]


def _profile_with_target_type(target_type: str):
    return {
        "business_domain": "it",
        "document_family": {
            "family_name": "Reserved Type Test",
            "family_type": "incident_case",
            "role": "postmortem",
            "reason": "test",
            "confidence": 0.95,
        },
        "family_relationships": [
            {"relationship_type": "governs", "target_name": "Suspicious Target",
             "target_type": target_type, "confidence": 0.9},
        ],
    }


@pytest.mark.asyncio
async def test_a_reserved_structural_target_type_is_coerced_to_process(db_session):
    doc = await _make_document_node(db_session, T1, P1, "postmortem.pdf", source_id=6)
    await svc.apply_document_family(
        db_session, T1, P1, document_node_id=doc, asset_id=6,
        profile=_profile_with_target_type("dashboard"), created_by=U1,
    )
    res = await db_session.execute(
        text(
            """
            SELECT node_type, source_type, source_id FROM ai_project_graph_nodes
            WHERE tenant_id=:t AND project_id=:p AND name='Suspicious Target'
            """
        ),
        {"t": T1, "p": P1},
    )
    row = res.fetchone()
    assert row is not None
    node_type, source_type, source_id = row
    assert node_type == "process"
    assert source_type is None
    assert source_id is None


@pytest.mark.asyncio
async def test_a_non_reserved_target_type_passes_through_unchanged(db_session):
    doc = await _make_document_node(db_session, T1, P1, "postmortem2.pdf", source_id=7)
    await svc.apply_document_family(
        db_session, T1, P1, document_node_id=doc, asset_id=7,
        profile=_profile_with_target_type("supplier"), created_by=U1,
    )
    res = await db_session.execute(
        text(
            """
            SELECT node_type FROM ai_project_graph_nodes
            WHERE tenant_id=:t AND project_id=:p AND name='Suspicious Target'
            """
        ),
        {"t": T1, "p": P1},
    )
    assert res.scalar() == "supplier"
