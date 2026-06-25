"""Tenant Allowed-Domains enforcement.

When a tenant turns on ``allowed_domains_enabled``, only users whose email
domain is on the tenant's active allow-list (plus the tenant owner and tenant
admins) may sign up, be invited, receive transactional email, or sign in.

First pass: plain, case-insensitive, exact domain match (no wildcards).
"""

from __future__ import annotations

import re

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.tenant_roles import to_tenant_role
from app.models.tenant import Tenant, TenantAllowedDomain
from app.models.user import User

# Standard error copy shown to users denied by the domain restriction.
ACCESS_DENIED_MESSAGE = (
    "This tenant only allows accounts from approved email domains. "
    "Contact your tenant administrator."
)
INVITE_DENIED_MESSAGE = "This email domain is not allowed for this tenant."

# A conservative domain validator: labels of letters/digits/hyphens separated by
# dots, with a 2+ char alphabetic TLD. No wildcards, no scheme, no '@'.
_DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(?<!-)"
    r"(?:\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))*\.[A-Za-z]{2,}$"
)


def email_domain(email: str) -> str:
    """Return the lowercase domain portion of an email address."""
    return email.split("@")[-1].lower().strip()


def normalize_email_domain(email: str) -> str:
    """Return the normalized (trimmed, lowercase) domain of an email address."""
    return email.split("@")[-1].strip().lower()


def normalize_domain(domain: str) -> str:
    """Normalize a domain for storage/comparison (lowercase, trimmed)."""
    return (domain or "").strip().lower().lstrip("@")


def is_valid_domain(domain: str) -> bool:
    """True if ``domain`` is a syntactically valid bare domain (no wildcards)."""
    d = normalize_domain(domain)
    if not d or "*" in d or "@" in d or "/" in d or " " in d:
        return False
    return bool(_DOMAIN_RE.match(d))


async def _active_domains(session: AsyncSession, tenant_id: int) -> set[str]:
    rows = await session.scalars(
        select(TenantAllowedDomain.domain).where(
            TenantAllowedDomain.tenant_id == tenant_id,
            TenantAllowedDomain.is_active.is_(True),
        )
    )
    return {normalize_domain(d) for d in rows if d}


async def is_email_allowed_for_tenant(
    session: AsyncSession,
    *,
    tenant_id: int,
    email: str,
    user_id: int | None = None,
) -> bool:
    """Whether ``email`` may access ``tenant_id`` under the domain policy.

    Rules (in order):
    - restriction disabled -> allow
    - caller is the tenant owner -> allow
    - caller is a super-admin or tenant admin -> allow
    - email domain is on the tenant's active allow-list -> allow
    - otherwise -> deny
    """
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None or not tenant.allowed_domains_enabled:
        return True

    if user_id is not None:
        if tenant.owner_user_id is not None and tenant.owner_user_id == user_id:
            return True
        user = await session.get(User, user_id)
        if user is not None and (
            user.is_super_admin or to_tenant_role(user.role) == "admin"
        ):
            return True

    return email_domain(email) in await _active_domains(session, tenant_id)


async def enforce_allowed_domain(
    session: AsyncSession,
    *,
    tenant_id: int,
    email: str,
    user_id: int | None = None,
    purpose: str = "access",
) -> None:
    """Raise HTTP 403 when ``email`` is not allowed for ``tenant_id``.

    A no-op when the restriction is disabled or the caller is exempt (the
    original tenant owner or a tenant/super admin). ``purpose`` is one of
    ``signup``/``invite``/``email``/``access`` and only shapes the error copy
    (the allow-list itself is never leaked to the caller).
    """
    if await is_email_allowed_for_tenant(
        session, tenant_id=tenant_id, email=email, user_id=user_id
    ):
        return
    detail = (
        INVITE_DENIED_MESSAGE
        if purpose in ("invite", "signup")
        else ACCESS_DENIED_MESSAGE
    )
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)
