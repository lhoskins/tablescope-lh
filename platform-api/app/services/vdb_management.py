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


def _generate_vdb_id() -> str:
    """Generate a 7-digit numeric VDB ID matching the servlet convention."""
    return "".join(secrets.choice(string.digits) for _ in range(7))


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
            timeout=httpx.Timeout(60.0, connect=10.0),
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

    async def create_user_vdb(
        self, *, org_id: int, user_id: int
    ) -> VDBProvisionResult:
        """Create and deploy a user-level VDB via the servlet.

        Calls POST /TeiidExcelImporterTest/vdb-management/createVDB which:
        1. Creates VDB XML from template in /customers/{org_id}/{user_id}/vdb/
        2. Deploys the VDB to Teiid via the Admin API
        """
        vdb_id = _generate_vdb_id()
        username = f"vdb_user_{vdb_id}"
        password = _generate_password()

        payload = {
            "org_id": org_id,
            "vdb_id": vdb_id,
            "username": username,
            "password": password,
            "teiid_host": "localhost",
            "teiid_port": 9999,
            "vdb_type": "user",
            "user_id": user_id,
        }

        logger.info(
            "Creating user VDB: org_id=%s user_id=%s vdb_id=%s",
            org_id, user_id, vdb_id,
        )

        try:
            response = await self._client.post(
                "/TeiidExcelImporterTest/vdb-management/createVDB",
                json=payload,
            )
        except httpx.RequestError as exc:
            raise VDBProvisioningError(f"Failed to contact Teiid servlet: {exc}") from exc

        if response.status_code >= 400:
            raise VDBProvisioningError(
                f"Teiid servlet rejected VDB creation: {response.status_code} {response.text}"
            )

        logger.info("User VDB created and deployed: vdb_id=%s", vdb_id)

        return VDBProvisionResult(
            vdb_id=vdb_id,
            vdb_username=username,
            vdb_password=password,
            vdb_host=self._settings.teiid_pg_host,
            vdb_port=self._settings.teiid_pg_port,
        )

    async def create_shared_vdb(self, *, org_id: int) -> VDBProvisionResult:
        """Create and deploy a shared (tenant-level) VDB via the servlet."""
        vdb_id = _generate_vdb_id()
        username = f"vdb_shared_{vdb_id}"
        password = _generate_password()

        payload = {
            "org_id": org_id,
            "vdb_id": vdb_id,
            "username": username,
            "password": password,
            "teiid_host": "localhost",
            "teiid_port": 9999,
            "vdb_type": "shared",
        }

        logger.info("Creating shared VDB: org_id=%s vdb_id=%s", org_id, vdb_id)

        try:
            response = await self._client.post(
                "/TeiidExcelImporterTest/vdb-management/createVDB",
                json=payload,
            )
        except httpx.RequestError as exc:
            raise VDBProvisioningError(f"Failed to contact Teiid servlet: {exc}") from exc

        if response.status_code >= 400:
            raise VDBProvisioningError(
                f"Teiid servlet rejected shared VDB creation: {response.status_code} {response.text}"
            )

        logger.info("Shared VDB created and deployed: vdb_id=%s", vdb_id)

        return VDBProvisionResult(
            vdb_id=vdb_id,
            vdb_username=username,
            vdb_password=password,
            vdb_host=self._settings.teiid_pg_host,
            vdb_port=self._settings.teiid_pg_port,
        )

    async def redeploy_vdb(
        self, vdb_id: str, *, vdb_file_path: str | None = None
    ) -> None:
        """Redeploy an existing VDB via the servlet."""
        payload: dict = {
            "vdb_id": vdb_id,
            "teiid_host": "localhost",
            "teiid_port": 9999,
        }
        if vdb_file_path:
            payload["vdb_file_path"] = vdb_file_path

        try:
            response = await self._client.post(
                "/TeiidExcelImporterTest/vdb-management/redeployVDB",
                json=payload,
            )
        except httpx.RequestError as exc:
            raise VDBProvisioningError(f"Failed to redeploy VDB {vdb_id}: {exc}") from exc
        if response.status_code >= 400:
            raise VDBProvisioningError(
                f"Teiid redeploy failed for {vdb_id}: {response.status_code} {response.text}"
            )
        logger.info("VDB redeployed: vdb_id=%s", vdb_id)

    async def provision_user_vdb(
        self, *, tenant_external_id: str, user_external_id: str
    ) -> VDBProvisionResult:
        """Legacy provisioning endpoint (kept for backward compatibility)."""
        return await self.create_user_vdb(
            org_id=int(tenant_external_id) if tenant_external_id.isdigit() else 0,
            user_id=int(user_external_id) if user_external_id.isdigit() else 0,
        )

    async def provision_shared_vdb(self, *, tenant_external_id: str) -> VDBProvisionResult:
        """Legacy provisioning endpoint (kept for backward compatibility)."""
        return await self.create_shared_vdb(
            org_id=int(tenant_external_id) if tenant_external_id.isdigit() else 0,
        )
