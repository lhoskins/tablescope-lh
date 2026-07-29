"""Supabase Auth integration (backend, service-role).

Single environment-configured auth provider — NOT one Supabase project per
tenant. This service uses the **service role key** (never exposed to the
frontend) to find/create/invite users via the GoTrue admin API, and maps a
Supabase user onto a local Tablescope :class:`User`.

JWT/session validation is delegated to :func:`app.auth.clerk.verify_external_token`
which already verifies Supabase RS256 tokens against the project JWKS.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.clerk import verify_external_token
from app.auth.jwt import AuthError
from app.config import get_settings
from app.models.tenant_membership import TenantAuthBinding
from app.models.user import User

logger = logging.getLogger(__name__)


class SupabaseConfigError(RuntimeError):
    """Raised when Supabase is not configured (URL / service role key missing)."""


class SupabaseAdminError(RuntimeError):
    """Raised when the Supabase admin API returns an error."""


@dataclass(slots=True)
class SupabaseUser:
    id: str
    email: str
    created: bool = False
    action_link: str | None = None
    # True once the user has confirmed their email / signed in at least once,
    # i.e. they already have working credentials and should be routed to
    # sign-in rather than a set-password flow.
    confirmed: bool = False


class SupabaseAuthService:
    """Thin wrapper over the GoTrue admin API + local user mapping."""

    def __init__(self, *, client: httpx.AsyncClient | None = None) -> None:
        settings = get_settings()
        self._base_url = settings.supabase_url.rstrip("/")
        self._service_key = settings.supabase_service_role_key
        self._client = client

    def _require_config(self) -> None:
        if not self._base_url or not self._service_key:
            raise SupabaseConfigError(
                "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be configured"
            )

    def _headers(self) -> dict[str, str]:
        return {
            "apikey": self._service_key,
            "Authorization": f"Bearer {self._service_key}",
            "Content-Type": "application/json",
        }

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        self._require_config()
        url = f"{self._base_url}{path}"
        if self._client is not None:
            return await self._client.request(method, url, headers=self._headers(), **kwargs)
        async with httpx.AsyncClient(timeout=20.0) as client:
            return await client.request(method, url, headers=self._headers(), **kwargs)

    # --- GoTrue admin operations -------------------------------------------------

    async def find_user_by_email(self, email: str) -> SupabaseUser | None:
        """Return the Supabase user with this email, or None.

        GoTrue admin list is paginated; we scan pages and match case-insensitively.
        """
        target = email.strip().lower()
        page = 1
        while page <= 50:  # hard cap to avoid runaway loops
            resp = await self._request(
                "GET", f"/auth/v1/admin/users?page={page}&per_page=200"
            )
            if resp.status_code != 200:
                raise SupabaseAdminError(
                    f"admin list users failed: HTTP {resp.status_code}"
                )
            body = resp.json()
            users = body.get("users", body if isinstance(body, list) else [])
            if not users:
                return None
            for u in users:
                if str(u.get("email", "")).strip().lower() == target:
                    return SupabaseUser(
                        id=u["id"],
                        email=u.get("email", email),
                        confirmed=bool(
                            u.get("email_confirmed_at")
                            or u.get("confirmed_at")
                            or u.get("last_sign_in_at")
                        ),
                    )
            if len(users) < 200:
                return None
            page += 1
        return None

    async def create_user(
        self,
        email: str,
        *,
        first_name: str | None = None,
        last_name: str | None = None,
        email_confirm: bool = False,
    ) -> SupabaseUser:
        """Create a Supabase user (no password). Never emails a password."""
        payload: dict[str, Any] = {
            "email": email,
            "email_confirm": email_confirm,
            "user_metadata": {
                k: v
                for k, v in {"first_name": first_name, "last_name": last_name}.items()
                if v is not None
            },
        }
        resp = await self._request("POST", "/auth/v1/admin/users", json=payload)
        if resp.status_code not in (200, 201):
            raise SupabaseAdminError(f"create user failed: HTTP {resp.status_code}")
        u = resp.json()
        return SupabaseUser(id=u["id"], email=u.get("email", email), created=True)

    async def _generate_link(
        self, *, link_type: str, email: str, redirect_to: str | None
    ) -> str:
        """Generate a GoTrue action link of ``link_type`` (``invite``/``magiclink``).

        ``redirect_to`` must be sent top-level (not under ``options``) or GoTrue
        ignores it and falls back to the project Site URL.
        """
        payload: dict[str, Any] = {"type": link_type, "email": email}
        if redirect_to:
            payload["redirect_to"] = redirect_to
        resp = await self._request(
            "POST",
            "/auth/v1/admin/generate_link",
            json=payload,
        )
        if resp.status_code not in (200, 201):
            raise SupabaseAdminError(f"generate_link failed: HTTP {resp.status_code}")
        body = resp.json()
        link = body.get("action_link") or body.get("properties", {}).get("action_link")
        if not link:
            raise SupabaseAdminError("generate_link returned no action_link")
        return str(link)

    async def generate_invite_link(
        self, email: str, *, redirect_to: str | None = None
    ) -> str:
        """Generate an invite action link (for a user not yet confirmed)."""
        return await self._generate_link(
            link_type="invite", email=email, redirect_to=redirect_to
        )

    async def generate_magic_link(
        self, email: str, *, redirect_to: str | None = None
    ) -> str:
        """Generate a single-use magic sign-in link (for an existing user)."""
        return await self._generate_link(
            link_type="magiclink", email=email, redirect_to=redirect_to
        )

    async def generate_recovery_link(
        self, email: str, *, redirect_to: str | None = None
    ) -> str:
        """Generate a single-use password-recovery action link.

        The returned link is a GoTrue /verify URL. Callers that need the
        token_hash for a client-side verifyOtp flow should extract it from the
        query string (token=...).
        """
        return await self._generate_link(
            link_type="recovery", email=email, redirect_to=redirect_to
        )

    async def create_or_invite_user(
        self,
        email: str,
        *,
        first_name: str | None = None,
        last_name: str | None = None,
        redirect_to: str | None = None,
    ) -> SupabaseUser:
        """Find an existing Supabase user, else create one and generate an invite link.

        Never creates or emails a password.
        """
        existing = await self.find_user_by_email(email)
        if existing is not None:
            # An unconfirmed existing user (e.g. created during a prior, failed
            # provisioning attempt) still needs to set a password — hand back a
            # set-password link so retries route to password creation, not a
            # sign-in page they can't yet use.
            if not existing.confirmed and redirect_to:
                try:
                    existing.action_link = await self.generate_magic_link(
                        email, redirect_to=redirect_to
                    )
                except SupabaseAdminError as exc:
                    logger.warning(
                        "could not generate set-password link for existing "
                        "unconfirmed user: %s",
                        exc,
                    )
            return existing
        user = await self.create_user(
            email, first_name=first_name, last_name=last_name
        )
        try:
            user.action_link = await self.generate_invite_link(
                email, redirect_to=redirect_to
            )
        except SupabaseAdminError as exc:  # invite link is best-effort
            logger.warning("could not generate invite link for new user: %s", exc)
        return user

    # --- local user mapping ------------------------------------------------------

    async def link_local_user(
        self,
        session: AsyncSession,
        *,
        supabase_user_id: str,
        email: str,
        tenant_id: int,
        role: str = "viewer",
        first_name: str | None = None,
        last_name: str | None = None,
    ) -> User:
        """Find-or-create a local User bound to a Supabase identity + tenant.

        Also records a :class:`TenantAuthBinding`. Idempotent on
        (supabase_user_id) and (tenant_id, email).
        """
        # Scope identity to the tenant: the same Supabase user can have a
        # distinct local user in each tenant it belongs to.
        user = await session.scalar(
            select(User).where(
                User.supabase_user_id == supabase_user_id,
                User.tenant_id == tenant_id,
            )
        )
        if user is None:
            user = await session.scalar(
                select(User).where(
                    User.tenant_id == tenant_id, User.email == email
                )
            )
        if user is None:
            user = User(
                tenant_id=tenant_id,
                email=email,
                role=role,
                first_name=first_name,
                last_name=last_name,
                display_name=_display_name(first_name, last_name) or email,
            )
            session.add(user)
        # Keep the Supabase identity in sync (external_id powers /auth/exchange).
        user.supabase_user_id = supabase_user_id
        if not user.external_id:
            user.external_id = supabase_user_id
        await session.flush()

        binding = await session.scalar(
            select(TenantAuthBinding).where(
                TenantAuthBinding.provider == "supabase",
                TenantAuthBinding.supabase_user_id == supabase_user_id,
                TenantAuthBinding.tenant_id == tenant_id,
            )
        )
        if binding is None:
            binding = TenantAuthBinding(
                provider="supabase",
                supabase_user_id=supabase_user_id,
                email=email,
                tenant_id=tenant_id,
                user_id=user.id,
            )
            session.add(binding)
        else:
            binding.tenant_id = tenant_id
            binding.user_id = user.id
            binding.email = email
        await session.flush()
        return user

    async def validate_token(self, token: str) -> dict[str, Any]:
        """Validate a Supabase session JWT and return its claims."""
        try:
            return await verify_external_token(token, provider="supabase")
        except AuthError as exc:
            raise SupabaseAdminError(str(exc)) from exc


def _display_name(first: str | None, last: str | None) -> str | None:
    parts = [p for p in (first, last) if p]
    return " ".join(parts) if parts else None
