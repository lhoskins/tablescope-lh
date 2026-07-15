"""Repository connector registry."""

from __future__ import annotations

from typing import Any

from app.connectors.repositories.base import RepositoryConnector, RepositoryConnectorError

_REGISTRY: dict[str, RepositoryConnector] = {}


def register_repository_connector(
    connector_type: str,
    connector: RepositoryConnector,
) -> None:
    """Register a repository connector implementation."""
    if not connector_type:
        raise ValueError("connector_type must be a non-empty string")
    _REGISTRY[connector_type] = connector


def get_repository_connector(connector_type: str) -> RepositoryConnector:
    """Return the connector implementation for ``connector_type`` or fail safely."""
    connector = _REGISTRY.get(connector_type)
    if connector is None:
        raise RepositoryConnectorError(
            f"Unknown repository connector type: {connector_type!r}"
        )
    return connector


def list_repository_connector_types() -> list[dict[str, Any]]:
    """Return metadata for all registered connectors."""
    return [
        {
            "connector_type": ct,
            "name": ct.replace("_", " ").title(),
        }
        for ct in sorted(_REGISTRY.keys())
    ]
