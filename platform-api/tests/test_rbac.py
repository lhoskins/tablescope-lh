"""RBAC dependency tests."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.auth.context import RequestContext
from app.auth.jwt import TokenClaims
from app.auth.rbac import Role, require_permission, require_role


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
