"""Read-only Google Drive/Sheets REST client.

Uses the plain REST APIs directly over httpx (``drive/v3``, ``sheets/v4``)
rather than the heavy ``google-api-python-client`` SDK -- this matches how
every other external integration in this codebase talks to its provider
(``llm_client.py``, the QuickBooks/HubSpot connectors) and keeps the calls
unit-testable by mocking httpx the same way ``test_llm_client_openai_target``
already does, with no SDK/credentials object to fake.

Scope of this module: file discovery, tab enumeration, and range preview
only (Workstreams B/C of the implementation plan). It does not create Teiid
data sources or persist anything -- callers do that.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_DRIVE_API = "https://www.googleapis.com/drive/v3"
_SHEETS_API = "https://sheets.googleapis.com/v4"

#: MIME types the connector supports, per the implementation plan's source
#: matrix (native Sheets, Excel, CSV). Anything else is filtered out of file
#: listings so users are never offered a file type the connector can't read.
SUPPORTED_MIME_TYPES = {
    "application/vnd.google-apps.spreadsheet": "google_sheet",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.ms-excel": "xls",
    "text/csv": "csv",
}

_FILE_FIELDS = "id,name,mimeType,owners,modifiedTime,shared,driveId"


class GoogleDriveError(Exception):
    """Raised when the Drive/Sheets API rejects or fails a request.

    ``requires_reauth`` marks a 401 -- the access token is expired/invalid
    even though it was refreshed moments ago, meaning the underlying grant
    itself is no longer valid (e.g. the user revoked Tablescope's access in
    their Google Account) -- so a caller can prompt reconnection instead of
    surfacing a dead-end error.
    """

    def __init__(self, message: str, *, requires_reauth: bool = False) -> None:
        super().__init__(message)
        self.requires_reauth = requires_reauth


class GoogleDriveClient:
    """Thin async wrapper over the Drive v3 and Sheets v4 REST APIs.

    One instance per request; ``access_token`` is a short-lived OAuth bearer
    token the caller has already refreshed if needed (see ``oauth.py``).
    """

    def __init__(self, access_token: str, *, timeout: float = 30.0) -> None:
        self._access_token = access_token
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._access_token}"}

    async def _get(self, url: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            try:
                resp = await client.get(url, headers=self._headers(), params=params)
            except httpx.RequestError as exc:
                raise GoogleDriveError(f"Failed to contact Google API: {exc}") from exc
        if resp.status_code == 401:
            raise GoogleDriveError(
                "Google access token is expired or invalid.", requires_reauth=True
            )
        if resp.status_code == 403:
            raise GoogleDriveError("Access to this Google file was denied.")
        if resp.status_code == 404:
            raise GoogleDriveError("Google file or range not found.")
        if resp.status_code >= 400:
            logger.warning("Google API request to %s failed: %s", url, resp.text[:500])
            raise GoogleDriveError(f"Google API request failed ({resp.status_code}).")
        return resp.json()

    async def list_supported_files(
        self, *, page_size: int = 100, page_token: str | None = None
    ) -> dict[str, Any]:
        """List Drive files the connected account can access, filtered to
        supported MIME types (native Sheets, Excel, CSV)."""
        mime_query = " or ".join(f"mimeType='{m}'" for m in SUPPORTED_MIME_TYPES)
        params: dict[str, Any] = {
            "q": f"({mime_query}) and trashed=false",
            "fields": f"nextPageToken,files({_FILE_FIELDS})",
            "pageSize": page_size,
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
        if page_token:
            params["pageToken"] = page_token
        data = await self._get(f"{_DRIVE_API}/files", params=params)
        files = [
            {
                **f,
                "sourceType": SUPPORTED_MIME_TYPES.get(f.get("mimeType", "")),
            }
            for f in data.get("files", [])
        ]
        return {"files": files, "nextPageToken": data.get("nextPageToken")}

    async def get_file_metadata(self, file_id: str) -> dict[str, Any]:
        return await self._get(
            f"{_DRIVE_API}/files/{file_id}",
            params={"fields": _FILE_FIELDS, "supportsAllDrives": "true"},
        )

    async def list_sheet_tabs(self, spreadsheet_id: str) -> list[dict[str, Any]]:
        """List tabs (sheets) in a native Google Sheets spreadsheet, with
        stable sheetId, title, and used-range grid dimensions."""
        data = await self._get(
            f"{_SHEETS_API}/spreadsheets/{spreadsheet_id}",
            params={"fields": "sheets.properties"},
        )
        tabs = []
        for sheet in data.get("sheets", []):
            props = sheet.get("properties", {})
            grid = props.get("gridProperties", {})
            tabs.append(
                {
                    "sheetId": props.get("sheetId"),
                    "title": props.get("title"),
                    "rowCount": grid.get("rowCount"),
                    "columnCount": grid.get("columnCount"),
                }
            )
        return tabs

    async def get_range_values(
        self, spreadsheet_id: str, range_a1: str
    ) -> list[list[Any]]:
        """Fetch a range's current EFFECTIVE values (not display strings).

        Default ``valueRenderOption=FORMATTED_VALUE`` would return the
        "#####" Excel/Sheets shows for a too-narrow column; ``UNFORMATTED_VALUE``
        returns the real underlying number/date serial regardless of display
        width, matching the plan's "read the underlying numeric values" rule
        (section 6.3, 10).
        """
        data = await self._get(
            f"{_SHEETS_API}/spreadsheets/{spreadsheet_id}/values/{range_a1}",
            params={
                "valueRenderOption": "UNFORMATTED_VALUE",
                "dateTimeRenderOption": "FORMATTED_STRING",
            },
        )
        return data.get("values", [])

    async def batch_get_range_values(
        self, spreadsheet_id: str, ranges: list[str]
    ) -> dict[str, list[list[Any]]]:
        """Fetch several ranges from the same spreadsheet in one call (plan
        section 7.3: "use batchGet for several ranges on the same live file
        to reduce provider calls")."""
        if not ranges:
            return {}
        data = await self._get(
            f"{_SHEETS_API}/spreadsheets/{spreadsheet_id}/values:batchGet",
            params={
                "ranges": ranges,
                "valueRenderOption": "UNFORMATTED_VALUE",
                "dateTimeRenderOption": "FORMATTED_STRING",
            },
        )
        out: dict[str, list[list[Any]]] = {}
        for vr in data.get("valueRanges", []):
            requested_range = vr.get("range", "")
            out[requested_range] = vr.get("values", [])
        return out
