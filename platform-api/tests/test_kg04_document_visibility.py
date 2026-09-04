"""KG-04: the Knowledge Graph must honor per-document visibility and real
project membership at read time, not just tenant/project existence.

Two confirmed gaps:

1. ``project_graph.py``'s ``GET /projects/{id}/graph`` checked only that the
   project belonged to the caller's tenant -- any same-tenant user, even a
   non-member of a private project, could read its Knowledge Graph. Every
   other KG route already went through the real owner-or-active-member
   policy (``app.services.project_access``); this route was missed.
2. Even for an authorized project member, a document uploaded with
   ``visibility="private"`` is only for its owner (or a tenant admin) per
   ``project_assets.py``'s own policy -- but the cached graph snapshot is
   shared by every member, so a private document's node/summary could still
   surface to a teammate who is a legitimate project member but not that
   document's owner.

Run from ``platform-api``: ``pytest -q tests/test_kg04_document_visibility.py``.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.auth.jwt import create_access_token
from app.models.project import Project, ProjectMember
from app.models.project_asset import ProjectAsset
from app.services.knowledge_graph.visibility import filter_payload_for_viewer

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _mock_supabase(monkeypatch):
    import app.routes.tenants_users as tenants_module
    from app.services.supabase_auth_service import SupabaseAuthService, SupabaseUser

    class _FakeSupabase(SupabaseAuthService):
        def __init__(self) -> None:
            pass

        async def create_or_invite_user(
            self, email, *, first_name=None, last_name=None, redirect_to=None
        ) -> SupabaseUser:
            return SupabaseUser(id=f"supa-{email}", email=email, created=True, action_link="x")

    class _FakeEmail:
        async def send_transactional_email(
            self, *, to, template, variables, subject=None, reply_to=None
        ) -> bool:
            return True

    monkeypatch.setattr(tenants_module, "SupabaseAuthService", _FakeSupabase)
    monkeypatch.setattr(tenants_module, "EmailService", _FakeEmail)


def _headers(tenant_id: int, user_id: int, role: str = "viewer") -> dict:
    token = create_access_token(sub="u", tenant_id=tenant_id, user_id=user_id, role=role)
    return {"Authorization": f"Bearer {token}"}


async def _make_tenant(client, service_headers, slug: str) -> int:
    r = await client.post(
        "/api/tenants", json={"slug": slug, "name": f"{slug} tenant"}, headers=service_headers
    )
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


async def _make_user(client, service_headers, tenant_id: int, email: str) -> int:
    r = await client.post(
        f"/api/tenants/{tenant_id}/users",
        json={
            "email": email,
            "display_name": email.split("@")[0],
            "role": "editor",
            "external_id": f"ext-{email}",
        },
        headers=service_headers,
    )
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


async def test_project_graph_denies_a_same_tenant_non_member_on_a_private_project(
    client, db_session, service_headers
):
    """The confirmed gap: GET /graph only checked tenant match, not
    ownership/active membership -- unlike every other KG route."""
    tenant_id = await _make_tenant(client, service_headers, "kg04-private")
    owner_id = await _make_user(client, service_headers, tenant_id, "owner@kg04-private.com")
    outsider_id = await _make_user(client, service_headers, tenant_id, "outsider@kg04-private.com")

    project = Project(tenant_id=tenant_id, owner_id=owner_id, name="P", is_shared=False)
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    r = await client.get(
        f"/api/projects/{project.id}/graph",
        headers=_headers(tenant_id, outsider_id),
    )
    assert r.status_code == 403


async def test_legacy_graph_hides_private_document_from_non_owner_member(
    client, db_session, service_headers
):
    """A project member who isn't the document's owner must not see a
    private document's node on the legacy {nodes, edges} graph, but its
    owner must."""
    tenant_id = await _make_tenant(client, service_headers, "kg04-legacy")
    owner_id = await _make_user(client, service_headers, tenant_id, "owner@kg04-legacy.com")
    member_id = await _make_user(client, service_headers, tenant_id, "member@kg04-legacy.com")

    project = Project(tenant_id=tenant_id, owner_id=owner_id, name="P", is_shared=True)
    db_session.add(project)
    await db_session.flush()
    db_session.add(ProjectMember(project_id=project.id, user_id=member_id, is_active=True))

    asset = ProjectAsset(
        tenant_id=tenant_id, project_id=project.id, owner_user_id=owner_id,
        asset_type="document", title="Owner's Private Memo", filename="memo.pdf",
        storage_location="memo.pdf", visibility="private",
    )
    db_session.add(asset)
    await db_session.flush()

    await db_session.execute(
        text(
            """
            INSERT INTO ai_project_graph_nodes
                (tenant_id, project_id, node_type, name, source_type, source_id,
                 properties, is_active, created_by)
            VALUES (:tid, :pid, 'document', 'Owner''s Private Memo', 'project_asset',
                    :sid, '{}', true, :owner)
            """
        ),
        {"tid": tenant_id, "pid": project.id, "sid": asset.id, "owner": owner_id},
    )
    await db_session.commit()

    r_member = await client.get(
        f"/api/projects/{project.id}/graph",
        headers=_headers(tenant_id, member_id),
    )
    assert r_member.status_code == 200
    names_member = {n["label"] for n in r_member.json()["nodes"]}
    assert "Owner's Private Memo" not in names_member

    r_owner = await client.get(
        f"/api/projects/{project.id}/graph",
        headers=_headers(tenant_id, owner_id),
    )
    assert r_owner.status_code == 200
    names_owner = {n["label"] for n in r_owner.json()["nodes"]}
    assert "Owner's Private Memo" in names_owner


async def test_filter_payload_for_viewer_strips_private_document_and_its_cards(
    db_session,
):
    """Unit-level proof for the node-centric path's filter: a private
    document node, its edges, and any card/gap/action/trace-path citing it
    as evidence are stripped for a non-owner viewer, and left untouched for
    the owner."""
    tenant_id = 1
    project = Project(tenant_id=tenant_id, owner_id=10, name="P")
    db_session.add(project)
    await db_session.flush()

    asset = ProjectAsset(
        tenant_id=tenant_id, project_id=project.id, owner_user_id=10,
        asset_type="document", title="Private Doc", filename="d.pdf",
        storage_location="d.pdf", visibility="private",
    )
    db_session.add(asset)
    await db_session.flush()

    payload = {
        "centerNode": {"id": 1, "type": "process", "label": "Process A"},
        "nodes": [
            {"id": 1, "type": "process", "label": "Process A", "source_type": None,
             "source_id": None, "graphKey": "process:1", "displayGroup": "Process"},
            {"id": 2, "type": "document", "label": "Private Doc",
             "source_type": "project_asset", "source_id": asset.id,
             "graphKey": "doc:2", "displayGroup": "Documents"},
        ],
        "edges": [
            {"id": 1, "source": 1, "target": 2, "type": "evidence_for"},
        ],
        "insightCards": [
            {"id": "kgcard:process:1", "nodeKey": "process:1",
             "traceToEvidence": {"nodeIds": [1, 2], "edgeIds": [1], "nodeKeys": []}},
        ],
        "gaps": [{"id": "gap:doc:2", "nodeKey": "doc:2"}],
        "recommendedActions": [{"id": "action:doc:2", "nodeKey": "doc:2"}],
        "tracePaths": [{"id": "trace:process:1", "nodeIds": [1, 2], "edgeIds": [1]}],
        "stats": {"nodeCount": 2, "edgeCount": 1, "cardCount": 1, "gapCount": 1, "byDisplayGroup": {}},
    }

    filtered = await filter_payload_for_viewer(
        db_session, payload, tenant_id=tenant_id, user_id=99, role="member",
    )
    assert {n["id"] for n in filtered["nodes"]} == {1}
    assert filtered["edges"] == []
    assert filtered["insightCards"] == []
    assert filtered["gaps"] == []
    assert filtered["recommendedActions"] == []
    assert filtered["tracePaths"] == []
    assert filtered["stats"]["nodeCount"] == 1

    unfiltered = await filter_payload_for_viewer(
        db_session, payload, tenant_id=tenant_id, user_id=10, role="member",
    )
    assert {n["id"] for n in unfiltered["nodes"]} == {1, 2}
    assert len(unfiltered["insightCards"]) == 1


async def test_filter_payload_for_viewer_blanks_out_a_hidden_center_node(db_session):
    """Requesting a private document's own node as the center must not echo
    its title back -- it degrades to an empty/"not found"-shaped response."""
    tenant_id = 1
    project = Project(tenant_id=tenant_id, owner_id=10, name="P")
    db_session.add(project)
    await db_session.flush()

    asset = ProjectAsset(
        tenant_id=tenant_id, project_id=project.id, owner_user_id=10,
        asset_type="document", title="Private Doc", filename="d.pdf",
        storage_location="d.pdf", visibility="private",
    )
    db_session.add(asset)
    await db_session.flush()

    payload = {
        "centerNode": {"id": 2, "type": "document", "label": "Private Doc"},
        "nodes": [
            {"id": 2, "type": "document", "label": "Private Doc",
             "source_type": "project_asset", "source_id": asset.id,
             "graphKey": "doc:2", "displayGroup": "Documents"},
        ],
        "edges": [],
        "insightCards": [],
        "gaps": [],
        "recommendedActions": [],
        "tracePaths": [],
        "stats": {"nodeCount": 1, "edgeCount": 0, "cardCount": 0, "gapCount": 0, "byDisplayGroup": {}},
    }

    filtered = await filter_payload_for_viewer(
        db_session, payload, tenant_id=tenant_id, user_id=99, role="member",
    )
    assert filtered["centerNode"] is None
    assert filtered["nodes"] == []
    assert filtered["visibilityRestricted"] is True
