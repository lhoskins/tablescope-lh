"""RLS probes intentionally omit application tenant predicates."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.security.rls import rls_scope
from scripts import manage_postgres_rls

from .conftest import Database


async def test_unfiltered_reads_and_missing_context(database: Database) -> None:
    with rls_scope(tenant_id=1, user_id=1):
        async with database.app() as session:
            ids = list(await session.scalars(text("SELECT id FROM projects ORDER BY id")))
            assert ids == ([1] if database.stage.enforcement else [1, 2])
    async with database.app() as session:
        ids = list(await session.scalars(text("SELECT id FROM projects ORDER BY id")))
        assert ids == ([] if database.stage.enforcement else [1, 2])


async def test_own_tenant_crud(database: Database) -> None:
    with rls_scope(tenant_id=1, user_id=1):
        async with database.app() as session:
            identifier = await session.scalar(text(
                "INSERT INTO projects (tenant_id, owner_id, name, is_shared) "
                "VALUES (1, 1, 'Own tenant write', false) RETURNING id"
            ))
            await session.commit()
            assert await session.scalar(
                text("UPDATE projects SET name='Updated' WHERE id=:id RETURNING name"),
                {"id": identifier},
            ) == "Updated"
            await session.commit()
            assert await session.scalar(
                text("DELETE FROM projects WHERE id=:id RETURNING id"), {"id": identifier},
            ) == identifier
            await session.commit()


@pytest.mark.parametrize("statement", [
    "UPDATE projects SET name='Other tenant' WHERE id=2 RETURNING id",
    "DELETE FROM projects WHERE id=2 RETURNING id",
])
async def test_cross_tenant_update_delete(database: Database, statement: str) -> None:
    with rls_scope(tenant_id=1, user_id=1):
        async with database.app() as session:
            ids = list(await session.scalars(text(statement)))
            assert ids == ([] if database.stage.enforcement else [2])
            await session.rollback()


@pytest.mark.parametrize("statement", [
    "INSERT INTO projects (tenant_id, owner_id, name, is_shared) VALUES (2, 2, 'Other tenant', false)",
    "UPDATE projects SET tenant_id=2 WHERE id=1",
])
async def test_cross_tenant_insert_and_move(database: Database, statement: str) -> None:
    with rls_scope(tenant_id=1, user_id=1):
        async with database.app() as session:
            if database.stage.enforcement:
                with pytest.raises(DBAPIError, match="row-level security"):
                    await session.execute(text(statement))
            else:
                await session.execute(text(statement))
            await session.rollback()


async def test_missing_context_cannot_insert(database: Database) -> None:
    async with database.app() as session:
        statement = text(
            "INSERT INTO projects (tenant_id, owner_id, name, is_shared) "
            "VALUES (1, 1, 'Missing principal', false)"
        )
        if database.stage.enforcement:
            with pytest.raises(DBAPIError, match="row-level security"):
                await session.execute(statement)
        else:
            await session.execute(statement)
        await session.rollback()


@pytest.mark.parametrize("finish", ["commit", "rollback", "exception"])
async def test_pool_reuse_clears_context(database: Database, finish: str) -> None:
    with rls_scope(tenant_id=1, user_id=1):
        async with database.worker() as session:
            pid = await session.scalar(text("SELECT pg_backend_pid()"))
            assert await session.scalar(text("SELECT tablescope_current_tenant_id()")) == (
                1 if database.stage.context else None
            )
            if finish == "commit":
                await session.commit()
            elif finish == "rollback":
                await session.rollback()
            else:
                with pytest.raises(DBAPIError):
                    await session.execute(text("SELECT 1/0"))
    async with database.worker() as session:
        assert await session.scalar(text("SELECT pg_backend_pid()")) == pid
        assert await session.scalar(text("SELECT tablescope_current_tenant_id()")) is None
        await session.commit()
    with rls_scope(tenant_id=2, user_id=2):
        async with database.worker() as session:
            assert await session.scalar(text("SELECT pg_backend_pid()")) == pid
            ids = list(await session.scalars(text("SELECT id FROM projects ORDER BY id")))
            assert ids == ([2] if database.stage.enforcement else [1, 2])


async def test_concurrent_tenants(database: Database) -> None:
    gate = asyncio.Event()

    async def read(tenant_id: int) -> list[int]:
        with rls_scope(tenant_id=tenant_id, user_id=tenant_id):
            gate.set()
            await gate.wait()
            await asyncio.sleep(0)
            async with database.app() as session:
                return list(await session.scalars(text("SELECT id FROM projects ORDER BY id")))

    assert await asyncio.gather(read(1), read(2)) == (
        [[1], [2]] if database.stage.enforcement else [[1, 2], [1, 2]]
    )


async def test_dry_run_and_rollback(database: Database, monkeypatch: pytest.MonkeyPatch) -> None:
    assert database.switch("enable", monkeypatch, apply=False) == 0
    with database.owner.connect() as connection:
        assert connection.scalar(text(
            "SELECT relrowsecurity FROM pg_class WHERE oid='projects'::regclass"
        )) == database.stage.enforcement
    if database.stage.context:
        assert database.switch("enable", monkeypatch, apply=True) == 0
        async with database.app() as session:
            assert list(await session.scalars(text("SELECT id FROM projects"))) == []
        assert database.switch("disable", monkeypatch, apply=True) == 0
        async with database.app() as session:
            assert list(await session.scalars(text("SELECT id FROM projects ORDER BY id"))) == [1, 2]
        with database.owner.connect() as connection:
            assert connection.scalar(text(
                "SELECT count(*) FROM pg_policies WHERE tablename='projects' "
                "AND policyname='tablescope_tenant_isolation'"
            )) == 1


async def test_guard_rejects_superuser(database: Database, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", database.owner_url.render_as_string(hide_password=False))
    with pytest.raises(SystemExit, match="NOSUPERUSER NOBYPASSRLS"):
        manage_postgres_rls.main([
            "enable", "--runtime-role", str(database.owner_url.username), "--tables", "projects", "--apply",
        ])
