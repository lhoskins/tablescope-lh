"""``project_table_schema`` must cover every project data source, not only
uploaded files.

Live finding: ``project_table_schema`` (the source of ``allowed_tables`` for
the TS-ISO-002 SQL/table authorization gate, and of the column-context used
by SQL normalization/repair) only ever queried ``FileSourceMeta``. Every
JDBC database connector and every SaaS connector object (ServiceNow, HubSpot,
Salesforce, QuickBooks, ...) is registered as a ``DatabaseDataSource`` row
instead, so it never appeared in the allowlist. Concretely this meant:

- previewing/querying a database- or SaaS-sourced table in a project that
  also had at least one uploaded file was rejected with "Unauthorized table
  reference", even though the table is a real, project-scoped data source;
- in a project with *no* uploaded files at all, ``allowed_tables`` was
  always empty, which made ``authorize_sql``'s ``if allowed_tables:`` guard
  skip the table-allowlist check entirely -- silently disabling the very
  protection TS-ISO-002 added for any all-database/all-SaaS project.

Run from ``platform-api``: ``pytest -q tests/test_project_table_schema.py``.
"""

from __future__ import annotations

import pytest

from app.models.database_data_source import DatabaseDataSource, DataSourceColumn
from app.models.file_source_meta import FileSourceMeta
from app.models.project import Project
from app.services.teiid_sql.string_filters import project_table_schema

pytestmark = pytest.mark.anyio


async def _project(db_session, tenant_id: int, owner_id: int = 1) -> Project:
    project = Project(tenant_id=tenant_id, owner_id=owner_id, name="P", is_shared=False)
    db_session.add(project)
    await db_session.flush()
    return project


async def test_includes_a_saas_connector_table_alongside_a_file_source(db_session):
    tenant_id = 401
    project = await _project(db_session, tenant_id)

    db_session.add(
        FileSourceMeta(
            tenant_id=tenant_id, project_id=project.id, owner_id=1,
            view_name="example_csv", file_name="example.csv",
            column_types=[{"name": "id", "type": "integer"}],
        )
    )
    ds = DatabaseDataSource(
        tenant_id=tenant_id, project_id=project.id, created_by=1,
        display_name="change_request", source_type="saas_object",
        connector_type="servicenow", db_type="servicenow",
        host="https://dev.service-now.com", port=0, database_name="",
        schema_name="", table_name="change_request",
        username="svc", teiid_model_name="ds_1_src", teiid_table_name="change_request",
        teiid_view_name="change_request_SERVICENOW", teiid_jndi_name="java:/ds_1_servicenow",
        status="active", archived=False,
    )
    db_session.add(ds)
    await db_session.flush()
    db_session.add(
        DataSourceColumn(data_source_id=ds.id, column_name="number", data_type="string")
    )
    await db_session.commit()

    schema = await project_table_schema(db_session, tenant_id=tenant_id, project_id=project.id)
    tables = {entry["table"] for entry in schema}
    assert tables == {"example_csv", "change_request_SERVICENOW"}

    saas_entry = next(e for e in schema if e["table"] == "change_request_SERVICENOW")
    assert saas_entry["columns"] == [{"name": "number", "type": "string"}]


async def test_excludes_archived_and_inactive_database_data_sources(db_session):
    tenant_id = 402
    project = await _project(db_session, tenant_id)

    db_session.add(
        DatabaseDataSource(
            tenant_id=tenant_id, project_id=project.id, created_by=1,
            display_name="draft one", source_type="database_table",
            db_type="postgresql", host="h", port=5432, database_name="d",
            schema_name="public", table_name="t1",
            username="u", teiid_model_name="m1", teiid_table_name="t1",
            teiid_view_name="draft_view", teiid_jndi_name="java:/m1",
            status="draft", archived=False,
        )
    )
    db_session.add(
        DatabaseDataSource(
            tenant_id=tenant_id, project_id=project.id, created_by=1,
            display_name="archived one", source_type="database_table",
            db_type="postgresql", host="h", port=5432, database_name="d",
            schema_name="public", table_name="t2",
            username="u", teiid_model_name="m2", teiid_table_name="t2",
            teiid_view_name="archived_view", teiid_jndi_name="java:/m2",
            status="active", archived=True,
        )
    )
    await db_session.commit()

    schema = await project_table_schema(db_session, tenant_id=tenant_id, project_id=project.id)
    assert schema == []


async def test_no_file_sources_still_authorizes_database_only_projects(db_session):
    """The 'fail-open' side of the bug: a project with zero uploaded files
    must still get a non-empty allowlist when it has database/SaaS sources,
    so authorize_sql's table-allowlist check actually runs instead of
    silently no-op'ing on an empty list."""
    tenant_id = 403
    project = await _project(db_session, tenant_id)

    db_session.add(
        DatabaseDataSource(
            tenant_id=tenant_id, project_id=project.id, created_by=1,
            display_name="orders", source_type="database_table",
            db_type="postgresql", host="h", port=5432, database_name="d",
            schema_name="public", table_name="orders",
            username="u", teiid_model_name="m1", teiid_table_name="orders",
            teiid_view_name="orders_view", teiid_jndi_name="java:/m1",
            status="active", archived=False,
        )
    )
    await db_session.commit()

    schema = await project_table_schema(db_session, tenant_id=tenant_id, project_id=project.id)
    assert [e["table"] for e in schema] == ["orders_view"]
