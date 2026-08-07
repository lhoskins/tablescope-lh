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
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from urllib.parse import quote, quote_plus

from sqlalchemy import MetaData, Table, create_engine, inspect, select, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

# A "simple" SQL identifier needs no quoting: starts with a letter, then only
# letters / digits / underscores, all lower-case.
_SIMPLE_LOWER_IDENT = re.compile(r"^[a-z][a-z0-9_]*$")

# Salesforce connector renames system columns in the local staging schema.
# When the native Teiid translator is used, these must map back to the API names.
_SALESFORCE_BASE_COLUMN_MAP = {
    "salesforce_id": "Id",
    "is_deleted": "IsDeleted",
    "created_date": "CreatedDate",
    "last_modified_date": "LastModifiedDate",
    "system_modstamp": "SystemModstamp",
}

# HubSpot and QuickBooks live translators rename API columns locally.
# source_identifier() maps the local column names back to the source names.
_HUBSPOT_BASE_COLUMN_MAP = {
    "hubspot_id": "id",
    "archived": "archived",
    "created_at": "createdAt",
    "updated_at": "updatedAt",
}

_QUICKBOOKS_BASE_COLUMN_MAP = {
    "quickbooks_id": "Id",
    "sync_token": "SyncToken",
    "created_time": "MetaData.CreateTime",
    "updated_time": "MetaData.LastUpdatedTime",
}


def source_identifier(db_type: str, name: str | None) -> str | None:
    """Return the identifier *as stored in the source database*.

    Oracle folds unquoted identifiers to UPPER CASE, but SQLAlchemy reflection
    reports them lower-case.  When Teiid sends a quoted identifier verbatim via
    NAMEINSOURCE, the case must match exactly or Oracle raises ORA-00904 /
    ORA-00942.  So for Oracle we upper-case simple lower-case identifiers and
    leave anything that genuinely needs quoting (spaces, mixed case, reserved
    words) untouched.

    Salesforce system columns are renamed locally (e.g. ``salesforce_id`` ->
    ``Id``); map them back so the Teiid native translator resolves the real API
    field name.  User-selected fields already use their API names and pass
    through unchanged.
    """
    if name is None:
        return None
    if db_type == "oracle" and _SIMPLE_LOWER_IDENT.match(name):
        return name.upper()
    if db_type == "snowflake" and _SIMPLE_LOWER_IDENT.match(name):
        return name.upper()
    if db_type == "databricks" and _SIMPLE_LOWER_IDENT.match(name):
        return name.lower()
    if db_type == "salesforce":
        return _SALESFORCE_BASE_COLUMN_MAP.get(name, name)
    if db_type == "hubspot":
        return _HUBSPOT_BASE_COLUMN_MAP.get(name, name)
    if db_type == "quickbooks":
        return _QUICKBOOKS_BASE_COLUMN_MAP.get(name, name)
    return name


def normalize_db_password(value: str | None) -> str | None:
    """Collapse a blank/whitespace-only DB password to ``None``.

    Some databases (e.g. a MySQL account configured without a password) connect
    with no password at all.  An empty string must be treated as "no password"
    so the credential can be omitted from the connection URL and the
    Teiid/WildFly datasource registration (WildFly rejects ``password=""``).
    Non-empty passwords are returned verbatim — passwords may legitimately
    contain leading/trailing spaces, so we only treat all-whitespace as blank.
    """
    if value is None:
        return None
    if value == "":
        return None
    if value.strip() == "":
        return None
    return value


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
        # mssql-jdbc 12.x encrypts by default and validates the server cert;
        # trust it so federation works against self-signed SQL Server instances.
        jdbc_template=(
            "jdbc:sqlserver://{host}:{port};databaseName={database}"
            ";encrypt=true;trustServerCertificate=true"
        ),
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
    "snowflake": DbTypeConfig(
        db_type="snowflake",
        default_port=443,
        sa_dialect="snowflake",
        teiid_translator="snowflake",
        # Host should be the account identifier; the full JDBC URL appends the
        # Snowflake domain if the user supplied a bare account name.
        jdbc_template="jdbc:snowflake://{host}:{port}/?db={database}",
        system_schemas=frozenset({"INFORMATION_SCHEMA"}),
    ),
    "databricks": DbTypeConfig(
        db_type="databricks",
        default_port=443,
        sa_dialect="databricks",
        teiid_translator="databricks",
        # database_name carries the SQL warehouse HTTP path (e.g.
        # /sql/1.0/endpoints/...).  AuthMech=3 selects personal-access-token auth
        # combined with the datasource user-name "token".
        jdbc_template=(
            "jdbc:databricks://{host}:{port}/default;"
            "transportMode=http;ssl=1;AuthMech=3;httpPath={database}"
        ),
        system_schemas=frozenset({"information_schema"}),
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
    if db_type == "snowflake":
        if "." not in host:
            host = f"{host}.snowflakecomputing.com"
        database_name = quote(database_name, safe="")
    elif db_type == "databricks":
        database_name = quote(database_name, safe="/")
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

    @property
    def resolved_username(self) -> str:
        if self.db_type == "databricks" and not self.username:
            return "token"
        return self.username


def _build_snowflake_engine(params: ConnectionParams, raw_pwd: str | None, connect_args: dict) -> Engine:
    """Snowflake's dialect accepts the account identifier as the URL host."""
    user = quote_plus(params.username)
    auth = f"{user}:{quote_plus(raw_pwd)}" if raw_pwd is not None else user
    # account or full account-locator are both acceptable to snowflake-sqlalchemy.
    host = params.host
    db = quote_plus(params.database_name)
    url = f"snowflake://{auth}@{host}/{db}"
    return create_engine(
        url,
        connect_args=connect_args,
        pool_pre_ping=True,
        pool_size=1,
        max_overflow=0,
    )


def _build_databricks_engine(params: ConnectionParams, raw_pwd: str | None, connect_args: dict) -> Engine:
    """Databricks warehouse: password is a personal access token; user is 'token'."""
    user = quote_plus(params.resolved_username)
    auth = f"{user}:{quote_plus(raw_pwd)}" if raw_pwd is not None else user
    host = params.host
    # database_name is the warehouse HTTP path.
    http_path = quote(params.database_name, safe="")
    url = f"databricks://{auth}@{host}?http_path={http_path}"
    return create_engine(
        url,
        connect_args=connect_args,
        pool_pre_ping=True,
        pool_size=1,
        max_overflow=0,
    )


def _build_engine(params: ConnectionParams) -> Engine:
    cfg = get_db_type_config(params.db_type)
    raw_pwd = normalize_db_password(params.password)

    if params.db_type == "snowflake":
        connect_args: dict = {"login_timeout": 10}
        return _build_snowflake_engine(params, raw_pwd, connect_args)
    if params.db_type == "databricks":
        connect_args = {"_socket_timeout": 30, "_http_timeout": 30}
        return _build_databricks_engine(params, raw_pwd, connect_args)

    user = quote_plus(params.username)
    # No-password connections must not produce ``user:@host`` — omit the
    # credential separator entirely so drivers connect without a password.
    auth = f"{user}:{quote_plus(raw_pwd)}" if raw_pwd is not None else user
    host = params.host
    port = params.resolved_port
    db = quote_plus(params.database_name)

    if params.db_type == "oracle":
        # Connect by service name (matches the JDBC thin service-name form).
        url = f"{cfg.sa_dialect}://{auth}@{host}:{port}/?service_name={db}"
    else:
        url = f"{cfg.sa_dialect}://{auth}@{host}:{port}/{db}"

    # Connection-timeout argument names differ across DBAPI drivers.
    connect_args = {}
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
                    "name_in_source": source_identifier(
                        params.db_type, col["name"]
                    ),
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


def _jsonify(value: object) -> object:
    """Coerce a DBAPI cell value into something JSON-serialisable."""
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes | bytearray):
        return f"<{len(value)} bytes>"
    return str(value)


def sample_rows(
    params: ConnectionParams,
    schema_name: str | None,
    table_name: str,
    limit: int = 20,
) -> dict:
    """Return a small sample of rows for previewing a table's data.

    Reflects the table so the query works across dialects, then runs a single
    ``SELECT * ... LIMIT n``. Values are coerced to JSON-friendly types.
    """
    limit = max(1, min(limit, 100))
    engine = _build_engine(params)
    try:
        table = Table(
            table_name,
            MetaData(),
            schema=schema_name,
            autoload_with=engine,
        )
        columns = [c.name for c in table.columns]
        with engine.connect() as conn:
            result = conn.execute(select(table).limit(limit))
            rows = [[_jsonify(v) for v in row] for row in result.fetchall()]
        return {"columns": columns, "rows": rows}
    except Exception as exc:
        logger.warning("DB sample_rows failed: %s", exc)
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
        "SMALLINT", "INT2", "SMALLSERIAL", "TINYINT", "YEAR", "BYTEINT",
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
        # Snowflake / Databricks
        "STRING", "VARIANT", "OBJECT", "ARRAY", "MAP", "STRUCT",
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
