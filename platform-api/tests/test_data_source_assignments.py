"""Tests for DB Admin data source assignments (issue 5)."""

from __future__ import annotations

import pytest

from app.auth.jwt import create_access_token
from app.models.database_data_source import DatabaseDataSource
from app.models.tenant import Tenant
from app.models.user import User


async def _setup_tenant(db_session):
    tenant = Tenant(slug="assign-tenant", name="Assign Tenant")
    db_session.add(tenant)
    await db_session.commit()
    await db_session.refresh(tenant)

    async def _user(email, role, ext):
        user = User(
            tenant_id=tenant.id,
            email=email,
            display_name=email.split("@")[0],
            role=role,
            external_id=ext,
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
        return {"id": user.id, "email": user.email, "role": user.role}

    admin = await _user("admin@acme.com", "admin", "ext-admin")
    db_admin = await _user("dba@acme.com", "db_admin", "ext-dba")
    member = await _user("member@acme.com", "member", "ext-member")
    other = await _user("other@acme.com", "member", "ext-other")
    return {"id": tenant.id}, admin, db_admin, member, other


def _headers(tenant_id, user_id, role):
    token = create_access_token(
        sub=str(user_id), tenant_id=tenant_id, user_id=user_id, role=role
    )
    return {"Authorization": f"Bearer {token}"}


async def _seed_source(db_session, tenant_id: int) -> DatabaseDataSource:
    src = DatabaseDataSource(
        tenant_id=tenant_id,
        display_name="Boeing Supplier Quality DB",
        source_type="database_table",
        db_type="mysql",
        host="db.example.com",
        port=3306,
        database_name="quality",
        table_name="suppliers",
        username="svc",
        teiid_model_name="m_quality",
        teiid_table_name="suppliers",
        teiid_view_name="v_quality_suppliers",
        teiid_jndi_name="java:/quality",
        status="active",
    )
    db_session.add(src)
    await db_session.commit()
    await db_session.refresh(src)
    return src


@pytest.mark.asyncio
async def test_admin_and_db_admin_can_assign_member_cannot(
    client, db_session
) -> None:
    tenant, admin, db_admin, member, other = await _setup_tenant(db_session)
    src = await _seed_source(db_session, tenant["id"])

    admin_h = _headers(tenant["id"], admin["id"], "admin")
    dba_h = _headers(tenant["id"], db_admin["id"], "db_admin")
    member_h = _headers(tenant["id"], member["id"], "member")

    # Admin lists assignable sources.
    r = await client.get("/api/admin/assignable-db-sources", headers=admin_h)
    assert r.status_code == 200, r.text
    assert any(
        s["database_data_source_id"] == src.id for s in r.json()
    )

    # Member cannot list assignable sources or assign.
    r = await client.get(
        "/api/admin/assignable-db-sources", headers=member_h
    )
    assert r.status_code == 403
    r = await client.post(
        "/api/admin/data-source-assignments",
        json={
            "database_data_source_id": src.id,
            "assigned_user_ids": [member["id"]],
            "friendly_name": "Quality DB",
            "read_only": True,
        },
        headers=member_h,
    )
    assert r.status_code == 403

    # Admin assigns to the member.
    r = await client.post(
        "/api/admin/data-source-assignments",
        json={
            "database_data_source_id": src.id,
            "assigned_user_ids": [member["id"]],
            "friendly_name": "Boeing Supplier Quality DB",
            "read_only": True,
        },
        headers=admin_h,
    )
    assert r.status_code == 200, r.text
    rows = r.json()
    assert len(rows) == 1
    assignment_id = rows[0]["id"]
    assert rows[0]["assigned_user_id"] == member["id"]

    # DB Admin can also assign (to the "other" user).
    r = await client.post(
        "/api/admin/data-source-assignments",
        json={
            "database_data_source_id": src.id,
            "assigned_user_ids": [other["id"]],
            "friendly_name": "Shared Quality",
            "read_only": True,
        },
        headers=dba_h,
    )
    assert r.status_code == 200, r.text

    # Member sees the assigned source in Connected Databases.
    r = await client.get("/api/database-sources/connected", headers=member_h)
    assert r.status_code == 200, r.text
    assigned = [i for i in r.json() if i["source"] == "assigned"]
    assert len(assigned) == 1
    item = assigned[0]
    assert item["display_name"] == "Boeing Supplier Quality DB"
    assert item["read_only"] is True
    assert item["can_edit_connection"] is False
    assert item["database_data_source_id"] == src.id

    # Duplicate active assignment is prevented (refreshed, not duplicated).
    r = await client.post(
        "/api/admin/data-source-assignments",
        json={
            "database_data_source_id": src.id,
            "assigned_user_ids": [member["id"]],
            "friendly_name": "Renamed Quality DB",
            "read_only": False,
        },
        headers=admin_h,
    )
    assert r.status_code == 200, r.text
    r = await client.get("/api/admin/data-source-assignments", headers=admin_h)
    member_rows = [
        a for a in r.json() if a["assigned_user_id"] == member["id"]
    ]
    assert len(member_rows) == 1
    assert member_rows[0]["friendly_name"] == "Renamed Quality DB"

    # Update friendly name via PUT.
    r = await client.put(
        f"/api/admin/data-source-assignments/{assignment_id}",
        json={"friendly_name": "Final Name"},
        headers=admin_h,
    )
    assert r.status_code == 200, r.text
    assert r.json()["friendly_name"] == "Final Name"

    # Remove the assignment -> member no longer sees it.
    r = await client.delete(
        f"/api/admin/data-source-assignments/{assignment_id}",
        headers=admin_h,
    )
    assert r.status_code == 200, r.text
    r = await client.get("/api/database-sources/connected", headers=member_h)
    assert all(i["source"] != "assigned" for i in r.json())


@pytest.mark.asyncio
async def test_unassigned_user_does_not_see_source(
    client, db_session
) -> None:
    tenant, admin, _db_admin, member, other = await _setup_tenant(db_session)
    src = await _seed_source(db_session, tenant["id"])
    admin_h = _headers(tenant["id"], admin["id"], "admin")

    r = await client.post(
        "/api/admin/data-source-assignments",
        json={
            "database_data_source_id": src.id,
            "assigned_user_ids": [member["id"]],
            "friendly_name": "Quality DB",
        },
        headers=admin_h,
    )
    assert r.status_code == 200, r.text

    other_h = _headers(tenant["id"], other["id"], "member")
    r = await client.get("/api/database-sources/connected", headers=other_h)
    assert r.status_code == 200, r.text
    assert all(i["source"] != "assigned" for i in r.json())
