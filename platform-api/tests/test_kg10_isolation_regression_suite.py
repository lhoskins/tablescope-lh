"""KG-10: an automated isolation regression suite across every Knowledge
Graph route.

Scope note: the review's item #10 asks for "every KG and downstream
endpoint" (AI Assistant, Business Insights, Project Insights, dashboards,
executive summaries). This suite covers every route that is actually part of
the Knowledge Graph surface (``knowledge_graph.py`` and ``project_graph.py``)
with one shared, parametrized fixture matrix: cross-tenant access to a known
project id, and same-tenant access by a user who is neither the owner nor an
active member of a private project. The "downstream" half of that ask
(grounded-answer evaluations against AI Assistant/Business Insights/etc.
proving they use -- and never leak across -- the correct KG version) is
covered separately by item #50, which is a distinct, larger undertaking
(each of those features has its own request/response shape); folding it in
here would just be a weaker, un-scoped version of that work.

Run from ``platform-api``: ``pytest -q tests/test_kg10_isolation_regression_suite.py``.
"""

from __future__ import annotations

import pytest

from app.auth.jwt import create_access_token
from app.models.project import Project

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


def _headers(tenant_id: int, user_id: int, role: str) -> dict:
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


async def _private_project(client, db_session, service_headers, slug: str):
    """One tenant, an owner, a same-tenant non-member outsider, and a
    private (non-shared) project."""
    tenant_id = await _make_tenant(client, service_headers, slug)
    owner_id = await _make_user(client, service_headers, tenant_id, f"owner@{slug}.com")
    outsider_id = await _make_user(client, service_headers, tenant_id, f"outsider@{slug}.com")

    project = Project(tenant_id=tenant_id, owner_id=owner_id, name="P", is_shared=False)
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return tenant_id, owner_id, outsider_id, project


# (method, path template, minimum role, json body or None)
KG_ROUTES = [
    ("GET", "/api/projects/{pid}/knowledge-graph/status", "viewer", None),
    ("POST", "/api/projects/{pid}/knowledge-graph/rebuild", "editor", None),
    ("POST", "/api/projects/{pid}/knowledge-graph/rebuild/incremental", "editor", {"change_set": []}),
    ("GET", "/api/projects/{pid}/knowledge-graph/builds", "viewer", None),
    ("GET", "/api/projects/{pid}/knowledge-graph/builds/1", "viewer", None),
    ("POST", "/api/projects/{pid}/knowledge-graph/health-check", "editor", None),
    ("GET", "/api/projects/{pid}/knowledge-graph/health", "viewer", None),
    ("GET", "/api/projects/{pid}/knowledge-graph/versions", "viewer", None),
    ("GET", "/api/projects/{pid}/knowledge-graph/dependencies/executive-insight", "viewer", None),
    ("GET", "/api/projects/{pid}/graph", "viewer", None),
]


async def _call(client, method: str, path: str, headers: dict, body):
    if method == "GET":
        return await client.get(path, headers=headers)
    return await client.post(path, json=body or {}, headers=headers)


@pytest.mark.parametrize("method,path_tmpl,role,body", KG_ROUTES)
async def test_route_denies_a_same_tenant_non_member_on_a_private_project(
    client, db_session, service_headers, method, path_tmpl, role, body,
):
    _, _, outsider_id, project = await _private_project(
        client, db_session, service_headers, f"kg10-{abs(hash((method, path_tmpl))) % 100000}",
    )
    path = path_tmpl.format(pid=project.id)
    r = await _call(client, method, path, _headers(project.tenant_id, outsider_id, role), body)
    assert r.status_code == 403, f"{method} {path_tmpl} -> {r.status_code}, expected 403: {r.text}"


@pytest.mark.parametrize("method,path_tmpl,role,body", KG_ROUTES)
async def test_route_rejects_a_different_tenants_project_id(
    client, db_session, service_headers, method, path_tmpl, role, body,
):
    slug = f"kg10x-{abs(hash((method, path_tmpl))) % 100000}"
    _, _, _, project_a = await _private_project(client, db_session, service_headers, f"{slug}-a")
    tenant_b, user_b, _, _ = await _private_project(client, db_session, service_headers, f"{slug}-b")

    path = path_tmpl.format(pid=project_a.id)
    r = await _call(client, method, path, _headers(tenant_b, user_b, role), body)
    assert r.status_code == 404, f"{method} {path_tmpl} -> {r.status_code}, expected 404: {r.text}"


#  These two routes legitimately 404 on a brand-new project with no data yet
# (no build #1 exists; no health check has ever run) -- that's a real "not
# found", not an access denial, so the owner sanity check below expects it.
_EXPECTED_EMPTY_STATE_404 = {
    "/api/projects/{pid}/knowledge-graph/builds/1",
    "/api/projects/{pid}/knowledge-graph/health",
}


@pytest.mark.parametrize("method,path_tmpl,role,body", KG_ROUTES)
async def test_route_allows_the_owner(
    client, db_session, service_headers, method, path_tmpl, role, body,
):
    """Sanity check: the same matrix doesn't just fail closed for everyone --
    the project's own owner must still get through to the route's own logic
    (whatever it returns, never a 403 access denial, and never a 404 except
    the genuine empty-state cases above)."""
    tenant_id, owner_id, _, project = await _private_project(
        client, db_session, service_headers, f"kg10o-{abs(hash((method, path_tmpl))) % 100000}",
    )
    path = path_tmpl.format(pid=project.id)
    r = await _call(client, method, path, _headers(tenant_id, owner_id, role), body)
    if path_tmpl in _EXPECTED_EMPTY_STATE_404:
        assert r.status_code == 404, f"{method} {path_tmpl} -> {r.status_code} for the owner: {r.text}"
    else:
        assert r.status_code not in (403, 404), f"{method} {path_tmpl} -> {r.status_code} for the owner: {r.text}"
