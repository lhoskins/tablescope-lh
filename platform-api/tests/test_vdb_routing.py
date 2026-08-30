"""Unit tests for VDBRoutingService's per-project SharedVDB routing.

Covers the reconciliation of vdb_routing.py and query_sql_helpers.py: a
shared project must route to *its own* SharedVDB (keyed on
``(tenant_id, project_id)``, migration 0087), never the owner's UserVDB and
never another shared project's VDB in the same tenant.
"""

from __future__ import annotations

import pytest

from app.auth.context import RequestContext
from app.auth.jwt import TokenClaims
from app.models.project import Project, ProjectMember
from app.models.shared_vdb import SharedVDB
from app.models.tenant import Tenant
from app.models.user import User
from app.models.user_vdb import UserVDB
from app.services.vdb_routing import (
    VDBNotConfiguredError,
    VDBRoutingService,
)

pytestmark = pytest.mark.anyio


def _context(tenant_id: int, user_id: int) -> RequestContext:
    return RequestContext(
        claims=TokenClaims(sub=str(user_id), tenant_id=tenant_id, user_id=user_id, role="editor")
    )


async def _seed_tenant_owner(db_session, slug: str) -> tuple[int, int]:
    tenant = Tenant(slug=slug, name=slug)
    db_session.add(tenant)
    await db_session.flush()
    user = User(
        tenant_id=tenant.id,
        email=f"owner@{slug}.com",
        display_name="Owner",
        role="admin",
        external_id=f"ext-{slug}",
    )
    db_session.add(user)
    await db_session.flush()
    return tenant.id, user.id


async def _add_second_member(db_session, tenant_id: int, project: Project) -> None:
    """`VDBRoutingService._reconcile_is_shared` derives ``is_shared`` from
    member count (>1), overriding whatever ``Project.is_shared`` was
    constructed with -- so a project meant to exercise the shared-VDB path
    needs a real second member, not just the ``is_shared=True`` flag."""
    other = User(
        tenant_id=tenant_id,
        email=f"member-{project.id}@example.com",
        display_name="Member",
        role="editor",
        external_id=f"ext-member-{project.id}",
    )
    db_session.add(other)
    await db_session.flush()
    db_session.add_all(
        [
            ProjectMember(project_id=project.id, user_id=project.owner_id, role="owner", is_active=True),
            ProjectMember(project_id=project.id, user_id=other.id, role="viewer", is_active=True),
        ]
    )


async def test_shared_project_routes_to_its_own_shared_vdb(db_session):
    tenant_id, owner_id = await _seed_tenant_owner(db_session, "vr-shared")
    project = Project(tenant_id=tenant_id, owner_id=owner_id, name="Shared", is_shared=True)
    db_session.add(project)
    await db_session.flush()
    await _add_second_member(db_session, tenant_id, project)
    shared_vdb = SharedVDB(
        tenant_id=tenant_id,
        project_id=project.id,
        vdb_id="shared-vdb",
        vdb_username="u",
        encrypted_password="p",
        is_active=True,
    )
    db_session.add(shared_vdb)
    # A UserVDB for the owner also exists -- routing must NOT pick this one.
    db_session.add(
        UserVDB(
            tenant_id=tenant_id,
            user_id=owner_id,
            vdb_id="owner-vdb",
            vdb_username="u",
            encrypted_password="p",
            is_active=True,
        )
    )
    await db_session.commit()

    vdb, vdb_type = await VDBRoutingService(db_session).get_vdb_for_query(
        context=_context(tenant_id, owner_id), project_id=project.id
    )
    assert vdb_type == "shared"
    assert vdb.vdb_id == "shared-vdb"


async def test_two_shared_projects_in_same_tenant_resolve_to_different_vdbs(db_session):
    tenant_id, owner_id = await _seed_tenant_owner(db_session, "vr-two-shared")
    project_a = Project(tenant_id=tenant_id, owner_id=owner_id, name="A", is_shared=True)
    project_b = Project(tenant_id=tenant_id, owner_id=owner_id, name="B", is_shared=True)
    db_session.add_all([project_a, project_b])
    await db_session.flush()
    await _add_second_member(db_session, tenant_id, project_a)
    await _add_second_member(db_session, tenant_id, project_b)
    db_session.add_all(
        [
            SharedVDB(
                tenant_id=tenant_id,
                project_id=project_a.id,
                vdb_id="shared-vdb-a",
                vdb_username="u",
                encrypted_password="p",
                is_active=True,
            ),
            SharedVDB(
                tenant_id=tenant_id,
                project_id=project_b.id,
                vdb_id="shared-vdb-b",
                vdb_username="u",
                encrypted_password="p",
                is_active=True,
            ),
        ]
    )
    await db_session.commit()

    service = VDBRoutingService(db_session)
    vdb_a, _ = await service.get_vdb_for_query(
        context=_context(tenant_id, owner_id), project_id=project_a.id
    )
    vdb_b, _ = await service.get_vdb_for_query(
        context=_context(tenant_id, owner_id), project_id=project_b.id
    )
    assert vdb_a.vdb_id == "shared-vdb-a"
    assert vdb_b.vdb_id == "shared-vdb-b"
    assert vdb_a.vdb_id != vdb_b.vdb_id


async def test_shared_project_without_shared_vdb_raises_instead_of_falling_back(db_session):
    tenant_id, owner_id = await _seed_tenant_owner(db_session, "vr-no-shared-vdb")
    project = Project(tenant_id=tenant_id, owner_id=owner_id, name="Shared", is_shared=True)
    db_session.add(project)
    await db_session.flush()
    await _add_second_member(db_session, tenant_id, project)
    # Only the owner's private VDB exists -- no SharedVDB row for this project.
    db_session.add(
        UserVDB(
            tenant_id=tenant_id,
            user_id=owner_id,
            vdb_id="owner-vdb",
            vdb_username="u",
            encrypted_password="p",
            is_active=True,
        )
    )
    await db_session.commit()

    with pytest.raises(VDBNotConfiguredError):
        await VDBRoutingService(db_session).get_vdb_for_query(
            context=_context(tenant_id, owner_id), project_id=project.id
        )


async def test_private_project_routes_to_users_own_vdb(db_session):
    tenant_id, owner_id = await _seed_tenant_owner(db_session, "vr-private")
    project = Project(tenant_id=tenant_id, owner_id=owner_id, name="Mine", is_shared=False)
    db_session.add(project)
    await db_session.flush()
    db_session.add(
        UserVDB(
            tenant_id=tenant_id,
            user_id=owner_id,
            vdb_id="owner-vdb",
            vdb_username="u",
            encrypted_password="p",
            is_active=True,
        )
    )
    await db_session.commit()

    vdb, vdb_type = await VDBRoutingService(db_session).get_vdb_for_query(
        context=_context(tenant_id, owner_id), project_id=project.id
    )
    assert vdb_type == "user"
    assert vdb.vdb_id == "owner-vdb"
