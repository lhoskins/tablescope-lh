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

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        servlet_url: str | None = None,
        pg_host: str | None = None,
        pg_port: int | None = None,
    ) -> None:
        settings = get_settings()
        self._settings = settings
        # When a tenant is bound to a dedicated data plane the caller passes the
        # tenant container's servlet/PG endpoint; otherwise we use the shared
        # global Teiid so single-tenant behaviour is preserved.
        self._servlet_url = servlet_url or settings.teiid_servlet_url
        self._pg_host = pg_host or settings.teiid_pg_host
        self._pg_port = pg_port or settings.teiid_pg_port
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=self._servlet_url,
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
        # Use fixed 'test/test' credentials matching WildFly's
        # application-users.properties — same as original Tablescope/Redash.
        username = "test"
        password = "test"

        payload = {
            "org_id": org_id,
            "vdb_id": vdb_id,
            "username": username,
            "password": password,
            "teiid_host": "localhost",
            "teiid_port": 9990,
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

        # Sync VDB file to S3 if enabled
        self._sync_vdb_to_s3(org_id, vdb_id, vdb_type="user", user_id=user_id)

        return VDBProvisionResult(
            vdb_id=vdb_id,
            vdb_username=username,
            vdb_password=password,
            vdb_host=self._pg_host,
            vdb_port=self._pg_port,
        )

    async def create_shared_vdb(self, *, org_id: int) -> VDBProvisionResult:
        """Create and deploy a shared (tenant-level) VDB via the servlet."""
        vdb_id = _generate_vdb_id()
        username = "test"
        password = "test"

        payload = {
            "org_id": org_id,
            "vdb_id": vdb_id,
            "username": username,
            "password": password,
            "teiid_host": "localhost",
            "teiid_port": 9990,
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

        # Sync VDB file to S3 if enabled
        self._sync_vdb_to_s3(org_id, vdb_id, vdb_type="shared")

        return VDBProvisionResult(
            vdb_id=vdb_id,
            vdb_username=username,
            vdb_password=password,
            vdb_host=self._pg_host,
            vdb_port=self._pg_port,
        )

    def _sync_vdb_to_s3(self, org_id: int, vdb_id: str, *, vdb_type: str, user_id: int | None = None) -> None:
        """Sync VDB XML file to S3 after creation/modification."""
        if not self._settings.s3_enabled:
            return
        try:
            from app.services.s3_storage import S3StorageService
            s3_svc = S3StorageService()
            if vdb_type == "shared":
                local_path = f"{self._settings.customer_base_path}/{org_id}/shared/vdb/{vdb_id}-vdb.xml"
                s3_key = s3_svc.get_s3_key_for_shared_vdb(org_id, vdb_id)
            else:
                local_path = f"{self._settings.customer_base_path}/{org_id}/{user_id}/vdb/{vdb_id}-vdb.xml"
                s3_key = s3_svc.get_s3_key_for_vdb(org_id, user_id or 0, vdb_id)
            import os
            if os.path.exists(local_path):
                s3_svc.upload_file(local_path, s3_key)
            else:
                logger.warning("VDB file not found for S3 sync: %s", local_path)
        except Exception as e:
            logger.warning("S3 VDB sync failed (non-fatal): %s", e)

    async def redeploy_vdb(
        self, vdb_id: str, *, vdb_file_path: str | None = None
    ) -> None:
        """Redeploy an existing VDB via the servlet."""
        payload: dict = {
            "vdb_id": vdb_id,
            "teiid_host": "localhost",
            "teiid_port": 9990,
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

    async def delete_vdb(
        self,
        vdb_id: str,
        *,
        org_id: int,
        vdb_type: str = "shared",
        user_id: int | None = None,
    ) -> None:
        """Undeploy a VDB from Teiid and archive its file via the servlet.

        Best-effort: a missing/already-undeployed VDB is not treated as fatal so
        tenant deletion can proceed even if Teiid no longer has the VDB.
        """
        payload: dict = {
            "org_id": org_id,
            "vdb_id": vdb_id,
            "teiid_host": "localhost",
            "teiid_port": 9990,
            "vdb_type": vdb_type,
        }
        if vdb_type == "user" and user_id is not None:
            payload["user_id"] = user_id

        try:
            response = await self._client.post(
                "/TeiidExcelImporterTest/vdb-management/deleteVDB",
                json=payload,
            )
        except httpx.RequestError as exc:
            raise VDBProvisioningError(
                f"Failed to contact Teiid servlet to delete VDB {vdb_id}: {exc}"
            ) from exc
        if response.status_code >= 400:
            raise VDBProvisioningError(
                f"Teiid delete failed for {vdb_id}: {response.status_code} {response.text}"
            )
        logger.info("VDB deleted/undeployed: vdb_id=%s", vdb_id)

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
