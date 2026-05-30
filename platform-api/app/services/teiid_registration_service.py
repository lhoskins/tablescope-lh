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

import httpx

from app.config import get_settings
from app.services.database_introspection_service import (
    build_jdbc_url,
    get_db_type_config,
)

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

    def __init__(self, *, client: httpx.AsyncClient | None = None) -> None:
        settings = get_settings()
        self._settings = settings
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=settings.teiid_servlet_url,
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
            "password": password,
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
