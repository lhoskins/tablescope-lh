"""Integration tests for the SMB/network-path import pipeline.

These tests exercise the full acquisition path through the staging service
and verify that tenant-bound source IP binding is plumbed from the database
to the SMB socket.
"""

from __future__ import annotations

import hashlib

import pytest

import app.services.file_ingestion as file_ingestion
from app.config import get_settings
from app.models.tenant import Tenant
from app.models.tenant_data_plane import TenantDataPlane


@pytest.fixture
async def _seeded(db_session):
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
    return db_session


@pytest.mark.asyncio
async def test_network_import_uses_tenant_source_ip(_seeded, monkeypatch):
    from app.models.network_file_connection import NetworkFileConnection
    from app.services import smb_gateway

    monkeypatch.setenv("FILE_IMPORT_NETWORK_ENABLED", "true")
    monkeypatch.setenv("FILE_IMPORT_ALLOWED_SMB_HOSTS", "fileserver")
    monkeypatch.setenv("FILE_IMPORT_QUARANTINE_PATH", "/tmp/quarantine")
    get_settings.cache_clear()

    conn = NetworkFileConnection(
        id=7,
        tenant_id=1,
        name="repo",
        host="fileserver",
        port=445,
        share_name="data",
        approved_root_path="finance",
        username="tablescope_ro",
        secret_encrypted="gAAAAAtoken",
        enabled=True,
        archived=False,
    )

    captured: dict = {}

    async def _fake_read_network_file(resolved, connection, *, source_ip=None):
        captured["source_ip"] = source_ip
        return b"name\nvalue\n"

    monkeypatch.setattr(smb_gateway, "read_network_file", _fake_read_network_file)
    monkeypatch.setattr(file_ingestion, "read_network_file", _fake_read_network_file)

    ip_json = '{"ifname": "eth1", "addr_info": [{"family": "inet", "local": "172.30.10.5"}]}'
    monkeypatch.setattr(
        "app.services.tenant_network_source_ip.subprocess.run",
        lambda *a, **k: type("R", (), {"returncode": 0, "stdout": ip_json})(),
    )

    job, staged = await file_ingestion.acquire_network_path(
        _seeded,
        tenant_id=1,
        user_id=1,
        project_id=None,
        connection=conn,
        path=r"\\fileserver\data\finance\sales.csv",
    )

    assert captured.get("source_ip") == "172.30.10.5"
    assert staged.sha256 == hashlib.sha256(b"name\nvalue\n").hexdigest()
    assert job.method == "network_path"
