"""Data-source lifecycle: archive, restore, preflight and permanent delete.

Covers file, database and SaaS sources, the lifecycle identity contract, and
tenant/permission isolation.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import create_access_token
from app.config import get_settings
from app.models.connector_credential import ConnectorCredential
from app.models.database_data_source import DatabaseDataSource
from app.models.file_source_meta import FileSourceMeta
from app.models.project import Project
from app.models.saas_object_data_source import SaasObjectDataSource
from app.models.saved_query import SavedQuery
from app.models.tenant import Tenant
from app.models.user import User


def _headers(tenant_id: int, user_id: int, role: str = "editor") -> dict:
    return {
        "Authorization": f"Bearer {create_access_token(sub='u', tenant_id=tenant_id, user_id=user_id, role=role)}"
    }


class _FakeTeiidResponse:
    def __init__(self, status: int, text: str) -> None:
        self.status_code = status
        self.text = text


class _FakeTeiidClient:
    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, *args, **kwargs):
        return _FakeTeiidResponse(200, "ok")

    async def get(self, *args, **kwargs):
        return _FakeTeiidResponse(200, "ok")


@pytest.fixture(autouse=True)
def _stub_teiid_delete(monkeypatch):
    """Prevent delete endpoints from touching a real Teiid server."""
    for module in (
        "app.routes.database_sources_lifecycle",
        "app.routes.upload_datasources",
        "app.routes.saas_sources",
    ):
        monkeypatch.setattr(f"{module}.httpx.AsyncClient", _FakeTeiidClient)


async def _seed_project(
    session: AsyncSession,
    tmp_path: Path,
) -> tuple[Tenant, User, Project]:
    tenant = Tenant(slug="acme", name="Acme")
    session.add(tenant)
    await session.flush()

    user = User(
        tenant_id=tenant.id,
        email="owner@acme.com",
        display_name="Owner",
        role="editor",
    )
    session.add(user)
    await session.flush()

    project = Project(
        tenant_id=tenant.id,
        owner_id=user.id,
        name="Test Project",
        is_shared=False,
    )
    session.add(project)
    await session.flush()
    return tenant, user, project


def _make_file(tmp_path: Path, tenant_id: int, user_id: int, name: str) -> Path:
    uploads = tmp_path / str(tenant_id) / str(user_id) / "uploads"
    uploads.mkdir(parents=True)
    path = uploads / name
    path.write_text("id\n1\n")
    return path


async def _seed_file_source(
    session: AsyncSession,
    tmp_path: Path,
    project: Project,
    user: User,
) -> FileSourceMeta:
    _make_file(tmp_path, project.tenant_id, user.id, "sales.csv")
    meta = FileSourceMeta(
        tenant_id=project.tenant_id,
        owner_id=user.id,
        project_id=project.id,
        view_name="sales_CSV",
        file_name="sales.csv",
    )
    session.add(meta)
    await session.commit()
    return meta


async def _seed_db_source(
    session: AsyncSession,
    project: Project,
    user: User,
    archived: bool = False,
    source_type: str = "database_table",
) -> DatabaseDataSource:
    ds = DatabaseDataSource(
        tenant_id=project.tenant_id,
        project_id=project.id,
        created_by=user.id,
        display_name="Orders",
        source_type=source_type,
        db_type="postgres",
        host="localhost",
        port=5432,
        database_name="db",
        schema_name="public",
        table_name="orders",
        username="user",
        password_encrypted="x",
        teiid_model_name="model_orders",
        teiid_table_name="tbl_orders",
        teiid_view_name="orders_POSTGRES",
        teiid_jndi_name="java:/orders",
        status="active",
        archived=archived,
    )
    session.add(ds)
    await session.commit()
    await session.refresh(ds)
    return ds


async def _seed_saas_source(
    session: AsyncSession,
    project: Project,
    user: User,
) -> tuple[DatabaseDataSource, SaasObjectDataSource]:
    credential = ConnectorCredential(
        tenant_id=project.tenant_id,
        created_by=user.id,
        connector_type="servicenow",
        display_name="SN cred",
    )
    session.add(credential)
    await session.flush()

    ds = await _seed_db_source(
        session, project, user, source_type="saas_object"
    )
    ds.connector_type = "servicenow"
    ds.teiid_view_name = "incident_SERVICENOW"
    saas = SaasObjectDataSource(
        tenant_id=project.tenant_id,
        database_data_source_id=ds.id,
        credential_id=credential.id,
        connector_type="servicenow",
        object_type="incident",
        selected_properties=[],
        staging_schema="public",
        staging_table="staging_incident",
    )
    session.add(saas)
    await session.commit()
    await session.refresh(saas)
    return ds, saas


async def _seed_dependency(
    session: AsyncSession,
    project: Project,
    user: User,
    view_name: str,
) -> SavedQuery:
    q = SavedQuery(
        project_id=project.id,
        owner_id=user.id,
        name="Saved query",
        sql_text=f'SELECT * FROM "{view_name}"',
    )
    session.add(q)
    await session.commit()
    return q


@pytest.mark.asyncio
async def test_project_datasources_exposes_lifecycle_identity(
    client,
    db_session,
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        get_settings(), "customer_base_path", str(tmp_path)
    )
    tenant, user, project = await _seed_project(db_session, tmp_path)
    await _seed_file_source(db_session, tmp_path, project, user)
    db = await _seed_db_source(db_session, project, user)
    _, saas = await _seed_saas_source(db_session, project, user)

    resp = await client.get(
        f"/api/projects/{project.id}/datasources?include_archived=true",
        headers=_headers(tenant.id, user.id),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    kinds = {d["lifecycleKind"]: d["lifecycleId"] for d in data}

    assert kinds["file"] == "sales_CSV"
    assert kinds["database"] == str(db.id)
    assert kinds["saas"] == str(saas.id)


@pytest.mark.asyncio
async def test_archive_and_restore_file_source(client, db_session, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "customer_base_path", str(tmp_path))
    tenant, user, project = await _seed_project(db_session, tmp_path)
    meta = await _seed_file_source(db_session, tmp_path, project, user)

    resp = await client.patch(
        f"/api/upload/datasources/{meta.view_name}/archive",
        headers=_headers(tenant.id, user.id),
        json={"archived": True},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["archived"] is True

    await db_session.refresh(meta)
    assert meta.archived is True
    assert meta.project_id == project.id

    resp = await client.patch(
        f"/api/upload/datasources/{meta.view_name}/archive",
        headers=_headers(tenant.id, user.id),
        json={"archived": False},
    )
    assert resp.status_code == 200, resp.text
    await db_session.refresh(meta)
    assert meta.archived is False


@pytest.mark.asyncio
async def test_archive_and_restore_database_source(client, db_session, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "customer_base_path", str(tmp_path))
    tenant, user, project = await _seed_project(db_session, tmp_path)
    ds = await _seed_db_source(db_session, project, user)

    resp = await client.patch(
        f"/api/database-sources/{ds.id}/archive",
        headers=_headers(tenant.id, user.id),
        json={"archived": True},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["archived"] is True

    resp = await client.patch(
        f"/api/database-sources/{ds.id}/archive",
        headers=_headers(tenant.id, user.id),
        json={"archived": False},
    )
    assert resp.status_code == 200, resp.text
    await db_session.refresh(ds)
    assert ds.archived is False
    assert ds.project_id == project.id


@pytest.mark.asyncio
async def test_archive_and_restore_saas_source(client, db_session, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "customer_base_path", str(tmp_path))
    tenant, user, project = await _seed_project(db_session, tmp_path)
    ds, saas = await _seed_saas_source(db_session, project, user)

    resp = await client.patch(
        f"/api/saas-sources/{saas.id}/archive",
        headers=_headers(tenant.id, user.id),
        json={"archived": True},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["archived"] is True
    await db_session.refresh(ds)
    assert ds.archived is True
    assert ds.project_id == project.id

    resp = await client.patch(
        f"/api/saas-sources/{saas.id}/archive",
        headers=_headers(tenant.id, user.id),
        json={"archived": False},
    )
    assert resp.status_code == 200, resp.text
    await db_session.refresh(ds)
    assert ds.archived is False


@pytest.mark.asyncio
async def test_file_delete_preflight_blocks_active_dependencies(
    client, db_session, tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(get_settings(), "customer_base_path", str(tmp_path))
    tenant, user, project = await _seed_project(db_session, tmp_path)
    meta = await _seed_file_source(db_session, tmp_path, project, user)
    await _seed_dependency(db_session, project, user, meta.view_name)

    preflight = await client.get(
        f"/api/upload/datasources/{meta.view_name}/preflight-delete",
        headers=_headers(tenant.id, user.id),
    )
    assert preflight.status_code == 200, preflight.text
    body = preflight.json()
    assert body["safe"] is False
    assert body["archived"] is False
    assert any(b["category"] == "not_archived" for b in body["blockers"])

    # Even if archived, the active dependency still blocks deletion.
    meta.archived = True
    await db_session.commit()
    preflight = await client.get(
        f"/api/upload/datasources/{meta.view_name}/preflight-delete",
        headers=_headers(tenant.id, user.id),
    )
    assert preflight.json()["safe"] is False
    assert any(
        b["category"] == "active_dependencies"
        for b in preflight.json()["blockers"]
    )

    delete = await client.delete(
        f"/api/upload/datasources/{meta.view_name}",
        headers=_headers(tenant.id, user.id),
    )
    assert delete.status_code == 409


@pytest.mark.asyncio
async def test_file_delete_succeeds_when_archived_and_no_dependencies(
    client, db_session, tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(get_settings(), "customer_base_path", str(tmp_path))
    tenant, user, project = await _seed_project(db_session, tmp_path)
    meta = await _seed_file_source(db_session, tmp_path, project, user)
    meta.archived = True
    await db_session.commit()

    preflight = await client.get(
        f"/api/upload/datasources/{meta.view_name}/preflight-delete",
        headers=_headers(tenant.id, user.id),
    )
    assert preflight.json()["safe"] is True

    delete = await client.delete(
        f"/api/upload/datasources/{meta.view_name}",
        headers=_headers(tenant.id, user.id),
    )
    assert delete.status_code == 200
    assert delete.json()["status"] == "deleted"

    # Metadata row is removed; physical file may remain (best-effort).
    remaining = await db_session.scalar(
        select(FileSourceMeta).where(FileSourceMeta.id == meta.id)
    )
    assert remaining is None


@pytest.mark.asyncio
async def test_database_delete_preflight_blocks_active_dependencies(
    client, db_session, tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(get_settings(), "customer_base_path", str(tmp_path))
    tenant, user, project = await _seed_project(db_session, tmp_path)
    ds = await _seed_db_source(db_session, project, user, archived=True)
    await _seed_dependency(db_session, project, user, ds.teiid_view_name)

    preflight = await client.get(
        f"/api/database-sources/{ds.id}/preflight-delete",
        headers=_headers(tenant.id, user.id),
    )
    assert preflight.json()["safe"] is False
    assert any(
        b["category"] == "active_dependencies"
        for b in preflight.json()["blockers"]
    )

    delete = await client.delete(
        f"/api/database-sources/{ds.id}",
        headers=_headers(tenant.id, user.id),
    )
    assert delete.status_code == 409


@pytest.mark.asyncio
async def test_database_delete_succeeds_when_no_dependencies(
    client, db_session, tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(get_settings(), "customer_base_path", str(tmp_path))
    tenant, user, project = await _seed_project(db_session, tmp_path)
    ds = await _seed_db_source(db_session, project, user, archived=True)

    preflight = await client.get(
        f"/api/database-sources/{ds.id}/preflight-delete",
        headers=(headers := _headers(tenant.id, user.id)),
    )
    assert preflight.json()["safe"] is True

    delete = await client.delete(
        f"/api/database-sources/{ds.id}",
        headers=headers,
    )
    assert delete.status_code == 200


@pytest.mark.asyncio
async def test_saas_delete_preflight_blocks_active_dependencies(
    client, db_session, tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(get_settings(), "customer_base_path", str(tmp_path))
    tenant, user, project = await _seed_project(db_session, tmp_path)
    ds, saas = await _seed_saas_source(db_session, project, user)
    ds.archived = True
    await db_session.commit()
    await _seed_dependency(db_session, project, user, ds.teiid_view_name)

    preflight = await client.get(
        f"/api/saas-sources/{saas.id}/preflight-delete",
        headers=_headers(tenant.id, user.id),
    )
    assert preflight.json()["safe"] is False
    assert any(
        b["category"] == "active_dependencies"
        for b in preflight.json()["blockers"]
    )

    delete = await client.delete(
        f"/api/saas-sources/{saas.id}",
        headers=_headers(tenant.id, user.id),
    )
    assert delete.status_code == 409


@pytest.mark.asyncio
async def test_saas_delete_succeeds_and_cascades_to_backing_db(
    client, db_session, tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(get_settings(), "customer_base_path", str(tmp_path))
    tenant, user, project = await _seed_project(db_session, tmp_path)
    ds, saas = await _seed_saas_source(db_session, project, user)
    ds.archived = True
    await db_session.commit()

    preflight = await client.get(
        f"/api/saas-sources/{saas.id}/preflight-delete",
        headers=_headers(tenant.id, user.id),
    )
    assert preflight.json()["safe"] is True

    delete = await client.delete(
        f"/api/saas-sources/{saas.id}",
        headers=_headers(tenant.id, user.id),
    )
    assert delete.status_code == 200

    assert (
        await db_session.scalar(
            select(SaasObjectDataSource).where(SaasObjectDataSource.id == saas.id)
        )
    ) is None
    assert (
        await db_session.scalar(
            select(DatabaseDataSource).where(DatabaseDataSource.id == ds.id)
        )
    ) is None


@pytest.mark.asyncio
async def test_lifecycle_is_tenant_isolated(
    client, db_session, tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(get_settings(), "customer_base_path", str(tmp_path))
    tenant_a, user_a, project_a = await _seed_project(db_session, tmp_path)
    tenant_b = Tenant(slug="other", name="Other")
    db_session.add(tenant_b)
    await db_session.flush()
    user_b = User(
        tenant_id=tenant_b.id,
        email="other@example.com",
        display_name="Other",
        role="editor",
    )
    db_session.add(user_b)
    await db_session.commit()

    ds = await _seed_db_source(db_session, project_a, user_a)

    resp = await client.patch(
        f"/api/database-sources/{ds.id}/archive",
        headers=_headers(tenant_b.id, user_b.id),
        json={"archived": True},
    )
    assert resp.status_code == 404

    preflight = await client.get(
        f"/api/database-sources/{ds.id}/preflight-delete",
        headers=_headers(tenant_b.id, user_b.id),
    )
    assert preflight.status_code == 404

    delete = await client.delete(
        f"/api/database-sources/{ds.id}",
        headers=_headers(tenant_b.id, user_b.id),
    )
    assert delete.status_code == 404
