"""Resolve the storage boundary for an organization.

An organization bound to a TenantDataPlane must never fall back to the global
bucket. Missing or unvalidated metadata is therefore a hard error. Legacy
organizations with no data-plane record retain the shared storage path.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.tenant_data_plane import STORAGE_STATUS_READY, TenantDataPlane


class StorageIsolationError(RuntimeError):
    """The requested tenant storage boundary is absent or unsafe."""


@dataclass(frozen=True, slots=True)
class StorageBinding:
    bucket_name: str
    region: str
    prefix: str
    local_base: Path
    access_point_arn: str | None = None
    vpc_endpoint_id: str | None = None
    endpoint_url: str | None = None
    kms_key_arn: str | None = None
    role_arn: str | None = None
    force_private: bool = False
    dedicated: bool = False

    def key(self, relative_key: str) -> str:
        clean = relative_key.lstrip("/")
        prefix = self.prefix.strip("/")
        return f"{prefix}/{clean}" if prefix else clean


class TenantStorageResolver:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def resolve_for_org(self, org_id: int) -> StorageBinding:
        plane = await self._session.scalar(
            select(TenantDataPlane).where(TenantDataPlane.org_tenant_id == org_id)
        )
        if plane is None:
            settings = get_settings()
            return StorageBinding(
                bucket_name=settings.s3_bucket_name,
                region=settings.s3_region,
                prefix="",
                local_base=Path(settings.customer_base_path),
            )

        required = {
            "s3_bucket_name": plane.s3_bucket_name,
            "s3_region": plane.s3_region,
            "s3_access_point_arn": plane.s3_access_point_arn,
            "s3_vpc_endpoint_id": plane.s3_vpc_endpoint_id,
            "s3_endpoint_url": plane.s3_endpoint_url,
            "s3_kms_key_arn": plane.s3_kms_key_arn,
            "s3_role_arn": plane.s3_role_arn,
        }
        missing = sorted(name for name, value in required.items() if not value)
        if missing:
            raise StorageIsolationError(
                f"tenant {plane.tenant_id} private storage is incomplete: {', '.join(missing)}"
            )
        if not plane.s3_force_private:
            raise StorageIsolationError(f"tenant {plane.tenant_id} private storage is not enforced")
        if plane.storage_status != STORAGE_STATUS_READY:
            raise StorageIsolationError(
                f"tenant {plane.tenant_id} storage is not validated (status={plane.storage_status})"
            )

        settings = get_settings()
        if plane.s3_bucket_name == settings.s3_bucket_name:
            raise StorageIsolationError(
                f"tenant {plane.tenant_id} cannot use the shared S3 bucket"
            )
        endpoint = urlparse(plane.s3_endpoint_url or "")
        hostname = endpoint.hostname or ""
        if endpoint.scheme != "https" or (plane.s3_vpc_endpoint_id or "") not in hostname:
            raise StorageIsolationError(f"tenant {plane.tenant_id} S3 endpoint is not private")
        if not (plane.s3_access_point_arn or "").startswith(f"arn:aws:s3:{plane.s3_region}:"):
            raise StorageIsolationError(f"tenant {plane.tenant_id} S3 access point region mismatch")
        if not (plane.s3_kms_key_arn or "").startswith(f"arn:aws:kms:{plane.s3_region}:"):
            raise StorageIsolationError(f"tenant {plane.tenant_id} KMS key region mismatch")

        assert plane.s3_bucket_name and plane.s3_region
        return StorageBinding(
            bucket_name=plane.s3_bucket_name,
            region=plane.s3_region,
            prefix=plane.s3_prefix or "",
            local_base=Path(plane.vdb_host_path),
            access_point_arn=plane.s3_access_point_arn,
            vpc_endpoint_id=plane.s3_vpc_endpoint_id,
            endpoint_url=plane.s3_endpoint_url,
            kms_key_arn=plane.s3_kms_key_arn,
            role_arn=plane.s3_role_arn,
            force_private=True,
            dedicated=True,
        )
