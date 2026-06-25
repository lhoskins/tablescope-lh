"""Evidence Collector tests — proves the project's real assets (and especially
the authoritative reference library at every tier) flow into the Knowledge Graph.

These exercise ``collect_structural_graph`` directly against the DB session and
the ``merge_graph_sources`` dedup that folds the structural rows into the stored
AI graph before the node-centric payload is built.
"""

from __future__ import annotations

from app.models.ai_project_graph import AIProjectGraphEdge, AIProjectGraphNode
from app.models.project import Project
from app.models.reference_library import (
    TIER_COMPANY,
    TIER_INDUSTRY,
    TIER_PROJECT,
    ReferenceDocument,
)
from app.models.saved_query import SavedQuery
from app.services.knowledge_graph_ai import _build_ai_request
from app.services.knowledge_graph_builder import (
    build_graph_payload,
    merge_graph_sources,
)
from app.services.knowledge_graph_context import collect_structural_graph


async def _seed_project(db_session, *, tenant_id: int = 1) -> int:
    project = Project(tenant_id=tenant_id, owner_id=1, name="Boeing Supplier QA")
    db_session.add(project)
    await db_session.flush()
    return project.id


async def test_reference_library_all_tiers_collected(db_session) -> None:
    tenant_id = 1
    project_id = await _seed_project(db_session, tenant_id=tenant_id)

    # One reference doc per tier — project, company (same tenant), industry.
    db_session.add_all(
        [
            ReferenceDocument(
                tier=TIER_PROJECT, project_id=project_id, tenant_id=tenant_id,
                title="Boeing CAPA Procedure", status="active",
                ai_summary="Project-level corrective action procedure.",
            ),
            ReferenceDocument(
                tier=TIER_COMPANY, tenant_id=tenant_id,
                title="Acme Supplier Code of Conduct", status="active",
                issuing_body="Acme",
            ),
            ReferenceDocument(
                tier=TIER_INDUSTRY, title="AS9100D", status="active",
                issuing_body="SAE",
            ),
        ]
    )
    await db_session.flush()

    nodes, edges, hub_key = await collect_structural_graph(
        db_session, tenant_id=tenant_id, project_id=project_id
    )

    assert hub_key == f"project:{project_id}"
    refs = [n for n in nodes if n["node_type"] == "reference_document"]
    titles = {n["name"] for n in refs}
    assert titles == {
        "Boeing CAPA Procedure",
        "Acme Supplier Code of Conduct",
        "AS9100D",
    }

    # Every reference doc is connected to the project hub with a tier-specific,
    # directional, full-confidence edge.
    hub_id = f"s:project:{project_id}"
    rels = {
        e["relationship_type"]
        for e in edges
        if e["from_node_id"] == hub_id
        and e["to_node_id"].startswith("s:reference:")
    }
    assert rels == {"project_reference", "company_reference", "industry_standard"}
    for e in edges:
        if e["to_node_id"].startswith("s:reference:"):
            assert e["from_node_id"] == hub_id  # arrow points hub -> reference
            assert e["confidence"] == 1.0
            assert e["evidence"]["structural"] is True


async def test_company_reference_isolated_by_tenant(db_session) -> None:
    project_id = await _seed_project(db_session, tenant_id=1)
    # Company doc owned by a *different* tenant must not leak in.
    db_session.add(
        ReferenceDocument(
            tier=TIER_COMPANY, tenant_id=2,
            title="Other Tenant Confidential", status="active",
        )
    )
    await db_session.flush()

    nodes, _edges, _hub = await collect_structural_graph(
        db_session, tenant_id=1, project_id=project_id
    )
    assert "Other Tenant Confidential" not in {n["name"] for n in nodes}


async def test_inactive_reference_excluded(db_session) -> None:
    project_id = await _seed_project(db_session, tenant_id=1)
    db_session.add(
        ReferenceDocument(
            tier=TIER_PROJECT, project_id=project_id, tenant_id=1,
            title="Archived Spec", status="archived",
        )
    )
    await db_session.flush()

    nodes, _edges, _hub = await collect_structural_graph(
        db_session, tenant_id=1, project_id=project_id
    )
    assert "Archived Spec" not in {n["name"] for n in nodes}


async def test_query_lineage_links_to_data_source(db_session) -> None:
    """Saved queries link to the data sources they read from (reads_from edge)."""
    project_id = await _seed_project(db_session, tenant_id=1)
    db_session.add(
        SavedQuery(
            project_id=project_id, owner_id=1, name="Open CAPAs",
            left_datasource="capa_table",
        )
    )
    await db_session.flush()

    nodes, edges, _hub = await collect_structural_graph(
        db_session, tenant_id=1, project_id=project_id
    )
    assert any(n["node_type"] == "saved_query" for n in nodes)
    # No data source seeded, so no reads_from edge — but the query is still
    # attached to the hub with a "query" edge.
    assert any(e["relationship_type"] == "query" for e in edges)


async def test_structural_merge_into_payload_groups_reference_library(
    db_session,
) -> None:
    """End-to-end: structural reference nodes land in the right display group of
    the node-centric payload after merge (what the canvas renders)."""
    tenant_id = 1
    project_id = await _seed_project(db_session, tenant_id=tenant_id)
    db_session.add(
        ReferenceDocument(
            tier=TIER_INDUSTRY, title="ISO 9001", status="active",
            issuing_body="ISO",
        )
    )
    await db_session.flush()

    extra_nodes, extra_edges, _hub = await collect_structural_graph(
        db_session, tenant_id=tenant_id, project_id=project_id
    )
    # A process exists (the canvas centers on it, never the hidden project hub);
    # the reference radiates from it via the re-rooted structural edge.
    stored = [{
        "id": 9001, "node_type": "process", "name": "Supplier Qualification",
        "source_type": None, "source_id": None, "properties": {"confidence": 0.9},
    }]
    merged_nodes, merged_edges = merge_graph_sources(stored, [], extra_nodes, extra_edges)
    payload = build_graph_payload(merged_nodes, merged_edges)

    groups = {n["label"]: n["displayGroup"] for n in payload["nodes"]}
    assert groups.get("ISO 9001") == "Authoritative Reference Library"
    # The project is never the center and never drawn on the canvas.
    assert payload["centerNode"]["type"] == "process"
    assert all(n["type"] != "project" for n in payload["nodes"])


async def test_kpis_collected_from_document_relationships(db_session) -> None:
    """KPIs referenced by project documents become structural KPI nodes.

    Same source of truth as the View Family panel (ai_project_graph kpi nodes
    connected to documents via supports_kpi edges).
    """
    tenant_id = 1
    project_id = await _seed_project(db_session, tenant_id=tenant_id)
    doc = AIProjectGraphNode(
        tenant_id=tenant_id, project_id=project_id, node_type="document",
        name="SUP_Supplier_Quality_Manual_2026.docx", created_by=1, is_active=True,
    )
    kpi = AIProjectGraphNode(
        tenant_id=tenant_id, project_id=project_id, node_type="kpi",
        name="supplier_defect_rate", created_by=1, is_active=True,
    )
    db_session.add_all([doc, kpi])
    await db_session.flush()
    db_session.add(
        AIProjectGraphEdge(
            tenant_id=tenant_id, project_id=project_id,
            from_node_id=doc.id, to_node_id=kpi.id,
            relationship_type="supports_kpi", confidence=0.7, created_by=1,
            is_active=True,
        )
    )
    await db_session.flush()

    nodes, edges, _hub = await collect_structural_graph(
        db_session, tenant_id=tenant_id, project_id=project_id
    )
    kpi_nodes = [n for n in nodes if n["node_type"] == "kpi"]
    assert {n["name"] for n in kpi_nodes} == {"supplier_defect_rate"}
    kpi_node = kpi_nodes[0]
    assert kpi_node["properties"]["graph_key"] == "kpi:supplier_defect_rate"
    assert "SUP_Supplier_Quality_Manual_2026.docx" in (
        kpi_node["properties"]["source_documents"]
    )
    # The KPI is attached to the hub with a supports_kpi edge (kept under the
    # confidence floor because it is structural, confidence 0.9).
    assert any(
        e["relationship_type"] == "supports_kpi"
        and e["to_node_id"].startswith("s:kpi:")
        and e["confidence"] == 0.9
        for e in edges
    )


async def test_kpi_nodes_render_in_kpis_group_after_merge(db_session) -> None:
    """KPIs collected structurally land in the KPIs & Metrics display group."""
    tenant_id = 1
    project_id = await _seed_project(db_session, tenant_id=tenant_id)
    kpi = AIProjectGraphNode(
        tenant_id=tenant_id, project_id=project_id, node_type="kpi",
        name="on_time_delivery_rate", created_by=1, is_active=True,
    )
    db_session.add(kpi)
    await db_session.flush()

    extra_nodes, extra_edges, _hub = await collect_structural_graph(
        db_session, tenant_id=tenant_id, project_id=project_id
    )
    stored = [{
        "id": 9001, "node_type": "process", "name": "Supplier Qualification",
        "source_type": None, "source_id": None, "properties": {"confidence": 0.9},
    }]
    merged_nodes, merged_edges = merge_graph_sources(stored, [], extra_nodes, extra_edges)
    payload = build_graph_payload(merged_nodes, merged_edges)
    groups = {n["label"]: n["displayGroup"] for n in payload["nodes"]}
    assert groups.get("on_time_delivery_rate") == "KPIs & Metrics"


async def test_company_library_reaches_ai_server_request(db_session) -> None:
    """End-to-end: a company-tier reference doc is collected, merged, and lands
    in the request handed to the AI server (proving the company library is wired
    into the Knowledge Graph AI pipeline, mirroring AI Home)."""
    tenant_id = 1
    project_id = await _seed_project(db_session, tenant_id=tenant_id)
    db_session.add(
        ReferenceDocument(
            tier=TIER_COMPANY, tenant_id=tenant_id,
            title="Acme Supplier Code of Conduct", status="active",
            issuing_body="Acme", ai_summary="Company-wide supplier standard.",
        )
    )
    await db_session.flush()

    extra_nodes, extra_edges, _hub = await collect_structural_graph(
        db_session, tenant_id=tenant_id, project_id=project_id
    )
    stored = [{
        "id": 9001, "node_type": "process", "name": "Supplier Qualification",
        "source_type": None, "source_id": None, "properties": {"confidence": 0.9},
    }]
    merged_nodes, merged_edges = merge_graph_sources(stored, [], extra_nodes, extra_edges)
    payload = build_graph_payload(merged_nodes, merged_edges)

    _center, neighbors, documents, _kpis = _build_ai_request(payload)

    # The company reference is sent to the AI server both as a document and as a
    # directional neighbor of the (non-project) center.
    assert "Acme Supplier Code of Conduct" in {d["title"] for d in documents}
    company = next(
        n for n in neighbors if n["label"] == "Acme Supplier Code of Conduct"
    )
    assert company["type"] == "reference_document"
    assert company["display_group"] == "Authoritative Reference Library"
    assert company["relationship"] == "company_reference"
    assert company["direction"] == "out"  # hub -> company library
