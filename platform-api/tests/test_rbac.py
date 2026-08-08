"""RBAC dependency tests."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.auth.context import RequestContext
from app.auth.jwt import TokenClaims
from app.auth.rbac import (
    Role,
    require_human_platform_admin,
    require_permission,
    require_platform_admin,
    require_role,
)


def _context(role: str = "viewer", permissions: list[str] | None = None) -> RequestContext:
    return RequestContext(
        claims=TokenClaims(
            sub="u",
            tenant_id=1,
            user_id=1,
            role=role,
            permissions=permissions or [],
        )
    )


async def test_admin_passes_admin_requirement() -> None:
    dep = require_role(Role.ADMIN)
    ctx = await dep(context=_context("admin"))
    assert ctx.role == "admin"


async def test_viewer_fails_editor_requirement() -> None:
    dep = require_role(Role.EDITOR)
    with pytest.raises(HTTPException) as exc:
        await dep(context=_context("viewer"))
    assert exc.value.status_code == 403


async def test_permission_required() -> None:
    dep = require_permission("scopes:write")
    with pytest.raises(HTTPException):
        await dep(context=_context("editor", []))
    ctx = await dep(context=_context("editor", ["scopes:write"]))
    assert ctx.has_permission("scopes:write")


def _mock_session(is_super_admin: bool = False, role: str = "viewer", is_active: bool = True) -> AsyncMock:
    user = AsyncMock()
    user.is_super_admin = is_super_admin
    user.role = role
    user.is_active = is_active
    session = AsyncMock()
    session.get.return_value = user
    return session


async def test_platform_admin_allows_super_admin() -> None:
    session = _mock_session(is_super_admin=True, role="viewer")
    ctx = await require_platform_admin(session=session, context=_context("viewer"))
    assert ctx.role == "viewer"


async def test_platform_admin_allows_root_admin() -> None:
    session = _mock_session(role="root_admin")
    ctx = await require_platform_admin(session=session, context=_context("root_admin"))
    assert ctx.role == "root_admin"


async def test_platform_admin_rejects_tenant_admin() -> None:
    session = _mock_session(role="tenant_admin")
    with pytest.raises(HTTPException) as exc:
        await require_platform_admin(session=session, context=_context("tenant_admin"))
    assert exc.value.status_code == 403


async def test_platform_admin_rejects_inactive_user() -> None:
    session = _mock_session(role="root_admin", is_active=False)
    with pytest.raises(HTTPException) as exc:
        await require_platform_admin(session=session, context=_context("root_admin"))
    assert exc.value.status_code == 403


async def test_platform_admin_allows_service_caller() -> None:
    ctx = RequestContext(
        claims=TokenClaims(sub="service:test", tenant_id=0, user_id=0, role="admin", permissions=["service:*"]),
        is_service=True,
    )
    session = AsyncMock()
    result = await require_platform_admin(session=session, context=ctx)
    assert result.is_service


async def test_human_platform_admin_allows_root_admin() -> None:
    session = _mock_session(role="root_admin")
    ctx = await require_human_platform_admin(session=session, context=_context("root_admin"))
    assert ctx.role == "root_admin"


async def test_human_platform_admin_rejects_service_caller() -> None:
    ctx = RequestContext(
        claims=TokenClaims(sub="service:test", tenant_id=0, user_id=0, role="admin", permissions=["service:*"]),
        is_service=True,
    )
    session = AsyncMock()
    with pytest.raises(HTTPException) as exc:
        await require_human_platform_admin(session=session, context=ctx)
    assert exc.value.status_code == 403
    assert "service ident" in exc.value.detail.lower()


async def test_human_platform_admin_rejects_tenant_admin() -> None:
    session = _mock_session(role="tenant_admin")
    with pytest.raises(HTTPException) as exc:
        await require_human_platform_admin(session=session, context=_context("tenant_admin"))
    assert exc.value.status_code == 403


async def test_post_runtime_targets_route_rejects_service_caller(client, service_headers) -> None:
    r = await client.post(
        "/api/llm-framework/runtime-targets",
        json={"name": "test-target", "host": "http://ollama:11434"},
        headers=service_headers,
    )
    assert r.status_code == 403
    assert "service ident" in r.text.lower()
