"""Tests for the Google Drive/Sheets REST client (app/services/google_drive/client.py)."""

from __future__ import annotations

import httpx
import pytest

from app.services.google_drive.client import GoogleDriveClient, GoogleDriveError

pytestmark = pytest.mark.anyio


async def test_list_supported_files_filters_and_tags_source_type(monkeypatch):
    captured: dict = {}

    async def fake_get(self, url, **kwargs):
        captured["url"] = url
        captured["params"] = kwargs.get("params")
        return httpx.Response(
            200,
            json={
                "files": [
                    {
                        "id": "f1",
                        "name": "Pricing",
                        "mimeType": "application/vnd.google-apps.spreadsheet",
                    },
                ],
                "nextPageToken": "np",
            },
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    client = GoogleDriveClient("token-abc")
    result = await client.list_supported_files()

    assert "drive/v3/files" in captured["url"]
    assert captured["params"]["q"]
    assert result["files"][0]["sourceType"] == "google_sheet"
    assert result["nextPageToken"] == "np"


async def test_list_sheet_tabs_returns_stable_ids_and_grid_dims(monkeypatch):
    async def fake_get(self, url, **kwargs):
        return httpx.Response(
            200,
            json={
                "sheets": [
                    {
                        "properties": {
                            "sheetId": 111,
                            "title": "Table 1",
                            "gridProperties": {"rowCount": 20, "columnCount": 6},
                        }
                    },
                    {
                        "properties": {
                            "sheetId": 222,
                            "title": "Table 2",
                            "gridProperties": {"rowCount": 10, "columnCount": 6},
                        }
                    },
                ]
            },
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    client = GoogleDriveClient("token-abc")
    tabs = await client.list_sheet_tabs("spreadsheet-1")

    assert len(tabs) == 2
    assert tabs[0] == {"sheetId": 111, "title": "Table 1", "rowCount": 20, "columnCount": 6}


async def test_get_range_values_requests_unformatted_values(monkeypatch):
    captured: dict = {}

    async def fake_get(self, url, **kwargs):
        captured["url"] = url
        captured["params"] = kwargs.get("params")
        return httpx.Response(
            200,
            json={"values": [["Hours", "Unit Price"], ["10", "1200"]]},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    client = GoogleDriveClient("token-abc")
    values = await client.get_range_values("spreadsheet-1", "A1:F10")

    assert captured["params"]["valueRenderOption"] == "UNFORMATTED_VALUE"
    assert values == [["Hours", "Unit Price"], ["10", "1200"]]


async def test_batch_get_range_values_maps_by_requested_range(monkeypatch):
    async def fake_get(self, url, **kwargs):
        return httpx.Response(
            200,
            json={
                "valueRanges": [
                    {"range": "Sheet1!A1:F10", "values": [["a"]]},
                    {"range": "Sheet1!J1:O10", "values": [["b"]]},
                ]
            },
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    client = GoogleDriveClient("token-abc")
    result = await client.batch_get_range_values(
        "spreadsheet-1", ["Sheet1!A1:F10", "Sheet1!J1:O10"]
    )

    assert result["Sheet1!A1:F10"] == [["a"]]
    assert result["Sheet1!J1:O10"] == [["b"]]


async def test_batch_get_range_values_returns_empty_for_no_ranges():
    client = GoogleDriveClient("token-abc")
    assert await client.batch_get_range_values("spreadsheet-1", []) == {}


async def test_401_raises_expired_token_error(monkeypatch):
    async def fake_get(self, url, **kwargs):
        return httpx.Response(401, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    client = GoogleDriveClient("token-abc")
    with pytest.raises(GoogleDriveError, match="expired"):
        await client.list_supported_files()


async def test_403_raises_access_denied_error(monkeypatch):
    async def fake_get(self, url, **kwargs):
        return httpx.Response(403, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    client = GoogleDriveClient("token-abc")
    with pytest.raises(GoogleDriveError, match="denied"):
        await client.get_range_values("spreadsheet-1", "A1:F10")


async def test_request_error_is_wrapped(monkeypatch):
    async def fake_get(self, url, **kwargs):
        raise httpx.ConnectError("dns failure", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    client = GoogleDriveClient("token-abc")
    with pytest.raises(GoogleDriveError, match="Failed to contact"):
        await client.list_supported_files()
