"""Salesforce SaaS connector (REST + SOQL).

Auth for MVP is the OAuth 2.0 username-password flow (easy for testing/internal
use).  ``config`` carries ``client_id``, ``client_secret``, ``username``,
``password`` and ``security_token`` (appended to the password), plus an optional
``login_url`` (defaults to the production login host; use the test host for
sandboxes).  A token is obtained per operation and the returned ``instance_url``
is used for subsequent API calls.

Objects are described via the sObject describe API and records fetched with SOQL
(paged through ``nextRecordsUrl``).  Long-term this should move to OAuth/JWT and
the Bulk API, but the connector interface stays the same.
"""

from __future__ import annotations

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

_API_VERSION = "v59.0"
_DEFAULT_LOGIN_URL = "https://login.salesforce.com"

# MVP object set.
_OBJECTS: list[ObjectInfo] = [
    ObjectInfo(name="Account", label="Accounts"),
    ObjectInfo(name="Contact", label="Contacts"),
    ObjectInfo(name="Opportunity", label="Opportunities"),
    ObjectInfo(name="Lead", label="Leads"),
]
_OBJECT_NAMES = {o.name for o in _OBJECTS}

# Standard system fields synced into base columns for every object.
_SYSTEM_FIELDS = [
    "Id",
    "IsDeleted",
    "CreatedDate",
    "LastModifiedDate",
    "SystemModstamp",
]


def _pg_type_for(sf_type: str) -> str:
    t = (sf_type or "").lower()
    if t == "boolean":
        return "boolean"
    if t == "int":
        return "integer"
    if t in ("double", "currency", "percent"):
        return "double precision"
    if t == "date":
        return "date"
    if t == "datetime":
        return "timestamptz"
    # string, textarea, picklist, reference, id, email, phone, url, ...
    return "text"


def _safe_error(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code in (400, 401):
            return (
                "Salesforce authentication failed. Check client id/secret, "
                "username, password and security token."
            )
        if code == 403:
            return "Salesforce denied access. Check the Connected App permissions."
        return f"Salesforce API error (HTTP {code})."
    if isinstance(exc, httpx.RequestError):
        return "Could not reach Salesforce. Check network connectivity."
    return "Salesforce request failed."


class SalesforceConnector(SaasConnector):
    connector_type = "salesforce"

    async def _authenticate(self, config: dict) -> tuple[str, str]:
        """Return (access_token, instance_url) via username-password OAuth."""
        cfg = config or {}
        required = ("client_id", "client_secret", "username", "password")
        missing = [k for k in required if not cfg.get(k)]
        if missing:
            raise SaasConnectorError(
                f"Missing Salesforce credentials: {', '.join(missing)}."
            )
        login_url = (cfg.get("login_url") or _DEFAULT_LOGIN_URL).rstrip("/")
        password = cfg["password"] + (cfg.get("security_token") or "")
        form = {
            "grant_type": "password",
            "client_id": cfg["client_id"],
            "client_secret": cfg["client_secret"],
            "username": cfg["username"],
            "password": password,
        }
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{login_url}/services/oauth2/token", data=form
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            logger.warning("Salesforce auth failed: %s", exc)
            raise SaasConnectorError(_safe_error(exc)) from exc
        token = data.get("access_token")
        instance_url = data.get("instance_url")
        if not token or not instance_url:
            raise SaasConnectorError("Salesforce did not return an access token.")
        return token, instance_url

    def _check_object(self, object_type: str) -> None:
        if object_type not in _OBJECT_NAMES:
            raise SaasConnectorError(
                f"Unsupported Salesforce object '{object_type}'. "
                f"Supported: {', '.join(sorted(_OBJECT_NAMES))}."
            )

    async def test_connection(self, config: dict) -> dict:
        _token, instance_url = await self._authenticate(config)
        return {"instance_url": instance_url, "authenticated": True}

    async def list_objects(self, config: dict) -> list[ObjectInfo]:
        await self._authenticate(config)
        return list(_OBJECTS)

    async def list_fields(self, config: dict, object_type: str) -> list[FieldInfo]:
        self._check_object(object_type)
        token, instance_url = await self._authenticate(config)
        url = (
            f"{instance_url}/services/data/{_API_VERSION}"
            f"/sobjects/{object_type}/describe"
        )
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    url, headers={"Authorization": f"Bearer {token}"}
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            logger.warning("Salesforce describe failed: %s", exc)
            raise SaasConnectorError(_safe_error(exc)) from exc

        fields: list[FieldInfo] = []
        for f in data.get("fields", []):
            name = f.get("name")
            if not name:
                continue
            saas_type = f.get("type", "string")
            fields.append(
                FieldInfo(
                    name=name,
                    label=f.get("label") or name,
                    saas_type=saas_type,
                    pg_type=_pg_type_for(saas_type),
                )
            )
        fields.sort(key=lambda f: f.label.lower())
        return fields

    def id_column(self, object_type: str) -> str:
        return "salesforce_id"

    def base_columns(self, object_type: str) -> list[StagingColumn]:
        return [
            StagingColumn(name="salesforce_id", pg_type="text", primary_key=True),
            StagingColumn(name="is_deleted", pg_type="boolean"),
            StagingColumn(name="created_date", pg_type="timestamptz"),
            StagingColumn(name="last_modified_date", pg_type="timestamptz"),
            StagingColumn(name="system_modstamp", pg_type="timestamptz"),
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
        token, instance_url = await self._authenticate(config)

        # SOQL excludes system fields we map to fixed base columns to avoid
        # duplicate selection; user fields are appended.
        field_list = list(
            dict.fromkeys([*_SYSTEM_FIELDS, *selected_fields])
        )
        soql = f"SELECT {', '.join(field_list)} FROM {object_type}"
        if limit is not None:
            soql += f" LIMIT {int(limit)}"

        records: list[dict] = []
        headers = {"Authorization": f"Bearer {token}"}
        next_url: str | None = (
            f"{instance_url}/services/data/{_API_VERSION}/query"
        )
        params: dict | None = {"q": soql}
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                while next_url:
                    resp = await client.get(next_url, headers=headers, params=params)
                    resp.raise_for_status()
                    data = resp.json()
                    for item in data.get("records", []):
                        records.append(self._normalize(item, selected_fields))
                        if limit is not None and len(records) >= limit:
                            return records
                    if data.get("done", True):
                        break
                    next_rel = data.get("nextRecordsUrl")
                    next_url = f"{instance_url}{next_rel}" if next_rel else None
                    params = None  # nextRecordsUrl is fully-formed
        except SaasConnectorError:
            raise
        except Exception as exc:
            logger.warning("Salesforce fetch_records failed: %s", exc)
            raise SaasConnectorError(_safe_error(exc)) from exc
        return records

    def _normalize(self, item: dict, selected_fields: list[str]) -> dict:
        row: dict = {
            "salesforce_id": item.get("Id"),
            "is_deleted": bool(item.get("IsDeleted", False)),
            "created_date": item.get("CreatedDate"),
            "last_modified_date": item.get("LastModifiedDate"),
            "system_modstamp": item.get("SystemModstamp"),
            RAW_JSON_KEY: item,
        }
        for name in selected_fields:
            row[name] = item.get(name)
        return row


__all__ = ["SalesforceConnector"]
