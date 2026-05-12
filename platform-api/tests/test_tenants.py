"""Tenant + user CRUD route tests."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest


@pytest.fixture()
def customer_dir(monkeypatch, tmp_path):
    target = tmp_path / "customers"
    monkeypatch.setenv("CUSTOMER_BASE_PATH", str(target))
    from app.config import get_settings

    get_settings.cache_clear()
    yield target
    if target.exists():
        shutil.rmtree(target)


async def test_create_tenant_and_user(client, service_headers, customer_dir: Path) -> None:
    response = await client.post(
        "/api/tenants",
        json={"slug": "acme", "name": "Acme Co"},
        headers=service_headers,
    )
    assert response.status_code == 201, response.text
    tenant = response.json()
    assert tenant["slug"] == "acme"

    response = await client.post(
        f"/api/tenants/{tenant['id']}/users",
        json={
            "email": "alice@example.com",
            "display_name": "Alice",
            "role": "editor",
            "external_id": "ext-alice",
        },
        headers=service_headers,
    )
    assert response.status_code == 201, response.text
    user = response.json()
    assert user["email"] == "alice@example.com"
    assert user["tenant_id"] == tenant["id"]

    response = await client.get(
        f"/api/tenants/{tenant['id']}/users",
        headers=service_headers,
    )
    assert response.status_code == 200
    assert len(response.json()) == 1

    assert (customer_dir / "acme").exists()
    assert (customer_dir / "acme" / "users" / "ext-alice").exists()


async def test_anonymous_cannot_create_tenant(client) -> None:
    response = await client.post(
        "/api/tenants",
        json={"slug": "x", "name": "x"},
    )
    assert response.status_code == 401
