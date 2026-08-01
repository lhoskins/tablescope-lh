"""Versioned data-source updates: preflight, activation guards and history."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import create_access_token
from app.models.file_source_meta import FileSourceMeta
from app.models.file_source_version import STATUS_STAGED, FileSourceVersion
from app.models.tenant import Tenant
from app.models.user import User
from app.services.file_sources import detect_column_types

BASE_CSV = b"id,amount\n1,10\n2,20\n"
ADDED_COLUMN_CSV = b"id,amount,region\n1,10,EU\n2,20,US\n"
MISSING_COLUMN_CSV = b"id\n1\n2\n"
TYPE_CHANGED_CSV = b"id,amount\n1,ten\n2,twenty\n"

VIEW_NAME = "sales_CSV"


def _headers(tenant_id: int, user_id: int, role: str = "editor") -> dict:
    token = create_access_token(
        sub="u", tenant_id=tenant_id, user_id=user_id, role=role
    )
    return {"Authorization": f"Bearer {token}"}


async def _seed(session: AsyncSession, tmp_path: Path, monkeypatch) -> tuple[int, int]:
    """Create a tenant, user and file data source backed by a real CSV file."""
    tenant = Tenant(slug="v-tenant", name="Version Tenant")
    session.add(tenant)
    await session.flush()
    user = User(
        tenant_id=tenant.id,
        email="v@test.com",
        display_name="V User",
        role="editor",
    )
    session.add(user)
    await session.flush()
    session.add(
        FileSourceMeta(
            tenant_id=tenant.id,
            owner_id=user.id,
            view_name=VIEW_NAME,
            file_name="sales.csv",
            vdb_type="user",
            column_types=detect_column_types(BASE_CSV, "sales.csv"),
        )
    )
    await session.commit()

    uploads = tmp_path / str(tenant.id) / str(user.id) / "uploads"
    uploads.mkdir(parents=True)
    (uploads / "sales.csv").write_bytes(BASE_CSV)

    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "customer_base_path", str(tmp_path))
    return tenant.id, user.id


@pytest.mark.asyncio
async def test_preflight_reports_added_columns_and_stages_a_version(
    client, db_session, tmp_path, monkeypatch
) -> None:
    tenant_id, user_id = await _seed(db_session, tmp_path, monkeypatch)

    resp = await client.post(
        f"/api/upload/datasources/{VIEW_NAME}/versions/preflight",
        headers=_headers(tenant_id, user_id),
        files={"file": ("sales.csv", ADDED_COLUMN_CSV, "text/csv")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["canActivate"] is True
    assert body["compatibility"]["addedColumns"] == ["region"]
    assert body["compatibility"]["removedColumns"] == []
    assert body["version"]["status"] == STATUS_STAGED
    assert body["version"]["versionNumber"] == 2
    assert body["activeVersion"]["versionNumber"] == 1
    # The live source is untouched until the staged version is activated.
    assert (tmp_path / str(tenant_id) / str(user_id) / "uploads" / "sales.csv").read_bytes() == BASE_CSV


@pytest.mark.asyncio
async def test_preflight_blocks_a_removed_column(
    client, db_session, tmp_path, monkeypatch
) -> None:
    tenant_id, user_id = await _seed(db_session, tmp_path, monkeypatch)

    resp = await client.post(
        f"/api/upload/datasources/{VIEW_NAME}/versions/preflight",
        headers=_headers(tenant_id, user_id),
        files={"file": ("sales.csv", MISSING_COLUMN_CSV, "text/csv")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["canActivate"] is False
    assert body["compatibility"]["removedColumns"] == ["amount"]


@pytest.mark.asyncio
async def test_preflight_blocks_a_column_type_change(
    client, db_session, tmp_path, monkeypatch
) -> None:
    tenant_id, user_id = await _seed(db_session, tmp_path, monkeypatch)

    resp = await client.post(
        f"/api/upload/datasources/{VIEW_NAME}/versions/preflight",
        headers=_headers(tenant_id, user_id),
        files={"file": ("sales.csv", TYPE_CHANGED_CSV, "text/csv")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["canActivate"] is False
    assert [c["column"] for c in body["compatibility"]["typeChangedColumns"]] == ["amount"]


@pytest.mark.asyncio
async def test_activation_is_refused_for_a_blocked_version(
    client, db_session, tmp_path, monkeypatch
) -> None:
    tenant_id, user_id = await _seed(db_session, tmp_path, monkeypatch)
    headers = _headers(tenant_id, user_id)

    staged = await client.post(
        f"/api/upload/datasources/{VIEW_NAME}/versions/preflight",
        headers=headers,
        files={"file": ("sales.csv", MISSING_COLUMN_CSV, "text/csv")},
    )
    version_id = staged.json()["version"]["id"]

    resp = await client.post(
        f"/api/upload/datasources/{VIEW_NAME}/versions/{version_id}/activate",
        headers=headers,
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "incompatible_schema"


@pytest.mark.asyncio
async def test_documents_cannot_update_a_data_source(
    client, db_session, tmp_path, monkeypatch
) -> None:
    tenant_id, user_id = await _seed(db_session, tmp_path, monkeypatch)

    resp = await client.post(
        f"/api/upload/datasources/{VIEW_NAME}/versions/preflight",
        headers=_headers(tenant_id, user_id),
        files={"file": ("sales.pdf", b"%PDF-1.7\ntrailer\n", "application/pdf")},
    )
    assert resp.status_code == 409
    assert "document" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_a_different_file_name_is_refused(
    client, db_session, tmp_path, monkeypatch
) -> None:
    tenant_id, user_id = await _seed(db_session, tmp_path, monkeypatch)

    resp = await client.post(
        f"/api/upload/datasources/{VIEW_NAME}/versions/preflight",
        headers=_headers(tenant_id, user_id),
        files={"file": ("other.csv", ADDED_COLUMN_CSV, "text/csv")},
    )
    assert resp.status_code == 409
    assert "File name mismatch" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_unknown_source_is_not_found(
    client, db_session, tmp_path, monkeypatch
) -> None:
    tenant_id, user_id = await _seed(db_session, tmp_path, monkeypatch)

    resp = await client.post(
        "/api/upload/datasources/NOPE_CSV/versions/preflight",
        headers=_headers(tenant_id, user_id),
        files={"file": ("sales.csv", BASE_CSV, "text/csv")},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_version_history_lists_the_staged_and_baseline_versions(
    client, db_session, tmp_path, monkeypatch
) -> None:
    tenant_id, user_id = await _seed(db_session, tmp_path, monkeypatch)
    headers = _headers(tenant_id, user_id)

    await client.post(
        f"/api/upload/datasources/{VIEW_NAME}/versions/preflight",
        headers=headers,
        files={"file": ("sales.csv", ADDED_COLUMN_CSV, "text/csv")},
    )
    resp = await client.get(
        f"/api/upload/datasources/{VIEW_NAME}/versions", headers=headers
    )
    assert resp.status_code == 200
    versions = resp.json()
    assert [v["versionNumber"] for v in versions] == [2, 1]
    assert versions[1]["status"] == "active"


@pytest.mark.asyncio
async def test_rollback_requires_an_archived_version(
    client, db_session, tmp_path, monkeypatch
) -> None:
    tenant_id, user_id = await _seed(db_session, tmp_path, monkeypatch)
    headers = _headers(tenant_id, user_id)

    staged = await client.post(
        f"/api/upload/datasources/{VIEW_NAME}/versions/preflight",
        headers=headers,
        files={"file": ("sales.csv", ADDED_COLUMN_CSV, "text/csv")},
    )
    version_id = staged.json()["version"]["id"]

    resp = await client.post(
        f"/api/upload/datasources/{VIEW_NAME}/versions/{version_id}/rollback",
        headers=headers,
    )
    assert resp.status_code == 409
    assert "archived" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_viewers_cannot_stage_an_update(
    client, db_session, tmp_path, monkeypatch
) -> None:
    tenant_id, user_id = await _seed(db_session, tmp_path, monkeypatch)

    resp = await client.post(
        f"/api/upload/datasources/{VIEW_NAME}/versions/preflight",
        headers=_headers(tenant_id, user_id, role="viewer"),
        files={"file": ("sales.csv", ADDED_COLUMN_CSV, "text/csv")},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_another_tenant_cannot_see_versions(
    client, db_session, tmp_path, monkeypatch
) -> None:
    tenant_id, user_id = await _seed(db_session, tmp_path, monkeypatch)

    resp = await client.get(
        f"/api/upload/datasources/{VIEW_NAME}/versions",
        headers=_headers(tenant_id + 99, user_id),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_staged_files_are_recorded_outside_the_live_directory(
    client, db_session, tmp_path, monkeypatch
) -> None:
    tenant_id, user_id = await _seed(db_session, tmp_path, monkeypatch)

    await client.post(
        f"/api/upload/datasources/{VIEW_NAME}/versions/preflight",
        headers=_headers(tenant_id, user_id),
        files={"file": ("sales.csv", ADDED_COLUMN_CSV, "text/csv")},
    )
    staged = await db_session.get(FileSourceVersion, 2)
    assert staged is not None
    assert staged.stored_path is not None
    assert ".staging" in staged.stored_path
    assert Path(staged.stored_path).read_bytes() == ADDED_COLUMN_CSV
