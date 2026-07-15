"""Route tests for repository connector administration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
import smbclient
from httpx import AsyncClient

from app.auth.jwt import create_access_token
from app.services.supabase_auth_service import SupabaseAuthService, SupabaseUser

pytestmark = pytest.mark.anyio


class _FakeSupabase(SupabaseAuthService):
    def __init__(self) -> None:
        pass

    async def create_or_invite_user(
        self, email, *, first_name=None, last_name=None, redirect_to=None
    ) -> SupabaseUser:
        return SupabaseUser(
            id=f"supa-{email}",
            email=email,
            created=True,
            action_link=f"https://invite/{email}",
        )


class _FakeEmail:
    async def send_transactional_email(
        self, *, to, template, variables, subject=None, reply_to=None, tenant_id=None, **kwargs
    ) -> bool:
        return True


@pytest.fixture(autouse=True)
def _mock_supabase(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.routes.tenants as tenants_module

    monkeypatch.setattr(tenants_module, "SupabaseAuthService", _FakeSupabase)
    monkeypatch.setattr(tenants_module, "EmailService", _FakeEmail)


@dataclass
class _FakeStat:
    st_size: int = 0
    st_ino: int = 12345
    st_mtime: float = 1704067200.0
    st_ctime: float = 1704067200.0


@dataclass
class _FakeDirEntry:
    name: str
    is_dir_flag: bool = False
    is_file_flag: bool = True
    is_symlink_flag: bool = False

    def is_dir(self) -> bool:
        return self.is_dir_flag

    def is_file(self) -> bool:
        return self.is_file_flag

    def is_symlink(self) -> bool:
        return self.is_symlink_flag

    def stat(self, *, follow_symlinks: bool = True) -> _FakeStat:
        return _FakeStat()

    def inode(self) -> int:
        return 12345


def _auth_headers(tenant_id: int, user_id: int, role: str = "tenant_admin") -> dict:
    token = create_access_token(
        sub="u", tenant_id=tenant_id, user_id=user_id, role=role
    )
    return {"Authorization": f"Bearer {token}"}


async def _setup(client: AsyncClient, service_headers: dict, slug: str = "repo-tenant"):
    r = await client.post(
        "/api/tenants",
        json={"slug": slug, "name": f"{slug} tenant"},
        headers=service_headers,
    )
    assert r.status_code == 201, r.text
    tenant = r.json()

    r = await client.post(
        f"/api/tenants/{tenant['id']}/users",
        json={
            "email": f"{slug}@test.com",
            "display_name": "Repo User",
            "role": "admin",
            "external_id": f"ext-{slug}",
        },
        headers=service_headers,
    )
    assert r.status_code == 201, r.text
    user = r.json()
    headers = _auth_headers(tenant["id"], user["id"])
    return tenant, user, headers


@pytest.fixture(autouse=True)
def _patch_smb_and_redis(monkeypatch: pytest.MonkeyPatch) -> None:

    def _fake_scandir(path: str) -> list[Any]:
        return [
            _FakeDirEntry("report.pdf", is_dir_flag=False, is_file_flag=True),
            _FakeDirEntry("archive", is_dir_flag=True, is_file_flag=False),
        ]

    monkeypatch.setattr("smbclient.register_session", lambda server, **kwargs: None)
    monkeypatch.setattr("smbclient.delete_session", lambda server: None)
    monkeypatch.setattr(smbclient, "scandir", _fake_scandir)
    monkeypatch.setattr("smbclient.path.isdir", lambda path: True)
    monkeypatch.setattr("socket.getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("127.0.0.1", 0))])

    async def _fake_enqueue(*, tenant_id: int, connection_id: int, scan_id: int) -> str:
        return f"job-{scan_id}"

    import app.routes.repository_connectors as rc
    monkeypatch.setattr(rc, "enqueue_scan_repository_connection", _fake_enqueue)


async def test_list_connector_types(client: AsyncClient, service_headers: dict) -> None:
    tenant, user, headers = await _setup(client, service_headers)
    r = await client.get("/api/repository-connectors/types", headers=headers)
    assert r.status_code == 200
    types = r.json()
    assert any(t["connector_type"] == "unc" for t in types)


async def test_create_and_list_connections(
    client: AsyncClient,
    service_headers: dict,
) -> None:
    tenant, user, headers = await _setup(client, service_headers)

    body = {
        "name": "Finance share",
        "connector_type": "unc",
        "config": {"rootPath": r"\\server\share\Finance"},
        "secret": {"username": "svc", "password": "secret"},
    }
    r = await client.post("/api/repository-connectors/", json=body, headers=headers)
    assert r.status_code == 201, r.text
    conn = r.json()
    assert conn["name"] == "Finance share"
    assert conn["has_credential"] is True
    assert "secret" not in conn

    r = await client.get("/api/repository-connectors/", headers=headers)
    assert r.status_code == 200
    assert any(c["id"] == conn["id"] for c in r.json())


async def test_update_with_version_conflict(
    client: AsyncClient,
    service_headers: dict,
) -> None:
    tenant, user, headers = await _setup(client, service_headers)

    body = {
        "name": "Finance share",
        "connector_type": "unc",
        "config": {"rootPath": r"\\server\share\Finance"},
        "secret": {"username": "svc", "password": "secret"},
    }
    r = await client.post("/api/repository-connectors/", json=body, headers=headers)
    conn = r.json()

    patch = {"name": "Finance share updated", "expected_version": 999}
    r = await client.patch(
        f"/api/repository-connectors/{conn['id']}",
        json=patch,
        headers=headers,
    )
    assert r.status_code == 409


async def test_test_connection_config(client: AsyncClient, service_headers: dict) -> None:
    tenant, user, headers = await _setup(client, service_headers)

    body = {
        "connector_type": "unc",
        "config": {"rootPath": r"\\server\share"},
        "secret": {"username": "u", "password": "p"},
    }
    r = await client.post("/api/repository-connectors/test", json=body, headers=headers)
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["success"] is True


async def test_test_existing_connection(
    client: AsyncClient,
    service_headers: dict,
) -> None:
    tenant, user, headers = await _setup(client, service_headers)

    body = {
        "name": "HR share",
        "connector_type": "unc",
        "config": {"rootPath": r"\\server\share\HR"},
        "secret": {"username": "u", "password": "p"},
    }
    r = await client.post("/api/repository-connectors/", json=body, headers=headers)
    conn = r.json()

    r = await client.post(
        f"/api/repository-connectors/{conn['id']}/test",
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["success"] is True


async def test_start_scan(client: AsyncClient, service_headers: dict) -> None:
    tenant, user, headers = await _setup(client, service_headers)

    body = {
        "name": "Ops share",
        "connector_type": "unc",
        "config": {"rootPath": r"\\server\share\Ops"},
        "secret": {"username": "u", "password": "p"},
    }
    r = await client.post("/api/repository-connectors/", json=body, headers=headers)
    conn = r.json()

    r = await client.post(
        f"/api/repository-connectors/{conn['id']}/scans",
        headers=headers,
    )
    assert r.status_code == 202, r.text
    scan = r.json()
    assert scan["status"] == "queued"
    assert scan["job_id"].startswith("job-")

    r = await client.get(
        f"/api/repository-connectors/{conn['id']}/scans",
        headers=headers,
    )
    assert r.status_code == 200
    assert any(s["id"] == scan["id"] for s in r.json())


async def test_profile_and_items_return_cleanly(
    client: AsyncClient,
    service_headers: dict,
) -> None:
    tenant, user, headers = await _setup(client, service_headers)

    body = {
        "name": "Empty share",
        "connector_type": "unc",
        "config": {"rootPath": r"\\server\share\Empty"},
        "secret": {"username": "u", "password": "p"},
    }
    r = await client.post("/api/repository-connectors/", json=body, headers=headers)
    conn = r.json()

    r = await client.get(
        f"/api/repository-connectors/{conn['id']}/profile",
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["profile"]["total_files"] == 0

    r = await client.get(
        f"/api/repository-connectors/{conn['id']}/items",
        headers=headers,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["items"] == []
    assert data["total"] == 0


async def test_tenant_isolation(
    client: AsyncClient,
    service_headers: dict,
) -> None:
    tenant1, user1, headers1 = await _setup(client, service_headers, slug="t1")
    tenant2, user2, headers2 = await _setup(client, service_headers, slug="t2")

    body = {
        "name": "Shared",
        "connector_type": "unc",
        "config": {"rootPath": r"\\server\share"},
        "secret": {"username": "u", "password": "p"},
    }
    r = await client.post("/api/repository-connectors/", json=body, headers=headers1)
    conn = r.json()

    r = await client.get(
        f"/api/repository-connectors/{conn['id']}",
        headers=headers2,
    )
    assert r.status_code == 404
