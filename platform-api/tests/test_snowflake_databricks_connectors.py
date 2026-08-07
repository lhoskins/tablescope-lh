"""Databricks + Snowflake native Teiid JDBC connector wiring.

Covers the engine-specific JDBC URL construction, source-identifier casing, and
DB_TYPES configuration used by both the SQLAlchemy introspection path and the
WildFly/Teiid runtime datasource.
"""

from __future__ import annotations

import pytest

from app.services.database_introspection_service import (
    build_jdbc_url,
    get_db_type_config,
    map_to_teiid_type,
    source_identifier,
)


def test_get_db_type_config_returns_snowflake() -> None:
    cfg = get_db_type_config("snowflake")
    assert cfg.db_type == "snowflake"
    assert cfg.default_port == 443
    assert cfg.sa_dialect == "snowflake"
    assert cfg.teiid_translator == "snowflake"
    assert "INFORMATION_SCHEMA" in cfg.system_schemas


def test_get_db_type_config_returns_databricks() -> None:
    cfg = get_db_type_config("databricks")
    assert cfg.db_type == "databricks"
    assert cfg.default_port == 443
    assert cfg.sa_dialect == "databricks"
    assert cfg.teiid_translator == "databricks"


def test_build_jdbc_url_snowflake_bare_account_gets_domain() -> None:
    url = build_jdbc_url(
        db_type="snowflake",
        host="myaccount",
        port=443,
        database_name="MYDB",
    )
    assert url == "jdbc:snowflake://myaccount.snowflakecomputing.com:443/?db=MYDB"


def test_build_jdbc_url_snowflake_full_host_preserved() -> None:
    url = build_jdbc_url(
        db_type="snowflake",
        host="myaccount.east-us-2.azure.snowflakecomputing.com",
        port=443,
        database_name="analytics",
    )
    assert (
        url
        == "jdbc:snowflake://myaccount.east-us-2.azure.snowflakecomputing.com:443/?db=analytics"
    )


def test_build_jdbc_url_databricks_uses_http_path() -> None:
    http_path = "/sql/1.0/endpoints/abc123"
    url = build_jdbc_url(
        db_type="databricks",
        host="dbc-abc.cloud.databricks.com",
        port=443,
        database_name=http_path,
    )
    assert (
        url
        == "jdbc:databricks://dbc-abc.cloud.databricks.com:443/default;"
        "transportMode=http;ssl=1;AuthMech=3;httpPath=/sql/1.0/endpoints/abc123"
    )


def test_build_jdbc_url_escapes_databricks_http_path() -> None:
    url = build_jdbc_url(
        db_type="databricks",
        host="dbc-abc.cloud.databricks.com",
        port=443,
        database_name="/sql/1.0/endpoints/a b",
    )
    assert "httpPath=/sql/1.0/endpoints/a%20b" in url


def test_build_jdbc_url_escapes_snowflake_database() -> None:
    url = build_jdbc_url(
        db_type="snowflake",
        host="myaccount",
        port=443,
        database_name="my db",
    )
    assert "db=my%20db" in url


@pytest.mark.parametrize(
    ("db_type", "input_name", "expected"),
    [
        ("snowflake", "customer_id", "CUSTOMER_ID"),
        ("databricks", "CustomerID", "CustomerID"),
    ],
)
def test_source_identifier_casing(db_type: str, input_name: str, expected: str) -> None:
    assert source_identifier(db_type, input_name) == expected


def test_map_to_teiid_type_snowflake_and_databricks_variants() -> None:
    assert map_to_teiid_type("VARCHAR(16777216)") == "string"
    assert map_to_teiid_type("NUMBER(38,0)") == "double"
    assert map_to_teiid_type("BOOLEAN") == "boolean"
    assert map_to_teiid_type("VARIANT") == "string"
    assert map_to_teiid_type("ARRAY") == "string"
    assert map_to_teiid_type("STRING") == "string"
    assert map_to_teiid_type("TINYINT") == "short"
    assert map_to_teiid_type("BYTEINT") == "short"
