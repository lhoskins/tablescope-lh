"""Tests for auto-creating a saved query when a data source is created."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.auth.jwt import create_access_token
from app.models.saved_query import SavedQuery
from app.services.auto_query import (
    default_sql,
    ensure_datasource_query,
    strip_extension,
)


def test_strip_extension() -> None:
    assert strip_extension("SUP Parts.xlsx") == "SUP Parts"
    assert strip_extension("SUP Parts.CSV") == "SUP Parts"
    assert strip_extension("orders.json") == "orders"
    assert strip_extension("data.parquet") == "data"
    assert strip_extension("no_extension") == "no_extension"
    # Only strips a single trailing known extension.
    assert strip_extension("report.2024.tsv") == "report.2024"


def test_default_sql_explicit_columns() -> None:
    sql = default_sql("SUP_Parts_CSV", ["PartNumber", "PartName"])
    assert sql == 'SELECT\n  "PartNumber",\n  "PartName"\nFROM "SUP_Parts_CSV"'


def test_default_sql_falls_back_to_star() -> None:
    assert default_sql("SUP_Parts_CSV", None) == 'SELECT * FROM "SUP_Parts_CSV"'
    assert default_sql("SUP_Parts_CSV", []) == 'SELECT * FROM "SUP_Parts_CSV"'


def _editor_headers(tenant_id: int, user_id: int) -> dict:
    token = create_access_token(
        sub="u", tenant_id=tenant_id, user_id=user_id, role="editor"
    )
    return {"Authorization": f"Bearer {token}"}


async def _project(client, service_headers):
    r = await client.post(
        "/api/tenants",
        json={"slug": "aq-tenant", "name": "Auto Query Tenant"},
        headers=service_headers,
    )
    assert r.status_code == 201
    tenant = r.json()
    r = await client.post(
        f"/api/tenants/{tenant['id']}/users",
        json={
            "email": "aq@test.com",
            "display_name": "AQ User",
            "role": "editor",
            "external_id": "ext-aq",
        },
        headers=service_headers,
    )
    assert r.status_code == 201
    user = r.json()
    headers = _editor_headers(tenant["id"], user["id"])
    r = await client.post(
        "/api/projects",
        json={"name": "AQ Project", "description": "t", "is_shared": False},
        headers=headers,
    )
    assert r.status_code == 201
    return r.json(), user, headers


@pytest.fixture(autouse=True)
def _mock_supabase(monkeypatch):
    import app.routes.tenants as tenants_module
    from app.services.supabase_auth_service import (
        SupabaseAuthService,
        SupabaseUser,
    )

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
        async def send(self, spec, *, to, template) -> bool:
            return True

    monkeypatch.setattr(tenants_module, "SupabaseAuthService", _FakeSupabase)
    monkeypatch.setattr(tenants_module, "EmailService", _FakeEmail)


async def test_ensure_datasource_query_creates_and_dedupes(
    client, db_session, service_headers
) -> None:
    project, user, headers = await _project(client, service_headers)
    pid = project["id"]

    created = await ensure_datasource_query(
        db_session,
        project_id=pid,
        owner_id=user["id"],
        display_name="SUP Parts.xlsx",
        view_name="SUP_Parts_CSV",
        columns=["PartNumber", "PartName"],
    )
    await db_session.commit()
    assert created is not None
    assert created.name == "SUP Parts"
    assert created.left_datasource == "SUP_Parts_CSV"
    assert created.ai_generated is False
    assert '"PartNumber"' in created.sql_text

    # Calling again for the same view does not create a duplicate.
    again = await ensure_datasource_query(
        db_session,
        project_id=pid,
        owner_id=user["id"],
        display_name="SUP Parts.xlsx",
        view_name="SUP_Parts_CSV",
        columns=["PartNumber"],
    )
    await db_session.commit()
    assert again.id == created.id

    rows = (
        await db_session.scalars(
            select(SavedQuery).where(SavedQuery.project_id == pid)
        )
    ).all()
    assert len(rows) == 1


async def test_ensure_datasource_query_suffixes_name_clash(
    client, db_session, service_headers
) -> None:
    project, user, headers = await _project(client, service_headers)
    pid = project["id"]

    # A manual query already occupies the name "SUP Parts".
    r = await client.post(
        f"/api/projects/{pid}/queries",
        json={"name": "SUP Parts", "left_datasource": "other_view"},
        headers=headers,
    )
    assert r.status_code == 201

    created = await ensure_datasource_query(
        db_session,
        project_id=pid,
        owner_id=user["id"],
        display_name="SUP Parts.csv",
        view_name="SUP_Parts_CSV",
        columns=None,
    )
    await db_session.commit()
    assert created is not None
    assert created.name == "SUP Parts (2)"


async def test_ensure_datasource_query_no_project_returns_none(
    db_session,
) -> None:
    result = await ensure_datasource_query(
        db_session,
        project_id=None,
        owner_id=1,
        display_name="x.csv",
        view_name="x",
    )
    assert result is None
