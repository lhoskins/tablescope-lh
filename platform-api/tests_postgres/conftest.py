"""Opt-in RLS checks against disposable clones of a local, migrated database."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app import database as database_module
from app.auth import membership
from app.auth.jwt import create_access_token
from app.config import get_settings
from app.main import create_app
from app.models import Project, ProjectBusinessContext, Tenant, User, UserVDB
from app.models.billing import TenantProvisioningRequest
from app.security.rls import current_rls_principal
from app.tasks import workflows
from scripts import manage_postgres_rls

PASSWORD = "local-rls-test-only"
WAVE = (
    "users", "projects", "user_vdbs", "shared_vdbs",
    "project_business_contexts", "knowledge_graphs", "knowledge_graph_versions",
    "knowledge_graph_health_checks", "tenant_provisioning_requests",
)


@dataclass(frozen=True)
class Stage:
    context: bool
    enforcement: bool


@dataclass
class Database:
    owner: Engine
    owner_url: URL
    app: async_sessionmaker[AsyncSession]
    worker: async_sessionmaker[AsyncSession]
    stage: Stage

    def switch(self, command: str, monkeypatch: pytest.MonkeyPatch, *, apply: bool) -> int:
        with monkeypatch.context() as env:
            env.setenv("DATABASE_URL", self.owner_url.render_as_string(hide_password=False))
            arguments = [command, "--tables", *WAVE]
            if command == "enable":
                arguments.extend(["--runtime-role", "tablescope_app"])
            if apply:
                arguments.append("--apply")
            return manage_postgres_rls.main(arguments)


@pytest.fixture(
    params=[Stage(False, False), Stage(True, False), Stage(True, True)],
    ids=["baseline", "context-only", "enforced"],
)
def stage(request: pytest.FixtureRequest) -> Stage:
    return request.param


@pytest.fixture(scope="session")
def template() -> Iterator[tuple[Engine, URL]]:
    raw = os.environ.get("RLS_TEST_TEMPLATE_URL")
    if not raw:
        pytest.skip("Set RLS_TEST_TEMPLATE_URL to a disposable local PostgreSQL template")
    url = make_url(raw).set(drivername="postgresql+psycopg2")
    if (
        url.host != "127.0.0.1"
        or url.database != "tablescope_rls_validation"
        or url.port is None
    ):
        pytest.fail("RLS template must be 127.0.0.1:<port>/tablescope_rls_validation")
    owner = create_engine(url)
    with owner.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM tenants")) == 0, (
            "The RLS template must contain schema only, without tenant data"
        )
        assert connection.scalar(text("SELECT count(*) FROM users")) == 0
    owner.dispose()
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        yield admin, url
    finally:
        admin.dispose()


@pytest_asyncio.fixture
async def database(
    template: tuple[Engine, URL],
    stage: Stage,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> AsyncIterator[Database]:
    admin, template_url = template
    name = f"rls_case_{uuid4().hex}"
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}" TEMPLATE tablescope_rls_validation'))
    owner_url = template_url.set(database=name)
    owner = create_engine(owner_url)
    app_url = owner_url.set(drivername="postgresql+asyncpg", username="tablescope_app", password=PASSWORD)
    worker_url = app_url.set(username="tablescope_worker")
    app_engine = create_async_engine(app_url, pool_size=2, max_overflow=0)
    worker_engine = create_async_engine(worker_url, pool_size=1, max_overflow=0)
    owner_engine = create_async_engine(owner_url.set(drivername="postgresql+asyncpg"))
    app_sessions = async_sessionmaker(app_engine, expire_on_commit=False)
    worker_sessions = async_sessionmaker(worker_engine, expire_on_commit=False)
    try:
        with owner.begin() as connection:
            connection.execute(text("GRANT USAGE ON SCHEMA public TO tablescope_app, tablescope_worker"))
            connection.execute(text(
                "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public "
                "TO tablescope_app, tablescope_worker"
            ))
            connection.execute(text(
                "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public "
                "TO tablescope_app, tablescope_worker"
            ))
            assert not connection.scalar(text(
                "SELECT bool_or(rolsuper OR rolbypassrls) FROM pg_roles "
                "WHERE rolname IN ('tablescope_app', 'tablescope_worker')"
            ))
            assert connection.scalar(text(
                "SELECT count(*) FROM pg_class WHERE relowner IN "
                "(SELECT oid FROM pg_roles WHERE rolname IN ('tablescope_app', 'tablescope_worker'))"
            )) == 0
        for key, value in {
            "DATABASE_URL": app_url.render_as_string(hide_password=False),
            "POSTGRES_RLS_CONTEXT_ENABLED": str(stage.context),
            "ENVIRONMENT": "test",
            "JWT_SECRET_KEY": "local-rls-validation-jwt-key-only",
            "SERVICE_API_KEYS": "local-rls-validation-service-key",
            "CUSTOMER_BASE_PATH": str(tmp_path / "customers"),
            "S3_ENABLED": "false",
            "PROMETHEUS_ENABLED": "false",
        }.items():
            monkeypatch.setenv(key, value)
        get_settings.cache_clear()
        monkeypatch.setattr(database_module, "SessionLocal", app_sessions)
        monkeypatch.setattr(membership, "SessionLocal", app_sessions)
        monkeypatch.setattr(workflows, "SessionLocal", worker_sessions)
        async with async_sessionmaker(owner_engine, expire_on_commit=False)() as session:
            for identifier in (1, 2):
                tenant = Tenant(id=identifier, slug=f"rls-{identifier}", name=f"RLS tenant {identifier}")
                session.add(tenant)
                await session.flush()
                user = User(
                    id=identifier, tenant_id=identifier, email=f"rls-{identifier}@example.com",
                    role="admin", is_active=True, status="active",
                )
                user.set_password(PASSWORD)
                session.add(user)
                await session.flush()
                session.add(Project(
                    id=identifier, tenant_id=identifier, owner_id=identifier,
                    name=f"RLS project {identifier}",
                ))
                session.add(UserVDB(
                    tenant_id=identifier, user_id=identifier, vdb_id=f"rls_vdb_{identifier}",
                    vdb_username="local-user", encrypted_password="local-unused-password",
                ))
                await session.flush()
                session.add(ProjectBusinessContext(
                    tenant_id=identifier, project_id=identifier, version=0, ai_context_enabled=True,
                ))
                session.add(TenantProvisioningRequest(
                    tenant_id=identifier, tier_key="test", deployment_mode="shared",
                    tenant_slug=tenant.slug, tenant_admin_email=user.email,
                    stripe_checkout_session_id=f"cs_rls_{identifier}",
                ))
            await session.commit()
            for table in ("tenants", "users", "projects"):
                await session.execute(text(
                    f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                    f"(SELECT max(id) FROM {table}))"
                ))
            await session.commit()
        db = Database(owner, owner_url, app_sessions, worker_sessions, stage)
        if stage.enforcement:
            assert db.switch("enable", monkeypatch, apply=True) == 0
        yield db
        assert current_rls_principal() is None
    finally:
        await app_engine.dispose()
        await worker_engine.dispose()
        await owner_engine.dispose()
        owner.dispose()
        get_settings.cache_clear()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))


@pytest_asyncio.fixture
async def client(database: Database) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://rls.test") as client:
        yield client


def headers(tenant_id: int = 1, user_id: int = 1) -> dict[str, str]:
    return {"Authorization": "Bearer " + create_access_token(
        sub=str(user_id), tenant_id=tenant_id, user_id=user_id, role="admin",
        extra_claims={"aal": "aal2"},
    )}
