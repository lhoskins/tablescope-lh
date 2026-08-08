"""Tenant SSO configuration, policy, and identity mapping routes."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models.user_auth_identity import UserAuthIdentity
from app.schemas.enterprise_auth import (
    EnterpriseAuthSettingsRead,
    IdentityMappingConfirm,
    IdentityMappingRead,
    SsoConfiguration,
    SsoConfigurationRead,
    SsoPolicyUpdate,
    SsoTestResponse,
)
from app.services.enterprise_auth import (
    audit_enterprise_auth_event,
    decrypt_sso_provider_id,
    encrypt_sso_provider_id,
    get_enterprise_auth_settings,
    hash_entity_id,
)
from app.services.sso_provider_service import SsoProviderAdminError, SsoProviderService

router = APIRouter(prefix="/tenants/current/enterprise-auth/sso", tags=["enterprise-auth"])


@router.get("/configuration", response_model=SsoConfigurationRead)
async def get_sso_configuration(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> SsoConfigurationRead:
    settings = await get_enterprise_auth_settings(session, context.tenant_id)
    domains: list[str] = []
    entity_id = None
    if settings.sso_provider_entity_id_hash:
        entity_id = f"<stored hash: {settings.sso_provider_entity_id_hash}>"
    return SsoConfigurationRead(
        provider_friendly_name=settings.sso_provider_display_name,
        identity_provider_type="saml",
        expected_entity_id=entity_id,
        allowed_email_domains=domains,
        sso_status=settings.sso_status,
        sso_last_tested_at=settings.sso_last_tested_at,
        sso_last_test_result=settings.sso_last_test_result,
    )


@router.put("/configuration", response_model=EnterpriseAuthSettingsRead)
async def update_sso_configuration(
    payload: SsoConfiguration,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> EnterpriseAuthSettingsRead:
    if context.aal != "aal2":
        raise HTTPException(
            status_code=409,
            detail="Verify your own phone (step-up authentication) before configuring SSO.",
        )

    service = SsoProviderService()
    settings = await get_enterprise_auth_settings(session, context.tenant_id)
    try:
        current_provider_id = decrypt_sso_provider_id(settings.sso_provider_id_encrypted)
        if current_provider_id:
            result = await service.update_provider(
                current_provider_id,
                metadata_url=payload.metadata_url,
                metadata_xml=payload.metadata_xml,
                domains=payload.allowed_email_domains or [],
                name_id_format="urn:oasis:names:tc:SAML:2.0:nameid-format:persistent",
            )
        else:
            result = await service.create_provider(
                friendly_name=payload.provider_friendly_name,
                metadata_url=payload.metadata_url,
                metadata_xml=payload.metadata_xml,
                domains=payload.allowed_email_domains or [],
                name_id_format="urn:oasis:names:tc:SAML:2.0:nameid-format:persistent",
            )
        provider_id = result.get("sso_provider_id") or result.get("id")
        if not provider_id:
            raise SsoProviderAdminError("Supabase did not return a provider id")
    except SsoProviderAdminError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    settings.sso_provider_id_encrypted = encrypt_sso_provider_id(provider_id)
    settings.sso_provider_display_name = payload.provider_friendly_name
    settings.sso_provider_entity_id_hash = hash_entity_id(payload.expected_entity_id)
    settings.sso_status = "configured"
    settings.updated_by = context.user_id
    await session.commit()
    await audit_enterprise_auth_event(
        session,
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        scope="sso_configuration",
        title=f"SSO provider {payload.provider_friendly_name!r} configured",
    )
    return EnterpriseAuthSettingsRead.model_validate(settings)


@router.post("/test", response_model=SsoTestResponse)
async def test_sso_configuration(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> SsoTestResponse:
    settings = await get_enterprise_auth_settings(session, context.tenant_id)
    provider_id = decrypt_sso_provider_id(settings.sso_provider_id_encrypted)
    if not provider_id:
        raise HTTPException(status_code=404, detail="SSO provider not configured")
    service = SsoProviderService()
    try:
        ok = await service.test_provider(provider_id)
        settings.sso_status = "tested" if ok else "error"
        settings.sso_last_tested_at = datetime.now(tz=UTC)
        settings.sso_last_test_result = "SSO start URL generated successfully" if ok else "SSO start URL failed"
        await session.commit()
        return SsoTestResponse(
            success=ok,
            status=settings.sso_status,
            message=settings.sso_last_test_result,
        )
    except SsoProviderAdminError as exc:
        settings.sso_status = "error"
        settings.sso_last_tested_at = datetime.now(tz=UTC)
        settings.sso_last_test_result = str(exc)
        await session.commit()
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put("/policy", response_model=EnterpriseAuthSettingsRead)
async def update_sso_policy(
    payload: SsoPolicyUpdate,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> EnterpriseAuthSettingsRead:
    if context.aal != "aal2":
        raise HTTPException(
            status_code=409,
            detail="Verify your own phone (step-up authentication) before changing SSO policy.",
        )
    settings = await get_enterprise_auth_settings(session, context.tenant_id)
    if payload.sso_required and not settings.sso_enabled:
        raise HTTPException(
            status_code=409,
            detail="Enable SSO before requiring it.",
        )
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return EnterpriseAuthSettingsRead.model_validate(settings)
    for key, value in updates.items():
        setattr(settings, key, value)
    settings.updated_by = context.user_id
    await session.commit()
    for key, value in updates.items():
        await audit_enterprise_auth_event(
            session,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            scope="sso_policy",
            title=f"{key} changed to {value}",
        )
    return EnterpriseAuthSettingsRead.model_validate(settings)


# ---------------------------------------------------------------------------
# Identity mappings
# ---------------------------------------------------------------------------


@router.get("/identity-mappings", response_model=list[IdentityMappingRead])
async def list_identity_mappings(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> list[IdentityMappingRead]:
    rows = await session.scalars(
        select(UserAuthIdentity).where(
            UserAuthIdentity.tenant_id == context.tenant_id,
            UserAuthIdentity.provider_type.in_(["supabase_saml", "ldap_directory"]),
        )
    )
    return [IdentityMappingRead.model_validate(r) for r in rows]


@router.post("/identity-mappings/{identity_id}/confirm")
async def confirm_identity_mapping(
    identity_id: int,
    payload: IdentityMappingConfirm,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> dict[str, str]:
    identity = await session.get(UserAuthIdentity, identity_id)
    if identity is None or identity.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Identity mapping not found")
    identity.user_id = payload.user_id
    identity.verification_state = "confirmed"
    identity.linked_by = context.user_id
    identity.linked_at = datetime.now(tz=UTC)
    await session.commit()
    await audit_enterprise_auth_event(
        session,
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        scope="identity_mapping",
        title=f"Identity mapping {identity_id} confirmed to user {payload.user_id}",
    )
    return {"status": "confirmed"}


@router.post("/identity-mappings/{identity_id}/reject")
async def reject_identity_mapping(
    identity_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> dict[str, str]:
    identity = await session.get(UserAuthIdentity, identity_id)
    if identity is None or identity.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Identity mapping not found")
    identity.verification_state = "rejected"
    identity.linked_by = context.user_id
    identity.linked_at = datetime.now(tz=UTC)
    await session.commit()
    await audit_enterprise_auth_event(
        session,
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        scope="identity_mapping",
        title=f"Identity mapping {identity_id} rejected",
    )
    return {"status": "rejected"}
