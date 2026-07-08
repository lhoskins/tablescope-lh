"""Shared pytest fixtures.

Tests use an in-memory SQLite database via aiosqlite. The platform API's
production database is Postgres + asyncpg, but the application code is
written against the SQLAlchemy 2.0 async API and avoids Postgres-specific
features, so SQLite is sufficient for unit tests of routes and services.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-xxxxxxxxxxxxxxxxxxxx")
os.environ.setdefault("SERVICE_API_KEYS", "test-service-key")
os.environ.setdefault("PROMETHEUS_ENABLED", "false")
os.environ.setdefault("CUSTOMER_BASE_PATH", "/tmp/tablescope-test-customers")
os.environ.setdefault("DRILLDOWN_CONFIG_PATH", "/tmp/tablescope-test-drilldown.json")

from app import database as database_module
from app.config import get_settings
from app.main import create_app
from app.models import Base


@pytest_asyncio.fixture(scope="function")
async def db_engine() -> AsyncIterator:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(db_engine) -> AsyncIterator[AsyncSession]:
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session


def _build_app(db_engine, *, enforce_membership: bool):
    get_settings.cache_clear()
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app = create_app()
    app.dependency_overrides[database_module.get_db] = override_get_db
    if not enforce_membership:
        # Most route tests mint synthetic tokens without seeding a matching
        # membership row; bypass the DB-backed membership check so they keep
        # exercising route/role logic. Tenant-isolation behaviour is covered
        # explicitly via the ``client_strict`` fixture.
        from app.auth.context import get_request_context
        from app.auth.membership import require_membership

        app.dependency_overrides[require_membership] = get_request_context
    return app


@pytest_asyncio.fixture(scope="function")
async def client(db_engine) -> AsyncIterator[AsyncClient]:
    app = _build_app(db_engine, enforce_membership=False)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest_asyncio.fixture(scope="function")
async def client_strict(db_engine) -> AsyncIterator[AsyncClient]:
    """Client with real tenant-membership enforcement (no bypass)."""
    app = _build_app(db_engine, enforce_membership=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest.fixture
def service_headers() -> dict:
    return {"X-API-Key": "test-service-key"}
