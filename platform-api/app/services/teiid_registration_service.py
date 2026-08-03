"""Teiid registration for database-backed data sources.

Generates Teiid-safe identifiers and asks the WildFly/Teiid servlet to:

1. create a runtime JDBC datasource (``createDataSource`` Admin API),
2. add a physical model for the table into the user's VDB,
3. add a view over that model into the ``MyCompany`` virtual model,
4. redeploy the VDB.

The heavy lifting lives in the Java servlet (it has the Teiid Admin API on the
classpath).  This module is a thin async HTTP client plus the naming rules.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import unquote, urlparse

import httpx

from app.config import get_settings
from app.services.database_introspection_service import (
    build_jdbc_url,
    get_db_type_config,
    normalize_db_password,
)


def _platform_db_password() -> str | None:
    """Return the password for the platform's own Postgres from settings."""
    url = urlparse(get_settings().database_url)
    if url.password is None:
        return None
    return unquote(url.password)


def _platform_db_params() -> dict[str, str | int]:
    """Return host/port/database/username for the platform's own Postgres."""
    url = urlparse(get_settings().database_url)
    return {
        "host": url.hostname or "db",
        "port": url.port or 5432,
        "database_name": (url.path or "/tablescope").lstrip("/"),
        "username": unquote(url.username) if url.username else "tablescope",
    }


def _platform_password_for_source(ds) -> str | None:
    """If ``ds`` points at the platform's own Postgres, return its password.

    SaaS and local-staging data sources are stored with no encrypted password
    because the table lives in the app database.  WildFly/Teiid still needs a
    non-empty credential for the JDBC datasource, so fall back to the platform
    DB password parsed from ``DATABASE_URL``.
    """
    expected = _platform_db_params()
    if (
        ds.host == expected["host"]
        and str(ds.port) == str(expected["port"])
        and ds.database_name == expected["database_name"]
        and ds.username == expected["username"]
    ):
        return _platform_db_password()
    return None

logger = logging.getLogger(__name__)

_RESERVED = {
    "select", "from", "where", "table", "view", "model", "user", "group",
    "order", "by", "join", "on", "as", "and", "or", "not", "null",
}


class TeiidRegistrationError(Exception):
    """Raised when Teiid registration of a DB data source fails."""


def sanitize_identifier(value: str) -> str:
    """Make an arbitrary string safe for use as a Teiid identifier.

    Strips spaces, hyphens and special characters, collapses repeats, ensures
    it starts with a letter/underscore, and avoids reserved SQL words.
    """
    cleaned = re.sub(r"[^0-9A-Za-z_]+", "_", value.strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    if not cleaned:
        cleaned = "ds"
    if not re.match(r"^[A-Za-z_]", cleaned):
        cleaned = f"_{cleaned}"
    if cleaned.lower() in _RESERVED:
        cleaned = f"{cleaned}_"
    return cleaned


def generate_teiid_names(*, data_source_id: int, db_type: str, table_name: str) -> dict:
    """Deterministic, collision-resistant Teiid names for a data source."""
    safe_table = sanitize_identifier(table_name)
    return {
        "model_name": f"ds_{data_source_id}_src",
        "jndi_name": f"java:/ds_{data_source_id}_{db_type}",
        "ds_name": f"ds_{data_source_id}_{db_type}",
        "teiid_table_name": safe_table,
    }


def generate_view_name(*, display_name: str, db_type: str) -> str:
    """A friendly, unique view name surfaced to the query builder."""
    base = sanitize_identifier(display_name)
    suffix = db_type.upper()
    return f"{base}_{suffix}"


class TeiidRegistrationService:
    """Async client around the servlet's ``createDatabaseSource`` endpoint."""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        servlet_url: str | None = None,
    ) -> None:
        settings = get_settings()
        self._settings = settings
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=servlet_url or settings.teiid_servlet_url,
            timeout=httpx.Timeout(120.0, connect=10.0),
            headers=(
                {"X-API-Key": settings.teiid_servlet_api_key}
                if settings.teiid_servlet_api_key
                else {}
            ),
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def register_servicenow_source(
        self,
        *,
        vdb_id: str,
        org_id: int,
        user_id: int,
        instance_url: str,
        username: str,
        password: str,
        object_type: str,
        model_name: str,
        teiid_table_name: str,
        ds_name: str,
        jndi_name: str,
        view_name: str,
        columns: list[dict],
    ) -> dict:
        """Register a ServiceNow table using the custom Teiid translator.

        Unlike ``register_database_source``, this does not create a JDBC
        datasource; the ServiceNow translator opens HTTP connections directly.
        """
        payload = {
            "vdb_id": vdb_id,
            "org_id": org_id,
            "user_id": user_id,
            "teiid_host": "localhost",
            "teiid_port": 9990,
            "db_type": "servicenow",
            "translator": "servicenow",
            "jdbc_url": instance_url,
            "instance_url": instance_url,
            "table_name": object_type,
            "username": username,
            "password": password,
            "model_name": model_name,
            "teiid_table_name": teiid_table_name,
            "jndi_name": jndi_name,
            "ds_name": ds_name,
            "view_name": view_name,
            "schema_name": "",
            "columns": columns,
            "force": True,
        }

        safe_payload = {k: v for k, v in payload.items() if k != "password"}
        logger.info("Registering ServiceNow source in Teiid: %s", safe_payload)

        try:
            response = await self._client.post(
                "/TeiidExcelImporterTest/vdb-management/createDatabaseSource",
                json=payload,
            )
        except httpx.RequestError as exc:
            raise TeiidRegistrationError(
                f"Failed to contact Teiid servlet: {exc}"
            ) from exc

        if response.status_code >= 400:
            raise TeiidRegistrationError(
                f"Teiid rejected ServiceNow source registration: "
                f"{response.status_code} {response.text}"
            )

        try:
            body = response.json()
        except Exception:
            body = {"raw": response.text}

        if isinstance(body, dict) and body.get("error"):
            raise TeiidRegistrationError(str(body["error"]))

        return body

    async def register_database_source(
        self,
        *,
        vdb_id: str,
        org_id: int,
        user_id: int,
        db_type: str,
        host: str,
        port: int,
        database_name: str,
        schema_name: str | None,
        table_name: str,
        username: str,
        password: str,
        ssl_mode: str | None,
        model_name: str,
        teiid_table_name: str,
        jndi_name: str,
        ds_name: str,
        view_name: str,
        columns: list[dict],
    ) -> dict:
        """Register the DB table in the user's VDB and redeploy."""
        cfg = get_db_type_config(db_type)
        jdbc_url = build_jdbc_url(
            db_type=db_type, host=host, port=port, database_name=database_name
        )

        # No-password sources must register without a credential. WildFly
        # rejects an empty password, so send "" (the servlet omits the
        # parameter) rather than a meaningless empty value.
        normalized_password = normalize_db_password(password) or ""

        payload = {
            "vdb_id": vdb_id,
            "org_id": org_id,
            "user_id": user_id,
            "teiid_host": "localhost",
            "teiid_port": 9990,
            "db_type": db_type,
            "translator": cfg.teiid_translator,
            "jdbc_url": jdbc_url,
            "host": host,
            "port": port,
            "database_name": database_name,
            "schema_name": schema_name or "",
            "table_name": table_name,
            "username": username,
            "password": normalized_password,
            "ssl_mode": ssl_mode or "",
            "model_name": model_name,
            "teiid_table_name": teiid_table_name,
            "jndi_name": jndi_name,
            "ds_name": ds_name,
            "view_name": view_name,
            "columns": columns,
        }

        # Never log the password.
        safe_payload = {k: v for k, v in payload.items() if k != "password"}
        logger.info("Registering DB source in Teiid: %s", safe_payload)

        try:
            response = await self._client.post(
                "/TeiidExcelImporterTest/vdb-management/createDatabaseSource",
                json=payload,
            )
        except httpx.RequestError as exc:
            raise TeiidRegistrationError(
                f"Failed to contact Teiid servlet: {exc}"
            ) from exc

        if response.status_code >= 400:
            raise TeiidRegistrationError(
                f"Teiid rejected database source registration: "
                f"{response.status_code} {response.text}"
            )

        try:
            body = response.json()
        except Exception:
            body = {"raw": response.text}

        if isinstance(body, dict) and body.get("error"):
            raise TeiidRegistrationError(str(body["error"]))

        return body


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
