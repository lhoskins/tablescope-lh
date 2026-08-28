
from __future__ import annotations

import httpx

from app.config import get_settings
from app.services.connection_pool import pool_manager
from app.services.database_introspection_service import (
    build_jdbc_url,
    get_db_type_config,
    normalize_db_password,
)
from app.services.vdb_warming import warm_vdb

from .naming import _RESERVED as _RESERVED
from .naming import generate_teiid_names as generate_teiid_names
from .naming import generate_view_name as generate_view_name
from .naming import logger
from .naming import sanitize_identifier as sanitize_identifier
from .platform_db import _platform_db_params as _platform_db_params
from .platform_db import _platform_db_password as _platform_db_password
from .platform_db import _platform_password_for_source as _platform_password_for_source

"""Teiid registration for database-backed data sources.

Generates Teiid-safe identifiers and asks the WildFly/Teiid servlet to:

1. create a runtime JDBC datasource (``createDataSource`` Admin API),
2. add a physical model for the table into the user's VDB,
3. add a view over that model into the ``MyCompany`` virtual model,
4. redeploy the VDB.

The heavy lifting lives in the Java servlet (it has the Teiid Admin API on the
classpath).  This module is a thin async HTTP client plus the naming rules.
"""


class TeiidRegistrationError(Exception):
    """Raised when Teiid registration of a DB data source fails."""


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

    async def _warm_vdb(self, vdb_id: str) -> None:
        """Best-effort pool warm after a source is registered."""
        await warm_vdb(
            vdb_id,
            vdb_host=self._settings.teiid_pg_host,
            vdb_port=self._settings.teiid_pg_port,
            connect_timeout=60.0,
            timeout=15.0,
            warm_views=False,
            max_concurrent_views=1,
            max_attempts=1,
            retry_delay=2.0,
        )

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

        await pool_manager.evict_by_vdb_id(vdb_id)
        return body

    async def register_salesforce_source(
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
        """Register a Salesforce object using the native Teiid salesforce translator.

        This creates a JCA connection factory in WildFly pointing at the
        Salesforce SOAP login endpoint, then adds a physical model + view to the
        VDB.  No local staging table is used; SOQL is executed live against
        Salesforce.
        """
        payload = {
            "vdb_id": vdb_id,
            "org_id": org_id,
            "user_id": user_id,
            "teiid_host": "localhost",
            "teiid_port": 9990,
            "db_type": "salesforce",
            "translator": "salesforce-41",
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
        logger.info("Registering Salesforce source in Teiid: %s", safe_payload)

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
                f"Teiid rejected Salesforce source registration: "
                f"{response.status_code} {response.text}"
            )

        try:
            body = response.json()
        except Exception:
            body = {"raw": response.text}

        if isinstance(body, dict) and body.get("error"):
            raise TeiidRegistrationError(str(body["error"]))

        await pool_manager.evict_by_vdb_id(vdb_id)
        return body

    async def register_hubspot_source(
        self,
        *,
        vdb_id: str,
        org_id: int,
        user_id: int,
        access_token: str,
        object_type: str,
        model_name: str,
        teiid_table_name: str,
        ds_name: str,
        jndi_name: str,
        view_name: str,
        columns: list[dict],
    ) -> dict:
        """Register a HubSpot CRM object using the custom Teiid translator."""
        payload = {
            "vdb_id": vdb_id,
            "org_id": org_id,
            "user_id": user_id,
            "teiid_host": "localhost",
            "teiid_port": 9990,
            "db_type": "hubspot",
            "translator": "hubspot",
            "jdbc_url": "https://api.hubapi.com",
            "instance_url": "https://api.hubapi.com",
            "table_name": object_type,
            "username": "",
            "password": access_token,
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
        logger.info("Registering HubSpot source in Teiid: %s", safe_payload)

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
                f"Teiid rejected HubSpot source registration: "
                f"{response.status_code} {response.text}"
            )

        try:
            body = response.json()
        except Exception:
            body = {"raw": response.text}

        if isinstance(body, dict) and body.get("error"):
            raise TeiidRegistrationError(str(body["error"]))

        await pool_manager.evict_by_vdb_id(vdb_id)
        return body

    async def register_quickbooks_source(
        self,
        *,
        vdb_id: str,
        org_id: int,
        user_id: int,
        access_token: str,
        realm_id: str,
        environment: str,
        object_type: str,
        model_name: str,
        teiid_table_name: str,
        ds_name: str,
        jndi_name: str,
        view_name: str,
        columns: list[dict],
    ) -> dict:
        """Register a QuickBooks Online object using the custom Teiid translator."""
        base_url = (
            "https://sandbox-quickbooks.api.intuit.com"
            if str(environment).lower() == "sandbox"
            else "https://quickbooks.api.intuit.com"
        )
        payload = {
            "vdb_id": vdb_id,
            "org_id": org_id,
            "user_id": user_id,
            "teiid_host": "localhost",
            "teiid_port": 9990,
            "db_type": "quickbooks",
            "translator": "quickbooks",
            "jdbc_url": base_url,
            "instance_url": base_url,
            "realm_id": realm_id,
            "environment": environment,
            "table_name": object_type,
            "username": "",
            "password": access_token,
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
        logger.info("Registering QuickBooks source in Teiid: %s", safe_payload)

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
                f"Teiid rejected QuickBooks source registration: "
                f"{response.status_code} {response.text}"
            )

        try:
            body = response.json()
        except Exception:
            body = {"raw": response.text}

        if isinstance(body, dict) and body.get("error"):
            raise TeiidRegistrationError(str(body["error"]))

        await pool_manager.evict_by_vdb_id(vdb_id)
        return body

    async def register_google_sheets_source(
        self,
        *,
        vdb_id: str,
        org_id: int,
        user_id: int,
        spreadsheet_id: str,
        refresh_token: str,
        client_id: str,
        client_secret: str,
        sheet_name: str,
        teiid_table_name: str,
        model_name: str,
        ds_name: str,
        jndi_name: str,
        view_name: str,
        columns: list[dict],
    ) -> dict:
        """Register a Google Sheet tab using the native Teiid google-spreadsheet translator.

        Creates a JCA connection factory in WildFly for the Google Spreadsheet
        resource adapter, then adds a physical model + view to the VDB.
        """
        payload = {
            "vdb_id": vdb_id,
            "org_id": org_id,
            "user_id": user_id,
            "teiid_host": "localhost",
            "teiid_port": 9990,
            "db_type": "google-spreadsheet",
            "translator": "google-spreadsheet",
            "jdbc_url": "",
            "instance_url": "",
            "spreadsheet_id": spreadsheet_id,
            "table_name": sheet_name,
            "username": "",
            "password": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
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
        logger.info("Registering Google Sheets source in Teiid: %s", safe_payload)

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
                f"Teiid rejected Google Sheets source registration: "
                f"{response.status_code} {response.text}"
            )

        try:
            body = response.json()
        except Exception:
            body = {"raw": response.text}

        if isinstance(body, dict) and body.get("error"):
            raise TeiidRegistrationError(str(body["error"]))

        await pool_manager.evict_by_vdb_id(vdb_id)
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

        await pool_manager.evict_by_vdb_id(vdb_id)
        return body


def __getattr__(name: str):
    mapping = {
        "reconcile_database_sources": "reconcile",
    }
    mod = mapping.get(name)
    if mod is None:
        raise AttributeError(name)
    imported = __import__(
        f"{__name__}.{mod}", fromlist=[mod]
    )
    return getattr(imported, name)
