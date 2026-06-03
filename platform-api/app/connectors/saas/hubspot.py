"""HubSpot SaaS connector (CRM v3 API, Private App token).

Auth for MVP is a HubSpot Private App access token (``config["access_token"]``).
We support the core CRM objects contacts/companies/deals; HubSpot returns rich
property metadata per object which drives field selection and typing.

Records are paged through ``/crm/v3/objects/{object}`` and normalised into
staging-column-keyed dicts; the full payload is preserved under ``raw_json``.
"""

from __future__ import annotations

import logging

import httpx

from app.connectors.base import (
    RAW_JSON_KEY,
    FieldInfo,
    ObjectInfo,
    PreviewResult,
    SaasConnector,
    SaasConnectorError,
    StagingColumn,
)

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.hubapi.com"
_PAGE_SIZE = 100

# MVP object set.  Labels are user-facing.
_OBJECTS: list[ObjectInfo] = [
    ObjectInfo(name="contacts", label="Contacts"),
    ObjectInfo(name="companies", label="Companies"),
    ObjectInfo(name="deals", label="Deals"),
]
_OBJECT_NAMES = {o.name for o in _OBJECTS}


def _pg_type_for(hubspot_type: str) -> str:
    """Map a HubSpot property type to a Postgres column type."""
    t = (hubspot_type or "").lower()
    if t == "number":
        return "double precision"
    if t == "bool":
        return "boolean"
    if t == "datetime":
        return "timestamptz"
    if t == "date":
        return "date"
    # string, enumeration, phone_number, etc.
    return "text"


def _safe_error(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code in (401, 403):
            return "HubSpot rejected the token. Check the Private App token and its scopes."
        if code == 429:
            return "HubSpot rate limit hit. Please retry in a moment."
        return f"HubSpot API error (HTTP {code})."
    if isinstance(exc, httpx.RequestError):
        return "Could not reach HubSpot. Check network connectivity."
    return "HubSpot request failed."


class HubSpotConnector(SaasConnector):
    connector_type = "hubspot"

    def _headers(self, config: dict) -> dict:
        token = (config or {}).get("access_token", "")
        if not token:
            raise SaasConnectorError("Missing HubSpot access token.")
        return {"Authorization": f"Bearer {token}"}

    def _check_object(self, object_type: str) -> None:
        if object_type not in _OBJECT_NAMES:
            raise SaasConnectorError(
                f"Unsupported HubSpot object '{object_type}'. "
                f"Supported: {', '.join(sorted(_OBJECT_NAMES))}."
            )

    async def test_connection(self, config: dict) -> dict:
        headers = self._headers(config)
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(
                    f"{_BASE_URL}/account-info/v3/details", headers=headers
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            logger.warning("HubSpot test_connection failed: %s", exc)
            raise SaasConnectorError(_safe_error(exc)) from exc
        return {
            "portal_id": data.get("portalId"),
            "time_zone": data.get("timeZone"),
            "account_type": data.get("accountType"),
        }

    async def list_objects(self, config: dict) -> list[ObjectInfo]:
        # Validate the token but return the fixed MVP object set.
        await self.test_connection(config)
        return list(_OBJECTS)

    async def list_fields(self, config: dict, object_type: str) -> list[FieldInfo]:
        self._check_object(object_type)
        headers = self._headers(config)
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    f"{_BASE_URL}/crm/v3/properties/{object_type}", headers=headers
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            logger.warning("HubSpot list_fields failed: %s", exc)
            raise SaasConnectorError(_safe_error(exc)) from exc

        fields: list[FieldInfo] = []
        for prop in data.get("results", []):
            name = prop.get("name")
            if not name:
                continue
            saas_type = prop.get("type", "string")
            fields.append(
                FieldInfo(
                    name=name,
                    label=prop.get("label") or name,
                    saas_type=saas_type,
                    pg_type=_pg_type_for(saas_type),
                )
            )
        fields.sort(key=lambda f: f.label.lower())
        return fields

    def id_column(self, object_type: str) -> str:
        return "hubspot_id"

    def base_columns(self, object_type: str) -> list[StagingColumn]:
        return [
            StagingColumn(name="hubspot_id", pg_type="text", primary_key=True),
            StagingColumn(name="archived", pg_type="boolean"),
            StagingColumn(name="created_at", pg_type="timestamptz"),
            StagingColumn(name="updated_at", pg_type="timestamptz"),
        ]

    async def _field_types(
        self, config: dict, object_type: str, selected_fields: list[str]
    ) -> dict[str, str]:
        fields = await self.list_fields(config, object_type)
        by_name = {f.name: f for f in fields}
        return {
            name: by_name[name].saas_type
            for name in selected_fields
            if name in by_name
        }

    async def fetch_records(
        self,
        config: dict,
        object_type: str,
        selected_fields: list[str],
        *,
        limit: int | None = None,
    ) -> list[dict]:
        self._check_object(object_type)
        headers = self._headers(config)
        type_map = await self._field_types(config, object_type, selected_fields)

        records: list[dict] = []
        after: str | None = None
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                while True:
                    params: dict = {
                        "limit": _PAGE_SIZE,
                        "archived": "false",
                    }
                    if selected_fields:
                        params["properties"] = ",".join(selected_fields)
                    if after:
                        params["after"] = after
                    resp = await client.get(
                        f"{_BASE_URL}/crm/v3/objects/{object_type}",
                        headers=headers,
                        params=params,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    for item in data.get("results", []):
                        records.append(
                            self._normalize(item, selected_fields, type_map)
                        )
                        if limit is not None and len(records) >= limit:
                            return records
                    after = (
                        data.get("paging", {}).get("next", {}).get("after")
                        if data.get("paging")
                        else None
                    )
                    if not after:
                        break
        except SaasConnectorError:
            raise
        except Exception as exc:
            logger.warning("HubSpot fetch_records failed: %s", exc)
            raise SaasConnectorError(_safe_error(exc)) from exc
        return records

    def _normalize(
        self, item: dict, selected_fields: list[str], type_map: dict[str, str]
    ) -> dict:
        props = item.get("properties", {}) or {}
        row: dict = {
            "hubspot_id": item.get("id"),
            "archived": bool(item.get("archived", False)),
            "created_at": item.get("createdAt"),
            "updated_at": item.get("updatedAt"),
            RAW_JSON_KEY: item,
        }
        for name in selected_fields:
            row[name] = _coerce(props.get(name), type_map.get(name, "string"))
        return row


def _coerce(value, hubspot_type: str):
    """Best-effort coercion of a HubSpot string value to a python type."""
    if value is None or value == "":
        return None
    t = (hubspot_type or "").lower()
    try:
        if t == "number":
            return float(value)
        if t == "bool":
            return str(value).lower() in ("true", "1", "yes")
    except (TypeError, ValueError):
        return None
    # datetime/date/string are stored as-is (ISO strings parse into pg types).
    return value


# Re-export for type-checkers / callers that import the preview type here.
__all__ = ["HubSpotConnector", "PreviewResult"]
