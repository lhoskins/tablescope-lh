"""Tests for the document-family knowledge-graph service (Phase 15).

Exercises the family threshold rules, dedup, edge lifecycle, member rollups,
and tenant/project isolation directly against the ``project_graph_service``
using an in-memory SQLite database.
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


def _profile(family_name, confidence, *, family_type="incident_case", role="postmortem",
             business_domain="it", relationships=None):
    return {
        "business_domain": business_domain,
        "document_family": {
            "family_name": family_name,
            "family_type": family_type,
            "role": role,
            "reason": "test",
            "confidence": confidence,
        },
        "family_relationships": relationships or [],
    }


async def _active_family_count(session, tenant_id, project_id):
    res = await session.execute(
        text(
            """
            SELECT COUNT(*) FROM ai_project_graph_nodes
            WHERE tenant_id=:t AND project_id=:p
              AND node_type='document_family' AND is_active=true
            """
        ),
        {"t": tenant_id, "p": project_id},
    )
    return int(res.scalar() or 0)


async def _belongs_edge_count(session, tenant_id, project_id):
    res = await session.execute(
        text(
            """
            SELECT COUNT(*) FROM ai_project_graph_edges
            WHERE tenant_id=:t AND project_id=:p
              AND relationship_type='belongs_to_family' AND is_active=true
            """
        ),
        {"t": tenant_id, "p": project_id},
    )
    return int(res.scalar() or 0)


def test_normalize_family_key():
    assert svc.normalize_family_key("IT Change Management") == "it_change_management"
    assert svc.normalize_family_key("  CloudAuth / Outage! ") == "cloudauth_outage"
    assert svc.normalize_family_key("") == ""


@pytest.mark.asyncio
async def test_auto_link_high_confidence(db_session):
    doc = await _make_document_node(db_session, T1, P1, "postmortem.pdf", source_id=1)
    result = await svc.apply_document_family(
        db_session, T1, P1, document_node_id=doc, asset_id=1,
        profile=_profile("CloudAuth Incident", 0.95), created_by=U1,
    )
    assert result is not None
    assert result["status"] == "auto_linked"
    assert await _active_family_count(db_session, T1, P1) == 1
    assert await _belongs_edge_count(db_session, T1, P1) == 1


@pytest.mark.asyncio
async def test_suggest_mid_confidence_creates_no_edge(db_session):
    doc = await _make_document_node(db_session, T1, P1, "review.pptx", source_id=2)
    result = await svc.apply_document_family(
        db_session, T1, P1, document_node_id=doc, asset_id=2,
        profile=_profile("Ops Review", 0.80), created_by=U1,
    )
    assert result is not None
    assert result["status"] == "suggested"
    assert await _active_family_count(db_session, T1, P1) == 0
    assert await _belongs_edge_count(db_session, T1, P1) == 0


@pytest.mark.asyncio
async def test_ignore_low_confidence(db_session):
    doc = await _make_document_node(db_session, T1, P1, "misc.txt", source_id=3)
    result = await svc.apply_document_family(
        db_session, T1, P1, document_node_id=doc, asset_id=3,
        profile=_profile("Weak Group", 0.40), created_by=U1,
    )
    assert result is None
    assert await _active_family_count(db_session, T1, P1) == 0
    assert await _belongs_edge_count(db_session, T1, P1) == 0


@pytest.mark.asyncio
async def test_no_duplicate_family_nodes(db_session):
    doc1 = await _make_document_node(db_session, T1, P1, "policy.docx", source_id=4)
    doc2 = await _make_document_node(db_session, T1, P1, "procedure.docx", source_id=5)
    await svc.apply_document_family(
        db_session, T1, P1, document_node_id=doc1, asset_id=4,
        profile=_profile("Change Management", 0.93), created_by=U1,
    )
    await svc.apply_document_family(
        db_session, T1, P1, document_node_id=doc2, asset_id=5,
        profile=_profile("Change Management", 0.91), created_by=U1,
    )
    # Two documents, same family name → exactly one family node, two edges.
    assert await _active_family_count(db_session, T1, P1) == 1
    assert await _belongs_edge_count(db_session, T1, P1) == 2


@pytest.mark.asyncio
async def test_relationship_edges_created(db_session):
    doc = await _make_document_node(db_session, T1, P1, "postmortem.pdf", source_id=6)
    profile = _profile(
        "CloudAuth Incident", 0.95,
        relationships=[
            {"relationship_type": "governs", "target_name": "Change Policy",
             "target_type": "document", "confidence": 0.9},
            {"relationship_type": "weird_unknown", "target_name": "Some Process",
             "target_type": "process", "confidence": 0.8},
        ],
    )
    await svc.apply_document_family(
        db_session, T1, P1, document_node_id=doc, asset_id=6,
        profile=profile, created_by=U1,
    )
    res = await db_session.execute(
        text(
            """
            SELECT relationship_type FROM ai_project_graph_edges
            WHERE tenant_id=:t AND project_id=:p AND from_node_id=:d
              AND relationship_type<>'belongs_to_family' AND is_active=true
            ORDER BY relationship_type
            """
        ),
        {"t": T1, "p": P1, "d": doc},
    )
    types = {r[0] for r in res.fetchall()}
    assert "governs" in types
    # Unknown relationship type falls back to related_family_member.
    assert "related_family_member" in types
    assert "weird_unknown" not in types


@pytest.mark.asyncio
async def test_members_rollup(db_session):
    doc = await _make_document_node(db_session, T1, P1, "procedure.docx", source_id=7)
    await svc.apply_document_family(
        db_session, T1, P1, document_node_id=doc, asset_id=7,
        profile=_profile("Patch Compliance", 0.95), created_by=U1,
    )
    fam_id = (
        await db_session.execute(
            text(
                "SELECT id FROM ai_project_graph_nodes "
                "WHERE node_type='document_family' AND project_id=:p"
            ),
            {"p": P1},
        )
    ).scalar()
    # Attach a datasource + kpi to the member document.
    ds_id = await svc._upsert_typed_node(
        db_session, T1, P1, U1, node_type="datasource", name="IT_Assets_Patch_Compliance",
    )
    kpi_id = await svc._upsert_typed_node(
        db_session, T1, P1, U1, node_type="kpi", name="patch_compliance_rate",
    )
    await svc._upsert_edge(
        db_session, T1, P1, U1, from_node_id=doc, to_node_id=ds_id,
        edge_type="related_to_datasource", confidence=0.9,
    )
    await svc._upsert_edge(
        db_session, T1, P1, U1, from_node_id=doc, to_node_id=kpi_id,
        edge_type="supports_kpi", confidence=0.9,
    )
    members = await svc.get_family_members(db_session, T1, P1, fam_id)
    assert len(members["documents"]) == 1
    assert any(m["name"] == "IT_Assets_Patch_Compliance" for m in members["datasources"])
    assert any(m["name"] == "patch_compliance_rate" for m in members["kpis"])


@pytest.mark.asyncio
async def test_delete_deactivates_and_archives(db_session):
    doc = await _make_document_node(db_session, T1, P1, "only.docx", source_id=8)
    await svc.apply_document_family(
        db_session, T1, P1, document_node_id=doc, asset_id=8,
        profile=_profile("Solo Family", 0.95), created_by=U1,
    )
    assert await _active_family_count(db_session, T1, P1) == 1

    affected = await svc.deactivate_document_edges(db_session, T1, P1, doc)
    assert len(affected) == 1
    for fid in affected:
        archived = await svc.archive_empty_family(db_session, T1, P1, fid)
        assert archived is True
    assert await _active_family_count(db_session, T1, P1) == 0
    assert await _belongs_edge_count(db_session, T1, P1) == 0


@pytest.mark.asyncio
async def test_reprocess_moves_to_new_family(db_session):
    doc = await _make_document_node(db_session, T1, P1, "doc.docx", source_id=9)
    await svc.apply_document_family(
        db_session, T1, P1, document_node_id=doc, asset_id=9,
        profile=_profile("Family A", 0.95), created_by=U1,
    )
    await svc.apply_document_family(
        db_session, T1, P1, document_node_id=doc, asset_id=9,
        profile=_profile("Family B", 0.95), created_by=U1,
    )
    # Document now belongs to exactly one active family (Family B).
    assert await _belongs_edge_count(db_session, T1, P1) == 1
    res = await db_session.execute(
        text(
            """
            SELECT n.name FROM ai_project_graph_edges e
            JOIN ai_project_graph_nodes n ON n.id = e.to_node_id
            WHERE e.from_node_id=:d AND e.relationship_type='belongs_to_family'
              AND e.is_active=true
            """
        ),
        {"d": doc},
    )
    assert res.scalar() == "Family B"


@pytest.mark.asyncio
async def test_tenant_isolation(db_session):
    doc = await _make_document_node(db_session, T1, P1, "t1.docx", source_id=10)
    await svc.apply_document_family(
        db_session, T1, P1, document_node_id=doc, asset_id=10,
        profile=_profile("Tenant1 Family", 0.95), created_by=U1,
    )
    fam_id = (
        await db_session.execute(
            text("SELECT id FROM ai_project_graph_nodes WHERE node_type='document_family'"),
        )
    ).scalar()
    # Wrong tenant cannot read the family or its members.
    assert await svc.get_family_node(db_session, 999, P1, fam_id) is None
    members = await svc.get_family_members(db_session, 999, P1, fam_id)
    assert members["documents"] == []
    # Wrong project also isolated.
    assert await svc.get_family_node(db_session, T1, 999, fam_id) is None
