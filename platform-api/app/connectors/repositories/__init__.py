"""Repository connector abstraction for enterprise file repositories."""

from __future__ import annotations

from app.connectors.repositories.base import RepositoryConnector, RepositoryConnectorError
from app.connectors.repositories.registry import (
    get_repository_connector,
    list_repository_connector_types,
    register_repository_connector,
)
from app.connectors.repositories.types import (
    ConnectionCheck,
    ConnectionTestResult,
    RepositoryItem,
    RepositoryPage,
)
from app.connectors.repositories.unc import UNCRepositoryConnector

register_repository_connector("unc", UNCRepositoryConnector())

__all__ = [
    "ConnectionCheck",
    "ConnectionTestResult",
    "get_repository_connector",
    "list_repository_connector_types",
    "register_repository_connector",
    "RepositoryConnector",
    "RepositoryConnectorError",
    "RepositoryItem",
    "RepositoryPage",
    "UNCRepositoryConnector",
]
