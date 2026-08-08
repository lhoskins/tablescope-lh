"""Determine the local IP address the shared worker should use for a tenant.

When the `platform-api-worker` container is connected to a tenant's Docker
network, it gets an interface inside that tenant's subnet. Binding outbound
SMB sockets to that IP lets the host's `DOCKER-USER` tenant firewall chain
classify the traffic by source subnet and enforce that the process can only
reach that tenant's approved on-prem CIDRs.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import socket
import subprocess
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant_data_plane import TenantDataPlane

logger = logging.getLogger(__name__)

#: Cached tenant source IP lookup. The worker's interface inside a tenant Docker
#: network is stable for the lifetime of the container, so a short TTL avoids
#: repeating subprocess/DNS work on every network file request.
_source_ip_cache: dict[int, tuple[str | None, datetime]] = {}
_SOURCE_IP_CACHE_TTL = timedelta(seconds=60)


def _ipv4_in_cidr(ip_str: str, network_str: str) -> bool:
    try:
        return ipaddress.ip_address(ip_str) in ipaddress.ip_network(network_str)
    except ValueError:
        return False


def _parse_ip_json(output: str) -> list[dict[str, Any]]:
    try:
        parsed = json.loads(output)
    except json.JSONDecodeError:
        return []
    if isinstance(parsed, dict):
        return [parsed]
    return parsed if isinstance(parsed, list) else []


def _parse_ip_text(output: str) -> list[str]:
    """Fallback text parser for ``ip -4 addr show`` output."""
    ips: list[str] = []
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("inet "):
            # Format: inet 172.30.10.2/24 brd ...
            parts = line.split()
            if len(parts) >= 2:
                ips.append(parts[1].split("/")[0])
    return ips


def _list_local_ipv4() -> list[str]:
    """Return all local IPv4 addresses visible to the current namespace."""
    # Prefer JSON output for robustness; fall back to text parsing.
    for cmd in (
        ["ip", "-4", "-json", "addr", "show"],
        ["ip", "-4", "addr", "show"],
    ):
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if result.returncode == 0:
                if cmd[2] == "-json":
                    ip_list: list[str] = []
                    for iface in _parse_ip_json(result.stdout):
                        for addr in iface.get("addr_info", []):
                            if addr.get("family") == "inet" and "local" in addr:
                                ip_list.append(addr["local"])
                    return ip_list
                return _parse_ip_text(result.stdout)
        except FileNotFoundError:
            continue
        except subprocess.TimeoutExpired:
            logger.warning("Timeout listing local IP addresses")

    # Minimal fallback when `ip` is not installed: getaddrinfo on the container's
    # hostname returns the IPv4 addresses assigned to all attached interfaces.
    ips: list[str] = []
    for host in (socket.gethostname(), socket.getfqdn()):
        try:
            for family, _, _, _, sockaddr in socket.getaddrinfo(
                host, None, socket.AF_INET
            ):
                if family == socket.AF_INET:
                    ips.append(sockaddr[0])
        except socket.gaierror:
            continue
    return list(dict.fromkeys(ips))


def find_source_ip_for_cidr(docker_subnet_cidr: str) -> str | None:
    """Return a local IPv4 address that belongs to ``docker_subnet_cidr``.

    Returns ``None`` when the worker is not connected to the tenant network.
    """
    if not docker_subnet_cidr:
        return None
    for ip in _list_local_ipv4():
        if _ipv4_in_cidr(ip, docker_subnet_cidr):
            return ip
    return None


async def get_tenant_source_ip(session: AsyncSession, tenant_id: int) -> str | None:
    """Find the worker's IP in the tenant Docker network.

    ``tenant_id`` is the application-level integer tenant id (the ``tenants.id``
    column). It is mapped through ``TenantDataPlane.org_tenant_id``.

    The IP lookup does blocking subprocess/socket work, so it runs off the
    async event loop and is cached for a short TTL.
    """
    now = datetime.now(UTC)
    cached = _source_ip_cache.get(tenant_id)
    if cached is not None and now - cached[1] < _SOURCE_IP_CACHE_TTL:
        return cached[0]

    plane = await session.scalar(
        select(TenantDataPlane).where(TenantDataPlane.org_tenant_id == tenant_id)
    )
    if plane is None:
        logger.debug("No TenantDataPlane for tenant %s", tenant_id)
        return None

    try:
        ip = await asyncio.wait_for(
            asyncio.to_thread(find_source_ip_for_cidr, plane.docker_subnet_cidr),
            timeout=10,
        )
    except TimeoutError:
        logger.warning("Timeout resolving source IP for tenant %s", tenant_id)
        ip = None
    _source_ip_cache[tenant_id] = (ip, now)
    return ip
