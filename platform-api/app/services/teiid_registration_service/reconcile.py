
from __future__ import annotations

from . import TeiidRegistrationService
from .naming import generate_teiid_names, logger
from .platform_db import _platform_password_for_source


async def reconcile_database_sources(session, *, only_id: int | None = None) -> dict:
    """Re-register active DB-table sources' JDBC datasources + VDB models in Teiid.

    Runtime JDBC datasources created through the Teiid Admin API live only in the
    running WildFly process; they do NOT survive a Teiid container restart or
    recreate.  After such a restart the persisted VDB XML still references those
    datasources, so every DB-table source fails with TEIID30498 ("Capabilities
    ... were not available").  This reconciler walks every active source and asks
    the servlet to (idempotently) recreate the datasource and redeploy the VDB,
    restoring all DB-table sources after a restart.  Safe to run repeatedly.
    """
    # Imported lazily to avoid import cycles at module load time.
    from sqlalchemy import select

    from app.models.database_data_source import DatabaseDataSource, DataSourceColumn
    from app.models.user_vdb import UserVDB
    from app.services import database_introspection_service as intro
    from app.services.crypto import decrypt_secret

    stmt = select(DatabaseDataSource).where(DatabaseDataSource.status == "active")
    if only_id is not None:
        stmt = stmt.where(DatabaseDataSource.id == only_id)
    sources = list((await session.scalars(stmt)).all())

    results: dict = {
        "total": len(sources),
        "ok": 0,
        "failed": 0,
        "skipped": 0,
        "errors": [],
    }
    if not sources:
        return results

    reg = TeiidRegistrationService()
    try:
        for ds in sources:
            if not ds.teiid_view_name or ds.created_by is None:
                results["skipped"] += 1
                continue

            user_vdb = await session.scalar(
                select(UserVDB).where(
                    UserVDB.tenant_id == ds.tenant_id,
                    UserVDB.user_id == ds.created_by,
                )
            )
            if user_vdb is None:
                results["skipped"] += 1
                continue

            cols = list(
                (
                    await session.scalars(
                        select(DataSourceColumn)
                        .where(DataSourceColumn.data_source_id == ds.id)
                        .order_by(DataSourceColumn.ordinal_position)
                    )
                ).all()
            )
            teiid_columns = [
                {
                    "name": c.column_name,
                    "name_in_source": intro.source_identifier(
                        ds.db_type, c.column_name
                    ),
                    "teiid_type": (
                        c.teiid_type_override
                        or intro.map_to_teiid_type(c.data_type or "")
                    ),
                }
                for c in cols
            ]

            names = generate_teiid_names(
                data_source_id=ds.id, db_type=ds.db_type, table_name=ds.table_name
            )
            try:
                password = (
                    decrypt_secret(ds.password_encrypted)
                    if ds.password_encrypted
                    else ""
                )
            except Exception:  # pragma: no cover - corrupt/rotated key
                password = ""

            # Staging/local DB sources may be stored without a password because
            # the table lives in the platform's own Postgres.  Fall back to the
            # platform DB password so Teiid can build a non-empty credential.
            if not password:
                password = _platform_password_for_source(ds) or ""

            try:
                if ds.db_type == "servicenow":
                    await reg.register_servicenow_source(
                        vdb_id=user_vdb.vdb_id,
                        org_id=ds.tenant_id,
                        user_id=ds.created_by,
                        instance_url=ds.host,
                        username=ds.username,
                        password=password,
                        object_type=ds.table_name,
                        model_name=ds.teiid_model_name or names["model_name"],
                        teiid_table_name=ds.teiid_table_name or names["teiid_table_name"],
                        ds_name=names["ds_name"],
                        jndi_name=ds.teiid_jndi_name or names["jndi_name"],
                        view_name=ds.teiid_view_name,
                        columns=teiid_columns,
                    )
                elif ds.db_type == "salesforce":
                    await reg.register_salesforce_source(
                        vdb_id=user_vdb.vdb_id,
                        org_id=ds.tenant_id,
                        user_id=ds.created_by,
                        instance_url=ds.host,
                        username=ds.username,
                        password=password,
                        object_type=ds.table_name,
                        model_name=ds.teiid_model_name or names["model_name"],
                        teiid_table_name=ds.teiid_table_name or names["teiid_table_name"],
                        ds_name=names["ds_name"],
                        jndi_name=ds.teiid_jndi_name or names["jndi_name"],
                        view_name=ds.teiid_view_name,
                        columns=teiid_columns,
                    )
                else:
                    await reg.register_database_source(
                        vdb_id=user_vdb.vdb_id,
                        org_id=ds.tenant_id,
                        user_id=ds.created_by,
                        db_type=ds.db_type,
                        host=ds.host,
                        port=ds.port,
                        database_name=ds.database_name,
                        schema_name=intro.source_identifier(ds.db_type, ds.schema_name),
                        table_name=intro.source_identifier(ds.db_type, ds.table_name)
                        or ds.table_name,
                        username=ds.username,
                        password=password,
                        ssl_mode=ds.ssl_mode,
                        model_name=ds.teiid_model_name or names["model_name"],
                        teiid_table_name=ds.teiid_table_name or names["teiid_table_name"],
                        jndi_name=ds.teiid_jndi_name or names["jndi_name"],
                        ds_name=names["ds_name"],
                        view_name=ds.teiid_view_name,
                        columns=teiid_columns,
                    )
                results["ok"] += 1
            except Exception as exc:
                results["failed"] += 1
                results["errors"].append({"id": ds.id, "error": str(exc)[:300]})
                logger.warning("Reconcile failed for ds %s: %s", ds.id, exc)
    finally:
        await reg.aclose()

    logger.info(
        "DB source reconcile complete: total=%s ok=%s failed=%s skipped=%s",
        results["total"],
        results["ok"],
        results["failed"],
        results["skipped"],
    )
    return results
