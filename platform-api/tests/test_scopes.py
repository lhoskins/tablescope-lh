"""Scope CRUD tests via the HTTP API."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from app.auth.jwt import create_access_token


@pytest.fixture()
def isolated_scope_file(monkeypatch):
    tmp = Path(tempfile.mkdtemp()) / "drilldownConfig.json"
    tmp.write_text(json.dumps({"drilldowns": []}))
    monkeypatch.setenv("DRILLDOWN_CONFIG_PATH", str(tmp))
    from app.config import get_settings

    get_settings.cache_clear()
    yield tmp
    if tmp.exists():
        tmp.unlink()
    os.rmdir(tmp.parent)


def _editor_headers(tenant_id: int = 1, user_id: int = 1) -> dict:
    token = create_access_token(
        sub="u", tenant_id=tenant_id, user_id=user_id, role="editor"
    )
    return {"Authorization": f"Bearer {token}"}


async def test_scope_lifecycle(client, isolated_scope_file) -> None:
    headers = _editor_headers()

    response = await client.get("/api/scopes", headers=headers)
    assert response.status_code == 200
    assert response.json() == []

    response = await client.post(
        "/api/scopes",
        json={
            "sourceTable": "orders",
            "sourceColumn": "customer_id",
            "targetTable": "customers",
            "targetColumn": "id",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["sourceTable"] == "orders"
    assert created["targetTable"] == "customers"
    assert created["tenantId"] == 1

    response = await client.get(
        "/api/scopes/orders/customer_id", headers=headers
    )
    assert response.status_code == 200

    response = await client.put(
        "/api/scopes/orders/customer_id",
        json={"targetTable": "vip_customers", "targetColumn": "id"},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["targetTable"] == "vip_customers"

    response = await client.delete(
        "/api/scopes/orders/customer_id", headers=headers
    )
    assert response.status_code == 204

    response = await client.get(
        "/api/scopes/orders/customer_id", headers=headers
    )
    assert response.status_code == 404


async def test_concurrent_scope_creation_no_data_loss(
    isolated_scope_file: Path,
) -> None:
    """Two parallel create_scope calls must both end up in the file.

    Regression for the TOCTOU race where each request had its own lock —
    after the fix, the module-level path-keyed lock serializes RMW cycles
    on the same file, so neither create is silently dropped.
    """
    import asyncio

    from app.services.scope_proxy import ScopeProxyService

    async def _one(service: ScopeProxyService, src_col: str) -> None:
        await service.create_scope(
            tenant_id=1,
            source_table="orders",
            source_column=src_col,
            target_table="customers",
            target_column="id",
        )

    services = [ScopeProxyService() for _ in range(10)]
    await asyncio.gather(*(_one(s, f"col_{i}") for i, s in enumerate(services)))

    payload = json.loads(isolated_scope_file.read_text())
    assert len(payload["drilldowns"]) == 10
    assert {d["sourceColumn"] for d in payload["drilldowns"]} == {
        f"col_{i}" for i in range(10)
    }


async def test_scope_isolated_by_tenant(client, isolated_scope_file) -> None:
    tenant_a = _editor_headers(tenant_id=10)
    tenant_b = _editor_headers(tenant_id=20)

    response = await client.post(
        "/api/scopes",
        json={
            "sourceTable": "orders",
            "sourceColumn": "customer_id",
            "targetTable": "customers",
            "targetColumn": "id",
        },
        headers=tenant_a,
    )
    assert response.status_code == 201

    response = await client.get("/api/scopes", headers=tenant_b)
    assert response.status_code == 200
    assert response.json() == []

    response = await client.get(
        "/api/scopes/orders/customer_id", headers=tenant_b
    )
    assert response.status_code == 404
