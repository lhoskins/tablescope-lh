"""Enterprise authentication helpers: identity linking, settings, and audit."""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_event import AuditEvent
from app.models.tenant_enterprise_auth_settings import TenantEnterpriseAuthSettings
from app.models.user import User
from app.models.user_auth_identity import UserAuthIdentity
from app.services.crypto import decrypt_secret, encrypt_secret

logger = logging.getLogger(__name__)


async def get_enterprise_auth_settings(
    session: AsyncSession, tenant_id: int
) -> TenantEnterpriseAuthSettings:
    """Return the tenant enterprise auth settings, creating the default row if absent."""
    settings = await session.scalar(
        select(TenantEnterpriseAuthSettings).where(
            TenantEnterpriseAuthSettings.tenant_id == tenant_id
        )
    )
    if settings is None:
        settings = TenantEnterpriseAuthSettings(tenant_id=tenant_id)
        session.add(settings)
        await session.flush()
    return settings


async def resolve_user_for_external_identity(
    session: AsyncSession,
    *,
    tenant_id: int,
    external_subject: str,
    provider_type: str,
    email: str | None = None,
    fallback_to_user_external_id: bool = True,
    allow_email_match: bool = False,
) -> User | None:
    """Resolve an external identity to a TableScope user.

    1. Look for a confirmed ``UserAuthIdentity`` row for this (tenant, provider, subject).
    2. If no row and ``fallback_to_user_external_id`` is True and the provider is
       ``supabase_local``, fall back to the legacy ``User.external_id`` match.
    3. If an email is supplied, ``allow_email_match`` is True, and still no user,
       look for an active user in the tenant with that email. Callers must
       approve the mapping explicitly; this path is disabled for SSO by default.

    This is the chokepoint for the identity-linking gap described in the plan.
    """
    identity = await session.scalar(
        select(UserAuthIdentity).where(
            UserAuthIdentity.tenant_id == tenant_id,
            UserAuthIdentity.provider_type == provider_type,
            UserAuthIdentity.external_subject == external_subject,
            UserAuthIdentity.suspended.is_(False),
        )
    )
    if identity is not None:
        return await session.get(User, identity.user_id)

    if fallback_to_user_external_id and provider_type in ("supabase_local", "supabase", "clerk"):
        user = await session.scalar(
            select(User).where(
                User.tenant_id == tenant_id,
                (User.external_id == external_subject) | (User.supabase_user_id == external_subject),
            )
        )
        if user is not None:
            return user

    if email and allow_email_match:
        user = await session.scalar(
            select(User).where(
                User.tenant_id == tenant_id,
                User.email.ilike(email),
                User.is_active.is_(True),
            )
        )
        if user is not None:
            return user

    return None


async def record_identity_link(
    session: AsyncSession,
    *,
    tenant_id: int,
    user_id: int,
    provider_type: str,
    external_subject: str,
    verification_state: str = "confirmed",
    linked_by: int | None = None,
    sso_provider_uuid: str | None = None,
    directory_connection_id: int | None = None,
) -> UserAuthIdentity:
    """Create or update a user-auth identity mapping."""
    now = datetime.now(tz=UTC)
    identity = await session.scalar(
        select(UserAuthIdentity).where(
            UserAuthIdentity.tenant_id == tenant_id,
            UserAuthIdentity.provider_type == provider_type,
            UserAuthIdentity.external_subject == external_subject,
        )
    )
    if identity is None:
        identity = UserAuthIdentity(
            tenant_id=tenant_id,
            user_id=user_id,
            provider_type=provider_type,
            external_subject=external_subject,
        )
        session.add(identity)

    identity.user_id = user_id
    identity.verification_state = verification_state
    identity.sso_provider_uuid = sso_provider_uuid
    identity.directory_connection_id = directory_connection_id
    identity.linked_at = now
    if linked_by is not None:
        identity.linked_by = linked_by
    identity.last_authenticated_at = now
    await session.flush()
    return identity


def encrypt_sso_provider_id(provider_id: str | None) -> str | None:
    if not provider_id:
        return None
    return encrypt_secret(provider_id)


def decrypt_sso_provider_id(token: str | None) -> str | None:
    if not token:
        return None
    try:
        return decrypt_secret(token)
    except ValueError:
        logger.warning("Failed to decrypt SSO provider id")
        return None


def hash_entity_id(entity_id: str | None) -> str | None:
    if not entity_id:
        return None
    return hashlib.sha256(entity_id.encode("utf-8")).hexdigest()


async def update_enterprise_auth_settings(
    session: AsyncSession,
    tenant_id: int,
    updates: dict[str, Any],
    updated_by: int | None = None,
) -> TenantEnterpriseAuthSettings:
    settings = await get_enterprise_auth_settings(session, tenant_id)
    for key, value in updates.items():
        if hasattr(settings, key):
            setattr(settings, key, value)
    if updated_by is not None:
        settings.updated_by = updated_by
    await session.flush()
    return settings


def encrypt_ldap_bind_secret(secret: str | None) -> str | None:
    if not secret:
        return None
    return encrypt_secret(secret)


def decrypt_ldap_bind_secret(token: str | None) -> str | None:
    if not token:
        return None
    try:
        return decrypt_secret(token)
    except ValueError:
        return None


async def audit_enterprise_auth_event(
    session: AsyncSession,
    *,
    tenant_id: int,
    user_id: int | None,
    scope: str,
    title: str,
    event_type: str = "enterprise_auth",
) -> None:
    """Append an audit event for enterprise authentication actions."""
    session.add(
        AuditEvent(
            tenant_id=tenant_id,
            user_id=user_id,
            event_type=event_type,
            scope=scope,
            title=title,
            prompt_type="enterprise_auth",
            tables_queried=[],
            documents_read=[],
        )
    )
