"""Tests for surfacing a Google Sheets reauth prompt from /api/query/datasource.

Live finding: "click on a table" for an already-created Google Sheets source
runs its query live through Teiid (not through the platform-api Google Drive
routes already fixed for reauth in ``spreadsheet_connections.py``). When the
stored refresh token is rejected, Teiid's own resource adapter fails the
query with a raw error string embedding its datasource name (e.g. "Query
failed: TEIID30504 ds_378_google-sheets: Google token refresh failed 400
..."), which previously reached the UI as a dead-end 502 instead of a
reconnect prompt.

Run from ``platform-api``:
``pytest -q tests/test_query_datasource_reauth.py``.
"""

from __future__ import annotations

import pytest

from app.auth.jwt import create_access_token
from app.models.database_data_source import DatabaseDataSource
from app.models.file_source_meta import FileSourceMeta
from app.models.project import Project
from app.models.user_vdb import UserVDB
from app.routes.query_sql_helpers import (
    SourceReauthRequiredError,
    _google_sheets_reauth_source_id,
)

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


async def _tenant(client, service_headers, slug: str) -> int:
    r = await client.post(
        "/api/tenants", json={"slug": slug, "name": f"{slug} tenant"}, headers=service_headers
    )
    assert r.status_code == 201
    return r.json()["id"]


async def _user(client, service_headers, tenant_id: int, email: str) -> int:
    r = await client.post(
        f"/api/tenants/{tenant_id}/users",
        json={
            "email": email,
            "display_name": "Q User",
            "role": "editor",
            "external_id": f"ext-{email}",
        },
        headers=service_headers,
    )
    assert r.status_code == 201
    return r.json()["id"]


class _FakeEndpoint:
    pg_host = "localhost"
    pg_port = 5433


class _FakeResolver:
    def __init__(self, session):
        pass

    async def resolve_for_org(self, tenant_id):
        return _FakeEndpoint()


async def _setup_project_with_sheet(client, db_session, service_headers, slug: str):
    tenant_id = await _tenant(client, service_headers, slug)
    owner_id = await _user(client, service_headers, tenant_id, f"owner@{slug}.com")

    project = Project(tenant_id=tenant_id, owner_id=owner_id, name="Mine", is_shared=False)
    db_session.add(project)
    db_session.add(
        UserVDB(
            tenant_id=tenant_id, user_id=owner_id, vdb_id="owner-vdb",
            vdb_username="u", encrypted_password="p", is_active=True,
        )
    )
    await db_session.commit()
    await db_session.refresh(project)

    sheet = FileSourceMeta(
        tenant_id=tenant_id, project_id=project.id, owner_id=owner_id,
        view_name="revenue_GOOGLE", file_name="Revenue", column_types=[],
        source_format="google_sheet", acquisition_method="google_drive",
        live_source_params={"spreadsheet_id": "abc", "connector_credential_id": 42},
    )
    db_session.add(sheet)
    await db_session.commit()
    await db_session.refresh(sheet)

    return tenant_id, owner_id, project, sheet


async def test_table_path_reports_reauth_required_on_a_google_sheets_token_failure(
    client, db_session, service_headers, monkeypatch
):
    tenant_id, owner_id, project, sheet = await _setup_project_with_sheet(
        client, db_session, service_headers, "qd-reauth-table"
    )

    import app.routes.query as query_module

    async def fake_project_table_schema(session, *, tenant_id, project_id):
        return [{"table": sheet.view_name, "columns": []}]

    async def fake_run_sql(**kwargs):
        raise SourceReauthRequiredError(
            f"Query failed: TEIID30504 ds_{sheet.id}_google-sheets: "
            "Google token refresh failed 400 invalid_grant",
            file_source_meta_id=sheet.id,
        )

    monkeypatch.setattr(query_module, "project_table_schema", fake_project_table_schema)
    monkeypatch.setattr(query_module, "_run_sql", fake_run_sql)
    monkeypatch.setattr(query_module, "TenantTeiidResolver", _FakeResolver)

    r = await client.post(
        "/api/query/datasource",
        json={"project_id": project.id, "tableName": sheet.view_name},
        headers=_headers(tenant_id, owner_id),
    )
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["code"] == "CONNECTOR_REAUTH_REQUIRED"
    assert detail["credentialId"] == 42


async def test_sql_path_reports_reauth_required_on_a_google_sheets_token_failure(
    client, db_session, service_headers, monkeypatch
):
    tenant_id, owner_id, project, sheet = await _setup_project_with_sheet(
        client, db_session, service_headers, "qd-reauth-sql"
    )

    import app.routes.query as query_module

    async def fake_project_table_schema(session, *, tenant_id, project_id):
        return [{"table": sheet.view_name, "columns": []}]

    async def fake_execute_sql_with_repair(**kwargs):
        raise SourceReauthRequiredError(
            f"Query failed: TEIID30504 ds_{sheet.id}_google-sheets: "
            "Google token refresh failed 400 invalid_grant",
            file_source_meta_id=sheet.id,
        )

    monkeypatch.setattr(query_module, "project_table_schema", fake_project_table_schema)
    monkeypatch.setattr(
        query_module, "_execute_sql_with_repair", fake_execute_sql_with_repair
    )
    monkeypatch.setattr(query_module, "TenantTeiidResolver", _FakeResolver)

    r = await client.post(
        "/api/query/datasource",
        json={"project_id": project.id, "sql": f'SELECT * FROM "{sheet.view_name}"'},
        headers=_headers(tenant_id, owner_id),
    )
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["code"] == "CONNECTOR_REAUTH_REQUIRED"
    assert detail["credentialId"] == 42


async def test_reauth_required_with_no_resolvable_credential_still_returns_409(
    client, db_session, service_headers, monkeypatch
):
    """A source id Teiid names that no longer maps to a FileSourceMeta row
    (deleted, or the message is misparsed) must still surface a reconnect
    prompt rather than falling back to a dead-end 502."""
    tenant_id, owner_id, project, sheet = await _setup_project_with_sheet(
        client, db_session, service_headers, "qd-reauth-missing"
    )

    import app.routes.query as query_module

    async def fake_project_table_schema(session, *, tenant_id, project_id):
        return [{"table": sheet.view_name, "columns": []}]

    async def fake_run_sql(**kwargs):
        raise SourceReauthRequiredError(
            "Query failed: TEIID30504 ds_999999_google-sheets: "
            "Google token refresh failed 400 invalid_grant",
            file_source_meta_id=999999,
        )

    monkeypatch.setattr(query_module, "project_table_schema", fake_project_table_schema)
    monkeypatch.setattr(query_module, "_run_sql", fake_run_sql)
    monkeypatch.setattr(query_module, "TenantTeiidResolver", _FakeResolver)

    r = await client.post(
        "/api/query/datasource",
        json={"project_id": project.id, "tableName": sheet.view_name},
        headers=_headers(tenant_id, owner_id),
    )
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["code"] == "CONNECTOR_REAUTH_REQUIRED"
    assert "credentialId" not in detail


async def test_a_non_reauth_teiid_failure_still_returns_a_plain_502(
    client, db_session, service_headers, monkeypatch
):
    """An unrelated Teiid failure against the same source (e.g. a genuinely
    bad query) must not be misreported as a reauth prompt."""
    tenant_id, owner_id, project, sheet = await _setup_project_with_sheet(
        client, db_session, service_headers, "qd-reauth-unrelated"
    )

    import app.routes.query as query_module
    from fastapi import HTTPException

    async def fake_project_table_schema(session, *, tenant_id, project_id):
        return [{"table": sheet.view_name, "columns": []}]

    async def fake_run_sql(**kwargs):
        raise HTTPException(
            status_code=502,
            detail=f'Query failed: TEIID30504 ds_{sheet.id}_google-sheets: connection reset',
        )

    monkeypatch.setattr(query_module, "project_table_schema", fake_project_table_schema)
    monkeypatch.setattr(query_module, "_run_sql", fake_run_sql)
    monkeypatch.setattr(query_module, "TenantTeiidResolver", _FakeResolver)

    r = await client.post(
        "/api/query/datasource",
        json={"project_id": project.id, "tableName": sheet.view_name},
        headers=_headers(tenant_id, owner_id),
    )
    assert r.status_code == 502


def test_google_sheets_reauth_source_id_extracts_the_id_when_auth_related():
    err = (
        "Query failed: TEIID30504 ds_378_google-sheets: "
        "Google token refresh failed 400 invalid_grant"
    )
    assert _google_sheets_reauth_source_id(err) == 378


def test_google_sheets_reauth_source_id_is_none_for_a_non_auth_failure():
    err = "Query failed: TEIID30504 ds_378_google-sheets: connection reset by peer"
    assert _google_sheets_reauth_source_id(err) is None


def test_google_sheets_reauth_source_id_is_none_for_a_non_google_sheets_source():
    err = "Query failed: TEIID30504 ds_378_servicenow: credential rejected, refresh failed"
    assert _google_sheets_reauth_source_id(err) is None
