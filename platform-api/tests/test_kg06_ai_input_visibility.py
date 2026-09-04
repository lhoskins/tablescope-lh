"""KG-05/KG-06: a document private to one project member must never reach
the AI server as context when the Knowledge Graph cache is (re)built by a
*different* member -- not just hidden from that member's own later reads
(see test_kg04_document_visibility.py), but never sent to the external AI
service in the first place, and never baked into a card that then gets
cached project-wide.

Run from ``platform-api``: ``pytest -q tests/test_kg06_ai_input_visibility.py``.
"""

from __future__ import annotations

import pytest

from app.models.project import Project
from app.models.project_asset import ProjectAsset
from app.services import knowledge_graph_ai as kg_ai
from app.services.knowledge_graph.snapshot import _precache_center_cards

pytestmark = pytest.mark.anyio


def _raw_graph(private_asset_id: int) -> tuple[list[dict], list[dict]]:
    nodes = [
        {"id": 1, "node_type": "process", "name": "Corrective Action Process",
         "source_type": None, "source_id": None, "properties": {"confidence": 0.95}},
        {"id": 2, "node_type": "document", "name": "Owner's Private Memo",
         "source_type": "project_asset", "source_id": private_asset_id,
         "properties": {"summary": "Confidential."}},
        {"id": 3, "node_type": "document", "name": "Shared Runbook",
         "source_type": "project_asset", "source_id": 999,
         "properties": {"summary": "Public runbook."}},
    ]
    edges = [
        {"id": 1, "from_node_id": 1, "to_node_id": 2, "relationship_type": "evidence_for", "confidence": 0.9, "evidence": {}},
        {"id": 2, "from_node_id": 1, "to_node_id": 3, "relationship_type": "evidence_for", "confidence": 0.9, "evidence": {}},
    ]
    return nodes, edges


async def test_precache_never_sends_another_members_private_document_to_ai(
    db_session, monkeypatch,
):
    tenant_id = 1
    owner_id = 10
    other_member_id = 20

    project = Project(tenant_id=tenant_id, owner_id=owner_id, name="P")
    db_session.add(project)
    await db_session.flush()

    asset = ProjectAsset(
        tenant_id=tenant_id, project_id=project.id, owner_user_id=owner_id,
        asset_type="document", title="Owner's Private Memo", filename="memo.pdf",
        storage_location="memo.pdf", visibility="private",
    )
    db_session.add(asset)
    await db_session.flush()

    nodes, edges = _raw_graph(asset.id)

    captured_neighbor_labels: list[set[str]] = []

    monkeypatch.setattr(kg_ai.ai, "is_enabled", lambda: True)

    async def _fake_cards(*, neighbors, documents, **_kwargs):
        captured_neighbor_labels.append({n["label"] for n in neighbors})
        return {"cards": []}

    monkeypatch.setattr(kg_ai.ai, "knowledge_graph_cards", _fake_cards)

    # A teammate (not the document's owner) triggers the rebuild.
    await _precache_center_cards(
        db_session, nodes, edges,
        tenant_id=tenant_id, user_id=other_member_id, project_id=project.id,
    )
    all_labels_seen = {label for call in captured_neighbor_labels for label in call}
    assert "Owner's Private Memo" not in all_labels_seen
    assert "Shared Runbook" in all_labels_seen

    # The document's own owner rebuilding sees their own document normally.
    captured_neighbor_labels.clear()
    await _precache_center_cards(
        db_session, nodes, edges,
        tenant_id=tenant_id, user_id=owner_id, project_id=project.id,
    )
    all_labels_seen = {label for call in captured_neighbor_labels for label in call}
    assert "Owner's Private Memo" in all_labels_seen
