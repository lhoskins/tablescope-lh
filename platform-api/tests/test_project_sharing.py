"""Tests for ProjectSharingService.share_project (task #17).

Live findings this fixes:
- SharedVDB used to be looked up/created per tenant, so two shared projects
  in the same tenant collided in the same VDB (migration 0087 makes it
  per (tenant_id, project_id) instead).
- share_project used to copy files into a folder
  (customer_folders.py's tenant-slug-based "shared/data") that nothing else
  -- not the Teiid VDB, not any other read path -- ever reads from, and
  then called the template-based redeploy_vdb, which never builds real
  views. It now reads each file's real bytes from the owner's actual
  uploads folder and posts them through the same /upload servlet mechanism
  already proven for private uploads (vdb_type=shared, project-scoped).

Run from ``platform-api``: ``pytest -q tests/test_project_sharing.py``.
"""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select

from app.auth.context import RequestContext
from app.auth.jwt import TokenClaims
from app.config import get_settings
from app.models.project import Project
from app.models.shared_vdb import SharedVDB
from app.models.tenant import Tenant
from app.models.user import User
from app.services.project_sharing import ProjectSharingError, ProjectSharingService
from app.services.vdb_management import VDBManagementService

pytestmark = pytest.mark.anyio


def _context(tenant_id: int, user_id: int) -> RequestContext:
    return RequestContext(
        claims=TokenClaims(sub=str(user_id), tenant_id=tenant_id, user_id=user_id, role="editor")
    )


async def _seed(db_session, slug: str) -> tuple[int, int]:
    tenant = Tenant(slug=slug, name=slug)
    db_session.add(tenant)
    await db_session.flush()
    owner = User(
        tenant_id=tenant.id,
        email=f"owner@{slug}.com",
        display_name="Owner",
        role="admin",
        external_id=f"ext-{slug}",
    )
    db_session.add(owner)
    await db_session.flush()
    return tenant.id, owner.id


def _write_upload(tmp_path, tenant_id: int, owner_id: int, filename: str, content: bytes) -> None:
    uploads = tmp_path / str(tenant_id) / str(owner_id) / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    (uploads / filename).write_bytes(content)


def _servlet_service(handler) -> VDBManagementService:
    client = httpx.AsyncClient(
        base_url="http://fake-servlet", transport=httpx.MockTransport(handler)
    )
    return VDBManagementService(client=client, pg_host="localhost", pg_port=1)


async def test_share_project_provisions_a_project_scoped_shared_vdb(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "customer_base_path", str(tmp_path))
    tenant_id, owner_id = await _seed(db_session, "ps-new")
    project = Project(tenant_id=tenant_id, owner_id=owner_id, name="P", is_shared=False)
    db_session.add(project)
    await db_session.flush()
    _write_upload(tmp_path, tenant_id, owner_id, "sales.csv", b"a,b\n1,2\n")
    await db_session.commit()

    seen_uploads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/createVDB"):
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path.endswith("/upload"):
            seen_uploads.append({"url": str(request.url), "body": request.content})
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(404)

    vdb_service = _servlet_service(handler)
    service = ProjectSharingService(db_session, vdb_service=vdb_service)
    try:
        result = await service.share_project(
            context=_context(tenant_id, owner_id),
            project_id=project.id,
            filenames=["sales.csv"],
        )
    finally:
        await service.aclose()

    assert result.copied_files == ["sales.csv"]
    assert len(seen_uploads) == 1
    assert b"sales" in seen_uploads[0]["body"]

    await db_session.refresh(project)
    assert project.is_shared is True
    assert project.owner_id == owner_id  # sharing never transfers ownership

    shared_vdb = await db_session.scalar(
        select(SharedVDB).where(SharedVDB.project_id == project.id)
    )
    assert shared_vdb is not None
    assert shared_vdb.tenant_id == tenant_id


async def test_share_project_reuses_existing_shared_vdb_for_this_project(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "customer_base_path", str(tmp_path))
    tenant_id, owner_id = await _seed(db_session, "ps-reuse")
    project = Project(tenant_id=tenant_id, owner_id=owner_id, name="P", is_shared=False)
    db_session.add(project)
    await db_session.flush()
    existing = SharedVDB(
        tenant_id=tenant_id,
        project_id=project.id,
        vdb_id="existing-vdb",
        vdb_username="test",
        encrypted_password="test",
        is_active=True,
    )
    db_session.add(existing)
    _write_upload(tmp_path, tenant_id, owner_id, "sales.csv", b"a,b\n1,2\n")
    await db_session.commit()

    create_vdb_calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/createVDB"):
            create_vdb_calls.append(1)
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path.endswith("/upload"):
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(404)

    vdb_service = _servlet_service(handler)
    service = ProjectSharingService(db_session, vdb_service=vdb_service)
    try:
        result = await service.share_project(
            context=_context(tenant_id, owner_id),
            project_id=project.id,
            filenames=["sales.csv"],
        )
    finally:
        await service.aclose()

    assert create_vdb_calls == []  # no new VDB provisioned
    assert result.shared_vdb_id == "existing-vdb"


async def test_share_project_rejects_non_owner(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "customer_base_path", str(tmp_path))
    tenant_id, owner_id = await _seed(db_session, "ps-nonowner")
    other = User(
        tenant_id=tenant_id,
        email="other@ps-nonowner.com",
        display_name="Other",
        role="editor",
        external_id="ext-other",
    )
    db_session.add(other)
    await db_session.flush()
    project = Project(tenant_id=tenant_id, owner_id=owner_id, name="P", is_shared=False)
    db_session.add(project)
    await db_session.commit()

    service = ProjectSharingService(db_session, vdb_service=_servlet_service(lambda r: httpx.Response(404)))
    try:
        with pytest.raises(ProjectSharingError, match="owner"):
            await service.share_project(
                context=_context(tenant_id, other.id),
                project_id=project.id,
                filenames=[],
            )
    finally:
        await service.aclose()


async def test_share_project_raises_on_missing_source_file(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "customer_base_path", str(tmp_path))
    tenant_id, owner_id = await _seed(db_session, "ps-missing")
    project = Project(tenant_id=tenant_id, owner_id=owner_id, name="P", is_shared=False)
    db_session.add(project)
    await db_session.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "ok"})

    service = ProjectSharingService(db_session, vdb_service=_servlet_service(handler))
    try:
        with pytest.raises(ProjectSharingError, match="Missing source file"):
            await service.share_project(
                context=_context(tenant_id, owner_id),
                project_id=project.id,
                filenames=["does-not-exist.csv"],
            )
    finally:
        await service.aclose()


async def test_share_project_rejects_path_traversal_filename(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "customer_base_path", str(tmp_path))
    tenant_id, owner_id = await _seed(db_session, "ps-traversal")
    project = Project(tenant_id=tenant_id, owner_id=owner_id, name="P", is_shared=False)
    db_session.add(project)
    await db_session.commit()

    service = ProjectSharingService(db_session, vdb_service=_servlet_service(lambda r: httpx.Response(200, json={})))
    try:
        with pytest.raises(ProjectSharingError):
            await service.share_project(
                context=_context(tenant_id, owner_id),
                project_id=project.id,
                filenames=["../../etc/passwd"],
            )
    finally:
        await service.aclose()
