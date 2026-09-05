"""Route-level test: a SaaS connector reporting ``requires_reauth`` must
surface as a structured, detectable error, not a plain 400.

Live finding: clicking "Create Data Source" on a SaaS connection whose
credentials had been rejected by the SaaS API (e.g. ServiceNow returning 401)
showed a dead-end error with no way to fix the connection from there. The
frontend needs a reliable signal (``detail.code``) to prompt reconnecting
instead of parsing English error text.

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
