"""QuickBooks Online SaaS connector (Accounting API, OAuth2 bearer token).

Auth for the MVP is an Intuit OAuth2 access token plus the company (realm) id:
``config["access_token"]`` and ``config["realm_id"]`` (``config["environment"]``
selects the sandbox vs production host, default production).  The structure
leaves room for a future refresh-token flow (``client_id`` / ``client_secret`` /
``refresh_token``) without changing the connector interface.

QuickBooks has no per-object describe endpoint, so fields are discovered by
sampling records with the SQL-like ``query`` API and inferring a Postgres type
per top-level key.  Records are paged with ``STARTPOSITION`` / ``MAXRESULTS`` and
normalised into staging-column-keyed dicts; the full payload is preserved under
``raw_json``.
"""

from __future__ import annotations

import json
import logging

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

_API_MINOR_VERSION = "65"
_PAGE_SIZE = 1000  # QuickBooks query MAXRESULTS hard cap.
_SAMPLE_SIZE = 25  # records sampled to infer fields.

_PRODUCTION_BASE = "https://quickbooks.api.intuit.com"
_SANDBOX_BASE = "https://sandbox-quickbooks.api.intuit.com"

# MVP object set.  ``name`` is the QuickBooks entity used in the query API.
_OBJECTS: list[ObjectInfo] = [
    ObjectInfo(name="Customer", label="Customers"),
    ObjectInfo(name="Invoice", label="Invoices"),
    ObjectInfo(name="Item", label="Items"),
    ObjectInfo(name="Vendor", label="Vendors"),
    ObjectInfo(name="Account", label="Accounts"),
    ObjectInfo(name="Payment", label="Payments"),
    ObjectInfo(name="Bill", label="Bills"),
]
_OBJECT_NAMES = {o.name for o in _OBJECTS}

# Top-level keys mapped to fixed base columns (or otherwise not user-selectable).
_RESERVED_KEYS = {"Id", "SyncToken", "MetaData", "domain", "sparse"}


def _pg_type_for_value(value: object) -> str:
    """Infer a Postgres staging type from a sampled QuickBooks value."""
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int | float)):
        return "double precision"
    # Nested objects/arrays (addresses, line items, refs) are stored as JSON text.
    if isinstance(value, (dict | list)):
        return "text"
    return "text"


def _coerce(value: object, pg_type: str) -> object:
    if value is None or value == "":
        return None
    try:
        if pg_type == "boolean":
            if isinstance(value, bool):
                return value
            return str(value).lower() in ("true", "1", "yes")
        if pg_type == "double precision":
            return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if isinstance(value, (dict | list)):
        return json.dumps(value)
    return str(value)


def _safe_error(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code == 401:
            return (
                "QuickBooks rejected the access token (it may have expired). "
                "Provide a fresh OAuth2 access token."
            )
        if code == 403:
            return "QuickBooks denied access. Check the app scopes and company access."
        if code == 429:
            return "QuickBooks rate limit hit. Please retry in a moment."
        return f"QuickBooks API error (HTTP {code})."
    if isinstance(exc, httpx.RequestError):
        return "Could not reach QuickBooks. Check network connectivity."
    return "QuickBooks request failed."


class QuickBooksConnector(SaasConnector):
    connector_type = "quickbooks"

    def _base_url(self, config: dict) -> str:
        env = str((config or {}).get("environment", "production")).lower()
        return _SANDBOX_BASE if env == "sandbox" else _PRODUCTION_BASE

    def _realm_id(self, config: dict) -> str:
        realm = str((config or {}).get("realm_id", "")).strip()
        if not realm:
            raise SaasConnectorError("Missing QuickBooks company (realm) id.")
        return realm

    def _headers(self, config: dict) -> dict:
        token = (config or {}).get("access_token", "")
        if not token:
            raise SaasConnectorError("Missing QuickBooks access token.")
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

    def _check_object(self, object_type: str) -> None:
        if object_type not in _OBJECT_NAMES:
            raise SaasConnectorError(
                f"Unsupported QuickBooks object '{object_type}'. "
                f"Supported: {', '.join(sorted(_OBJECT_NAMES))}."
            )

    async def _query(self, config: dict, soql: str) -> dict:
        base = self._base_url(config)
        realm = self._realm_id(config)
        headers = self._headers(config)
        url = f"{base}/v3/company/{realm}/query"
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.get(
                    url,
                    headers=headers,
                    params={"query": soql, "minorversion": _API_MINOR_VERSION},
                )
                resp.raise_for_status()
                return resp.json()
        except SaasConnectorError:
            raise
        except Exception as exc:
            logger.warning("QuickBooks query failed: %s", exc)
            raise SaasConnectorError(_safe_error(exc)) from exc

    async def test_connection(self, config: dict) -> dict:
        base = self._base_url(config)
        realm = self._realm_id(config)
        headers = self._headers(config)
        url = f"{base}/v3/company/{realm}/companyinfo/{realm}"
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(
                    url, headers=headers, params={"minorversion": _API_MINOR_VERSION}
                )
                resp.raise_for_status()
                data = resp.json()
        except SaasConnectorError:
            raise
        except Exception as exc:
            logger.warning("QuickBooks test_connection failed: %s", exc)
            raise SaasConnectorError(_safe_error(exc)) from exc
        info = data.get("CompanyInfo", {}) or {}
        return {
            "company_name": info.get("CompanyName"),
            "realm_id": realm,
            "environment": str((config or {}).get("environment", "production")),
        }

    async def list_objects(self, config: dict) -> list[ObjectInfo]:
        await self.test_connection(config)
        return list(_OBJECTS)

    async def _sample_records(self, config: dict, object_type: str) -> list[dict]:
        data = await self._query(
            config, f"SELECT * FROM {object_type} MAXRESULTS {_SAMPLE_SIZE}"
        )
        qr = data.get("QueryResponse", {}) or {}
        return qr.get(object_type, []) or []

    async def list_fields(self, config: dict, object_type: str) -> list[FieldInfo]:
        self._check_object(object_type)
        records = await self._sample_records(config, object_type)

        # Infer a type per key from the first non-null sampled value.
        types: dict[str, str] = {}
        for rec in records:
            if not isinstance(rec, dict):
                continue
            for key, value in rec.items():
                if key in _RESERVED_KEYS:
                    continue
                if value is None:
                    types.setdefault(key, "text")
                    continue
                types[key] = _pg_type_for_value(value)

        fields = [
            FieldInfo(name=k, label=k, saas_type="json", pg_type=v)
            for k, v in types.items()
        ]
        fields.sort(key=lambda f: f.label.lower())
        return fields

    def id_column(self, object_type: str) -> str:
        return "quickbooks_id"

    def base_columns(self, object_type: str) -> list[StagingColumn]:
        return [
            StagingColumn(name="quickbooks_id", pg_type="text", primary_key=True),
            StagingColumn(name="sync_token", pg_type="text"),
            StagingColumn(name="created_time", pg_type="timestamptz"),
            StagingColumn(name="updated_time", pg_type="timestamptz"),
        ]

    async def _field_types(
        self, config: dict, object_type: str, selected_fields: list[str]
    ) -> dict[str, str]:
        fields = await self.list_fields(config, object_type)
        by_name = {f.name: f.pg_type for f in fields}
        # Default unknown selections to text so coercion never crashes.
        return {name: by_name.get(name, "text") for name in selected_fields}

    async def fetch_records(
        self,
        config: dict,
        object_type: str,
        selected_fields: list[str],
        *,
        limit: int | None = None,
    ) -> list[dict]:
        self._check_object(object_type)
        type_map = await self._field_types(config, object_type, selected_fields)

        records: list[dict] = []
        start = 1
        while True:
            page = min(_PAGE_SIZE, limit - len(records)) if limit else _PAGE_SIZE
            soql = (
                f"SELECT * FROM {object_type} "
                f"STARTPOSITION {start} MAXRESULTS {page}"
            )
            data = await self._query(config, soql)
            qr = data.get("QueryResponse", {}) or {}
            items = qr.get(object_type, []) or []
            if not items:
                break
            for item in items:
                records.append(self._normalize(item, selected_fields, type_map))
                if limit is not None and len(records) >= limit:
                    return records
            if len(items) < page:
                break
            start += len(items)
        return records

    def _normalize(
        self, item: dict, selected_fields: list[str], type_map: dict[str, str]
    ) -> dict:
        meta = item.get("MetaData", {}) or {}
        row: dict = {
            "quickbooks_id": item.get("Id"),
            "sync_token": item.get("SyncToken"),
            "created_time": meta.get("CreateTime"),
            "updated_time": meta.get("LastUpdatedTime"),
            RAW_JSON_KEY: item,
        }
        for name in selected_fields:
            row[name] = _coerce(item.get(name), type_map.get(name, "text"))
        return row
