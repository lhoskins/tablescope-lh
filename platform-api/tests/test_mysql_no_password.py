"""Issue 4: the MySQL connector must allow a blank/no password."""

from __future__ import annotations

from app.services.database_introspection_service import (
    ConnectionParams,
    _build_engine,
)


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
