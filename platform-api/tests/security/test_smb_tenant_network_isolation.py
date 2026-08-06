"""Tenant-bound egress for SMB/network-path imports.

These tests verify that the SMB socket is bound to a worker IP inside the
tenant's Docker network so the host ``DOCKER-USER`` firewall chain can enforce
per-tenant CIDR isolation.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.services import smb_gateway
from app.services.smb_gateway import (
    NetworkFileConnection,
    NetworkPathError,
    ResolvedNetworkPath,
    check_network_access,
    read_network_file,
)
from app.services.tenant_network_source_ip import (
    find_source_ip_for_cidr,
    get_tenant_source_ip,
)


@pytest.mark.asyncio
async def test_get_tenant_source_ip_returns_ip_in_docker_subnet(db_session):
    from app.models.tenant import Tenant
    from app.models.tenant_data_plane import TenantDataPlane

    tenant = Tenant(id=1, name="Acme", slug="acme")
    plane = TenantDataPlane(
        tenant_id="acme",
        tenant_name="Acme",
        org_tenant_id=1,
        docker_network_name="tablescope-tenant-acme",
        docker_subnet_cidr="172.30.10.0/24",
        teiid_container_name="tablescope-teiid-acme",
        teiid_container_ip="172.30.10.3",
        teiid_servlet_url="http://example/vdb",
        teiid_pg_host="172.30.10.3",
        teiid_pg_port=5432,
        vdb_host_path="/tmp/vdb",
        vdb_container_path="/opt/vdb",
        allowed_onprem_cidrs=["10.250.10.0/24"],
    )
    db_session.add(tenant)
    db_session.add(plane)
    await db_session.commit()

    ip_json = json.dumps(
        [
            {
                "ifname": "eth0",
                "addr_info": [
                    {"family": "inet", "local": "172.31.0.2"},
                ],
            },
            {
                "ifname": "eth1",
                "addr_info": [
                    {"family": "inet", "local": "172.30.10.5"},
                ],
            },
        ]
    )
    with patch(
        "app.services.tenant_network_source_ip.subprocess.run",
        return_value=MagicMock(returncode=0, stdout=ip_json),
    ):
        source_ip = await get_tenant_source_ip(db_session, 1)

    assert source_ip == "172.30.10.5"


def test_find_source_ip_for_cidr_parses_text_fallback():
    text = """
1: lo: <LOOPBACK> mtu 65536
    inet 127.0.0.1/8 scope host lo
2: eth0: <BROADCAST> mtu 1500
    inet 172.30.20.7/24 brd 172.30.20.255 scope global eth0
"""
    with patch(
        "app.services.tenant_network_source_ip.subprocess.run",
        side_effect=[
            FileNotFoundError(),
            MagicMock(returncode=0, stdout=text),
        ],
    ):
        ip = find_source_ip_for_cidr("172.30.20.0/24")
    assert ip == "172.30.20.7"


def test_find_source_ip_for_cidr_returns_none_when_not_connected():
    with patch(
        "app.services.tenant_network_source_ip.subprocess.run",
        return_value=MagicMock(returncode=0, stdout="[]"),
    ):
        assert find_source_ip_for_cidr("10.99.0.0/24") is None


@pytest.mark.anyio
async def test_read_network_file_binds_socket_to_tenant_source_ip():
    captured: list[tuple] = []

    def _fake_create_connection(address, timeout=None, source_address=None):
        captured.append((address, source_address))
        raise OSError("no route")

    conn = NetworkFileConnection(
        id=1,
        tenant_id=1,
        name="repo",
        host="fileserver",
        port=445,
        share_name="data",
        approved_root_path="finance",
    )
    resolved = ResolvedNetworkPath(
        host="fileserver",
        share="data",
        relative_path="finance/sales.csv",
        filename="sales.csv",
    )

    with patch.object(smb_gateway, "_orig_create_connection", _fake_create_connection):
        with pytest.raises(NetworkPathError):
            await read_network_file(resolved, conn, source_ip="172.30.10.5")

    assert any(src == ("172.30.10.5", 0) for _, src in captured)


@pytest.mark.anyio
async def test_test_network_access_binds_socket_to_tenant_source_ip():
    captured: list[tuple] = []

    def _fake_create_connection(address, timeout=None, source_address=None):
        captured.append((address, source_address))
        raise OSError("no route")

    conn = NetworkFileConnection(
        id=1,
        tenant_id=1,
        name="repo",
        host="fileserver",
        port=445,
        share_name="data",
        approved_root_path="finance",
    )

    with patch.object(smb_gateway, "_orig_create_connection", _fake_create_connection):
        with pytest.raises(NetworkPathError):
            await check_network_access(conn, source_ip="172.30.10.5")

    assert any(src == ("172.30.10.5", 0) for _, src in captured)
