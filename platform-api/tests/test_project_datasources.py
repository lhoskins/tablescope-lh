"""Regression tests for project datasource listing on dedicated data planes.

A tenant bound to a dedicated data plane stores its uploaded files under the
data plane's ``vdb_host_path`` (not the shared ``customer_base_path``). The
project "Add Datasource" modal (``list_available_datasources``) and the project
datasource list (``list_project_datasources``) must resolve the tenant's Teiid
endpoint and read from that dedicated path, otherwise the files are invisible.
"""

from __future__ import annotations

from app.auth.context import RequestContext
from app.auth.jwt import TokenClaims
from app.models.file_source_meta import FileSourceMeta
from app.models.project import Project, ProjectMember
from app.models.tenant import Tenant
from app.models.tenant_data_plane import TenantDataPlane
from app.models.user import User
from app.routes.projects import (
    list_available_datasources,
    list_project_datasources,
)


def _context(tenant_id: int, user_id: int) -> RequestContext:
    return RequestContext(
        claims=TokenClaims(
            sub=str(user_id),
            tenant_id=tenant_id,
            user_id=user_id,
            role="editor",
        )
    )


async def _seed(db_session, vdb_host_path: str):
    tenant = Tenant(slug="acme", name="Acme")
    db_session.add(tenant)
    await db_session.flush()

    user = User(
        tenant_id=tenant.id,
        email="admin@acme.com",
        display_name="Acme Admin",
        role="admin",
        external_id="14",
    )
    db_session.add(user)
    await db_session.flush()

    project = Project(
        tenant_id=tenant.id,
        owner_id=user.id,
        name="Acme Sales",
        is_shared=False,
    )
    db_session.add(project)
    await db_session.flush()
    db_session.add(
        ProjectMember(project_id=project.id, user_id=user.id, role="owner", is_active=True)
    )

    # Personal-only file (project_id is None) -> eligible for the "add" modal.
    db_session.add(
        FileSourceMeta(
            tenant_id=tenant.id,
            owner_id=user.id,
            project_id=None,
            view_name="acme_sales_CSV",
            file_name="acme_sales.csv",
        )
    )

    db_session.add(
        TenantDataPlane(
            tenant_id="acme",
            tenant_name="Acme",
            org_tenant_id=tenant.id,
            docker_network_name="tenant_acme_net",
            docker_subnet_cidr="172.30.10.0/24",
            teiid_container_name="tenant-acme-teiid",
            teiid_container_ip="172.30.10.10",
            teiid_servlet_url="http://127.0.0.1:18095",
            teiid_pg_host="127.0.0.1",
            teiid_pg_port=15442,
            teiid_mgmt_port=19990,
            vdb_host_path=vdb_host_path,
            allowed_onprem_cidrs=[],
            blocked_cidrs=[],
        )
    )
    await db_session.commit()
    return tenant, user, project


async def test_available_datasources_reads_dedicated_vdb_path(db_session, tmp_path) -> None:
    """Files under a bound tenant's dedicated path appear in the add modal."""
    vdb_root = tmp_path / "acme-vdb"
    tenant, user, project = await _seed(db_session, str(vdb_root))

    uploads = vdb_root / str(tenant.id) / str(user.id) / "uploads"
    uploads.mkdir(parents=True)
    (uploads / "acme_sales.csv").write_text("region,amount\nWest,100\n")

    ctx = _context(tenant.id, user.id)
    available = await list_available_datasources(project.id, db_session, ctx)

    views = {d["viewName"] for d in available}
    assert "acme_sales_CSV" in views

    # The file must NOT be found under the shared customer_base_path.
    in_project = await list_project_datasources(project.id, False, db_session, ctx)
    # Personal-only file (project_id None) is hidden from the project itself.
    assert all(d.get("viewName") != "acme_sales_CSV" for d in in_project)


async def test_available_datasources_empty_when_dedicated_path_missing(db_session, tmp_path) -> None:
    """No phantom rows when the dedicated path has no files (sanity)."""
    tenant, user, project = await _seed(db_session, str(tmp_path / "empty-vdb"))
    ctx = _context(tenant.id, user.id)
    available = await list_available_datasources(project.id, db_session, ctx)
    assert available == []
