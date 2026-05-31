"""Database introspection service.

Connects to an *external* user-supplied database (not the platform metadata DB)
to validate credentials and enumerate schemas / tables / columns.  This powers
the "Connect Database Table" wizard.

PostgreSQL is the MVP.  The per-db-type config table makes adding MySQL and SQL
Server later a matter of installing the driver and filling in a row.

All driver calls are synchronous (SQLAlchemy core + DBAPI), so callers should
invoke the public helpers via ``starlette.concurrency.run_in_threadpool`` to
avoid blocking the event loop.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from urllib.parse import quote_plus

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


class DatabaseIntrospectionError(Exception):
    """User-facing introspection failure (safe message, no secrets)."""


@dataclass(frozen=True)
class DbTypeConfig:
    db_type: str
    default_port: int
    # SQLAlchemy dialect+driver used for introspection from platform-api.
    sa_dialect: str
    # Teiid translator name used when registering the source in the VDB.
    teiid_translator: str
    # JDBC URL template (used by the Teiid servlet to build the connection).
    jdbc_template: str
    # System schemas hidden from the user.
    system_schemas: frozenset[str] = field(default_factory=frozenset)


# Enabled engines.  Each needs (a) a Python DBAPI driver for introspection from
# platform-api and (b) a matching WildFly JDBC driver module so Teiid can build
# the runtime datasource.  Adding an engine is now just a row here plus the
# bundled driver module.
DB_TYPES: dict[str, DbTypeConfig] = {
    "postgresql": DbTypeConfig(
        db_type="postgresql",
        default_port=5432,
        sa_dialect="postgresql+psycopg2",
        teiid_translator="postgresql",
        jdbc_template="jdbc:postgresql://{host}:{port}/{database}",
        system_schemas=frozenset({"information_schema", "pg_catalog", "pg_toast"}),
    ),
    "mysql": DbTypeConfig(
        db_type="mysql",
        default_port=3306,
        sa_dialect="mysql+pymysql",
        teiid_translator="mysql5",
        jdbc_template="jdbc:mysql://{host}:{port}/{database}",
        system_schemas=frozenset(
            {"information_schema", "performance_schema", "mysql", "sys"}
        ),
    ),
    "sqlserver": DbTypeConfig(
        db_type="sqlserver",
        default_port=1433,
        sa_dialect="mssql+pymssql",
        teiid_translator="sqlserver",
        jdbc_template="jdbc:sqlserver://{host}:{port};databaseName={database}",
        system_schemas=frozenset(
            {
                "sys", "INFORMATION_SCHEMA", "guest", "db_owner",
                "db_accessadmin", "db_securityadmin", "db_ddladmin",
                "db_backupoperator", "db_datareader", "db_datawriter",
                "db_denydatareader", "db_denydatawriter",
            }
        ),
    ),
    "oracle": DbTypeConfig(
        db_type="oracle",
        default_port=1521,
        sa_dialect="oracle+oracledb",
        teiid_translator="oracle",
        # Oracle thin URL using a service name (the modern connect form).
        jdbc_template="jdbc:oracle:thin:@//{host}:{port}/{database}",
        system_schemas=frozenset(
            {
                "SYS", "SYSTEM", "OUTLN", "XDB", "CTXSYS", "MDSYS", "DBSNMP",
                "APPQOSSYS", "ORDSYS", "ORDDATA", "OLAPSYS", "WMSYS", "LBACSYS",
                "DVSYS", "AUDSYS", "GSMADMIN_INTERNAL", "DBSFWUSER", "GGSYS",
                "ANONYMOUS", "REMOTE_SCHEDULER_AGENT", "SYS$UMF", "PUBLIC",
            }
        ),
    ),
}

# No deferred engines remain; kept for the "unsupported yet" branch below.
FUTURE_DB_TYPES: dict[str, DbTypeConfig] = {}


def get_db_type_config(db_type: str) -> DbTypeConfig:
    cfg = DB_TYPES.get(db_type)
    if cfg is None:
        if db_type in FUTURE_DB_TYPES:
            raise DatabaseIntrospectionError(
                f"Database type '{db_type}' is not enabled yet. "
                "PostgreSQL is currently supported."
            )
        raise DatabaseIntrospectionError(f"Unsupported database type: {db_type!r}")
    return cfg


def build_jdbc_url(
    *, db_type: str, host: str, port: int, database_name: str
) -> str:
    cfg = get_db_type_config(db_type)
    return cfg.jdbc_template.format(host=host, port=port, database=database_name)


@dataclass
class ConnectionParams:
    db_type: str
    host: str
    port: int | None
    database_name: str
    username: str
    password: str
    ssl_mode: str | None = None

    @property
    def resolved_port(self) -> int:
        if self.port:
            return self.port
        return get_db_type_config(self.db_type).default_port


def _build_engine(params: ConnectionParams) -> Engine:
    cfg = get_db_type_config(params.db_type)
    user = quote_plus(params.username)
    pwd = quote_plus(params.password)
    host = params.host
    port = params.resolved_port
    db = quote_plus(params.database_name)

    if params.db_type == "oracle":
        # Connect by service name (matches the JDBC thin service-name form).
        url = f"{cfg.sa_dialect}://{user}:{pwd}@{host}:{port}/?service_name={db}"
    else:
        url = f"{cfg.sa_dialect}://{user}:{pwd}@{host}:{port}/{db}"

    # Connection-timeout argument names differ across DBAPI drivers.
    connect_args: dict = {}
    if params.db_type == "postgresql":
        connect_args["connect_timeout"] = 10
        if params.ssl_mode:
            connect_args["sslmode"] = params.ssl_mode
    elif params.db_type == "mysql":
        connect_args["connect_timeout"] = 10
    elif params.db_type == "sqlserver":
        connect_args["login_timeout"] = 10
        connect_args["timeout"] = 30
    elif params.db_type == "oracle":
        connect_args["tcp_connect_timeout"] = 10

    return create_engine(
        url,
        connect_args=connect_args,
        pool_pre_ping=True,
        pool_size=1,
        max_overflow=0,
    )


def _safe_error(exc: Exception) -> str:
    """Produce a user-safe error message that never leaks the password."""
    msg = str(exc)
    low = msg.lower()
    if "password authentication failed" in low or "authentication" in low:
        return "Authentication failed. Please verify username and password."
    if "could not translate host name" in low or "name or service not known" in low:
        return "Host could not be resolved. Please verify the host name."
    if "connection refused" in low or "timeout" in low or "timed out" in low:
        return (
            "Could not reach the database. Verify host, port, and network access."
        )
    if "does not exist" in low and "database" in low:
        return "Database does not exist. Please verify the database name."
    # Generic fallback — keep it friendly and free of connection internals.
    return (
        "Connection failed. Please verify host, port, database name, username, "
        "password, and network access."
    )


def test_connection(params: ConnectionParams) -> None:
    """Raise DatabaseIntrospectionError if the connection cannot be made."""
    engine = _build_engine(params)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        logger.warning("DB test_connection failed for %s:%s/%s: %s",
                       params.host, params.resolved_port, params.database_name, exc)
        raise DatabaseIntrospectionError(_safe_error(exc)) from exc
    finally:
        engine.dispose()


def list_schemas(params: ConnectionParams) -> list[str]:
    cfg = get_db_type_config(params.db_type)
    engine = _build_engine(params)
    try:
        inspector = inspect(engine)
        schemas = [
            s for s in inspector.get_schema_names() if s not in cfg.system_schemas
        ]
        return sorted(schemas)
    except Exception as exc:
        logger.warning("DB list_schemas failed: %s", exc)
        raise DatabaseIntrospectionError(_safe_error(exc)) from exc
    finally:
        engine.dispose()


def list_tables(params: ConnectionParams, schema_name: str | None) -> list[dict]:
    engine = _build_engine(params)
    try:
        inspector = inspect(engine)
        result: list[dict] = []
        for tbl in inspector.get_table_names(schema=schema_name):
            result.append(
                {"schema_name": schema_name, "table_name": tbl, "type": "table"}
            )
        for view in inspector.get_view_names(schema=schema_name):
            result.append(
                {"schema_name": schema_name, "table_name": view, "type": "view"}
            )
        result.sort(key=lambda r: r["table_name"])
        return result
    except Exception as exc:
        logger.warning("DB list_tables failed: %s", exc)
        raise DatabaseIntrospectionError(_safe_error(exc)) from exc
    finally:
        engine.dispose()


def list_columns(
    params: ConnectionParams, schema_name: str | None, table_name: str
) -> list[dict]:
    engine = _build_engine(params)
    try:
        inspector = inspect(engine)
        try:
            pk = set(
                inspector.get_pk_constraint(table_name, schema=schema_name).get(
                    "constrained_columns", []
                )
                or []
            )
        except Exception:
            pk = set()

        cols = inspector.get_columns(table_name, schema=schema_name)
        if not cols:
            raise DatabaseIntrospectionError(
                f"No columns found for table '{table_name}'."
            )
        result: list[dict] = []
        for idx, col in enumerate(cols):
            result.append(
                {
                    "name": col["name"],
                    "type": str(col.get("type")),
                    "nullable": bool(col.get("nullable", True)),
                    "primary_key": col["name"] in pk,
                    "ordinal_position": idx + 1,
                }
            )
        return result
    except DatabaseIntrospectionError:
        raise
    except Exception as exc:
        logger.warning("DB list_columns failed: %s", exc)
        raise DatabaseIntrospectionError(_safe_error(exc)) from exc
    finally:
        engine.dispose()


# Map a SQLAlchemy-rendered column type (e.g. "VARCHAR(255)", "INTEGER",
# "NUMERIC(10, 2)") to a Teiid runtime type used in CREATE FOREIGN TABLE DDL.
# Defaults to ``string`` for anything we do not recognise, which is always a
# safe choice for Teiid (it can read most things as text).
def map_to_teiid_type(sa_type: str) -> str:
    t = (sa_type or "").strip().upper()
    # Strip any length/precision qualifier, e.g. "VARCHAR(255)" -> "VARCHAR".
    base = t.split("(", 1)[0].strip()

    # Covers PostgreSQL, MySQL, SQL Server and Oracle rendered type names.
    integer_types = {"INTEGER", "INT", "INT4", "SERIAL", "MEDIUMINT"}
    long_types = {"BIGINT", "INT8", "BIGSERIAL"}
    short_types = {
        "SMALLINT", "INT2", "SMALLSERIAL", "TINYINT", "YEAR",
    }
    bool_types = {"BOOLEAN", "BOOL", "BIT"}
    decimal_types = {
        "NUMERIC", "DECIMAL", "MONEY", "SMALLMONEY", "DEC", "NUMBER",
    }
    float_types = {"REAL", "FLOAT4", "BINARY_FLOAT"}
    double_types = {
        "DOUBLE PRECISION", "FLOAT8", "FLOAT", "DOUBLE", "BINARY_DOUBLE",
    }
    string_types = {
        # PostgreSQL
        "VARCHAR", "CHARACTER VARYING", "CHAR", "CHARACTER", "TEXT", "NAME",
        "CITEXT", "UUID", "JSON", "JSONB", "XML", "ENUM",
        "INET", "CIDR", "MACADDR", "INTERVAL", "SET",
        # MySQL
        "TINYTEXT", "MEDIUMTEXT", "LONGTEXT",
        # SQL Server
        "NVARCHAR", "NCHAR", "NTEXT", "UNIQUEIDENTIFIER", "SYSNAME",
        # Oracle
        "VARCHAR2", "NVARCHAR2", "CLOB", "NCLOB", "ROWID", "UROWID", "LONG",
    }
    binary_types = {
        "BYTEA",
        # MySQL / SQL Server / Oracle
        "BLOB", "TINYBLOB", "MEDIUMBLOB", "LONGBLOB", "BINARY", "VARBINARY",
        "IMAGE", "RAW", "LONG RAW", "BFILE",
    }

    if base in integer_types:
        return "integer"
    if base in long_types:
        return "long"
    if base in short_types:
        return "short"
    if base in bool_types:
        return "boolean"
    if base in decimal_types:
        # Map exact numerics to double rather than bigdecimal: Teiid's PG-wire
        # binary encoding for NUMERIC/bigdecimal is not decodable by asyncpg
        # ("insufficient data in buffer"), whereas float8/double works.
        return "double"
    if base in float_types:
        return "float"
    if base in double_types:
        return "double"
    if base in string_types:
        return "string"
    if base == "DATE":
        return "date"
    if base.startswith("DATETIME") or base.startswith("SMALLDATETIME"):
        return "timestamp"
    if base.startswith("TIMESTAMP"):
        return "timestamp"
    if base.startswith("TIME"):
        return "time"
    if base in binary_types:
        return "varbinary"
    return "string"
