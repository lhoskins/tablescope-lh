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

from app import database as database_module  # noqa: E402  (env vars must be set first)
from app.config import get_settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import Base  # noqa: E402


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


@pytest_asyncio.fixture(scope="function")
async def client(db_engine) -> AsyncIterator[AsyncClient]:
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
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest.fixture
def service_headers() -> dict:
    return {"X-API-Key": "test-service-key"}
