"""Tests for surfacing a reauth prompt from /api/query/datasource.

Live finding: "click on a table" for an already-created live-translator
source (Google Sheets, or a ServiceNow/Salesforce/HubSpot/QuickBooks "live"
object) runs its query live through Teiid (not through the platform-api
routes already fixed for reauth in ``spreadsheet_connections.py``/
``saas_sources.py``). When the stored credential is rejected, Teiid's own
translator fails the query with a raw error string embedding its datasource
name (e.g. "Query failed: TEIID30504 ds_378_google-sheets: Google token
refresh failed 400 ..." or "Query failed: TEIID30504 ds_42_servicenow:
ServiceNow HTTP 401: ... User is not authenticated ..."), which previously
reached the UI as a dead-end 502 instead of a reconnect prompt.

Run from ``platform-api``:
``pytest -q tests/test_query_datasource_reauth.py``.
"""

from __future__ import annotations

import pytest

from app.auth.jwt import create_access_token
from app.models.database_data_source import DatabaseDataSource
from app.models.file_source_meta import FileSourceMeta
from app.models.project import Project
from app.models.saas_object_data_source import SaasObjectDataSource
from app.models.user_vdb import UserVDB
from app.routes.query_sql_helpers import (
    SourceReauthRequiredError,
    _live_translator_reauth_match,
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


async def _setup_project_with_servicenow_table(client, db_session, service_headers, slug: str):
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

    ds = DatabaseDataSource(
        tenant_id=tenant_id, project_id=project.id, created_by=owner_id,
        display_name="alm_asset", source_type="saas_object",
        connector_type="servicenow", db_type="servicenow",
        host="https://dev.service-now.com", port=0, database_name="",
        schema_name="", table_name="alm_asset",
        username="svc", teiid_model_name="ds_1_src",
        teiid_table_name="alm_asset", teiid_view_name="alm_asset_SERVICENOW",
        teiid_jndi_name="java:/ds_1_servicenow", status="active", archived=False,
    )
    db_session.add(ds)
    await db_session.commit()
    await db_session.refresh(ds)
    db_session.add(
        SaasObjectDataSource(
            tenant_id=tenant_id, database_data_source_id=ds.id, credential_id=99,
            connector_type="servicenow", object_type="alm_asset",
            selected_properties=["number"], staging_schema="", staging_table="",
            sync_mode="live", last_sync_status="live",
        )
    )
    await db_session.commit()

    return tenant_id, owner_id, project, ds


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
            data_source_id=sheet.id,
            connector_type="google-sheets",
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
    assert detail["connectorType"] == "google_drive"


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
            data_source_id=sheet.id,
            connector_type="google-sheets",
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
    assert detail["connectorType"] == "google_drive"


async def test_table_path_reports_reauth_required_on_a_servicenow_401(
    client, db_session, service_headers, monkeypatch
):
    """The reported bug: "click on a table" for an already-created
    ServiceNow object surfaces the raw Teiid 401 instead of a reauth
    prompt, even after "Create Data Source" already showed the correct
    Reconnect action for the same broken credential."""
    tenant_id, owner_id, project, ds = await _setup_project_with_servicenow_table(
        client, db_session, service_headers, "qd-reauth-servicenow"
    )

    import app.routes.query as query_module

    async def fake_project_table_schema(session, *, tenant_id, project_id):
        return [{"table": ds.teiid_view_name, "columns": []}]

    async def fake_run_sql(**kwargs):
        raise SourceReauthRequiredError(
            f'Query failed: TEIID30504 ds_{ds.id}_servicenow: ServiceNow HTTP 401: '
            '{"error":{"message":"User is not authenticated",'
            '"detail":"Required to provide Auth information"},"status":"failure"}',
            data_source_id=ds.id,
            connector_type="servicenow",
        )

    monkeypatch.setattr(query_module, "project_table_schema", fake_project_table_schema)
    monkeypatch.setattr(query_module, "_run_sql", fake_run_sql)
    monkeypatch.setattr(query_module, "TenantTeiidResolver", _FakeResolver)

    r = await client.post(
        "/api/query/datasource",
        json={"project_id": project.id, "tableName": ds.teiid_view_name},
        headers=_headers(tenant_id, owner_id),
    )
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["code"] == "CONNECTOR_REAUTH_REQUIRED"
    assert detail["credentialId"] == 99
    assert detail["connectorType"] == "servicenow"


async def test_reauth_required_with_no_resolvable_credential_still_returns_409(
    client, db_session, service_headers, monkeypatch
):
    """A source id Teiid names that no longer maps to a row (deleted, or the
    message is misparsed) must still surface a reconnect prompt rather than
    falling back to a dead-end 502."""
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
            data_source_id=999999,
            connector_type="google-sheets",
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

    from fastapi import HTTPException

    import app.routes.query as query_module

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


def test_live_translator_reauth_match_extracts_google_sheets_id_and_type():
    err = (
        "Query failed: TEIID30504 ds_378_google-sheets: "
        "Google token refresh failed 400 invalid_grant"
    )
    assert _live_translator_reauth_match(err) == (378, "google-sheets")


def test_live_translator_reauth_match_extracts_servicenow_401():
    err = (
        'Query failed: TEIID30504 ds_42_servicenow: ServiceNow HTTP 401: '
        '{"error":{"message":"User is not authenticated"}}'
    )
    assert _live_translator_reauth_match(err) == (42, "servicenow")


@pytest.mark.parametrize("connector_type", ["salesforce", "hubspot", "quickbooks"])
def test_live_translator_reauth_match_extracts_other_saas_connectors(connector_type):
    err = f"Query failed: TEIID30504 ds_7_{connector_type}: HTTP 401: unauthorized"
    assert _live_translator_reauth_match(err) == (7, connector_type)


def test_live_translator_reauth_match_is_none_for_a_non_auth_failure():
    err = "Query failed: TEIID30504 ds_378_google-sheets: connection reset by peer"
    assert _live_translator_reauth_match(err) is None


def test_live_translator_reauth_match_is_none_for_an_unknown_source_type():
    err = "Query failed: TEIID30504 ds_378_mysql: HTTP 401 unauthorized"
    assert _live_translator_reauth_match(err) is None
