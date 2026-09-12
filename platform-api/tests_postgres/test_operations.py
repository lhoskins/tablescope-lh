"""Identical application operations before and after PostgreSQL enforcement."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app import database as database_module
from app.services.stripe_billing_service import StripeBillingService
from app.tasks import workflows

from .conftest import PASSWORD, Database, headers


async def test_password_login_with_organization(client: AsyncClient) -> None:
    response = await client.post("/api/auth/login", json={
        "email": "rls-1@example.com", "password": PASSWORD, "tenant_slug": "rls-1",
    })
    assert response.status_code == 200, response.text
    assert response.json()["tenant_id"] == 1


async def test_password_login_without_organization(client: AsyncClient, database: Database) -> None:
    response = await client.post("/api/auth/login", json={
        "email": "rls-1@example.com", "password": PASSWORD,
    })
    assert response.status_code == (400 if database.stage.context else 200), response.text


async def test_authenticated_reads_and_refresh(client: AsyncClient) -> None:
    response = await client.get("/api/auth/me", headers=headers())
    assert response.status_code == 200, response.text
    assert response.json()["tenant_id"] == 1
    response = await client.get("/api/projects", headers=headers())
    assert response.status_code == 200, response.text
    assert [project["id"] for project in response.json()] == [1]
    response = await client.get("/api/projects/2", headers=headers())
    assert response.status_code == 404, response.text
    response = await client.post("/api/auth/refresh", headers=headers())
    assert response.status_code == 200, response.text


async def test_project_create_update_and_commit_context(client: AsyncClient) -> None:
    response = await client.post("/api/projects", headers=headers(), json={"name": "New RLS project"})
    assert response.status_code == 201, response.text
    project_id = response.json()["id"]
    response = await client.put(
        f"/api/projects/{project_id}", headers=headers(), json={"name": "Updated RLS project"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "Updated RLS project"


async def test_member_revocation(client: AsyncClient, database: Database) -> None:
    assert (await client.get("/api/auth/me", headers=headers())).status_code == 200
    with database.owner.begin() as connection:
        connection.execute(text("UPDATE users SET is_active=false WHERE id=1"))
    assert (await client.get("/api/auth/me", headers=headers())).status_code == 403
    assert (await client.get("/api/auth/me", headers=headers(2, 2))).status_code == 200


async def test_service_user_listing_remains_functional(client: AsyncClient) -> None:
    response = await client.get(
        "/api/tenants/1/users", headers={"X-API-Key": "local-rls-validation-service-key"},
    )
    assert response.status_code == 200, response.text
    assert [user["id"] for user in response.json()] == [1]


async def test_upload_worker_can_resolve_its_vdb(database: Database) -> None:
    assert await workflows._resolve_vdb_id(tenant_id=1, user_id=1, is_shared=False) == "rls_vdb_1"


async def test_public_provisioning_status(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def checkout(self: StripeBillingService, session_id: str) -> dict[str, str]:
        assert session_id == "cs_rls_1"
        return {"client_reference_id": "1"}

    monkeypatch.setattr(StripeBillingService, "retrieve_checkout_session", checkout)
    response = await client.get("/api/provisioning/status?session_id=cs_rls_1")
    assert response.status_code == 200, response.text
    assert response.json()["tenant_slug"] == "rls-1"


async def test_health_check_worker_commits(database: Database, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(database_module, "SessionLocal", database.worker)
    result = await workflows.run_knowledge_graph_health_check({}, tenant_id=1, project_id=1)
    assert result["status"] == "ok", result
    with database.owner.connect() as connection:
        assert connection.scalar(text(
            "SELECT count(*) FROM knowledge_graph_health_checks WHERE tenant_id=1 AND project_id=1"
        )) == 1
