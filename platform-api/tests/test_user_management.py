"""Permission tests for tenant user management endpoints."""

from __future__ import annotations

from app.auth.jwt import create_access_token


def _headers(role: str, tenant_id: int = 1, user_id: int = 1) -> dict:
    token = create_access_token(
        sub="u", tenant_id=tenant_id, user_id=user_id, role=role
    )
    return {"Authorization": f"Bearer {token}"}


async def test_root_admin_can_list_users(client) -> None:
    # root_admin administers the root tenant and must reach user management.
    res = await client.get("/api/tenants/1/users", headers=_headers("root_admin"))
    assert res.status_code == 200, res.text


async def test_tenant_admin_can_list_users(client) -> None:
    res = await client.get(
        "/api/tenants/1/users", headers=_headers("tenant_admin")
    )
    assert res.status_code == 200, res.text


async def test_editor_cannot_list_users(client) -> None:
    res = await client.get("/api/tenants/1/users", headers=_headers("editor"))
    assert res.status_code == 403


async def test_viewer_cannot_list_users(client) -> None:
    res = await client.get("/api/tenants/1/users", headers=_headers("viewer"))
    assert res.status_code == 403
