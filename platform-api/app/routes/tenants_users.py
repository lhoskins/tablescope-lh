"""Tenant user administration: invite, list, update, deactivate, delete.

Split from ``tenants.py``; siblings: ``tenants_crud.py``,
``tenants_settings.py`` and ``tenants_security_policy.py``.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.tenant_roles import to_tenant_role, validate_tenant_role
from app.config import get_settings
from app.database import get_db
from app.models.tenant import Tenant
from app.models.user import User
from app.models.user_vdb import UserVDB
from app.routes.tenants_crud import _require_user_management
from app.schemas.tenant import UserCreate, UserRead, UserUpdate
from app.services.allowed_domains import enforce_allowed_domain
from app.services.customer_folders import CustomerFolderService
from app.services.email_service import EmailService
from app.services.supabase_auth_service import (
    SupabaseAdminError,
    SupabaseAuthService,
    SupabaseConfigError,
)
from app.services.tenant_teiid_resolver import TenantTeiidResolver
from app.services.vdb_management import VDBManagementService, VDBProvisioningError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tenants", tags=["tenants"])

def _user_read_tenant(user: User) -> UserRead:
    """Serialize a user with its role mapped to the tenant vocabulary."""
    data = UserRead.model_validate(user)
    return data.model_copy(update={"role": to_tenant_role(data.role)})


@router.post(
    "/{tenant_id}/users",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_user(
    tenant_id: int,
    payload: UserCreate,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(_require_user_management),
) -> UserRead:
    if not context.is_service and context.tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail="Cannot create users in another tenant")

    payload.role = validate_tenant_role(payload.role)

    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    existing = await session.scalar(
        select(User).where(User.tenant_id == tenant_id, User.email == payload.email)
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="User already exists")

    # Enforce the tenant's Allowed-Domains policy on the invitee's email. The
    # invitee is a new user (never the owner/admin) so they must match the list.
    await enforce_allowed_domain(
        session, tenant_id=tenant_id, email=payload.email, purpose="invite"
    )

    # Supabase is the primary authenticator: create/link a Supabase identity and
    # send a "set your password" invite that lands on the set-password page. No
    # local password is ever stored. If Supabase is unavailable, the user is NOT
    # created (no local fallback).
    settings = get_settings()
    setup_url = f"{settings.app_base_url}/{tenant.slug}/set-password"
    supa = SupabaseAuthService()
    try:
        supa_user = await supa.create_or_invite_user(
            payload.email,
            first_name=payload.display_name,
            redirect_to=setup_url,
        )
    except (SupabaseConfigError, SupabaseAdminError) as exc:
        logger.warning("Supabase user creation failed for %s: %s", payload.email, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication provider unavailable; user was not created",
        ) from exc

    user = await supa.link_local_user(
        session,
        supabase_user_id=supa_user.id,
        email=payload.email,
        tenant_id=tenant_id,
        role=payload.role,
        first_name=payload.display_name,
    )
    user.role = payload.role
    if payload.display_name:
        user.display_name = payload.display_name
    invite_link = supa_user.action_link
    if invite_link is None:
        try:
            invite_link = await supa.generate_magic_link(
                payload.email, redirect_to=setup_url
            )
        except SupabaseAdminError as exc:
            logger.warning("Could not generate set-password link for %s: %s", payload.email, exc)

    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="User already exists") from exc

    # The first user provisioned for a tenant becomes its owner — always exempt
    # from the Allowed-Domains restriction so an admin can never lock themselves
    # out. (No-op once an owner is set.)
    if tenant.owner_user_id is None:
        tenant.owner_user_id = user.id

    CustomerFolderService().ensure_user_folders(
        tenant.slug, user.external_id or str(user.id)
    )

    # Create and deploy user VDB — target the dedicated container if bound.
    endpoint = await TenantTeiidResolver(session).resolve_for_org(tenant_id)
    vdb_svc = VDBManagementService(
        servlet_url=endpoint.servlet_url,
        pg_host=endpoint.pg_host,
        pg_port=endpoint.pg_port,
    )
    try:
        vdb_result = await vdb_svc.create_user_vdb(
            org_id=tenant_id, user_id=user.id,
        )
        user_vdb = UserVDB(
            tenant_id=tenant_id,
            user_id=user.id,
            vdb_id=vdb_result.vdb_id,
            vdb_username=vdb_result.vdb_username,
            encrypted_password=vdb_result.vdb_password,
            vdb_host=vdb_result.vdb_host,
            vdb_port=vdb_result.vdb_port,
            is_active=True,
            health_status="deployed",
        )
        session.add(user_vdb)
        logger.info("User VDB created for user %s: %s", user.email, vdb_result.vdb_id)
    except VDBProvisioningError as exc:
        logger.warning("Failed to create user VDB for user %s: %s", user.email, exc)
    finally:
        await vdb_svc.aclose()

    await session.commit()
    await session.refresh(user)

    # Send the branded magic-link invite (best-effort; never fails user creation).
    if invite_link is not None:
        try:
            await EmailService().send_transactional_email(
                to=payload.email,
                template="user_invitation",
                variables={
                    "first_name": payload.display_name or "",
                    "inviter_name": "A Tablescope administrator",
                    "workspace_name": tenant.name,
                    "role_name": payload.role.replace("_", " ").title(),
                    "invitation_link": invite_link,
                    "expiration_date": "in 24 hours",
                },
                tenant_id=tenant_id,
            )
        except Exception as exc:  # delivery is best-effort
            logger.warning("Failed to send invite email to %s: %s", payload.email, exc)

    return _user_read_tenant(user)


@router.get("/{tenant_id}/users", response_model=list[UserRead])
async def list_users(
    tenant_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(_require_user_management),
) -> list[UserRead]:
    if not context.is_service and context.tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail="Cannot list users in another tenant")
    rows = await session.scalars(select(User).where(User.tenant_id == tenant_id).order_by(User.id))
    return [_user_read_tenant(u) for u in rows]


@router.put(
    "/{tenant_id}/users/{user_id}",
    response_model=UserRead,
)
async def update_user(
    tenant_id: int,
    user_id: int,
    payload: UserUpdate,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(_require_user_management),
) -> UserRead:
    if not context.is_service and context.tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail="Cannot update users in another tenant")
    user = await session.get(User, user_id)
    if user is None or user.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="User not found")
    if payload.display_name is not None:
        user.display_name = payload.display_name
    if payload.role is not None:
        user.role = validate_tenant_role(payload.role)
    if payload.is_active is not None:
        user.is_active = payload.is_active
    if payload.password is not None:
        user.set_password(payload.password)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return _user_read_tenant(user)


@router.delete(
    "/{tenant_id}/users/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def deactivate_user(
    tenant_id: int,
    user_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(_require_user_management),
) -> Response:
    if not context.is_service and context.tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail="Cannot deactivate users in another tenant")
    user = await session.get(User, user_id)
    if user is None or user.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_active = False
    session.add(user)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/{tenant_id}/users/{user_id}/permanent",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_user_permanently(
    tenant_id: int,
    user_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(_require_user_management),
) -> Response:
    """Hard-delete an inactive user. Only works on deactivated users."""
    if not context.is_service and context.tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail="Cannot delete users in another tenant")
    user = await session.get(User, user_id)
    if user is None or user.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="User not found")
    if user.is_active:
        raise HTTPException(status_code=400, detail="User must be deactivated before permanent deletion")
    await session.delete(user)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
