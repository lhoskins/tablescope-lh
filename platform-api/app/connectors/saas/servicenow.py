"""ServiceNow SaaS connector (Table API, HTTP Basic Auth).

Auth for the MVP is a ServiceNow instance URL plus a username/password:
``config["instance_url"]`` (e.g. ``https://mycompany.service-now.com``),
``config["username"]``, ``config["password"]``. Basic Auth against the Table
API is the simplest supported path and matches this connector framework's
existing MVP scope (see ``hubspot.py``); an OAuth client-credentials flow can
be layered in later without changing the connector interface.

MVP object set is fixed to the three ITSM tables most commonly used as data
sources: Incidents (``incident``), Requests (``sc_request``), and Change
Requests (``change_request``). Field metadata is discovered per table from
``sys_dictionary`` (itself just another Table API table, so no separate
describe endpoint or extra auth is needed). Records are paged through
``/api/now/table/{table}`` with ``sysparm_offset``/``sysparm_limit`` and
normalised into staging-column-keyed dicts; the full payload is preserved
under ``raw_json``. ``sysparm_display_value=false`` is used throughout so
every field (including references) comes back as a plain string/sys_id
rather than the ``{value, display_value}`` object form — consistent typing
without a relationship-resolution pass, matching the other MVP connectors.
"""

from __future__ import annotations

import datetime as dt
import logging
import re

import httpx

from app.connectors.base import (
    RAW_JSON_KEY,
    FieldInfo,
    ObjectInfo,
    SaasConnector,
    SaasConnectorError,
    StagingColumn,
)

logger = logging.getLogger(__name__)

_PAGE_SIZE = 200

# MVP object set. ``name`` is the ServiceNow table name used in the Table API.
_OBJECTS: list[ObjectInfo] = [
    ObjectInfo(name="incident", label="Incidents"),
    ObjectInfo(name="sc_request", label="Requests"),
    ObjectInfo(name="change_request", label="Change Requests"),
]
_OBJECT_NAMES = {o.name for o in _OBJECTS}

# ServiceNow "internal_type" (from sys_dictionary) -> Postgres column type.
# Restricted to the staging service's allowed set (saas_staging_service._ALLOWED_PG_TYPES).
_TYPE_MAP: dict[str, str] = {
    "integer": "integer",
    "decimal": "double precision",
    "currency": "double precision",
    "boolean": "boolean",
    "glide_date_time": "timestamptz",
    "glide_date": "date",
}


def _pg_type_for(internal_type: str) -> str:
    """Map a ServiceNow sys_dictionary internal_type to a Postgres column type."""
    return _TYPE_MAP.get((internal_type or "").lower(), "text")


def _safe_error(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code in (401, 403):
            return "ServiceNow rejected the credentials. Check the instance URL, username, and password."
        if code == 404:
            return "ServiceNow table not found. Check the instance URL."
        if code == 429:
            return "ServiceNow rate limit hit. Please retry in a moment."
        return f"ServiceNow API error (HTTP {code})."
    if isinstance(exc, httpx.RequestError):
        return "Could not reach ServiceNow. Check the instance URL and network connectivity."
    return "ServiceNow request failed."


class ServiceNowConnector(SaasConnector):
    connector_type = "servicenow"

    def _base_url(self, config: dict) -> str:
        instance_url = ((config or {}).get("instance_url") or "").strip().rstrip("/")
        if not instance_url:
            raise SaasConnectorError("Missing ServiceNow instance URL.")
        if not instance_url.startswith("http"):
            instance_url = f"https://{instance_url}"
        return instance_url

    def _auth(self, config: dict) -> tuple[str, str]:
        username = (config or {}).get("username", "")
        password = (config or {}).get("password", "")
        if not username or not password:
            raise SaasConnectorError("Missing ServiceNow username or password.")
        return username, password

    def _check_object(self, object_type: str) -> None:
        if object_type not in _OBJECT_NAMES:
            raise SaasConnectorError(
                f"Unsupported ServiceNow table '{object_type}'. "
                f"Supported: {', '.join(sorted(_OBJECT_NAMES))}."
            )

    async def test_connection(self, config: dict) -> dict:
        base_url = self._base_url(config)
        auth = self._auth(config)
        try:
            async with httpx.AsyncClient(timeout=20.0, auth=auth) as client:
                resp = await client.get(
                    f"{base_url}/api/now/table/sys_user",
                    params={"sysparm_limit": 1, "sysparm_fields": "sys_id"},
                )
                resp.raise_for_status()
        except Exception as exc:
            logger.warning("ServiceNow test_connection failed: %s", exc)
            raise SaasConnectorError(_safe_error(exc)) from exc
        return {"instance_url": base_url, "authenticated": True}

    async def list_objects(self, config: dict) -> list[ObjectInfo]:
        # Validate the credentials but return the fixed MVP object set.
        await self.test_connection(config)
        return list(_OBJECTS)

    async def list_fields(self, config: dict, object_type: str) -> list[FieldInfo]:
        self._check_object(object_type)
        base_url = self._base_url(config)
        auth = self._auth(config)
        try:
            async with httpx.AsyncClient(timeout=30.0, auth=auth) as client:
                resp = await client.get(
                    f"{base_url}/api/now/table/sys_dictionary",
                    params={
                        "sysparm_query": f"name={object_type}^internal_type!=collection^elementISNOTEMPTY",
                        "sysparm_fields": "element,column_label,internal_type.name",
                        "sysparm_display_value": "false",
                        "sysparm_limit": 500,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            logger.warning("ServiceNow list_fields failed: %s", exc)
            raise SaasConnectorError(_safe_error(exc)) from exc

        fields: list[FieldInfo] = []
        seen: set[str] = set()
        for row in data.get("result", []):
            name = row.get("element")
            if not name or name in seen:
                continue
            seen.add(name)
            raw_type = row.get("internal_type.name") or row.get("internal_type") or "string"
            if isinstance(raw_type, dict):
                internal_type: str = raw_type.get("value") or "string"
            else:
                internal_type = raw_type
            fields.append(
                FieldInfo(
                    name=name,
                    label=row.get("column_label") or name,
                    saas_type=internal_type,
                    pg_type=_pg_type_for(internal_type),
                )
            )
        fields.sort(key=lambda f: f.label.lower())
        return fields

    def id_column(self, object_type: str) -> str:
        return "sys_id"

    def base_columns(self, object_type: str) -> list[StagingColumn]:
        return [
            StagingColumn(name="sys_id", pg_type="text", primary_key=True),
            StagingColumn(name="number", pg_type="text"),
            StagingColumn(name="sys_created_on", pg_type="timestamptz"),
            StagingColumn(name="sys_updated_on", pg_type="timestamptz"),
        ]

    async def fetch_records(
        self,
        config: dict,
        object_type: str,
        selected_fields: list[str],
        *,
        limit: int | None = None,
    ) -> list[dict]:
        self._check_object(object_type)
        base_url = self._base_url(config)
        auth = self._auth(config)

        # sys_id/number/sys_created_on/sys_updated_on are always fetched as
        # base columns; avoid requesting them twice if also selected.
        base_field_names = ["sys_id", "number", "sys_created_on", "sys_updated_on"]
        fetch_fields = base_field_names + [
            f for f in selected_fields if f not in base_field_names
        ]

        records: list[dict] = []
        offset = 0
        try:
            async with httpx.AsyncClient(timeout=60.0, auth=auth) as client:
                while True:
                    page_limit = _PAGE_SIZE
                    if limit is not None:
                        remaining = limit - len(records)
                        if remaining <= 0:
                            break
                        page_limit = min(page_limit, remaining)
                    resp = await client.get(
                        f"{base_url}/api/now/table/{object_type}",
                        params={
                            "sysparm_fields": ",".join(fetch_fields),
                            "sysparm_display_value": "false",
                            "sysparm_exclude_reference_link": "true",
                            "sysparm_limit": page_limit,
                            "sysparm_offset": offset,
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    page = data.get("result", [])
                    for item in page:
                        records.append(self._normalize(item, selected_fields))
                    if len(page) < page_limit:
                        break
                    offset += page_limit
        except SaasConnectorError:
            raise
        except Exception as exc:
            logger.warning("ServiceNow fetch_records failed: %s", exc)
            raise SaasConnectorError(_safe_error(exc)) from exc
        return records

    _DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    _DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")

    def _coerce_value(self, value: object) -> object:
        if not isinstance(value, str):
            return value
        if self._DATETIME_RE.match(value):
            try:
                return dt.datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return value
        if self._DATE_RE.match(value):
            try:
                return dt.datetime.strptime(value, "%Y-%m-%d").date()
            except ValueError:
                return value
        return value

    def _normalize(self, item: dict, selected_fields: list[str]) -> dict:
        row: dict = {
            "sys_id": item.get("sys_id"),
            "number": item.get("number"),
            "sys_created_on": self._coerce_value(item.get("sys_created_on") or None),
            "sys_updated_on": self._coerce_value(item.get("sys_updated_on") or None),
            RAW_JSON_KEY: item,
        }
        for name in selected_fields:
            value = item.get(name)
            if value in (None, ""):
                row[name] = None
            else:
                row[name] = self._coerce_value(value)
        return row


__all__ = ["ServiceNowConnector"]
