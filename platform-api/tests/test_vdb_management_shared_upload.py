"""Tests for VDBManagementService's project-scoped shared VDB provisioning
and the new upload_shared_file method (tasks #16).

Live finding this fixes: create_shared_vdb/redeployVDB are template-based
-- they rewrite path prefixes but never read a file's actual content, so a
"shared" VDB built only through them never gets real views for the files
copied into it. upload_shared_file instead calls the servlet's /upload
endpoint -- the same real view-building mechanism already proven for
private uploads (finalize_tabular.py) -- with vdb_type=shared and a
project_id so it lands in that project's own shared folder.

Run from ``platform-api``: ``pytest -q tests/test_vdb_management_shared_upload.py``.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.services.vdb_management import VDBManagementService, VDBProvisioningError

pytestmark = pytest.mark.anyio


def _service(handler) -> VDBManagementService:
    client = httpx.AsyncClient(
        base_url="http://fake-servlet", transport=httpx.MockTransport(handler)
    )
    return VDBManagementService(client=client, pg_host="localhost", pg_port=1)


async def test_create_shared_vdb_includes_project_id_in_payload():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"status": "ok"})

    svc = _service(handler)
    try:
        await svc.create_shared_vdb(org_id=42, project_id=7)
    finally:
        await svc.aclose()

    assert seen["body"]["org_id"] == 42
    assert seen["body"]["project_id"] == 7
    assert seen["body"]["vdb_type"] == "shared"


async def test_create_shared_vdb_omits_project_id_when_not_given():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"status": "ok"})

    svc = _service(handler)
    try:
        await svc.create_shared_vdb(org_id=42)
    finally:
        await svc.aclose()

    assert "project_id" not in seen["body"]


async def test_upload_shared_file_posts_multipart_with_shared_vdb_type():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["content_type"] = request.headers.get("content-type", "")
        seen["body"] = request.content
        return httpx.Response(200, json={"status": "ok", "view": "sales_csv"})

    svc = _service(handler)
    try:
        result = await svc.upload_shared_file(
            org_id=42, project_id=7, filename="sales.csv", content=b"a,b\n1,2\n"
        )
    finally:
        await svc.aclose()

    assert seen["url"].endswith("/TeiidExcelImporterTest/upload")
    assert seen["content_type"].startswith("multipart/form-data")
    body = seen["body"]
    assert b'name="org_id"' in body and b"42" in body
    assert b'name="project_id"' in body and b"7" in body
    assert b'name="vdb_type"' in body and b"shared" in body
    assert b'name="replace"' in body and b"true" in body
    assert b'filename="sales.csv"' in body
    assert result == {"status": "ok", "view": "sales_csv"}


async def test_upload_shared_file_raises_on_servlet_error_status():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    svc = _service(handler)
    try:
        with pytest.raises(VDBProvisioningError):
            await svc.upload_shared_file(
                org_id=42, project_id=7, filename="sales.csv", content=b"x"
            )
    finally:
        await svc.aclose()


async def test_upload_shared_file_raises_on_error_in_json_body():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": "could not parse file"})

    svc = _service(handler)
    try:
        with pytest.raises(VDBProvisioningError, match="could not parse file"):
            await svc.upload_shared_file(
                org_id=42, project_id=7, filename="sales.csv", content=b"x"
            )
    finally:
        await svc.aclose()


async def test_upload_shared_file_raises_when_servlet_unreachable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    svc = _service(handler)
    try:
        with pytest.raises(VDBProvisioningError):
            await svc.upload_shared_file(
                org_id=42, project_id=7, filename="sales.csv", content=b"x"
            )
    finally:
        await svc.aclose()
