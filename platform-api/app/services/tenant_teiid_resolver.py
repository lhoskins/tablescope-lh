"""Resolve the correct Teiid endpoint for a tenant.

Once the multi-tenant data plane is enabled, any backend operation that talks to
Teiid (VDB management, data-source registration, query execution, scope proxy)
must resolve the endpoint *by tenant* instead of using the single global
``TEIID_SERVLET_URL`` / ``TEIID_PG_HOST``.

This resolver looks up the tenant's :class:`TenantDataPlane` and returns its
dedicated servlet/PG endpoint. When no data plane exists for the tenant (the
default in dev/single-tenant mode) it falls back to the global settings, so
existing behaviour is preserved.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.tenant_data_plane import TenantDataPlane, TenantSecretRef
from app.services.tenant_layout import (
    TEIID_PG_CONTAINER_PORT,
    TEIID_SERVLET_CONTAINER_PORT,
)


@dataclass(slots=True)
class TeiidEndpoint:
    servlet_url: str
    pg_host: str
    pg_port: int
    api_key_secret_ref: str | None
    vdb_host_path: str
    tenant_id: str | None
    is_dedicated: bool


class TenantTeiidResolver:
    """Resolve a :class:`TeiidEndpoint` for a tenant, with dev-mode fallback."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _data_plane(self, tenant_id: str) -> TenantDataPlane | None:
        return await self._session.scalar(select(TenantDataPlane).where(TenantDataPlane.tenant_id == tenant_id))

    async def _data_plane_by_org(self, org_tenant_id: int) -> TenantDataPlane | None:
        return await self._session.scalar(
            select(TenantDataPlane).where(TenantDataPlane.org_tenant_id == org_tenant_id)
        )

    def _global_endpoint(self) -> TeiidEndpoint:
        settings = get_settings()
        return TeiidEndpoint(
            servlet_url=settings.teiid_servlet_url,
            pg_host=settings.teiid_pg_host,
            pg_port=settings.teiid_pg_port,
            api_key_secret_ref=None,
            vdb_host_path=settings.customer_base_path,
            tenant_id=None,
            is_dedicated=False,
        )

    async def _endpoint_for_plane(self, plane: TenantDataPlane) -> TeiidEndpoint:
        api_key_ref = await self._session.scalar(
            select(TenantSecretRef.secret_ref).where(
                TenantSecretRef.tenant_id == plane.tenant_id,
                TenantSecretRef.secret_name == "teiid_api_key",
            )
        )

        # When containerized, reach the tenant Teiid over the tenant Docker
        # network (container IP + container port); the host's 127.0.0.1 ports
        # are not reachable from inside another container.
        if get_settings().tenant_teiid_in_cluster and plane.teiid_container_ip:
            servlet_url = f"http://{plane.teiid_container_ip}:{TEIID_SERVLET_CONTAINER_PORT}"
            pg_host = plane.teiid_container_ip
            pg_port = TEIID_PG_CONTAINER_PORT
        else:
            servlet_url = plane.teiid_servlet_url
            pg_host = plane.teiid_pg_host
            pg_port = plane.teiid_pg_port

        return TeiidEndpoint(
            servlet_url=servlet_url,
            pg_host=pg_host,
            pg_port=pg_port,
            api_key_secret_ref=api_key_ref,
            vdb_host_path=plane.vdb_host_path,
            tenant_id=plane.tenant_id,
            is_dedicated=True,
        )

    async def resolve(self, tenant_id: str | None) -> TeiidEndpoint:
        """Return the Teiid endpoint for the data-plane ``tenant_id`` (slug).

        Falls back to the global single-tenant endpoint when the tenant has no
        dedicated data plane (dev mode / criteria 11-12).
        """
        if not tenant_id:
            return self._global_endpoint()
        plane = await self._data_plane(tenant_id)
        if plane is None:
            return self._global_endpoint()
        return await self._endpoint_for_plane(plane)

    async def resolve_for_org(self, org_tenant_id: int | None) -> TeiidEndpoint:
        """Return the Teiid endpoint for an *application* (org) tenant id.

        This is the entry point used by the serving path: a logged-in user's
        JWT carries the numeric org tenant id. If that org tenant is bound to a
        dedicated data plane (``tenant_data_planes.org_tenant_id``) all Teiid
        traffic is routed to that tenant's container; otherwise it falls back to
        the shared global Teiid so existing single-tenant tenants are unaffected.
        """
        if not org_tenant_id:
            return self._global_endpoint()
        plane = await self._data_plane_by_org(org_tenant_id)
        if plane is None:
            return self._global_endpoint()
        return await self._endpoint_for_plane(plane)
