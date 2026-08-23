"""Unit tests for project workspace active-resource resolution."""

from __future__ import annotations

import pytest

from app.auth.jwt import create_access_token
from app.services.supabase_auth_service import SupabaseAuthService, SupabaseUser
from app.services.workspace_context import resolve_active_resource_context

pytestmark = pytest.mark.anyio


class _FakeSupabase(SupabaseAuthService):
    def __init__(self) -> None:
        pass

    async def create_or_invite_user(
        self, email, *, first_name=None, last_name=None, redirect_to=None
    ) -> SupabaseUser:
        return SupabaseUser(
            id=f"supa-{email}",
            email=email,
            created=True,
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


def _headers(tenant_id: int, user_id: int, role: str = "editor") -> dict:
    token = create_access_token(sub="u", tenant_id=tenant_id, user_id=user_id, role=role)
    return {"Authorization": f"Bearer {token}"}


async def _setup(client, service_headers, slug: str):
    r = await client.post(
        "/api/tenants",
        json={"slug": slug, "name": f"{slug} tenant"},
        headers=service_headers,
    )
    assert r.status_code == 201
    tenant = r.json()

    r = await client.post(
        f"/api/tenants/{tenant['id']}/users",
        json={
            "email": f"{slug}@test.com",
            "display_name": "Workspace User",
            "role": "editor",
            "external_id": f"ext-{slug}",
        },
        headers=service_headers,
    )
    assert r.status_code == 201
    user = r.json()
    headers = _headers(tenant["id"], user["id"])

    r = await client.post(
        "/api/projects",
        json={"name": "Workspace Project", "description": "x", "is_shared": False},
        headers=headers,
    )
    assert r.status_code == 201
    project = r.json()
    return tenant, user, project, headers


async def test_resolve_table_returns_label_and_summary(client, db_session, service_headers):
    tenant, _, project, _ = await _setup(client, service_headers, "wc-table")
    from app.models import SavedQuery

    query = SavedQuery(
        project_id=project["id"], name="Top Customers", sql_text="SELECT 1"
    )
    db_session.add(query)
    await db_session.commit()
    await db_session.refresh(query)

    ctx = await resolve_active_resource_context(
        db_session,
        project_id=project["id"],
        resource_type="table",
        resource_id=query.id,
    )
    assert ctx is not None
    assert ctx.label == "Top Customers"
    assert "Top Customers" in ctx.summary


async def test_resolve_dashboard_returns_label_and_summary(client, db_session, service_headers):
    tenant, _, project, _ = await _setup(client, service_headers, "wc-dash")
    from app.models import Dashboard

    dashboard = Dashboard(
        project_id=project["id"],
        tenant_id=tenant["id"],
        name="Revenue Overview",
        config={"widgets": [{"id": 1}, {"id": 2}]},
    )
    db_session.add(dashboard)
    await db_session.commit()
    await db_session.refresh(dashboard)

    ctx = await resolve_active_resource_context(
        db_session,
        project_id=project["id"],
        resource_type="dashboard",
        resource_id=dashboard.id,
    )
    assert ctx is not None
    assert ctx.label == "Revenue Overview"
    assert "2 widget(s)" in ctx.summary


async def test_resolve_document_returns_label_and_summary(client, db_session, service_headers):
    tenant, _, project, _ = await _setup(client, service_headers, "wc-doc")
    from app.models import ProjectAsset

    asset = ProjectAsset(
        tenant_id=tenant["id"],
        project_id=project["id"],
        asset_type="pdf",
        title="Q3 Board Deck",
        filename="q3.pdf",
        storage_location="local://q3.pdf",
    )
    db_session.add(asset)
    await db_session.commit()
    await db_session.refresh(asset)

    ctx = await resolve_active_resource_context(
        db_session,
        project_id=project["id"],
        resource_type="document",
        resource_id=asset.id,
    )
    assert ctx is not None
    assert ctx.label == "Q3 Board Deck"


async def test_resolve_data_source_returns_label_and_summary(client, db_session, service_headers):
    tenant, _, project, _ = await _setup(client, service_headers, "wc-ds")
    from app.models import DatabaseDataSource

    source = DatabaseDataSource(
        tenant_id=tenant["id"],
        project_id=project["id"],
        display_name="Prod Sales DB",
        db_type="postgres",
        host="db.internal",
        port=5432,
        database_name="sales",
        table_name="orders",
        username="reader",
        teiid_model_name="m",
        teiid_table_name="t",
        teiid_view_name="v",
        teiid_jndi_name="j",
    )
    db_session.add(source)
    await db_session.commit()
    await db_session.refresh(source)

    ctx = await resolve_active_resource_context(
        db_session,
        project_id=project["id"],
        resource_type="data_source",
        resource_id=source.id,
    )
    assert ctx is not None
    assert ctx.label == "Prod Sales DB"
    assert "orders" in ctx.summary


async def test_resolve_returns_none_for_resource_in_another_project(
    client, db_session, service_headers
):
    tenant, _, project, _ = await _setup(client, service_headers, "wc-other-project")
    from app.models import SavedQuery

    query = SavedQuery(project_id=project["id"], name="Private Table")
    db_session.add(query)
    await db_session.commit()
    await db_session.refresh(query)

    ctx = await resolve_active_resource_context(
        db_session,
        project_id=project["id"] + 999999,
        resource_type="table",
        resource_id=query.id,
    )
    assert ctx is None


@pytest.mark.parametrize(
    "resource_type,resource_id",
    [(None, 1), ("not_a_type", 1), ("table", None)],
)
async def test_resolve_returns_none_for_invalid_input(
    db_session, resource_type, resource_id
):
    ctx = await resolve_active_resource_context(
        db_session,
        project_id=1,
        resource_type=resource_type,
        resource_id=resource_id,
    )
    assert ctx is None


async def test_resolve_returns_none_for_missing_resource_id(client, db_session, service_headers):
    _, _, project, _ = await _setup(client, service_headers, "wc-missing")
    ctx = await resolve_active_resource_context(
        db_session,
        project_id=project["id"],
        resource_type="dashboard",
        resource_id=999999999,
    )
    assert ctx is None
