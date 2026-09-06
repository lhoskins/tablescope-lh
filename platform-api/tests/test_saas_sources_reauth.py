"""Route-level tests for SaaS connector reauthorization.

Live finding #1: clicking "Create Data Source" on a SaaS connection whose
credentials had been rejected by the SaaS API (e.g. ServiceNow returning 401)
showed a dead-end error with no way to fix the connection from there. The
frontend needs a reliable signal (``detail.code``) to prompt reconnecting
instead of parsing English error text.

Live finding #2: the same root cause as the Google Drive reauth fix, but for
ServiceNow/Salesforce/HubSpot/QuickBooks -- these "live" sources are
registered directly into Teiid with a *copy* of the credential's username/
password/access token at creation time. Reconnecting a broken credential via
``PATCH /saas-sources/credentials/{id}`` updated the stored credential but
never re-registered an already-created live source, so a table created
before the reconnect kept failing on the stale value even after the
connection was "successfully" reconnected.

Run from ``platform-api``: ``pytest -q tests/test_saas_sources_reauth.py``.
"""

from __future__ import annotations

import pytest

from app.auth.jwt import create_access_token
from app.connectors.base import ObjectInfo, SaasConnectorError

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


def _headers(tenant_id: int, user_id: int) -> dict:
    token = create_access_token(sub="u", tenant_id=tenant_id, user_id=user_id, role="editor")
    return {"Authorization": f"Bearer {token}"}


async def _setup(client, service_headers, slug: str):
    r = await client.post(
        "/api/tenants", json={"slug": slug, "name": f"{slug} tenant"}, headers=service_headers
    )
    assert r.status_code == 201
    tenant = r.json()
    r = await client.post(
        f"/api/tenants/{tenant['id']}/users",
        json={
            "email": f"{slug}@test.com",
            "display_name": "SaaS User",
            "role": "editor",
            "external_id": f"ext-{slug}",
        },
        headers=service_headers,
    )
    assert r.status_code == 201
    user = r.json()
    return tenant, user, _headers(tenant["id"], user["id"])


async def test_list_objects_reports_reauth_required_when_connector_rejects_credentials(
    client, service_headers, monkeypatch
):
    import app.routes.saas_sources as routes

    tenant, _user, headers = await _setup(client, service_headers, "saas-reauth-objects")

    r = await client.post(
        "/api/saas-sources/credentials",
        json={"connector_type": "servicenow", "display_name": "ServiceNow Dev", "config": {}},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    credential_id = r.json()["id"]

    class _FakeConnector:
        async def list_objects(self, config):
            raise SaasConnectorError(
                "ServiceNow rejected the credentials. Check the instance URL, username, and password.",
                requires_reauth=True,
            )

    monkeypatch.setattr(routes, "get_connector", lambda connector_type: _FakeConnector())

    r = await client.post(
        "/api/saas-sources/objects",
        json={"credential_id": credential_id},
        headers=headers,
    )
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "CONNECTOR_REAUTH_REQUIRED"


async def test_list_objects_reports_a_plain_400_for_a_non_auth_failure(
    client, service_headers, monkeypatch
):
    import app.routes.saas_sources as routes

    tenant, _user, headers = await _setup(client, service_headers, "saas-non-reauth-objects")

    r = await client.post(
        "/api/saas-sources/credentials",
        json={"connector_type": "servicenow", "display_name": "ServiceNow Dev", "config": {}},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    credential_id = r.json()["id"]

    class _FakeConnector:
        async def list_objects(self, config):
            raise SaasConnectorError("ServiceNow API error (HTTP 500).")

    monkeypatch.setattr(routes, "get_connector", lambda connector_type: _FakeConnector())

    r = await client.post(
        "/api/saas-sources/objects",
        json={"credential_id": credential_id},
        headers=headers,
    )
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == "ServiceNow API error (HTTP 500)."


async def test_list_objects_still_works_normally_when_credentials_are_valid(
    client, service_headers, monkeypatch
):
    import app.routes.saas_sources as routes

    tenant, _user, headers = await _setup(client, service_headers, "saas-reauth-ok")

    r = await client.post(
        "/api/saas-sources/credentials",
        json={"connector_type": "servicenow", "display_name": "ServiceNow Dev", "config": {}},
        headers=headers,
    )
    credential_id = r.json()["id"]

    class _FakeConnector:
        async def list_objects(self, config):
            return [ObjectInfo(name="change_request", label="Change Request")]

    monkeypatch.setattr(routes, "get_connector", lambda connector_type: _FakeConnector())

    r = await client.post(
        "/api/saas-sources/objects",
        json={"credential_id": credential_id},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["objects"] == [{"name": "change_request", "label": "Change Request"}]


async def test_reconnecting_a_credential_reregisters_its_live_sources(
    client, db_session, service_headers, monkeypatch
):
    """The reported bug: reconnecting ServiceNow updates the stored
    credential, but an already-created ServiceNow table must also be
    re-registered against Teiid with the new credentials -- otherwise it
    keeps failing on the stale value the same way it did before "reconnect"."""
    import app.services.saas_source_service as saas_source_service

    tenant, user, headers = await _setup(client, service_headers, "saas-reregister")

    r = await client.post(
        "/api/saas-sources/credentials",
        json={
            "connector_type": "servicenow",
            "display_name": "ServiceNow Dev",
            "config": {
                "instance_url": "https://dev.service-now.com",
                "username": "old-user",
                "password": "old-pass",
            },
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    credential_id = r.json()["id"]

    from app.models.database_data_source import DatabaseDataSource, DataSourceColumn
    from app.models.saas_object_data_source import SaasObjectDataSource
    from app.models.user_vdb import UserVDB

    db_session.add(
        UserVDB(
            tenant_id=tenant["id"], user_id=user["id"], vdb_id="user-vdb",
            vdb_username="u", encrypted_password="p", is_active=True,
        )
    )
    ds = DatabaseDataSource(
        tenant_id=tenant["id"], project_id=None, created_by=user["id"],
        display_name="Change Request", source_type="saas_object",
        connector_type="servicenow", db_type="servicenow",
        host="https://dev.service-now.com", port=0, database_name="",
        schema_name="", table_name="change_request",
        username="old-user", teiid_model_name="ds_1_src",
        teiid_table_name="change_request", teiid_view_name="change_request_SERVICENOW",
        teiid_jndi_name="java:/ds_1_servicenow", status="active", archived=False,
    )
    db_session.add(ds)
    await db_session.commit()
    await db_session.refresh(ds)
    db_session.add(
        DataSourceColumn(
            data_source_id=ds.id, column_name="number", ordinal_position=1,
            data_type="text", nullable=True, primary_key=False,
        )
    )
    db_session.add(
        SaasObjectDataSource(
            tenant_id=tenant["id"], database_data_source_id=ds.id,
            credential_id=credential_id, connector_type="servicenow",
            object_type="change_request", selected_properties=["number"],
            staging_schema="", staging_table="", sync_mode="live",
            last_sync_status="live",
        )
    )
    await db_session.commit()

    captured: dict = {}

    class _FakeReg:
        def __init__(self):
            pass

        async def register_servicenow_source(self, **kwargs):
            captured.update(kwargs)
            return {"success": True}

        async def aclose(self):
            pass

    monkeypatch.setattr(saas_source_service, "TeiidRegistrationService", _FakeReg)

    r = await client.patch(
        f"/api/saas-sources/credentials/{credential_id}",
        json={
            "config": {
                "instance_url": "https://dev.service-now.com",
                "username": "new-user",
                "password": "new-pass",
            }
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text

    assert captured["username"] == "new-user"
    assert captured["password"] == "new-pass"
    assert captured["object_type"] == "change_request"
    assert captured["view_name"] == "change_request_SERVICENOW"
    assert captured["columns"] == [
        {"name": "number", "name_in_source": "number", "teiid_type": "string"}
    ]


async def test_reconnecting_a_credential_does_not_reregister_a_manual_sync_source(
    client, db_session, service_headers, monkeypatch
):
    """A staged (non-"live") SaaS source has no baked-in Teiid credential to
    go stale -- re-registering it on every credential update would be
    pointless Teiid churn, so it must be skipped."""
    import app.services.saas_source_service as saas_source_service

    tenant, user, headers = await _setup(client, service_headers, "saas-reregister-manual")

    r = await client.post(
        "/api/saas-sources/credentials",
        json={"connector_type": "hubspot", "display_name": "HubSpot", "config": {}},
        headers=headers,
    )
    credential_id = r.json()["id"]

    from app.models.database_data_source import DatabaseDataSource
    from app.models.saas_object_data_source import SaasObjectDataSource

    ds = DatabaseDataSource(
        tenant_id=tenant["id"], project_id=None, created_by=user["id"],
        display_name="Contacts", source_type="saas_object",
        connector_type="hubspot", db_type="postgresql",
        host="db", port=5432, database_name="tablescope",
        schema_name="saas_staging", table_name="hubspot_ds_1_contacts",
        username="postgres", teiid_model_name="ds_1_src",
        teiid_table_name="hubspot_ds_1_contacts", teiid_view_name="Contacts_HUBSPOT",
        teiid_jndi_name="java:/ds_1_postgresql", status="active", archived=False,
    )
    db_session.add(ds)
    await db_session.commit()
    await db_session.refresh(ds)
    db_session.add(
        SaasObjectDataSource(
            tenant_id=tenant["id"], database_data_source_id=ds.id,
            credential_id=credential_id, connector_type="hubspot",
            object_type="contacts", selected_properties=["email"],
            staging_schema="saas_staging", staging_table="hubspot_ds_1_contacts",
            sync_mode="manual", last_sync_status="pending",
        )
    )
    await db_session.commit()

    class _FakeReg:
        def __init__(self):
            raise AssertionError(
                "TeiidRegistrationService must not be constructed for a manual-sync source"
            )

    monkeypatch.setattr(saas_source_service, "TeiidRegistrationService", _FakeReg)

    r = await client.patch(
        f"/api/saas-sources/credentials/{credential_id}",
        json={"config": {"access_token": "new-token"}},
        headers=headers,
    )
    assert r.status_code == 200, r.text


async def test_reconnecting_a_credential_without_a_config_change_skips_reregistration(
    client, service_headers, monkeypatch
):
    """Renaming a connection (display_name only, no config) has nothing to
    re-register -- Teiid is not touched."""
    import app.routes.saas_sources as routes

    tenant, _user, headers = await _setup(client, service_headers, "saas-rename-only")

    r = await client.post(
        "/api/saas-sources/credentials",
        json={"connector_type": "servicenow", "display_name": "Old Name", "config": {}},
        headers=headers,
    )
    credential_id = r.json()["id"]

    called = False

    async def fake_reregister(session, credential):
        nonlocal called
        called = True
        return 0

    monkeypatch.setattr(routes, "reregister_live_saas_sources_for_credential", fake_reregister)

    r = await client.patch(
        f"/api/saas-sources/credentials/{credential_id}",
        json={"display_name": "New Name"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert called is False
