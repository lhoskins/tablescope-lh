"""Issue 4 / MySQL no-password datasource creation.

Covers the connector engine URL, the blank-password normalizer, and the
Teiid/WildFly registration payload (which must never carry an empty password —
WildFly rejects ``password=""`` with WFLYCTL0113).
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.services.database_introspection_service import (
    ConnectionParams,
    _build_engine,
    normalize_db_password,
)
from app.services.teiid_registration_service import TeiidRegistrationService


def _params(password: str) -> ConnectionParams:
    return ConnectionParams(
        db_type="mysql",
        host="db.example.com",
        port=3306,
        database_name="analytics",
        username="root",
        password=password,
    )


def test_mysql_engine_builds_with_empty_password() -> None:
    # An empty password must not raise and must produce a credentialless URL.
    engine = _build_engine(_params(""))
    assert engine.url.drivername == "mysql+pymysql"
    assert not engine.url.password
    assert engine.url.username == "root"


def test_mysql_engine_builds_with_password() -> None:
    engine = _build_engine(_params("s3cr3t"))
    assert engine.url.password == "s3cr3t"


@pytest.mark.parametrize("blank", [None, "", "   ", "\t"])
def test_normalize_db_password_collapses_blank(blank: str | None) -> None:
    assert normalize_db_password(blank) is None


@pytest.mark.parametrize("value", ["secret", " has spaces ", "0"])
def test_normalize_db_password_keeps_real_values(value: str) -> None:
    assert normalize_db_password(value) == value


async def _capture_registration_payload(password: str) -> dict:
    """Run register_database_source against a mock transport, return the payload."""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"success": True})

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://teiid.test",
    )
    reg = TeiidRegistrationService(client=client)
    try:
        await reg.register_database_source(
            vdb_id="1234567",
            org_id=1,
            user_id=2,
            db_type="mysql",
            host="db.example.com",
            port=3306,
            database_name="RFAM",
            schema_name=None,
            table_name="clan",
            username="rfam_user",
            password=password,
            ssl_mode=None,
            model_name="ds_1_src",
            teiid_table_name="clan",
            jndi_name="java:/ds_1_mysql",
            ds_name="ds_1_mysql",
            view_name="Clan_MYSQL",
            columns=[],
        )
    finally:
        await reg.aclose()
    return captured


async def test_registration_blank_password_sent_empty() -> None:
    # A blank MySQL password must reach the servlet as "" (the servlet then
    # omits the WildFly password parameter entirely).
    payload = await _capture_registration_payload("")
    assert payload["password"] == ""
    assert payload["username"] == "rfam_user"


async def test_registration_preserves_real_password() -> None:
    payload = await _capture_registration_payload("s3cr3t")
    assert payload["password"] == "s3cr3t"
