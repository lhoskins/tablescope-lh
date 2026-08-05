
from __future__ import annotations

from urllib.parse import unquote, urlparse

from app.config import get_settings


def _platform_db_password() -> str | None:
    """Return the password for the platform's own Postgres from settings."""
    url = urlparse(get_settings().database_url)
    if url.password is None:
        return None
    return unquote(url.password)


def _platform_db_params() -> dict[str, str | int]:
    """Return host/port/database/username for the platform's own Postgres."""
    url = urlparse(get_settings().database_url)
    return {
        "host": url.hostname or "db",
        "port": url.port or 5432,
        "database_name": (url.path or "/tablescope").lstrip("/"),
        "username": unquote(url.username) if url.username else "tablescope",
    }


def _platform_password_for_source(ds) -> str | None:
    """If ``ds`` points at the platform's own Postgres, return its password.

    SaaS and local-staging data sources are stored with no encrypted password
    because the table lives in the app database.  WildFly/Teiid still needs a
    non-empty credential for the JDBC datasource, so fall back to the platform
    DB password parsed from ``DATABASE_URL``.
    """
    expected = _platform_db_params()
    if (
        ds.host == expected["host"]
        and str(ds.port) == str(expected["port"])
        and ds.database_name == expected["database_name"]
        and ds.username == expected["username"]
    ):
        return _platform_db_password()
    return None
