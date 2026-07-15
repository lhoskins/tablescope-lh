"""Repository connector CRUD and connection testing."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.repositories import (
    RepositoryConnectorError,
    get_repository_connector,
    list_repository_connector_types,
)
from app.models import ConnectorCredential, RepositoryConnection
from app.services.crypto import decrypt_secret, encrypt_secret

logger = logging.getLogger(__name__)


class RepositoryServiceError(Exception):
    """User-facing repository service error."""


async def list_connector_types() -> list[dict[str, Any]]:
    return list_repository_connector_types()


async def list_connections(
    session: AsyncSession,
    tenant_id: int,
) -> list[dict[str, Any]]:
    result = await session.execute(
        select(RepositoryConnection)
        .where(RepositoryConnection.tenant_id == tenant_id)
        .order_by(RepositoryConnection.created_at.desc())
    )
    return [row.to_redacted_dict() for row in result.scalars().all()]


async def get_connection(
    session: AsyncSession,
    tenant_id: int,
    connection_id: int,
) -> dict[str, Any]:
    conn = await _load_connection(session, tenant_id, connection_id)
    return conn.to_redacted_dict()


async def create_connection(
    session: AsyncSession,
    tenant_id: int,
    user_id: int,
    payload: dict[str, Any],
) -> dict[str, Any]:
    connector_type = payload.get("connector_type", "")
    try:
        connector = get_repository_connector(connector_type)
    except RepositoryConnectorError as exc:
        raise RepositoryServiceError(str(exc)) from exc

    config = payload.get("config") or {}
    try:
        await connector.validate_config(config)
    except RepositoryConnectorError as exc:
        raise RepositoryServiceError(str(exc)) from exc

    credential_id: int | None = None
    secret = payload.get("secret")
    if secret:
        credential = ConnectorCredential(
            tenant_id=tenant_id,
            created_by=user_id,
            connector_type=connector_type,
            display_name=payload.get("name", "UNC repository credential"),
            secret_encrypted=encrypt_secret(json.dumps(secret)),
        )
        session.add(credential)
        await session.flush()
        credential_id = credential.id

    connection = RepositoryConnection(
        tenant_id=tenant_id,
        created_by=user_id,
        updated_by=user_id,
        name=payload.get("name", "Unnamed"),
        description=payload.get("description"),
        connector_type=connector_type,
        config_json=config,
        credential_id=credential_id,
        project_id=payload.get("project_id"),
        is_enabled=payload.get("is_enabled", True),
        scan_schedule=payload.get("scan_schedule"),
    )
    session.add(connection)
    await session.flush()
    return connection.to_redacted_dict()


async def update_connection(
    session: AsyncSession,
    tenant_id: int,
    user_id: int,
    connection_id: int,
    payload: dict[str, Any],
    expected_version: int,
) -> dict[str, Any]:
    conn = await _load_connection(session, tenant_id, connection_id)
    if conn.version != expected_version:
        raise RepositoryServiceError(
            f"Version conflict: expected {expected_version}, found {conn.version}"
        )

    connector = get_repository_connector(conn.connector_type)
    config = payload.get("config")
    if config is not None:
        try:
            await connector.validate_config(config)
        except RepositoryConnectorError as exc:
            raise RepositoryServiceError(str(exc)) from exc
        conn.config_json = config

    if "name" in payload:
        conn.name = payload["name"]
    if "description" in payload:
        conn.description = payload["description"]
    if "project_id" in payload:
        conn.project_id = payload["project_id"]
    if "is_enabled" in payload:
        conn.is_enabled = payload["is_enabled"]
    if "scan_schedule" in payload:
        conn.scan_schedule = payload["scan_schedule"]

    secret = payload.get("secret")
    if secret:
        if conn.credential_id:
            credential = await session.get(ConnectorCredential, conn.credential_id)
            if credential and credential.tenant_id == tenant_id:
                credential.secret_encrypted = encrypt_secret(json.dumps(secret))
                await session.flush()
        else:
            credential = ConnectorCredential(
                tenant_id=tenant_id,
                created_by=user_id,
                connector_type=conn.connector_type,
                display_name=conn.name,
                secret_encrypted=encrypt_secret(json.dumps(secret)),
            )
            session.add(credential)
            await session.flush()
            conn.credential_id = credential.id

    conn.version += 1
    conn.updated_by = user_id
    await session.flush()
    return conn.to_redacted_dict()


async def disable_connection(
    session: AsyncSession,
    tenant_id: int,
    connection_id: int,
    user_id: int,
) -> dict[str, Any]:
    conn = await _load_connection(session, tenant_id, connection_id)
    conn.is_enabled = False
    conn.status = "disabled"
    conn.updated_by = user_id
    await session.flush()
    return conn.to_redacted_dict()


async def _resolve_credentials(
    session: AsyncSession,
    tenant_id: int,
    conn: RepositoryConnection,
    provided_secret: dict[str, Any] | None,
) -> dict[str, Any]:
    if provided_secret:
        return provided_secret
    if not conn.credential_id:
        raise RepositoryServiceError("No credentials configured for this connector")
    credential = await session.get(ConnectorCredential, conn.credential_id)
    if credential is None or credential.tenant_id != tenant_id or not credential.secret_encrypted:
        raise RepositoryServiceError("Connector credential not found")
    try:
        return json.loads(decrypt_secret(credential.secret_encrypted))
    except Exception as exc:
        raise RepositoryServiceError("Unable to read stored credential") from exc


async def test_connection_by_config(
    session: AsyncSession,
    tenant_id: int,
    payload: dict[str, Any],
) -> dict[str, Any]:
    connector_type = payload.get("connector_type", "unc")
    connector = get_repository_connector(connector_type)
    config = payload.get("config") or {}
    secret = payload.get("secret") or {}

    try:
        await connector.validate_config(config)
        result = await connector.test_connection(config, secret)
    except RepositoryConnectorError as exc:
        return {
            "success": False,
            "checks": [{"name": "connection", "status": "failed", "message": str(exc)}],
            "sample": None,
            "warnings": [],
            "tested_at": datetime.now(UTC).isoformat(),
        }

    return _test_result_to_dict(result)


async def test_existing_connection(
    session: AsyncSession,
    tenant_id: int,
    connection_id: int,
) -> dict[str, Any]:
    conn = await _load_connection(session, tenant_id, connection_id)
    connector = get_repository_connector(conn.connector_type)
    credentials = await _resolve_credentials(session, tenant_id, conn, None)
    try:
        await connector.validate_config(conn.config_json)
        result = await connector.test_connection(conn.config_json, credentials)
    except RepositoryConnectorError as exc:
        return {
            "success": False,
            "checks": [{"name": "connection", "status": "failed", "message": str(exc)}],
            "sample": None,
            "warnings": [],
            "tested_at": datetime.now(UTC).isoformat(),
        }
    return _test_result_to_dict(result)


def _test_result_to_dict(result: Any) -> dict[str, Any]:
    return {
        "success": result.success,
        "checks": [
            {"name": c.name, "status": c.status, "message": c.message}
            for c in result.checks
        ],
        "sample": result.sample,
        "warnings": result.warnings,
        "tested_at": result.tested_at.isoformat(),
    }


async def _load_connection(
    session: AsyncSession,
    tenant_id: int,
    connection_id: int,
) -> RepositoryConnection:
    result = await session.execute(
        select(RepositoryConnection).where(
            RepositoryConnection.id == connection_id,
            RepositoryConnection.tenant_id == tenant_id,
        )
    )
    conn = result.scalar_one_or_none()
    if conn is None:
        raise RepositoryServiceError("Repository connector not found")
    return conn
