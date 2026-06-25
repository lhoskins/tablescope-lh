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


async def test_member_cannot_list_users(client) -> None:
    res = await client.get("/api/tenants/1/users", headers=_headers("member"))
    assert res.status_code == 403


async def test_admin_can_list_users(client) -> None:
    res = await client.get("/api/tenants/1/users", headers=_headers("admin"))
    assert res.status_code == 200, res.text


# ── Tenant role vocabulary ───────────────────────────────────────────

def test_to_tenant_role_maps_legacy_and_internal_roles() -> None:
    from app.auth.tenant_roles import to_tenant_role

    assert to_tenant_role("editor") == "member"
    assert to_tenant_role("viewer") == "member"
    assert to_tenant_role("member") == "member"
    assert to_tenant_role("db_admin") == "db_admin"
    assert to_tenant_role("admin") == "admin"
    assert to_tenant_role("tenant_admin") == "admin"
    assert to_tenant_role("root_admin") == "admin"
    assert to_tenant_role(None) == "member"


def test_validate_tenant_role_accepts_only_tenant_roles() -> None:
    import pytest
    from fastapi import HTTPException

    from app.auth.tenant_roles import validate_tenant_role

    assert validate_tenant_role("admin") == "admin"
    assert validate_tenant_role("db_admin") == "db_admin"
    assert validate_tenant_role("member") == "member"
    # Legacy values are mapped (older clients keep working).
    assert validate_tenant_role("editor") == "member"
    assert validate_tenant_role("viewer") == "member"
    # Anything else is rejected.
    with pytest.raises(HTTPException) as exc:
        validate_tenant_role("superuser")
    assert exc.value.status_code == 422


def test_member_role_still_satisfies_basic_rbac() -> None:
    # A member is a normal workspace user (editor-equivalent), never an admin.
    from app.auth.rbac import Role, has_role

    assert has_role("member", Role.VIEWER) is True
    assert has_role("member", Role.EDITOR) is True
    assert has_role("member", Role.ADMIN) is False
    assert has_role("db_admin", Role.EDITOR) is True
    assert has_role("db_admin", Role.ADMIN) is False
    assert has_role("admin", Role.ADMIN) is True
