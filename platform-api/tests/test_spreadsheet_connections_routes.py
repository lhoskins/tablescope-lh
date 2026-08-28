"""Tests for the Google Drive Spreadsheet connector routes.

Increment 1 scope: OAuth connection + read-only file/tab/range discovery.
Does not cover Teiid data-source creation (not implemented yet -- see the
route module's docstring and the Devin handoff notes).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.auth.jwt import create_access_token

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


def _editor_headers(tenant_id: int, user_id: int) -> dict:
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
            "display_name": "GD User",
            "role": "editor",
            "external_id": f"ext-{slug}",
        },
        headers=service_headers,
    )
    assert r.status_code == 201
    user = r.json()
    headers = _editor_headers(tenant["id"], user["id"])
    return tenant, user, headers


async def test_routes_404_when_feature_flag_disabled(client, service_headers, monkeypatch):
    import app.routes.spreadsheet_connections as sc

    _tenant, _user, headers = await _setup(client, service_headers, "gd-disabled")
    monkeypatch.setattr(
        sc, "get_settings", lambda: SimpleNamespace(google_drive_connector_v1_enabled=False)
    )
    r = await client.post("/api/spreadsheet-connections/authorize", headers=headers)
    assert r.status_code == 404


async def test_authorize_returns_url_and_state_when_enabled(client, service_headers, monkeypatch):
    import app.routes.spreadsheet_connections as sc

    _tenant, _user, headers = await _setup(client, service_headers, "gd-authorize")
    monkeypatch.setattr(sc, "_require_feature_enabled", lambda: None)
    monkeypatch.setattr(sc.gd, "is_configured", lambda: True)
    monkeypatch.setattr(
        sc.gd, "build_authorization_url", lambda *, state: f"https://accounts.google.com/auth?state={state}"
    )

    r = await client.post("/api/spreadsheet-connections/authorize", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["authorizationUrl"].endswith(body["state"])


async def test_authorize_503_when_not_configured(client, service_headers, monkeypatch):
    import app.routes.spreadsheet_connections as sc

    _tenant, _user, headers = await _setup(client, service_headers, "gd-unconfigured")
    monkeypatch.setattr(sc, "_require_feature_enabled", lambda: None)
    monkeypatch.setattr(sc.gd, "is_configured", lambda: False)

    r = await client.post("/api/spreadsheet-connections/authorize", headers=headers)
    assert r.status_code == 503


async def test_callback_rejects_state_for_a_different_user(client, service_headers, monkeypatch):
    import app.routes.spreadsheet_connections as sc
    import app.services.google_drive.oauth as gd_oauth

    tenant, _user, headers = await _setup(client, service_headers, "gd-callback-bad-state")
    monkeypatch.setattr(sc, "_require_feature_enabled", lambda: None)

    other_user_state = gd_oauth.create_state_token(tenant_id=tenant["id"], user_id=999999)
    r = await client.post(
        "/api/spreadsheet-connections/callback",
        json={"code": "abc", "state": other_user_state},
        headers=headers,
    )
    assert r.status_code == 400


async def test_callback_success_creates_connector_credential(
    client, service_headers, monkeypatch
):
    import app.routes.spreadsheet_connections as sc
    import app.services.google_drive.oauth as gd_oauth

    tenant, user, headers = await _setup(client, service_headers, "gd-callback-ok")
    monkeypatch.setattr(sc, "_require_feature_enabled", lambda: None)

    state = gd_oauth.create_state_token(tenant_id=tenant["id"], user_id=user["id"])

    async def fake_exchange(*, code):
        assert code == "one-time-code"
        return {"access_token": "at", "refresh_token": "rt", "expires_at": 1e15}

    monkeypatch.setattr(sc.gd, "exchange_code_for_tokens", fake_exchange)

    r = await client.post(
        "/api/spreadsheet-connections/callback",
        json={"code": "one-time-code", "state": state, "display_name": "My Drive"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["connector_type"] == "google_drive"
    assert body["display_name"] == "My Drive"
    assert body["has_secret"] is True

    r = await client.get("/api/spreadsheet-connections", headers=headers)
    assert r.status_code == 200
    assert len(r.json()) == 1


async def test_list_files_uses_a_valid_access_token(client, service_headers, monkeypatch):
    import app.routes.spreadsheet_connections as sc
    import app.services.google_drive.oauth as gd_oauth

    tenant, user, headers = await _setup(client, service_headers, "gd-list-files")
    monkeypatch.setattr(sc, "_require_feature_enabled", lambda: None)

    state = gd_oauth.create_state_token(tenant_id=tenant["id"], user_id=user["id"])

    async def fake_exchange(*, code):
        return {"access_token": "at", "refresh_token": "rt", "expires_at": 9e15}

    monkeypatch.setattr(sc.gd, "exchange_code_for_tokens", fake_exchange)
    r = await client.post(
        "/api/spreadsheet-connections/callback",
        json={"code": "c", "state": state},
        headers=headers,
    )
    connection_id = r.json()["id"]

    captured: dict = {}

    class _FakeClient:
        def __init__(self, access_token):
            captured["access_token"] = access_token

        async def list_supported_files(self, page_token=None):
            return {"files": [{"id": "f1", "name": "Pricing", "sourceType": "google_sheet"}]}

    monkeypatch.setattr(sc.gd, "GoogleDriveClient", _FakeClient)

    r = await client.get(
        f"/api/spreadsheet-connections/{connection_id}/files", headers=headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["files"][0]["id"] == "f1"
    assert captured["access_token"] == "at"


async def test_list_files_refreshes_an_expired_access_token(
    client, service_headers, monkeypatch
):
    import app.routes.spreadsheet_connections as sc
    import app.services.google_drive.oauth as gd_oauth

    tenant, user, headers = await _setup(client, service_headers, "gd-refresh")
    monkeypatch.setattr(sc, "_require_feature_enabled", lambda: None)

    state = gd_oauth.create_state_token(tenant_id=tenant["id"], user_id=user["id"])

    async def fake_exchange(*, code):
        # Already expired.
        return {"access_token": "stale-at", "refresh_token": "rt", "expires_at": 1.0}

    monkeypatch.setattr(sc.gd, "exchange_code_for_tokens", fake_exchange)
    r = await client.post(
        "/api/spreadsheet-connections/callback",
        json={"code": "c", "state": state},
        headers=headers,
    )
    connection_id = r.json()["id"]

    refresh_calls: list[str] = []

    async def fake_refresh(*, refresh_token):
        refresh_calls.append(refresh_token)
        return {"access_token": "fresh-at", "refresh_token": "rt", "expires_at": 9e15}

    monkeypatch.setattr(sc.gd, "refresh_access_token", fake_refresh)

    captured: dict = {}

    class _FakeClient:
        def __init__(self, access_token):
            captured["access_token"] = access_token

        async def list_supported_files(self, page_token=None):
            return {"files": []}

    monkeypatch.setattr(sc.gd, "GoogleDriveClient", _FakeClient)

    r = await client.get(
        f"/api/spreadsheet-connections/{connection_id}/files", headers=headers
    )
    assert r.status_code == 200, r.text
    assert refresh_calls == ["rt"]
    assert captured["access_token"] == "fresh-at"


async def test_delete_connection_removes_it(client, service_headers, monkeypatch):
    import app.routes.spreadsheet_connections as sc
    import app.services.google_drive.oauth as gd_oauth

    tenant, user, headers = await _setup(client, service_headers, "gd-delete")
    monkeypatch.setattr(sc, "_require_feature_enabled", lambda: None)

    state = gd_oauth.create_state_token(tenant_id=tenant["id"], user_id=user["id"])

    async def fake_exchange(*, code):
        return {"access_token": "at", "refresh_token": "rt", "expires_at": 9e15}

    monkeypatch.setattr(sc.gd, "exchange_code_for_tokens", fake_exchange)
    r = await client.post(
        "/api/spreadsheet-connections/callback",
        json={"code": "c", "state": state},
        headers=headers,
    )
    connection_id = r.json()["id"]

    r = await client.delete(f"/api/spreadsheet-connections/{connection_id}", headers=headers)
    assert r.status_code == 200
    assert r.json()["deleted"] is True

    r = await client.get("/api/spreadsheet-connections", headers=headers)
    assert r.json() == []


async def test_connection_not_found_for_a_different_tenant(client, service_headers, monkeypatch):
    import app.routes.spreadsheet_connections as sc
    import app.services.google_drive.oauth as gd_oauth

    tenant_a, user_a, headers_a = await _setup(client, service_headers, "gd-tenant-a")
    _tenant_b, _user_b, headers_b = await _setup(client, service_headers, "gd-tenant-b")
    monkeypatch.setattr(sc, "_require_feature_enabled", lambda: None)

    state = gd_oauth.create_state_token(tenant_id=tenant_a["id"], user_id=user_a["id"])

    async def fake_exchange(*, code):
        return {"access_token": "at", "refresh_token": "rt", "expires_at": 9e15}

    monkeypatch.setattr(sc.gd, "exchange_code_for_tokens", fake_exchange)
    r = await client.post(
        "/api/spreadsheet-connections/callback",
        json={"code": "c", "state": state},
        headers=headers_a,
    )
    connection_id = r.json()["id"]

    r = await client.get(
        f"/api/spreadsheet-connections/{connection_id}/files", headers=headers_b
    )
    assert r.status_code == 404


async def test_detect_tables_finds_multiple_tables(client, service_headers, monkeypatch):
    import app.routes.spreadsheet_connections as sc
    import app.services.google_drive.oauth as gd_oauth

    tenant, user, headers = await _setup(client, service_headers, "gd-detect-multi")
    monkeypatch.setattr(sc, "_require_feature_enabled", lambda: None)

    state = gd_oauth.create_state_token(tenant_id=tenant["id"], user_id=user["id"])

    async def fake_exchange(*, code):
        return {"access_token": "at", "refresh_token": "rt", "expires_at": 9e15}

    monkeypatch.setattr(sc.gd, "exchange_code_for_tokens", fake_exchange)
    r = await client.post(
        "/api/spreadsheet-connections/callback",
        json={"code": "c", "state": state},
        headers=headers,
    )
    connection_id = r.json()["id"]

    class _FakeClient:
        def __init__(self, access_token):
            pass

        async def get_file_metadata(self, file_id):
            return {"name": "Multi"}

        async def list_sheet_tabs(self, file_id):
            return [{"title": "Sheet1", "rowCount": 20, "columnCount": 10}]

        async def get_range_values(self, file_id, range_a1):
            return [
                ["A", "B", "C"],
                [1, 2, 3],
                [],
                ["D", "E", "F"],
                [4, 5, 6],
            ]

    monkeypatch.setattr(sc.gd, "GoogleDriveClient", _FakeClient)

    r = await client.post(
        f"/api/spreadsheet-connections/{connection_id}/files/f1/detect-tables",
        json={},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "tables" in body
    assert len(body["tables"]) == 2
    assert body["tables"][0]["mapping"]["rangeA1"] == "'Sheet1'!A1:C2"
    assert body["tables"][1]["mapping"]["rangeA1"] == "'Sheet1'!A4:C5"
    assert "mapping" in body and "columns" in body

    r = await client.get(
        f"/api/spreadsheet-connections/{connection_id}/files/f1/tables",
        headers=headers,
    )
    assert r.status_code == 200, r.text
    list_body = r.json()
    assert len(list_body["files"]) == 1
    assert len(list_body["files"][0]["tables"]) == 2
