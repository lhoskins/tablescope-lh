"""Supabase SSO/SAML provider management via the GoTrue admin API."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

_DEFAULT_ATTRIBUTE_MAPPING = {
    "keys": {
        "email": {"name": "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress"},
        "given_name": {"name": "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/givenname"},
        "name": {"name": "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name"},
        "family_name": {"name": "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/surname"},
        "name_id": {"name": "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/nameidentifier"},
    }
}


class SsoProviderConfigError(RuntimeError):
    """Raised when Supabase is not configured for SSO."""


class SsoProviderAdminError(RuntimeError):
    """Raised when the Supabase admin API returns an error."""


class SsoProviderService:
    """Manage Supabase SSO providers and generate SSO start URLs."""

    def __init__(self, *, client: httpx.AsyncClient | None = None) -> None:
        settings = get_settings()
        self._base_url = settings.supabase_url.rstrip("/")
        self._service_key = settings.supabase_service_role_key
        self._anon_key = settings.supabase_anon_key or settings.supabase_service_role_key
        self._client = client

    def _require_config(self) -> None:
        if not self._base_url or not self._service_key:
            raise SsoProviderConfigError(
                "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be configured"
            )

    def _admin_headers(self) -> dict[str, str]:
        return {
            "apikey": self._service_key,
            "Authorization": f"Bearer {self._service_key}",
            "Content-Type": "application/json",
        }

    def _anon_headers(self) -> dict[str, str]:
        return {
            "apikey": self._anon_key,
            "Authorization": f"Bearer {self._anon_key}",
            "Content-Type": "application/json",
        }

    async def _admin_request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        self._require_config()
        url = f"{self._base_url}{path}"
        if self._client is not None:
            return await self._client.request(method, url, headers=self._admin_headers(), **kwargs)
        async with httpx.AsyncClient(timeout=30.0) as client:
            return await client.request(method, url, headers=self._admin_headers(), **kwargs)

    async def _anon_request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        self._require_config()
        url = f"{self._base_url}{path}"
        if self._client is not None:
            return await self._client.request(method, url, headers=self._anon_headers(), **kwargs)
        async with httpx.AsyncClient(timeout=30.0) as client:
            return await client.request(method, url, headers=self._anon_headers(), **kwargs)

    async def create_provider(
        self,
        *,
        friendly_name: str,
        metadata_url: str | None,
        metadata_xml: str | None,
        domains: list[str],
        name_id_format: str = "urn:oasis:names:tc:SAML:2.0:nameid-format:persistent",
    ) -> dict[str, Any]:
        """Create a new SAML SSO provider in Supabase."""
        body: dict[str, Any] = {
            "type": "saml",
            "attribute_mapping": _DEFAULT_ATTRIBUTE_MAPPING,
            "name_id_format": name_id_format,
        }
        if metadata_url:
            body["metadata_url"] = metadata_url
        if metadata_xml:
            body["metadata_xml"] = metadata_xml
        if domains:
            body["domains"] = domains

        resp = await self._admin_request("POST", "/auth/v1/admin/sso/providers", json=body)
        if resp.status_code not in (200, 201):
            raise SsoProviderAdminError(
                f"Supabase create SSO provider failed: HTTP {resp.status_code} {resp.text}"
            )
        result = resp.json()
        # The Supabase API returns a list of providers when creating a new one.
        if isinstance(result, list) and result:
            return result[0]
        return result

    async def update_provider(
        self,
        provider_id: str,
        *,
        metadata_url: str | None,
        metadata_xml: str | None,
        domains: list[str],
        name_id_format: str = "urn:oasis:names:tc:SAML:2.0:nameid-format:persistent",
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "type": "saml",
            "attribute_mapping": _DEFAULT_ATTRIBUTE_MAPPING,
            "name_id_format": name_id_format,
        }
        if metadata_url:
            body["metadata_url"] = metadata_url
        if metadata_xml:
            body["metadata_xml"] = metadata_xml
        if domains:
            body["domains"] = domains

        resp = await self._admin_request(
            "PUT", f"/auth/v1/admin/sso/providers/{provider_id}", json=body
        )
        if resp.status_code not in (200, 201):
            raise SsoProviderAdminError(
                f"Supabase update SSO provider failed: HTTP {resp.status_code} {resp.text}"
            )
        return resp.json()

    async def delete_provider(self, provider_id: str) -> None:
        resp = await self._admin_request(
            "DELETE", f"/auth/v1/admin/sso/providers/{provider_id}"
        )
        if resp.status_code not in (200, 202, 204, 404):
            raise SsoProviderAdminError(
                f"Supabase delete SSO provider failed: HTTP {resp.status_code} {resp.text}"
            )

    async def start_sso_url(
        self,
        *,
        provider_id: str,
        redirect_to: str,
        use_domain: bool = False,
        email_domain: str | None = None,
    ) -> str:
        """Return the IdP authorization URL for the given provider."""
        body: dict[str, Any] = {
            "redirect_to": redirect_to,
            "skip_http_redirect": True,
        }
        if use_domain and email_domain:
            body["domain"] = email_domain
        else:
            body["provider_id"] = provider_id

        resp = await self._anon_request("POST", "/auth/v1/sso", json=body)
        if resp.status_code != 200:
            raise SsoProviderAdminError(
                f"Supabase SSO start failed: HTTP {resp.status_code} {resp.text}"
            )
        result = resp.json()
        url = result.get("url")
        if not url:
            raise SsoProviderAdminError("Supabase SSO start did not return a redirect URL")
        return url

    async def test_provider(self, provider_id: str) -> bool:
        """Smoke-test the provider by attempting to get the start URL."""
        try:
            await self.start_sso_url(
                provider_id=provider_id,
                redirect_to="https://localhost/sso/test",
            )
            return True
        except SsoProviderAdminError:
            return False
