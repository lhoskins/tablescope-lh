"""Tenant-facing role vocabulary.

The platform RBAC enum (:class:`app.auth.rbac.Role`) carries internal roles
(``root_admin``, ``tenant_admin``, ``editor``, ``viewer``, …) that drive
permission checks. Tenant administrators, however, only ever assign three roles
in the user-management UI:

* **Admin** — administers the tenant (users, settings).
* **DB Admin** — manages data sources / databases.
* **Member** — a regular workspace user.

This module maps between the two so the tenant UI stays simple without breaking
the underlying RBAC (legacy ``editor`` / ``viewer`` users are shown as Member).
"""

from __future__ import annotations

from fastapi import HTTPException, status

# The only roles assignable from the tenant user-management UI.
TENANT_ROLES: tuple[str, ...] = ("admin", "db_admin", "member")

TENANT_ROLE_LABELS: dict[str, str] = {
    "admin": "Admin",
    "db_admin": "DB Admin",
    "member": "Member",
}

# Map any stored/internal role onto the tenant vocabulary for display.
_DISPLAY_MAP: dict[str, str] = {
    "root_admin": "admin",
    "tenant_admin": "admin",
    "admin": "admin",
    "db_admin": "db_admin",
}


def to_tenant_role(role: str | None) -> str:
    """Map a stored/internal role onto the tenant vocabulary (Admin/DB Admin/Member).

    Anything that isn't an admin or DB admin (including legacy ``editor`` /
    ``viewer``) is presented as ``member``.
    """
    return _DISPLAY_MAP.get((role or "").lower(), "member")


def validate_tenant_role(role: str | None) -> str:
    """Validate an incoming tenant role, returning the normalized value.

    Legacy ``editor`` / ``viewer`` values are accepted and mapped to ``member``
    so older clients keep working; anything else outside the tenant vocabulary
    is rejected with HTTP 422.
    """
    r = (role or "").lower()
    if r in ("editor", "viewer"):
        return "member"
    if r not in TENANT_ROLES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Invalid role. Tenant roles must be one of: "
                + ", ".join(TENANT_ROLES)
            ),
        )
    return r
