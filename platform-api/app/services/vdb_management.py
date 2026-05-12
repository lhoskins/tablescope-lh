"""VDB Management Service.

Async port of `redash/services/vdb_management.py` covering the parts the
platform API needs at this layer:

- Provisioning a fresh VDB for a tenant/user/shared scope
- Triggering a Teiid redeploy via the Java servlet API
- Health checks against the servlet

The actual VDB XML generation and file copying still happen in the Java
servlets — this service is a thin async HTTP client that calls them.
"""

from __future__ import annotations

import logging
import secrets
import string
from dataclasses import dataclass

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class VDBProvisioningError(Exception):
    """Raised when VDB provisioning or deployment fails."""


@dataclass(slots=True)
class VDBProvisionResult:
    vdb_id: str
    vdb_username: str
    vdb_password: str
    vdb_host: str
    vdb_port: int


def _generate_vdb_id(prefix: str = "ts") -> str:
    alphabet = string.digits
    return f"{prefix}_{''.join(secrets.choice(alphabet) for _ in range(7))}"


def _generate_password(length: int = 24) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


class VDBManagementService:
    """Thin async client around the WildFly Teiid management servlet."""

    def __init__(self, *, client: httpx.AsyncClient | None = None) -> None:
        settings = get_settings()
        self._settings = settings
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=settings.teiid_servlet_url,
            timeout=httpx.Timeout(30.0, connect=10.0),
            headers={"X-API-Key": settings.teiid_servlet_api_key} if settings.teiid_servlet_api_key else {},
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def health(self) -> bool:
        try:
            response = await self._client.get("/health")
            return response.status_code < 500
        except httpx.RequestError as exc:
            logger.warning("Teiid servlet health check failed: %s", exc)
            return False

    async def provision_user_vdb(
        self, *, tenant_external_id: str, user_external_id: str
    ) -> VDBProvisionResult:
        """Provision a new user VDB by delegating to the Teiid servlet."""
        payload = {
            "tenant": tenant_external_id,
            "user": user_external_id,
            "kind": "user",
        }
        vdb_id = _generate_vdb_id("u")
        password = _generate_password()
        try:
            response = await self._client.post(
                "/vdb/provision",
                json={
                    **payload,
                    "vdb_id": vdb_id,
                    "username": vdb_id,
                    "password": password,
                },
            )
        except httpx.RequestError as exc:
            raise VDBProvisioningError(f"Failed to contact Teiid servlet: {exc}") from exc

        if response.status_code >= 400:
            raise VDBProvisioningError(
                f"Teiid servlet rejected provisioning: {response.status_code} {response.text}"
            )
        return VDBProvisionResult(
            vdb_id=vdb_id,
            vdb_username=vdb_id,
            vdb_password=password,
            vdb_host=self._settings.teiid_pg_host,
            vdb_port=self._settings.teiid_pg_port,
        )

    async def provision_shared_vdb(self, *, tenant_external_id: str) -> VDBProvisionResult:
        vdb_id = _generate_vdb_id("s")
        password = _generate_password()
        try:
            response = await self._client.post(
                "/vdb/provision",
                json={
                    "tenant": tenant_external_id,
                    "kind": "shared",
                    "vdb_id": vdb_id,
                    "username": vdb_id,
                    "password": password,
                },
            )
        except httpx.RequestError as exc:
            raise VDBProvisioningError(f"Failed to contact Teiid servlet: {exc}") from exc

        if response.status_code >= 400:
            raise VDBProvisioningError(
                f"Teiid servlet rejected provisioning: {response.status_code} {response.text}"
            )
        return VDBProvisionResult(
            vdb_id=vdb_id,
            vdb_username=vdb_id,
            vdb_password=password,
            vdb_host=self._settings.teiid_pg_host,
            vdb_port=self._settings.teiid_pg_port,
        )

    async def redeploy_vdb(self, vdb_id: str) -> None:
        try:
            response = await self._client.post(f"/vdb/{vdb_id}/redeploy")
        except httpx.RequestError as exc:
            raise VDBProvisioningError(f"Failed to redeploy VDB {vdb_id}: {exc}") from exc
        if response.status_code >= 400:
            raise VDBProvisioningError(
                f"Teiid redeploy failed for {vdb_id}: {response.status_code} {response.text}"
            )
