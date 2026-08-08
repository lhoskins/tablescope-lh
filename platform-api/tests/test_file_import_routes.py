"""Route-level behaviour for the file import API.

Covers what the builder depends on: capability discovery, refusal of unsafe
URLs with a safe message, tenant-scoped job access, cancellation, and the
admin-only surface for approved network locations.
"""

from __future__ import annotations

import pytest

from app.auth.jwt import create_access_token
from app.config import get_settings
from app.models.network_file_connection import NetworkFileConnection
from app.models.tenant import Tenant
from app.models.user import User
from app.services import file_ingestion

CSV = b"region,units\nnorth,10\n"


@pytest.fixture(autouse=True)
def _settings(tmp_path, monkeypatch):
    monkeypatch.setenv("FILE_IMPORT_QUARANTINE_PATH", str(tmp_path / "quarantine"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _headers(tenant_id: int, user_id: int, role: str = "editor") -> dict[str, str]:
    token = create_access_token(
        sub=str(user_id), tenant_id=tenant_id, user_id=user_id, role=role
    )
    return {"Authorization": f"Bearer {token}"}


async def _seed(db_session):
    tenant = Tenant(slug="imports", name="Imports Co")
    db_session.add(tenant)
    await db_session.commit()
    await db_session.refresh(tenant)
    user = User(
        tenant_id=tenant.id, email="editor@example.com", role="editor",
        external_id="ext-editor",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return tenant.id, user.id


@pytest.mark.asyncio
async def test_capabilities_report_enabled_methods(client, db_session):
    tenant_id, user_id = await _seed(db_session)
    res = await client.get(
        "/api/data-sources/imports/capabilities",
        headers=_headers(tenant_id, user_id),
    )
    assert res.status_code == 200
    body = res.json()
    assert body["local_upload_enabled"] is True
    assert body["url_import_enabled"] is True
    # Network import stays off until an operator turns it on.
    assert body["network_import_enabled"] is False
    assert body["network_connections"] == []


@pytest.mark.asyncio
async def test_capabilities_list_only_enabled_tenant_connections(client, db_session):
    tenant_id, user_id = await _seed(db_session)
    db_session.add_all(
        [
            NetworkFileConnection(
                tenant_id=tenant_id, name="Finance", host="fileserver",
                share_name="data", approved_root_path="finance",
                enabled=True, archived=False,
            ),
            NetworkFileConnection(
                tenant_id=tenant_id, name="Retired", host="oldserver",
                share_name="data", approved_root_path="",
                enabled=False, archived=False,
            ),
            NetworkFileConnection(
                tenant_id=tenant_id + 999, name="Other tenant", host="theirserver",
                share_name="data", approved_root_path="",
                enabled=True, archived=False,
            ),
        ]
    )
    await db_session.commit()

    res = await client.get(
        "/api/data-sources/imports/capabilities",
        headers=_headers(tenant_id, user_id),
    )
    names = [c["name"] for c in res.json()["network_connections"]]
    assert names == ["Finance"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "http://files.example.com/a.csv",
        "https://169.254.169.254/latest/meta-data/",
        "https://localhost/a.csv",
        "https://user:pw@files.example.com/a.csv",
    ],
)
async def test_unsafe_urls_are_refused(client, db_session, url):
    tenant_id, user_id = await _seed(db_session)
    res = await client.post(
        "/api/data-sources/imports/url",
        json={"url": url},
        headers=_headers(tenant_id, user_id),
    )
    assert res.status_code == 422
    # The message is user-safe and never echoes credentials.
    assert "pw" not in res.json()["detail"]


@pytest.mark.asyncio
async def test_network_import_is_refused_while_disabled(client, db_session):
    tenant_id, user_id = await _seed(db_session)
    connection = NetworkFileConnection(
        tenant_id=tenant_id, name="Finance", host="fileserver", share_name="data",
        approved_root_path="finance", enabled=True, archived=False,
    )
    db_session.add(connection)
    await db_session.commit()
    await db_session.refresh(connection)

    res = await client.post(
        "/api/data-sources/imports/network",
        json={
            "connection_id": connection.id,
            "path": r"\\fileserver\data\finance\sales.csv",
        },
        headers=_headers(tenant_id, user_id),
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_job_status_and_cancellation(client, db_session):
    tenant_id, user_id = await _seed(db_session)
    job, staged = await file_ingestion.acquire_local_upload(
        db_session, tenant_id=tenant_id, user_id=user_id, project_id=None,
        filename="sales.csv", data=CSV,
    )
    await db_session.commit()

    res = await client.get(
        f"/api/data-sources/imports/{job.id}", headers=_headers(tenant_id, user_id)
    )
    assert res.status_code == 200
    assert res.json()["import_job_id"] == job.id

    other = await client.get(
        f"/api/data-sources/imports/{job.id}",
        headers=_headers(tenant_id + 999, user_id),
    )
    assert other.status_code == 404

    cancelled = await client.delete(
        f"/api/data-sources/imports/{job.id}", headers=_headers(tenant_id, user_id)
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert not staged.content_path.exists()


@pytest.mark.asyncio
async def test_network_connection_admin_never_returns_the_secret(client, db_session):
    tenant_id, user_id = await _seed(db_session)
    created = await client.post(
        "/api/network-file-connections",
        json={
            "name": "Finance",
            "host": "FileServer",
            "share_name": "data",
            "approved_root_path": "finance",
            "username": "svc_reader",
            "password": "super-secret",
        },
        headers=_headers(tenant_id, user_id, role="admin"),
    )
    assert created.status_code == 200
    body = created.json()
    assert body["has_secret"] is True
    assert "super-secret" not in created.text
    assert "password" not in body
    assert "secret_encrypted" not in body
    # Hosts are normalised so the allowlist comparison is stable.
    assert body["host"] == "fileserver"

    listed = await client.get(
        "/api/network-file-connections",
        headers=_headers(tenant_id, user_id, role="admin"),
    )
    assert "super-secret" not in listed.text


@pytest.mark.asyncio
async def test_editors_cannot_manage_network_connections(client, db_session):
    tenant_id, user_id = await _seed(db_session)
    res = await client.get(
        "/api/network-file-connections", headers=_headers(tenant_id, user_id)
    )
    assert res.status_code == 403
