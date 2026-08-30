"""TS-ISO-003: the project-access policy must be the same everywhere.

Confirmed six distinct instances of the systemic gap the isolation
assessment flagged ("at least 6 divergent project-access implementations"):

1. ``knowledge_graph.py``: ``/health`` and ``/builds/{build_id}`` performed
   NO project-access check at all -- any authenticated user could read
   another tenant's knowledge-graph health/build data by supplying its
   ``project_id``/``build_id``. The other routes in that file only checked
   tenant membership (via the service-layer ``_require_project``), not
   project ownership/active-membership -- a same-tenant, cross-project leak
   for users who aren't members of a private/shared project.
2. ``project_insight.py``, ``project_actions_shared.py``, ``home_pins.py``:
   each had `if project.owner_id == user_id or project.is_shared: return`,
   which grants ANY same-tenant user access to a shared project without
   checking membership at all -- the membership-check code below it was
   unreachable whenever the project happened to be shared.
3. ``reference_library_documents.py`` and ``projects_shared.py`` queried
   ``ProjectMember`` without filtering ``is_active`` -- a removed member (or
   one demoted from project-admin) kept access/admin rights indefinitely
   (the same bug class as the already-fixed TS-ISO-009).

Run from ``platform-api``: ``pytest -q tests/test_ts_iso_003_project_access.py``.
"""

from __future__ import annotations

import pytest

from app.auth.context import RequestContext
from app.auth.jwt import TokenClaims, create_access_token
from app.models.project import Project, ProjectMember
from app.routes.projects_shared import _is_project_admin

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


async def _scenario(client, db_session, service_headers, slug: str, *, shared: bool):
    """One tenant, an owner, a non-member outsider, and a shared/private project."""
    tenant_id = await _make_tenant(client, service_headers, slug)
    owner_id = await _make_user(client, service_headers, tenant_id, f"owner@{slug}.com")
    outsider_id = await _make_user(client, service_headers, tenant_id, f"outsider@{slug}.com")

    project = Project(tenant_id=tenant_id, owner_id=owner_id, name="P", is_shared=shared)
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return tenant_id, owner_id, outsider_id, project


# ── knowledge_graph.py ──────────────────────────────────────────────


async def test_kg_health_rejects_a_different_tenants_project_id(
    client, db_session, service_headers
):
    """The confirmed zero-scoping bug: /health took project_id at face value."""
    _, _, _, project_a = await _scenario(
        client, db_session, service_headers, "kg-health-a", shared=True
    )
    tenant_b, user_b, _, _ = await _scenario(
        client, db_session, service_headers, "kg-health-b", shared=True
    )

    r = await client.get(
        f"/api/projects/{project_a.id}/knowledge-graph/health",
        headers=_headers(tenant_b, user_b),
    )
    assert r.status_code == 404


async def test_kg_build_by_id_rejects_a_different_tenants_project_id(
    client, db_session, service_headers
):
    """The confirmed zero-scoping bug: /builds/{id} only compared to the
    caller-supplied project_id, never the caller's tenant."""
    _, _, _, project_a = await _scenario(
        client, db_session, service_headers, "kg-build-a", shared=True
    )
    tenant_b, user_b, _, _ = await _scenario(
        client, db_session, service_headers, "kg-build-b", shared=True
    )

    r = await client.get(
        f"/api/projects/{project_a.id}/knowledge-graph/builds/1",
        headers=_headers(tenant_b, user_b),
    )
    assert r.status_code == 404


async def test_kg_status_denies_a_same_tenant_non_member_on_a_private_project(
    client, db_session, service_headers
):
    _, _, outsider_id, project = await _scenario(
        client, db_session, service_headers, "kg-private", shared=False
    )
    r = await client.get(
        f"/api/projects/{project.id}/knowledge-graph/status",
        headers=_headers(project.tenant_id, outsider_id),
    )
    assert r.status_code == 403


async def test_kg_status_denies_a_same_tenant_non_member_on_a_shared_project(
    client, db_session, service_headers
):
    """Same-tenant is not enough even when the project is shared -- the
    "strongest existing pattern" (ai_proxy_shared._authorize_project_access)
    already got this right; knowledge_graph.py's routes now go through it
    too instead of only checking tenant membership."""
    _, _, outsider_id, project = await _scenario(
        client, db_session, service_headers, "kg-shared", shared=True
    )
    r = await client.get(
        f"/api/projects/{project.id}/knowledge-graph/status",
        headers=_headers(project.tenant_id, outsider_id),
    )
    assert r.status_code == 403


async def test_kg_status_allows_an_active_member(client, db_session, service_headers):
    tenant_id, _owner_id, member_id, project = await _scenario(
        client, db_session, service_headers, "kg-member", shared=True
    )
    db_session.add(
        ProjectMember(project_id=project.id, user_id=member_id, role="viewer", is_active=True)
    )
    await db_session.commit()

    r = await client.get(
        f"/api/projects/{project.id}/knowledge-graph/status",
        headers=_headers(tenant_id, member_id),
    )
    assert r.status_code == 200


# ── is_shared blanket-access bug: project_insight / project_actions / home_pins ──


async def test_project_insight_denies_a_non_member_on_a_shared_project(
    client, db_session, service_headers
):
    _, _, outsider_id, project = await _scenario(
        client, db_session, service_headers, "insight-shared", shared=True
    )
    r = await client.get(
        f"/api/projects/{project.id}/insight",
        headers=_headers(project.tenant_id, outsider_id),
    )
    assert r.status_code == 403


async def test_project_actions_denies_a_non_member_on_a_shared_project(
    client, db_session, service_headers
):
    _, _, outsider_id, project = await _scenario(
        client, db_session, service_headers, "actions-shared", shared=True
    )
    r = await client.get(
        f"/api/projects/{project.id}/actions",
        headers=_headers(project.tenant_id, outsider_id),
    )
    assert r.status_code == 403


async def test_project_actions_allows_an_active_member_on_a_shared_project(
    client, db_session, service_headers
):
    tenant_id, _owner_id, member_id, project = await _scenario(
        client, db_session, service_headers, "actions-member", shared=True
    )
    db_session.add(
        ProjectMember(project_id=project.id, user_id=member_id, role="viewer", is_active=True)
    )
    await db_session.commit()

    r = await client.get(
        f"/api/projects/{project.id}/actions",
        headers=_headers(tenant_id, member_id),
    )
    assert r.status_code == 200


async def test_home_pins_denies_a_non_member_pinning_into_a_shared_project(
    client, db_session, service_headers
):
    _, _, outsider_id, project = await _scenario(
        client, db_session, service_headers, "pins-shared", shared=True
    )
    r = await client.post(
        "/api/home-pins",
        json={
            "pin_type": "insight_card",
            "pin_key": "insight:k1",
            "title": "T",
            "project_id": project.id,
        },
        headers=_headers(project.tenant_id, outsider_id),
    )
    # home_pins.py's _require_project_access wrapper maps a denied
    # _can_access_project (None) to 404, not 403 -- pre-existing behavior
    # of this file, unchanged by this fix.
    assert r.status_code == 404


async def test_home_pins_allows_an_active_member_pinning_into_a_shared_project(
    client, db_session, service_headers
):
    tenant_id, _owner_id, member_id, project = await _scenario(
        client, db_session, service_headers, "pins-member", shared=True
    )
    db_session.add(
        ProjectMember(project_id=project.id, user_id=member_id, role="viewer", is_active=True)
    )
    await db_session.commit()

    r = await client.post(
        "/api/home-pins",
        json={
            "pin_type": "insight_card",
            "pin_key": "insight:k1",
            "title": "T",
            "project_id": project.id,
        },
        headers=_headers(tenant_id, member_id),
    )
    assert r.status_code == 201


# ── missing is_active filter: reference_library_documents / projects_shared ──


async def test_reference_library_denies_a_deactivated_member(
    client, db_session, service_headers
):
    tenant_id, _owner_id, removed_id, project = await _scenario(
        client, db_session, service_headers, "ref-lib", shared=True
    )
    db_session.add(
        ProjectMember(project_id=project.id, user_id=removed_id, role="viewer", is_active=False)
    )
    await db_session.commit()

    r = await client.get(
        "/api/reference-library/documents",
        params={"tier": "project", "project_id": project.id},
        headers=_headers(tenant_id, removed_id),
    )
    assert r.status_code == 403


async def test_reference_library_allows_an_active_member(client, db_session, service_headers):
    tenant_id, _owner_id, member_id, project = await _scenario(
        client, db_session, service_headers, "ref-lib-active", shared=True
    )
    db_session.add(
        ProjectMember(project_id=project.id, user_id=member_id, role="viewer", is_active=True)
    )
    await db_session.commit()

    r = await client.get(
        "/api/reference-library/documents",
        params={"tier": "project", "project_id": project.id},
        headers=_headers(tenant_id, member_id),
    )
    assert r.status_code == 200


async def test_is_project_admin_denies_a_deactivated_admin_member(db_session):
    project = Project(tenant_id=1, owner_id=999, name="P", is_shared=True)
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    db_session.add(
        ProjectMember(project_id=project.id, user_id=42, role="admin", is_active=False)
    )
    await db_session.commit()

    context = RequestContext(
        claims=TokenClaims(sub="42", tenant_id=1, user_id=42, role="editor")
    )
    assert await _is_project_admin(db_session, project, context) is False


async def test_is_project_admin_allows_an_active_admin_member(db_session):
    project = Project(tenant_id=1, owner_id=999, name="P", is_shared=True)
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    db_session.add(
        ProjectMember(project_id=project.id, user_id=43, role="admin", is_active=True)
    )
    await db_session.commit()

    context = RequestContext(
        claims=TokenClaims(sub="43", tenant_id=1, user_id=43, role="editor")
    )
    assert await _is_project_admin(db_session, project, context) is True
