from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.security import rls


def test_rls_scope_restores_nested_principal() -> None:
    assert rls.current_rls_principal() is None
    with rls.rls_scope(tenant_id=1, user_id=10, source="outer"):
        assert rls.current_rls_principal().tenant_id == 1
        with rls.rls_scope(tenant_id=2, user_id=20, project_id=30, source="inner"):
            principal = rls.current_rls_principal()
            assert (principal.tenant_id, principal.user_id, principal.project_id) == (
                2,
                20,
                30,
            )
        assert rls.current_rls_principal().tenant_id == 1
    assert rls.current_rls_principal() is None


@pytest.mark.asyncio
async def test_rls_scope_isolated_between_async_tasks() -> None:
    gate = asyncio.Event()

    async def read(tenant_id: int) -> int:
        with rls.rls_scope(tenant_id=tenant_id, user_id=tenant_id):
            gate.set()
            await gate.wait()
            await asyncio.sleep(0)
            return rls.current_rls_principal().tenant_id

    assert await asyncio.gather(read(11), read(22)) == [11, 22]
    assert rls.current_rls_principal() is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"tenant_id": 0, "user_id": 1},
        {"tenant_id": -1, "user_id": 1},
        {"tenant_id": 1, "user_id": -1},
        {"tenant_id": 1, "user_id": 1, "project_id": 0},
    ],
)
def test_rls_scope_rejects_invalid_identifiers(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        with rls.rls_scope(**kwargs):
            pass


@pytest.mark.asyncio
async def test_auth_bootstrap_uses_transaction_local_set_config(monkeypatch) -> None:
    monkeypatch.setattr(
        rls,
        "get_settings",
        lambda: SimpleNamespace(postgres_rls_context_enabled=True),
    )
    calls: list[tuple[object, dict[str, str]]] = []

    class FakeSession:
        def get_bind(self):
            return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

        async def execute(self, statement, parameters):
            calls.append((statement, parameters))

    await rls.set_rls_session_context(
        FakeSession(), tenant_id=7, user_id=8, project_id=9
    )
    assert calls[0][1] == {"tenant_id": "7", "user_id": "8", "project_id": "9"}
    sql = str(calls[0][0])
    assert "set_config('tablescope.tenant_id'" in sql
    assert sql.count("true") == 3


@pytest.mark.asyncio
async def test_auth_bootstrap_is_noop_before_rollout(monkeypatch) -> None:
    monkeypatch.setattr(
        rls,
        "get_settings",
        lambda: SimpleNamespace(postgres_rls_context_enabled=False),
    )

    class NeverUsedSession:
        def get_bind(self):
            raise AssertionError("disabled RLS must not touch the connection")

    await rls.set_rls_session_context(NeverUsedSession(), tenant_id=1)


@pytest.mark.asyncio
async def test_rls_enabled_login_requires_explicit_organization(client, monkeypatch) -> None:
    from app.routes import auth as auth_routes

    monkeypatch.setattr(
        auth_routes,
        "get_settings",
        lambda: SimpleNamespace(postgres_rls_context_enabled=True),
    )
    response = await client.post(
        "/api/auth/login",
        json={"email": "same@example.com", "password": "irrelevant"},
    )
    assert response.status_code == 400
    assert "Organization is required" in response.json()["detail"]
