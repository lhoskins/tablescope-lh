"""Project Assets tests — document (asset) AI profile response envelope.

Covers the M4 fast-follow "document profile" surface: the asset AI-profile
endpoint stamps the shared ``presentation`` + ``envelope`` (DOCUMENT mode)
additively, keeping its bespoke profile-drawer renderer.
"""

from __future__ import annotations

import pytest

from app.auth.jwt import create_access_token
from app.models.project_asset import ProjectAsset
from app.services.supabase_auth_service import SupabaseAuthService, SupabaseUser


class _FakeSupabase(SupabaseAuthService):
    def __init__(self) -> None:
        pass

    async def create_or_invite_user(
        self, email, *, first_name=None, last_name=None, redirect_to=None
    ) -> SupabaseUser:
        return SupabaseUser(
            id=f"supa-{email}", email=email, created=True, action_link="x"
        )


class _FakeEmail:
    async def send_transactional_email(self, **kwargs) -> bool:
        return True


@pytest.fixture(autouse=True)
def _mock_supabase(monkeypatch):
    import app.routes.tenants as tenants_module

    monkeypatch.setattr(tenants_module, "SupabaseAuthService", _FakeSupabase)
    monkeypatch.setattr(tenants_module, "EmailService", _FakeEmail)


def _editor_headers(tenant_id: int, user_id: int) -> dict:
    token = create_access_token(
        sub="u", tenant_id=tenant_id, user_id=user_id, role="editor"
    )
    return {"Authorization": f"Bearer {token}"}


async def _setup(client, service_headers):
    r = await client.post(
        "/api/tenants",
        json={"slug": "assets-tenant", "name": "Assets Tenant"},
        headers=service_headers,
    )
    assert r.status_code == 201
    tenant = r.json()

    r = await client.post(
        f"/api/tenants/{tenant['id']}/users",
        json={
            "email": "assets@test.com",
            "display_name": "Assets User",
            "role": "editor",
            "external_id": "ext-assets",
        },
        headers=service_headers,
    )
    assert r.status_code == 201
    user = r.json()

    headers = _editor_headers(tenant["id"], user["id"])
    r = await client.post(
        "/api/projects",
        json={"name": "Docs", "description": "test", "is_shared": False},
        headers=headers,
    )
    assert r.status_code == 201
    return tenant, user, r.json(), headers


async def test_asset_ai_profile_emits_document_envelope(
    client, db_session, service_headers
) -> None:
    tenant, user, project, headers = await _setup(client, service_headers)

    asset = ProjectAsset(
        tenant_id=tenant["id"],
        project_id=project["id"],
        owner_user_id=user["id"],
        asset_type="pdf",
        title="Supplier Code of Conduct.pdf",
        filename="supplier_coc.pdf",
        storage_location="/tmp/supplier_coc.pdf",
        ai_status="ready",
        ai_summary="Governs supplier onboarding and audit cadence.",
    )
    db_session.add(asset)
    await db_session.commit()
    await db_session.refresh(asset)

    r = await client.get(
        f"/api/projects/{project['id']}/assets/{asset.id}/ai/profile",
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # M4 fast-follow (contract-only): the document profile emits the unified
    # ResponseEnvelope (DOCUMENT mode), additively, alongside its bespoke fields.
    assert body["presentation"]["mode"] == "document"
    env = body["envelope"]
    assert env["mode"] == "document"
    assert env["sections"] == body["presentation"]["sections"]
    assert env["summary"] == asset.ai_summary
    assert env["status"] == asset.ai_status
