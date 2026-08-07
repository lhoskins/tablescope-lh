"""Internal file proxy used by the per-tenant Teiid remote-file resource adapter.

This endpoint is intentionally not under ``/api`` and is whitelisted in the auth
middleware.  It validates the caller by source IP (must be inside the tenant's
Docker subnet) and streams the requested remote file back to Teiid.
"""

from __future__ import annotations

import ipaddress
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models.file_source_meta import FileSourceMeta
from app.models.network_file_connection import NetworkFileConnection
from app.services.safe_remote_fetch import fetch_remote_file
from app.services.smb_gateway import NetworkPathError, read_network_file, resolve_network_path
from app.services.tenant_network_source_ip import get_tenant_source_ip

logger = logging.getLogger(__name__)
router = APIRouter()


def _client_ip(request: Request) -> str | None:
    """Return the most trusted client IP for an internal Docker-network call."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def _ip_in_cidr(ip_str: str, cidr: str | None) -> bool:
    if not cidr:
        return False
    try:
        return ipaddress.ip_address(ip_str) in ipaddress.ip_network(cidr)
    except ValueError:
        return False


def _source_allowed(client_ip: str | None, tenant_cidr: str | None, extra: list[str]) -> bool:
    if not client_ip:
        return False
    if _ip_in_cidr(client_ip, tenant_cidr):
        return True
    for cidr in extra:
        if _ip_in_cidr(client_ip, cidr):
            return True
    return False


@router.get("/internal/file-proxy")
async def file_proxy(
    request: Request,
    data_source_id: int,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Stream a live remote file to the tenant Teiid container."""
    settings = get_settings()
    client_ip = _client_ip(request)

    meta = await db.scalar(
        select(FileSourceMeta).where(FileSourceMeta.id == data_source_id)
    )
    if meta is None or meta.live_source_params is None:
        raise HTTPException(status_code=404, detail="Live source not found")

    tenant_id = meta.tenant_id
    source_ip = await get_tenant_source_ip(db, tenant_id)
    tenant_cidr: str | None = None
    if source_ip:
        # Derive the tenant Docker subnet from the bound source IP.
        from app.models.tenant_data_plane import TenantDataPlane

        plane = await db.scalar(
            select(TenantDataPlane).where(TenantDataPlane.org_tenant_id == tenant_id)
        )
        tenant_cidr = plane.docker_subnet_cidr if plane else None

    extra_cidrs = [c.strip() for c in (settings.file_import_network_source_cidrs or "").split(",") if c.strip()]
    if not _source_allowed(client_ip, tenant_cidr, extra_cidrs):
        logger.warning(
            "Rejected remote file proxy request for data_source_id=%s from %s",
            data_source_id,
            client_ip,
        )
        raise HTTPException(status_code=403, detail="Forbidden")

    params: dict[str, Any] = meta.live_source_params
    source_type = params.get("type")

    try:
        if source_type == "network_path":
            connection = await db.scalar(
                select(NetworkFileConnection).where(
                    NetworkFileConnection.id == params["connection_id"]
                )
            )
            if connection is None:
                raise HTTPException(status_code=404, detail="Network connection not found")
            approved_hosts = [h.strip().lower() for h in (settings.file_import_smb_host_allowlist or [])]
            resolved = resolve_network_path(params["path"], connection, approved_hosts)
            data = await read_network_file(resolved, connection, source_ip=source_ip)
        elif source_type == "url":
            data, _ = await fetch_remote_file(params["url"])
        else:
            raise HTTPException(status_code=400, detail="Unsupported live source type")
    except NetworkPathError as exc:
        raise HTTPException(status_code=502, detail=exc.message) from exc
    except Exception as exc:
        logger.exception("Remote file proxy failed for data_source_id=%s", data_source_id)
        raise HTTPException(status_code=502, detail="Failed to fetch remote file") from exc

    data, content_type = _maybe_convert_to_csv(data, meta.source_format)
    return Response(content=data, media_type=content_type)


def _maybe_convert_to_csv(data: bytes, source_format: str | None) -> tuple[bytes, str]:
    ext = (source_format or "").lower()
    if ext not in {"xlsx", "xlsm", "xls"}:
        return data, _content_type_for_format(source_format)
    try:
        import csv
        import io

        import openpyxl

        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        ws = wb.active
        buf = io.StringIO()
        writer = csv.writer(buf)
        for row in ws.iter_rows(values_only=True):
            writer.writerow(["" if c is None else str(c) for c in row])
        wb.close()
        return buf.getvalue().encode("utf-8"), "text/csv"
    except Exception:
        # If conversion fails, fall back to returning the raw bytes.
        return data, _content_type_for_format(source_format)


def _content_type_for_format(source_format: str | None) -> str:
    ext = (source_format or "").lower()
    if ext in {"xlsx", "xlsm", "xls"}:
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if ext == "csv":
        return "text/csv"
    if ext in {"tsv", "txt"}:
        return "text/plain"
    return "application/octet-stream"
