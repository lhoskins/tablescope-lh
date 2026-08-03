"""Orchestration for SaaS-backed data sources.

Ties the connector framework to the existing database-table pipeline:

1. create the local Postgres staging table for a selected object,
2. register that staging table in Teiid (datasource + model + view) exactly like
   a normal PostgreSQL table — so it lists, joins and survives restarts via the
   same reconcile path,
3. sync records from the SaaS API into the staging table (upsert).

The Teiid-facing record is a ``DatabaseDataSource`` (``source_type="saas_object"``,
``db_type="postgresql"``) pointing at the platform's own Postgres; the
``SaasObjectDataSource`` row holds the SaaS metadata + sync state.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import unquote, urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.connectors.base import StagingColumn
from app.connectors.registry import get_connector
from app.models.connector_credential import ConnectorCredential
from app.models.database_data_source import DatabaseDataSource, DataSourceColumn
from app.models.saas_object_data_source import SaasObjectDataSource
from app.models.user_vdb import UserVDB
from app.services import database_introspection_service as intro
from app.services import saas_staging_service as staging
from app.services.auto_query import ensure_datasource_query
from app.services.crypto import decrypt_secret, encrypt_secret
from app.services.teiid_registration_service import (
    TeiidRegistrationService,
    generate_teiid_names,
    generate_view_name,
)

logger = logging.getLogger(__name__)

# Default cap for the initial sync so creating a source stays fast; a full
# resync (no cap) is available via the resync endpoint.
DEFAULT_INITIAL_SYNC_LIMIT = 10000


class SaasSourceError(Exception):
    """User-facing SaaS source error (safe message, no secrets)."""


@dataclass(frozen=True)
class _PgConn:
    host: str
    port: int
    database: str
    user: str
    password: str


def _app_pg_connection() -> _PgConn:
    """Parse the platform's own Postgres connection from settings.

    The staging tables live in this database; Teiid reaches it over the Docker
    network using the same host/port.
    """
    url = urlparse(get_settings().database_url)
    return _PgConn(
        host=url.hostname or "db",
        port=url.port or 5432,
        database=(url.path or "/tablescope").lstrip("/") or "tablescope",
        user=unquote(url.username) if url.username else "postgres",
        password=unquote(url.password) if url.password else "",
    )


def decrypt_config(credential: ConnectorCredential) -> dict:
    if not credential.secret_encrypted:
        return {}
    try:
        return json.loads(decrypt_secret(credential.secret_encrypted))
    except Exception as exc:  # pragma: no cover - corrupt/rotated key
        raise SaasSourceError("Stored connector credential could not be read.") from exc


def _staging_columns_for(
    connector, object_type: str, selected_fields: list[str], field_types: dict[str, str]
) -> list[StagingColumn]:
    base = connector.base_columns(object_type)
    selected = [
        StagingColumn(name=f, pg_type=field_types.get(f, "text"))
        for f in selected_fields
    ]
    return staging.all_columns(base, selected)


async def create_saas_source(
    session: AsyncSession,
    *,
    tenant_id: int,
    user_id: int,
    project_id: int | None,
    connector_type: str,
    credential_id: int,
    object_type: str,
    selected_fields: list[str],
    display_name: str,
) -> SaasObjectDataSource:
    """Create staging table + Teiid registration + metadata rows (draft sync)."""
    connector = get_connector(connector_type)

    credential = await session.get(ConnectorCredential, credential_id)
    if credential is None or credential.tenant_id != tenant_id:
        raise SaasSourceError("Connector credential not found.")
    config = decrypt_config(credential)

    # Resolve the user's VDB (where the view will live).
    user_vdb = await session.scalar(
        select(UserVDB).where(
            UserVDB.tenant_id == tenant_id, UserVDB.user_id == user_id
        )
    )
    if user_vdb is None:
        raise SaasSourceError("No VDB found for this user.")

    # Reject duplicate display names like the database-table route does.
    dup = await session.scalar(
        select(DatabaseDataSource).where(
            DatabaseDataSource.tenant_id == tenant_id,
            DatabaseDataSource.display_name == display_name,
        )
    )
    if dup is not None:
        raise SaasSourceError(
            f"A data source named '{display_name}' already exists."
        )

    # Field -> pg type from connector metadata.
    fields = await connector.list_fields(config, object_type)
    field_types = {f.name: f.pg_type for f in fields}
    columns = _staging_columns_for(
        connector, object_type, selected_fields, field_types
    )
    id_column = connector.id_column(object_type)

    pg = _app_pg_connection()
    is_servicenow = connector_type == "servicenow"

    sn_username = ""
    sn_password = ""
    sn_instance_url = ""
    if is_servicenow:
        sn_username = config.get("username", "")
        sn_password = config.get("password", "")
        sn_instance_url = (config.get("instance_url") or "").strip().rstrip("/")
        if sn_instance_url and not sn_instance_url.startswith("http"):
            sn_instance_url = f"https://{sn_instance_url}"

    # 1. DatabaseDataSource (draft) to allocate an id for naming.
    ds = DatabaseDataSource(
        tenant_id=tenant_id,
        project_id=project_id,
        created_by=user_id,
        display_name=display_name,
        source_type="saas_object",
        connector_type=connector_type,
        db_type="servicenow" if is_servicenow else "postgresql",
        host=sn_instance_url if is_servicenow else pg.host,
        port=0 if is_servicenow else pg.port,
        database_name="" if is_servicenow else pg.database,
        schema_name="" if is_servicenow else staging.STAGING_SCHEMA,
        table_name="",  # set after id is known
        username=sn_username if is_servicenow else pg.user,
        password_encrypted=(
            encrypt_secret(sn_password)
            if is_servicenow and sn_password
            else (encrypt_secret(pg.password) if pg.password else None)
        ),
        ssl_mode=None,
        teiid_model_name="",
        teiid_table_name="",
        teiid_view_name="",
        teiid_jndi_name="",
        status="draft",
        last_test_status="success",
        last_test_message="Connection successful",
        last_tested_at=datetime.now(UTC),
    )
    session.add(ds)
    await session.flush()  # assign ds.id

    if is_servicenow:
        ds_table_name = object_type.lower()
    else:
        ds_table_name = f"{connector_type}_ds_{ds.id}_{object_type.lower()}"
    ds.table_name = ds_table_name

    names = generate_teiid_names(
        data_source_id=ds.id, db_type=ds.db_type, table_name=ds_table_name
    )
    view_name = generate_view_name(
        display_name=display_name, db_type=connector_type
    )
    ds.teiid_model_name = names["model_name"]
    ds.teiid_table_name = names["teiid_table_name"]
    ds.teiid_jndi_name = names["jndi_name"]
    ds.teiid_view_name = view_name

    # 2. Persist column metadata (drives reconcile and query builder).
    for idx, col in enumerate(columns):
        session.add(
            DataSourceColumn(
                data_source_id=ds.id,
                column_name=col.name,
                ordinal_position=idx + 1,
                data_type=col.pg_type,
                nullable=not col.primary_key,
                primary_key=col.primary_key,
                created_at=datetime.now(UTC),
            )
        )

    # 3. SaaS metadata row.
    saas = SaasObjectDataSource(
        tenant_id=tenant_id,
        database_data_source_id=ds.id,
        credential_id=credential_id,
        connector_type=connector_type,
        object_type=object_type,
        selected_properties=selected_fields,
        staging_schema="" if is_servicenow else staging.STAGING_SCHEMA,
        staging_table="" if is_servicenow else ds_table_name,
        sync_mode="live" if is_servicenow else "manual",
        last_sync_status="live" if is_servicenow else "pending",
    )
    session.add(saas)

    # 4. Create the physical staging table in the app's Postgres (not needed
    # for ServiceNow, which is queried live via the custom Teiid translator).
    if not is_servicenow:
        await staging.create_staging_table(
            session,
            schema=staging.STAGING_SCHEMA,
            table=ds_table_name,
            columns=columns,
            id_column=id_column,
        )

    # 5. Register the source in Teiid.
    teiid_columns = [
        {
            "name": col.name,
            "name_in_source": intro.source_identifier(ds.db_type, col.name),
            "teiid_type": intro.map_to_teiid_type(col.pg_type),
        }
        for col in columns
    ]
    reg = TeiidRegistrationService()
    try:
        if is_servicenow:
            await reg.register_servicenow_source(
                vdb_id=user_vdb.vdb_id,
                org_id=tenant_id,
                user_id=user_id,
                instance_url=sn_instance_url,
                username=sn_username,
                password=sn_password,
                object_type=object_type,
                model_name=names["model_name"],
                teiid_table_name=names["teiid_table_name"],
                ds_name=names["ds_name"],
                jndi_name=names["jndi_name"],
                view_name=view_name,
                columns=teiid_columns,
            )
        else:
            await reg.register_database_source(
                vdb_id=user_vdb.vdb_id,
                org_id=tenant_id,
                user_id=user_id,
                db_type="postgresql",
                host=pg.host,
                port=pg.port,
                database_name=pg.database,
                schema_name=staging.STAGING_SCHEMA,
                table_name=ds_table_name,
                username=pg.user,
                password=pg.password,
                ssl_mode=None,
                model_name=names["model_name"],
                teiid_table_name=names["teiid_table_name"],
                jndi_name=names["jndi_name"],
                ds_name=names["ds_name"],
                view_name=view_name,
                columns=teiid_columns,
            )
    finally:
        await reg.aclose()

    ds.status = "active"

    # Auto-create a saved query so the new source shows up under project Tables.
    if project_id is not None:
        await ensure_datasource_query(
            session,
            project_id=project_id,
            owner_id=user_id,
            display_name=display_name,
            view_name=view_name,
            columns=[c.name for c in columns],
        )

    await session.commit()
    await session.refresh(saas)
    return saas


async def run_sync(
    session: AsyncSession,
    *,
    saas_source_id: int,
    limit: int | None = DEFAULT_INITIAL_SYNC_LIMIT,
) -> dict:
    """Sync a SaaS object into its staging table (upsert).  Idempotent."""
    saas = await session.get(SaasObjectDataSource, saas_source_id)
    if saas is None:
        raise SaasSourceError("SaaS data source not found.")

    if saas.connector_type == "servicenow":
        return {
            "status": "live",
            "message": "ServiceNow data is queried in real time; sync is not required.",
        }

    credential = await session.get(ConnectorCredential, saas.credential_id)
    if credential is None:
        raise SaasSourceError("Connector credential not found.")

    connector = get_connector(saas.connector_type)
    config = decrypt_config(credential)
    id_column = connector.id_column(saas.object_type)

    # Rebuild staging column list (with pg types) from persisted metadata.
    col_rows = list(
        (
            await session.scalars(
                select(DataSourceColumn)
                .where(
                    DataSourceColumn.data_source_id == saas.database_data_source_id
                )
                .order_by(DataSourceColumn.ordinal_position)
            )
        ).all()
    )
    columns = [
        StagingColumn(
            name=c.column_name,
            pg_type=c.data_type or "text",
            primary_key=bool(c.primary_key),
        )
        for c in col_rows
    ]

    saas.last_sync_status = "syncing"
    await session.commit()

    try:
        records = await connector.fetch_records(
            config,
            saas.object_type,
            list(saas.selected_properties or []),
            limit=limit,
        )
        await staging.upsert_records(
            session,
            schema=saas.staging_schema,
            table=saas.staging_table,
            columns=columns,
            id_column=id_column,
            rows=records,
        )
        total = await staging.count_rows(
            session, schema=saas.staging_schema, table=saas.staging_table
        )
        saas.last_sync_status = "success"
        saas.last_sync_at = datetime.now(UTC)
        saas.last_sync_message = f"Synced {len(records)} record(s)."
        saas.row_count = total
        await session.commit()
        return {
            "status": "success",
            "fetched": len(records),
            "row_count": total,
        }
    except Exception as exc:
        await session.rollback()
        saas.last_sync_status = "error"
        saas.last_sync_at = datetime.now(UTC)
        saas.last_sync_message = str(exc)[:500]
        await session.commit()
        logger.warning("SaaS sync failed for source %s: %s", saas_source_id, exc)
        raise
