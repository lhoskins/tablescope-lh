"""Tests for the Insight-First Knowledge Graph builder and graph endpoint.

The deterministic ``build_graph_payload`` does the heavy lifting, so most cases
are fast pure-function unit tests. A couple of endpoint tests cover the route
wiring, backward compatibility and tenant scoping.
"""

from __future__ import annotations

import pytest

from app.auth.jwt import create_access_token
from app.services.knowledge_graph_builder import (
    PIPELINE_VERSION,
    build_graph_payload,
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
    import app.routes.tenants as tenants_module

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


def test_default_center_is_a_process():
    payload = build_graph_payload(_nodes(), _edges())
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
