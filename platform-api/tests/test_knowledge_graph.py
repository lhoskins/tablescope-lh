"""Tests for the Insight-First Knowledge Graph builder and graph endpoint.

The deterministic ``build_graph_payload`` does the heavy lifting, so most cases
are fast pure-function unit tests. A couple of endpoint tests cover the route
wiring, backward compatibility and tenant scoping.
"""

from __future__ import annotations

import pytest

from app.auth.jwt import create_access_token
from app.models.ai_project_graph import AIProjectGraphEdge, AIProjectGraphNode
from app.services.knowledge_graph_builder import (
    MAX_NEIGHBORHOOD_NODES,
    PIPELINE_VERSION,
    _classify_relationship,
    _json_safe,
    build_graph_payload,
    build_node_centric_graph_from_snapshot,
    enrich_node,
    graph_key_for,
)
from app.services.supabase_auth_service import SupabaseAuthService, SupabaseUser


class _FakeSupabase(SupabaseAuthService):
    def __init__(self) -> None:
        pass

    async def create_or_invite_user(
        self, email, *, first_name=None, last_name=None, redirect_to=None
    ) -> SupabaseUser:
        return SupabaseUser(
            id=f"supa-{email}", email=email, created=True,
            action_link=f"https://invite/{email}",
        )


class _FakeEmail:
    async def send_transactional_email(
        self, *, to, template, variables, subject=None, reply_to=None
    ) -> bool:
        return True


@pytest.fixture(autouse=True)
def _mock_supabase(monkeypatch):
    import app.routes.tenants_users as tenants_module

    monkeypatch.setattr(tenants_module, "SupabaseAuthService", _FakeSupabase)
    monkeypatch.setattr(tenants_module, "EmailService", _FakeEmail)


# ── Fixtures: a small Corrective Action Process graph ────────────────

def _nodes() -> list[dict]:
    return [
        {"id": 1, "node_type": "project", "name": "Proj", "source_type": None, "source_id": None, "properties": {"project_id": 7}},
        {"id": 2, "node_type": "process", "name": "Corrective Action Process", "source_type": None, "source_id": None, "properties": {"confidence": 0.95, "summary": "Root-cause and CAPA workflow."}},
        {"id": 3, "node_type": "policy", "name": "Quality Manual", "source_type": "asset", "source_id": 30, "properties": {}},
        {"id": 4, "node_type": "kpi", "name": "On-time Closure", "source_type": None, "source_id": None, "properties": {}},
        {"id": 5, "node_type": "data_source", "name": "capa_table", "source_type": "datasource", "source_id": 50, "properties": {}},
        {"id": 6, "node_type": "saved_query", "name": "Open CAPAs", "source_type": "query", "source_id": 60, "properties": {}},
        {"id": 7, "node_type": "dashboard", "name": "CAPA Dashboard", "source_type": "dashboard", "source_id": 70, "properties": {}},
        {"id": 8, "node_type": "risk", "name": "Overdue CAPAs rising", "source_type": None, "source_id": None, "properties": {"severity": "urgent", "confidence": 0.88, "summary": "Overdue corrective actions are trending up."}},
        {"id": 9, "node_type": "gap", "name": "No SLA dashboard", "source_type": None, "source_id": None, "properties": {"authoritative_source": "ISO 9001", "gap_type": "missing_dashboard", "confidence": 0.8}},
        {"id": 10, "node_type": "gap", "name": "Floating gap", "source_type": None, "source_id": None, "properties": {}},
        {"id": 11, "node_type": "recommendation", "name": "Add SLA dashboard", "source_type": None, "source_id": None, "properties": {}},
        {"id": 12, "node_type": "document", "name": "Weakly linked doc", "source_type": "asset", "source_id": 120, "properties": {}},
        {"id": 13, "node_type": "risk", "name": "Lonely risk", "source_type": None, "source_id": None, "properties": {"confidence": 0.7}},
    ]


def _edges() -> list[dict]:
    def e(eid, a, b, rel, conf, ev=None):
        return {"id": eid, "from_node_id": a, "to_node_id": b, "relationship_type": rel, "confidence": conf, "evidence": ev or {}}

    return [
        e(1, 1, 2, "contains", 0.99),
        e(2, 2, 3, "governs", 0.95),
        e(3, 2, 4, "measures", 0.9),
        e(4, 2, 5, "uses", 0.85),
        e(5, 2, 6, "derived_from", 0.82),
        e(6, 2, 7, "visualizes", 0.8),
        e(7, 2, 8, "risk_from", 0.88),
        e(8, 8, 4, "evidence_for", 0.85),
        e(9, 8, 6, "evidence_for", 0.8),
        e(10, 2, 9, "gap_from", 0.8),
        e(11, 9, 3, "governed_by", 0.9),
        e(12, 2, 10, "gap_from", 0.8),
        e(13, 2, 11, "recommends", 0.8),
        e(14, 2, 12, "references", 0.55),  # low-confidence: hidden by default
        e(15, 11, 13, "follows_from", 0.8),  # Lonely risk only touches an action node
    ]


# ── Enrichment / keys ────────────────────────────────────────────────

def test_enrich_node_assigns_layer_group_and_key():
    n = enrich_node(_nodes()[1])  # process
    assert n["graphKey"] == "process:corrective_action_process"
    assert n["layer"] == "semantic"
    assert n["displayGroup"] == "Related Processes"
    assert n["confidence"] == 0.95


def test_graph_key_prefers_explicit_property():
    node = {"id": 99, "node_type": "kpi", "name": "X", "properties": {"graph_key": "kpi:custom"}}
    assert graph_key_for(node) == "kpi:custom"


def test_severity_defaults_and_override():
    risk = enrich_node({"id": 1, "node_type": "risk", "name": "R", "properties": {}})
    assert risk["severity"] == "urgent"
    explicit = enrich_node({"id": 2, "node_type": "risk", "name": "R", "properties": {"severity": "critical"}})
    assert explicit["severity"] == "critical"


# ── Center selection / node-centric rebuild ──────────────────────────

def test_center_by_graph_key():
    payload = build_graph_payload(_nodes(), _edges(), center_node="process:corrective_action_process")
    assert payload["centerNode"]["graphKey"] == "process:corrective_action_process"


def test_center_by_id():
    payload = build_graph_payload(_nodes(), _edges(), center_node="8")
    assert payload["centerNode"]["id"] == 8


def test_default_center_is_never_the_project():
    # The project is the data boundary but is never drawn or chosen as center;
    # the graph centers on the highest-signal process instead.
    payload = build_graph_payload(_nodes(), _edges())
    assert payload["centerNode"]["type"] != "project"
    assert payload["centerNode"]["type"] == "process"


def test_project_node_and_edges_excluded_from_canvas():
    payload = build_graph_payload(_nodes(), _edges())
    types = {n["type"] for n in payload["nodes"]}
    assert "project" not in types
    node_ids = {n["id"] for n in payload["nodes"]}
    # No returned edge references the hidden project node.
    project_ids = {n["id"] for n in _nodes() if n["node_type"] == "project"}
    for e in payload["edges"]:
        assert e["source"] in node_ids and e["target"] in node_ids
        assert e["source"] not in project_ids and e["target"] not in project_ids


def test_default_center_falls_back_to_process_without_project():
    nodes = [n for n in _nodes() if n["node_type"] != "project"]
    payload = build_graph_payload(nodes, _edges())
    assert payload["centerNode"]["type"] == "process"


def test_pipeline_version_present():
    payload = build_graph_payload(_nodes(), _edges())
    assert payload["pipeline_version"] == PIPELINE_VERSION
    assert payload["generated_at"]


# ── Confidence filtering ─────────────────────────────────────────────

def test_low_confidence_edge_hidden_by_default():
    payload = build_graph_payload(_nodes(), _edges(), center_node="process:corrective_action_process")
    labels = {n["label"] for n in payload["nodes"]}
    # Weakly linked doc is only reachable via a 0.55 edge -> dropped at 0.70.
    assert "Weakly linked doc" not in labels


def test_kpis_survive_when_reference_library_exceeds_cap():
    """Recommended (1-hop, hub-attached) and measured (2-hop, via a query) KPIs
    must always render even when the bulk reference library would otherwise
    fill the entire capped neighborhood and crowd them out."""
    hub = {"id": 1, "node_type": "project", "name": "Proj", "properties": {"project_id": 7}}
    center = {"id": 2, "node_type": "process", "name": "Center Process", "properties": {"confidence": 0.95}}
    rec_kpi = {"id": 3, "node_type": "kpi", "name": "Recommended KPI", "properties": {"kpiStatus": "recommended"}}
    query = {"id": 4, "node_type": "saved_query", "name": "Defect Query", "properties": {}}
    meas_kpi = {"id": 5, "node_type": "kpi", "name": "Measured KPI", "properties": {"kpiStatus": "measured"}}
    # Far more reference documents than the node cap, all attached to the hub.
    ref_docs = [
        {"id": 100 + i, "node_type": "reference_document", "name": f"Ref {i}", "properties": {}}
        for i in range(MAX_NEIGHBORHOOD_NODES + 20)
    ]
    nodes = [hub, center, rec_kpi, query, meas_kpi, *ref_docs]

    def e(eid, a, b, rel, conf):
        return {"id": eid, "from_node_id": a, "to_node_id": b, "relationship_type": rel, "confidence": conf, "evidence": {}}

    edges = [
        e(1, 1, 2, "contains", 0.99),
        e(2, 1, 3, "recommended_kpi", 0.9),   # hub -> recommended KPI (1-hop after re-root)
        e(3, 1, 4, "derived_from", 0.95),     # hub -> query (1-hop after re-root)
        e(4, 4, 5, "measures", 0.9),          # query -> measured KPI (2-hop)
    ]
    # Reference docs hang off the hub with high confidence so they compete hard.
    edges += [e(1000 + i, 1, 100 + i, "references", 0.99) for i in range(len(ref_docs))]

    payload = build_graph_payload(nodes, edges, center_node="process:center_process")
    labels = {n["label"] for n in payload["nodes"]}
    assert "Recommended KPI" in labels
    assert "Measured KPI" in labels


def test_inferred_relationships_included_when_requested():
    payload = build_graph_payload(
        _nodes(), _edges(),
        center_node="process:corrective_action_process",
        include_inferred=True,
    )
    labels = {n["label"] for n in payload["nodes"]}
    assert "Weakly linked doc" in labels


# ── Insight cards ────────────────────────────────────────────────────

def test_insight_card_generated_for_risk_with_evidence():
    payload = build_graph_payload(_nodes(), _edges(), center_node="process:corrective_action_process")
    risk_cards = [c for c in payload["insightCards"] if c["category"] == "risk"]
    assert any(c["title"] == "Overdue CAPAs rising" for c in risk_cards)


def test_card_without_evidence_is_not_generated():
    payload = build_graph_payload(_nodes(), _edges(), center_node="process:corrective_action_process")
    assert not any(c["title"] == "Lonely risk" for c in payload["insightCards"])


def test_every_insight_card_has_trace_payload():
    payload = build_graph_payload(_nodes(), _edges(), center_node="process:corrective_action_process")
    assert payload["insightCards"]
    for card in payload["insightCards"]:
        assert card["traceToEvidence"]["nodeIds"]
        assert card["evidencePath"]


# ── Gap detection (evidence-gated) ───────────────────────────────────

def test_supported_gap_is_returned():
    payload = build_graph_payload(_nodes(), _edges(), center_node="process:corrective_action_process")
    titles = {g["title"] for g in payload["gaps"]}
    assert "No SLA dashboard" in titles


def test_unsupported_gap_is_rejected():
    payload = build_graph_payload(_nodes(), _edges(), center_node="process:corrective_action_process")
    titles = {g["title"] for g in payload["gaps"]}
    assert "Floating gap" not in titles


def test_recommended_actions_returned():
    payload = build_graph_payload(_nodes(), _edges(), center_node="process:corrective_action_process")
    assert any(a["title"] == "Add SLA dashboard" for a in payload["recommendedActions"])


# ── Severity filter ──────────────────────────────────────────────────

def test_severity_filter_limits_cards():
    payload = build_graph_payload(
        _nodes(), _edges(),
        center_node="process:corrective_action_process",
        severity="urgent",
    )
    assert all(c["severity"] == "urgent" for c in payload["insightCards"])


# ── Backward compatibility ───────────────────────────────────────────

def test_nodes_and_edges_keep_legacy_shape():
    payload = build_graph_payload(_nodes(), _edges(), center_node="process:corrective_action_process")
    node = payload["nodes"][0]
    for key in ("id", "type", "label", "source_type", "source_id", "properties"):
        assert key in node
    edge = payload["edges"][0]
    for key in ("id", "source", "target", "type", "confidence", "evidence"):
        assert key in edge


def test_empty_graph_returns_empty_payload():
    payload = build_graph_payload([], [])
    assert payload["centerNode"] is None
    assert payload["nodes"] == []
    assert payload["insightCards"] == []
    assert payload["pipeline_version"] == PIPELINE_VERSION


# ── Relationship evidence classification (connector-style policy) ─────

def _kpi_node(status: str | None = None) -> dict:
    props = {"kpiStatus": status} if status else {}
    return {"id": 9, "type": "kpi", "label": "On-time Closure", "properties": props}


def _doc_node() -> dict:
    return {"id": 3, "type": "policy", "label": "Quality Manual", "properties": {}}


def test_classify_validated_edge_is_solid_explicit():
    edge = {"relationship_type": "governs", "confidence": 0.95,
            "evidence": {"validation_status": "validated"}}
    cls = _classify_relationship(edge, _doc_node(), {"id": 2, "type": "process"})
    assert cls["relationshipStrength"] == "explicit"
    assert cls["connectorStyle"] == "solid"
    assert cls["displayByDefault"] is True
    assert cls["validationStatus"] == "validated"


def test_classify_high_confidence_no_status_is_solid_explicit():
    edge = {"relationship_type": "measures", "confidence": 0.92, "evidence": {}}
    cls = _classify_relationship(edge, {"id": 2, "type": "process"}, _kpi_node("measured"))
    assert cls["relationshipStrength"] == "explicit"
    assert cls["connectorStyle"] == "solid"
    assert cls["evidenceBasis"] == "kpi_mapping"


def test_classify_inferred_rel_type_is_dotted():
    edge = {"relationship_type": "linked_by_inferred_join", "confidence": 0.8,
            "evidence": {}}
    cls = _classify_relationship(edge, {"id": 1, "type": "data_source"},
                                 {"id": 2, "type": "data_source"})
    assert cls["relationshipStrength"] == "inferred"
    assert cls["connectorStyle"] == "dotted"
    assert cls["displayByDefault"] is True  # >= 0.75 floor


def test_classify_inferred_below_floor_hidden_by_default():
    edge = {"relationship_type": "mentions", "confidence": 0.72, "evidence": {}}
    cls = _classify_relationship(edge, _doc_node(), {"id": 2, "type": "process"})
    assert cls["relationshipStrength"] == "inferred"
    assert cls["connectorStyle"] == "dotted"
    assert cls["displayByDefault"] is False


def test_classify_recommended_rel_type():
    edge = {"relationship_type": "recommended_kpi", "confidence": 0.6, "evidence": {}}
    cls = _classify_relationship(edge, {"id": 2, "type": "process"}, _kpi_node())
    assert cls["relationshipStrength"] == "recommended"
    assert cls["connectorStyle"] == "dashed"
    assert cls["displayByDefault"] is False
    assert cls["validationStatus"] == "suggested"


def test_classify_recommended_kpi_endpoint_overrides_rel_type():
    # A normal "measures" edge but the KPI endpoint is recommended → recommended.
    edge = {"relationship_type": "measures", "confidence": 0.95, "evidence": {}}
    cls = _classify_relationship(edge, {"id": 2, "type": "process"},
                                 _kpi_node("recommended"))
    assert cls["relationshipStrength"] == "recommended"
    assert cls["connectorStyle"] == "dashed"


def test_classify_rejected_status_is_hidden():
    edge = {"relationship_type": "governs", "confidence": 0.95,
            "evidence": {"validation_status": "rejected"}}
    cls = _classify_relationship(edge, _doc_node(), {"id": 2, "type": "process"})
    assert cls["relationshipStrength"] == "hidden"
    assert cls["connectorStyle"] == "hidden"
    assert cls["displayByDefault"] is False


def test_classify_weak_confidence_is_weak_dotted():
    # 0.50 <= confidence < 0.75 with no other evidence → weak, dotted, off.
    edge = {"relationship_type": "governs", "confidence": 0.6, "evidence": {}}
    cls = _classify_relationship(edge, _doc_node(), {"id": 2, "type": "process"})
    assert cls["relationshipStrength"] == "weak"
    assert cls["connectorStyle"] == "dotted"
    assert cls["displayByDefault"] is False
    assert cls["validationStatus"] == "weak"


def test_classify_low_confidence_is_hidden():
    edge = {"relationship_type": "governs", "confidence": 0.3, "evidence": {}}
    cls = _classify_relationship(edge, _doc_node(), {"id": 2, "type": "process"})
    assert cls["connectorStyle"] == "hidden"
    assert cls["relationshipStrength"] == "hidden"


def test_classify_connector_style_public_wrapper_node_agnostic():
    from app.services.knowledge_graph_builder import classify_connector_style

    cls = classify_connector_style(
        {"relationship_type": "recommended_kpi", "confidence": 0.6, "evidence": {}}
    )
    assert cls["relationshipStrength"] == "recommended"
    assert cls["connectorStyle"] == "dashed"
    assert "evidenceSummary" in cls


def _reference_node() -> dict:
    return {"id": 9, "type": "reference_document", "label": "ISO 9001",
            "properties": {}}


def test_classify_reference_membership_is_recommended_not_solid():
    # A reference doc attached to the project hub at confidence 1.0 must NOT be
    # a solid line — membership is guidance, not proven project evidence.
    edge = {"relationship_type": "industry_standard", "confidence": 1.0,
            "evidence": {"evidence_summary": "authoritative reference",
                         "structural": True}}
    cls = _classify_relationship(edge, _doc_node(), _reference_node())
    assert cls["relationshipStrength"] == "recommended"
    assert cls["connectorStyle"] == "dashed"
    assert cls["displayByDefault"] is False
    assert cls["evidenceBasis"] == "reference_membership"


def test_classify_reference_with_explicit_citation_is_solid():
    edge = {"relationship_type": "project_reference", "confidence": 1.0,
            "evidence": {"evidence_basis": "explicit_citation"}}
    cls = _classify_relationship(edge, _doc_node(), _reference_node())
    assert cls["relationshipStrength"] == "explicit"
    assert cls["connectorStyle"] == "solid"
    assert cls["displayByDefault"] is True


def test_classify_reference_with_inference_is_dotted():
    edge = {"relationship_type": "company_reference", "confidence": 0.8,
            "evidence": {"validation_status": "inferred"}}
    cls = _classify_relationship(edge, _doc_node(), _reference_node())
    assert cls["relationshipStrength"] == "inferred"
    assert cls["connectorStyle"] == "dotted"


def test_classified_metadata_present_on_built_edges():
    payload = build_graph_payload(
        _nodes(), _edges(), center_node="process:corrective_action_process",
    )
    for edge in payload["edges"]:
        assert "relationshipStrength" in edge
        assert "connectorStyle" in edge
        assert "evidenceSummary" in edge
        assert edge["connectorStyle"] in ("solid", "dotted", "dashed", "hidden")


# ── Endpoint wiring / tenant scope ───────────────────────────────────

def _editor_headers(tenant_id: int, user_id: int) -> dict:
    token = create_access_token(sub="u", tenant_id=tenant_id, user_id=user_id, role="editor")
    return {"Authorization": f"Bearer {token}"}


async def _make_project(client, service_headers, slug: str):
    r = await client.post("/api/tenants", json={"slug": slug, "name": slug}, headers=service_headers)
    assert r.status_code == 201
    tenant = r.json()
    r = await client.post(
        f"/api/tenants/{tenant['id']}/users",
        json={"email": f"{slug}@t.com", "display_name": "U", "role": "editor", "external_id": f"ext-{slug}"},
        headers=service_headers,
    )
    assert r.status_code == 201
    user = r.json()
    headers = _editor_headers(tenant["id"], user["id"])
    r = await client.post(
        "/api/projects",
        json={"name": "KG Project", "description": "x", "is_shared": False},
        headers=headers,
    )
    assert r.status_code == 201
    return tenant, user, r.json(), headers


def _stub_kg_ai(monkeypatch):
    """Stub the AI server so the KG pipeline produces grounded insight cards.

    Cards are AI-only (no deterministic fallback), so integration tests that
    expect cards must stub the AI client. The stub grounds one card in the
    centre's first neighbour so it survives the evidence gate.
    """
    from app.services import ai_intelligence_client as ai_client

    monkeypatch.setattr(ai_client, "is_enabled", lambda: True)

    async def _cards(*, neighbors, **kwargs):
        if not neighbors:
            return []
        return [{
            "id": "stub-1",
            "category": "business_insight",
            "severity": "info",
            "title": "AI insight",
            "summary": "Generated by the stubbed AI server.",
            "confidence": 0.9,
            "evidenceKeys": [neighbors[0]["graph_key"]],
            "recommendedAction": "Review.",
        }]

    monkeypatch.setattr(ai_client, "knowledge_graph_cards", _cards)


async def _seed_graph(db_session, *, tenant_id: int, project_id: int, user_id: int):
    """Insert a small process→document graph so the project has a visible center."""
    proc = AIProjectGraphNode(
        tenant_id=tenant_id, project_id=project_id, node_type="process",
        name="Supplier Qualification", properties={"confidence": 0.95},
        created_by=user_id, is_active=True,
    )
    doc = AIProjectGraphNode(
        tenant_id=tenant_id, project_id=project_id, node_type="document",
        name="Supplier Manual", properties={"summary": "Governs qualification."},
        created_by=user_id, is_active=True,
    )
    ds = AIProjectGraphNode(
        tenant_id=tenant_id, project_id=project_id, node_type="data_source",
        name="Supplier Master Table", properties={"summary": "Supplier records."},
        created_by=user_id, is_active=True,
    )
    db_session.add_all([proc, doc, ds])
    await db_session.flush()
    db_session.add_all([
        AIProjectGraphEdge(
            tenant_id=tenant_id, project_id=project_id,
            from_node_id=doc.id, to_node_id=proc.id,
            relationship_type="governs", confidence=0.95, created_by=user_id,
            is_active=True,
        ),
        AIProjectGraphEdge(
            tenant_id=tenant_id, project_id=project_id,
            from_node_id=doc.id, to_node_id=ds.id,
            relationship_type="references", confidence=0.9, created_by=user_id,
            is_active=True,
        ),
    ])
    await db_session.commit()


@pytest.mark.asyncio
async def test_endpoint_backward_compatible_without_params(client, service_headers):
    _tenant, _user, project, headers = await _make_project(client, service_headers, "kgbc")
    r = await client.get(f"/api/projects/{project['id']}/graph", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert "nodes" in body and "edges" in body
    assert "pipeline_version" not in body  # legacy shape unchanged


@pytest.mark.asyncio
async def test_endpoint_node_centric_returns_extended_contract(client, service_headers):
    _tenant, _user, project, headers = await _make_project(client, service_headers, "kgnc")
    r = await client.get(
        f"/api/projects/{project['id']}/graph?lens=process-centric&min_confidence=0.7",
        headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["pipeline_version"] == PIPELINE_VERSION
    for key in ("centerNode", "nodes", "edges", "insightCards", "gaps", "recommendedActions", "tracePaths", "stats"):
        assert key in body


@pytest.mark.asyncio
async def test_endpoint_enforces_tenant_scope(client, service_headers):
    _tenant, _user, project, _headers = await _make_project(client, service_headers, "kgowner")
    # A different tenant must not read this project's graph.
    _ot, _ou, _op, other_headers = await _make_project(client, service_headers, "kgintruder")
    r = await client.get(
        f"/api/projects/{project['id']}/graph?lens=insight-first", headers=other_headers
    )
    assert r.status_code in (403, 404)


# ── Snapshot payload sanitization (JSONB) ────────────────────────────

def test_json_safe_coerces_decimal_and_datetime():
    import datetime as dt
    from decimal import Decimal

    raw = {
        "edges": [{"confidence": Decimal("0.85"), "ts": dt.datetime(2026, 1, 1)}],
        "vals": (Decimal("1.5"), 2),
    }
    safe = _json_safe(raw)
    import json

    # Must be JSON-serializable (this is what the JSONB column requires).
    json.dumps(safe)
    assert safe["edges"][0]["confidence"] == 0.85
    assert isinstance(safe["edges"][0]["confidence"], float)
    assert safe["vals"] == [1.5, 2]


# ── Snapshot cache (from-snapshot rebuild) ───────────────────────────

def _full_snapshot(**overrides) -> dict:
    snap = {
        "id": 1,
        "fullGraph": {"nodes": _nodes(), "edges": _edges()},
        "generatedAt": "2026-01-01T00:00:00+00:00",
        "aiCardsByCenter": {},
    }
    snap.update(overrides)
    return snap


def test_from_snapshot_recenters_without_rebuild():
    payload = build_node_centric_graph_from_snapshot(
        _full_snapshot(), center_node="process:corrective_action_process",
    )
    assert payload["centerNode"]["graphKey"] == "process:corrective_action_process"
    assert payload["nodes"]


def test_from_snapshot_overlays_cached_ai_cards_for_matching_center():
    default = build_graph_payload(_nodes(), _edges())
    center_key = default["centerNode"]["graphKey"]
    cards = {
        "insightCards": [{"id": "ai-1", "category": "risk", "title": "AI risk"}],
        "gaps": [],
        "recommendedActions": [],
        "tracePaths": [],
        "aiGenerated": True,
    }
    snap = _full_snapshot(aiCardsByCenter={center_key: cards})
    payload = build_node_centric_graph_from_snapshot(snap)
    assert payload["insightCards"] == cards["insightCards"]
    assert payload["aiGenerated"] is True


def test_from_snapshot_overlays_cards_per_center():
    # Each centre keeps its own cached card bundle; clicking a node still shows
    # that node's cached insight cards.
    default = build_graph_payload(_nodes(), _edges())
    default_key = default["centerNode"]["graphKey"]
    other_key = "process:corrective_action_process"
    default_cards = {"insightCards": [{"id": "d", "category": "risk"}], "gaps": [],
                     "recommendedActions": [], "tracePaths": [], "aiGenerated": True}
    other_cards = {"insightCards": [{"id": "o", "category": "opportunity"}], "gaps": [],
                   "recommendedActions": [], "tracePaths": [], "aiGenerated": True}
    snap = _full_snapshot(aiCardsByCenter={default_key: default_cards, other_key: other_cards})
    payload = build_node_centric_graph_from_snapshot(snap, center_node=other_key)
    assert payload["centerNode"]["graphKey"] == other_key
    assert payload["insightCards"] == other_cards["insightCards"]


def test_center_eligible_keys_excludes_project_and_covers_all_nodes():
    from app.services.knowledge_graph_builder import _center_eligible_keys

    keys = _center_eligible_keys(_nodes())
    # The project hub is the hidden data boundary — never a centre.
    assert not any(k.startswith("project:") for k in keys)
    # Every visible (non-hidden) node is a centre candidate, so its cards get
    # pre-cached at build time.
    visible = [
        n for n in (enrich_node(n) for n in _nodes())
        if (n.get("type") or n.get("node_type")) != "project"
    ]
    assert len(keys) == len(visible)
    assert "process:corrective_action_process" in keys


def test_kpi_center_uses_kpi_centric_lens():
    kpi = enrich_node(_nodes()[3])  # "On-time Closure"
    assert kpi["type"] == "kpi"
    assert kpi["displayGroup"] == "KPIs & Metrics"
    assert kpi["recommendedLens"] == "kpi-centric"


def test_kpi_gap_card_when_no_query_or_dashboard_measures_it():
    # KPI connected only to a document -> measurement-gap card surfaces.
    nodes = [
        {"id": 1, "node_type": "kpi", "name": "defect_rate", "source_type": None,
         "source_id": None, "properties": {"confidence": 0.9}},
        {"id": 2, "node_type": "document", "name": "Quality Manual",
         "source_type": "asset", "source_id": 20, "properties": {}},
    ]
    edges = [{"id": 1, "from_node_id": 2, "to_node_id": 1,
              "relationship_type": "supports_kpi", "confidence": 0.9, "evidence": {}}]
    payload = build_graph_payload(nodes, edges, center_node="kpi:defect_rate")
    gap_cards = [c for c in payload["insightCards"] if c["category"] == "gap"]
    assert any("not measured" in c["title"] for c in gap_cards)
    assert any(g["nodeKey"] == "kpi:defect_rate" for g in payload["gaps"])


def test_kpi_no_gap_card_when_dashboard_measures_it():
    nodes = [
        {"id": 1, "node_type": "kpi", "name": "defect_rate", "source_type": None,
         "source_id": None, "properties": {"confidence": 0.9}},
        {"id": 2, "node_type": "dashboard", "name": "Quality Dashboard",
         "source_type": "dashboard", "source_id": 20, "properties": {}},
    ]
    edges = [{"id": 1, "from_node_id": 2, "to_node_id": 1,
              "relationship_type": "measures", "confidence": 0.9, "evidence": {}}]
    payload = build_graph_payload(nodes, edges, center_node="kpi:defect_rate")
    assert not any("not measured" in c["title"] for c in payload["insightCards"])


def test_gate_severity_caps_reference_only_findings():
    from app.services.evidence_severity import gate_severity

    assert gate_severity("critical", has_project_evidence=False) == "watch"
    assert gate_severity("warning", has_project_evidence=False) == "watch"
    assert gate_severity("critical", has_project_evidence=True) == "critical"
    assert gate_severity("info", has_project_evidence=False) == "info"
    assert gate_severity("opportunity", has_project_evidence=False) == "opportunity"


def test_ai_card_grounded_only_in_reference_doc_is_capped_to_watch():
    from app.services.knowledge_graph_ai import _map_card

    center = enrich_node({
        "id": 1, "node_type": "reference_document", "name": "DFARS Part 3",
        "source_type": "reference_document", "source_id": 1, "properties": {},
    })
    ref = enrich_node({
        "id": 2, "node_type": "reference_document", "name": "TCFD",
        "source_type": "reference_document", "source_id": 2, "properties": {},
    })
    nodes = [center, ref]
    nodes_by_key = {n["graphKey"]: n for n in nodes}
    raw = {
        "id": "c1", "category": "risk", "severity": "critical",
        "title": "Non-compliance risk", "summary": "Reference says so.",
        "confidence": 0.9, "evidenceKeys": [ref["graphKey"]],
    }
    card = _map_card(
        raw, index=0, center=center, nodes_by_key=nodes_by_key,
        nodes=nodes, edges=[],
    )
    assert card is not None
    assert card["severity"] == "watch"


def test_from_snapshot_shows_no_cards_for_uncached_center():
    # AI-only: a centre with no cached AI bundle shows no cards (no
    # deterministic fallback), never another centre's cached cards.
    cards = {
        "insightCards": [{"id": "ai-1", "category": "risk", "title": "AI risk"}],
        "gaps": [], "recommendedActions": [], "tracePaths": [], "aiGenerated": True,
    }
    snap = _full_snapshot(aiCardsByCenter={"project:proj": cards})
    payload = build_node_centric_graph_from_snapshot(
        snap, center_node="process:corrective_action_process",
    )
    assert payload["insightCards"] == []
    assert payload["aiGenerated"] is False


def test_get_snapshot_normalizes_legacy_single_center_cache():
    from app.services.knowledge_graph_builder import build_node_centric_graph_from_snapshot
    default = build_graph_payload(_nodes(), _edges())
    center_key = default["centerNode"]["graphKey"]
    cards = {"insightCards": [{"id": "legacy", "category": "risk"}], "gaps": [],
             "recommendedActions": [], "tracePaths": [], "aiGenerated": True}
    # Simulate the normalization done by get_project_graph_snapshot for an older
    # snapshot that stored a single aiCenterKey/aiCards pair.
    legacy = {"fullGraph": {"nodes": _nodes(), "edges": _edges()},
              "aiCardsByCenter": {center_key: cards}}
    payload = build_node_centric_graph_from_snapshot(legacy)
    assert payload["insightCards"] == cards["insightCards"]


@pytest.mark.asyncio
async def test_graph_response_includes_cache_metadata(client, service_headers):
    _t, _u, project, headers = await _make_project(client, service_headers, "kgcache")
    r = await client.get(
        f"/api/projects/{project['id']}/graph?lens=insight-first", headers=headers
    )
    assert r.status_code == 200
    body = r.json()
    assert body.get("lastUpdated")
    assert "snapshotId" in body
    # A plain GET (no refresh) is served as cached even when it lazily builds.
    assert body["isCached"] is True


@pytest.mark.asyncio
async def test_node_click_reads_cache_without_rebuild(client, service_headers, db_session):
    t, u, project, headers = await _make_project(client, service_headers, "kgclick")
    pid = project["id"]
    await _seed_graph(db_session, tenant_id=t["id"], project_id=pid, user_id=u["id"])
    first = (await client.get(
        f"/api/projects/{pid}/graph?lens=insight-first", headers=headers
    )).json()
    assert first["centerNode"] is not None
    assert first["centerNode"]["type"] != "project"
    # A node click (center_node) reads the cached snapshot: same timestamp, cached.
    second = (await client.get(
        f"/api/projects/{pid}/graph?lens=insight-first&center_node={first['centerNode']['graphKey']}",
        headers=headers,
    )).json()
    assert second["lastUpdated"] == first["lastUpdated"]
    assert second["isCached"] is True


@pytest.mark.asyncio
async def test_graph_populates_business_insight_cards(client, service_headers, db_session, monkeypatch):
    # With the AI server in the loop, a centre with connected evidence returns
    # AI-generated, evidence-gated business-insight cards (pre-cached at build).
    _stub_kg_ai(monkeypatch)
    t, u, project, headers = await _make_project(client, service_headers, "kgcards")
    pid = project["id"]
    await _seed_graph(db_session, tenant_id=t["id"], project_id=pid, user_id=u["id"])
    body = (await client.get(
        f"/api/projects/{pid}/graph?lens=insight-first", headers=headers
    )).json()
    assert "insightCards" in body
    assert len(body["insightCards"]) >= 1
    assert any(c["category"] == "business_insight" for c in body["insightCards"])
    assert all(c.get("aiGenerated") for c in body["insightCards"])


@pytest.mark.asyncio
async def test_insight_cards_persist_when_clicking_into_a_node(client, service_headers, db_session, monkeypatch):
    # Regression: clicking into a cached node must not blank the insight panel.
    # Cards for every centre are pre-cached at build time, so a non-default
    # centre still has its cards (served from cache, no rebuild/AI call).
    _stub_kg_ai(monkeypatch)
    t, u, project, headers = await _make_project(client, service_headers, "kgpersist")
    pid = project["id"]
    await _seed_graph(db_session, tenant_id=t["id"], project_id=pid, user_id=u["id"])
    # Default load (centers on the process) populates + caches its cards.
    default = (await client.get(
        f"/api/projects/{pid}/graph?lens=insight-first", headers=headers
    )).json()
    assert default["insightCards"]
    # Click the document node — it must return its own insight cards, not empty.
    doc_key = next(
        n["graphKey"] for n in default["nodes"] if n["type"] == "document"
    )
    clicked = (await client.get(
        f"/api/projects/{pid}/graph?lens=insight-first&center_node={doc_key}",
        headers=headers,
    )).json()
    assert clicked["centerNode"]["graphKey"] == doc_key
    assert clicked["insightCards"], "insight cards should not disappear on node click"
    # A second click reads the now-cached bundle without rebuilding.
    again = (await client.get(
        f"/api/projects/{pid}/graph?lens=insight-first&center_node={doc_key}",
        headers=headers,
    )).json()
    assert again["lastUpdated"] == clicked["lastUpdated"]
    assert again["insightCards"]


@pytest.mark.asyncio
async def test_refresh_rebuilds_and_updates_timestamp(client, service_headers):
    _t, _u, project, headers = await _make_project(client, service_headers, "kgrefresh")
    pid = project["id"]
    first = (await client.get(
        f"/api/projects/{pid}/graph?lens=insight-first", headers=headers
    )).json()
    import asyncio

    await asyncio.sleep(0.01)
    r = await client.post(f"/api/projects/{pid}/graph/refresh", headers=headers)
    assert r.status_code == 200
    refreshed = r.json()
    assert refreshed["lastUpdated"] != first["lastUpdated"]
    assert "snapshotId" in refreshed


@pytest.mark.asyncio
async def test_refresh_param_rebuilds_snapshot(client, service_headers):
    _t, _u, project, headers = await _make_project(client, service_headers, "kgrparam")
    pid = project["id"]
    first = (await client.get(
        f"/api/projects/{pid}/graph?lens=insight-first", headers=headers
    )).json()
    import asyncio

    await asyncio.sleep(0.01)
    refreshed = (await client.get(
        f"/api/projects/{pid}/graph?lens=insight-first&refresh=true", headers=headers
    )).json()
    assert refreshed["isCached"] is False
    assert refreshed["lastUpdated"] != first["lastUpdated"]
