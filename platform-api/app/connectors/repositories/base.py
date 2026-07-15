"""Abstract base for repository connectors.

Repository connectors are responsible for authentication, enumeration, metadata
retrieval, and streaming for a single repository type.  The scanner service
sits on top of this interface and owns persistence, profiling, change detection,
and audit.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.connectors.repositories.types import (
    ConnectionTestResult,
    RepositoryItem,
    RepositoryPage,
)


class RepositoryConnectorError(Exception):
    """User-facing, sanitized connector failure."""


class RepositoryConnector(ABC):
    """Async interface for a repository connector."""

    connector_type: str = ""

    @abstractmethod
    async def validate_config(self, config: dict[str, Any]) -> None:
        """Validate non-secret configuration. Raises RepositoryConnectorError."""

    @abstractmethod
    async def test_connection(
        self,
        config: dict[str, Any],
        credentials: dict[str, Any],
    ) -> ConnectionTestResult:
        """Run a structured, sanitized connection test."""

    @abstractmethod
    async def list_items(
        self,
        config: dict[str, Any],
        credentials: dict[str, Any],
        checkpoint: dict[str, Any] | None = None,
        page_size: int = 500,
    ) -> RepositoryPage:
        """Return one bounded page of repository items.

        The checkpoint is an opaque dictionary produced by the connector; the
        scanner passes it back to resume enumeration.
        """

    async def get_item_metadata(
        self,
        config: dict[str, Any],
        credentials: dict[str, Any],
        item_ref: str,
    ) -> RepositoryItem | None:
        """Return metadata for a single item by external_id or relative path."""
        return None  # pragma: no cover

    async def read_item(
        self,
        config: dict[str, Any],
        credentials: dict[str, Any],
        item_ref: str,
        limit_bytes: int | None = None,
    ) -> bytes:
        """Return the bytes of a file, optionally capped."""
        raise RepositoryConnectorError("Reading item content is not supported by this connector.")  # pragma: no cover

    def get_change_token(self, item: RepositoryItem) -> str | None:
        """Return the best available change token for the item.

        Prefer source ETag/version, then content hash, then modified timestamp.
        """
        if item.etag:
            return item.etag
        if item.content_hash:
            return item.content_hash
        if item.modified_at is not None:
            return item.modified_at.isoformat()
        return None

    async def close(self) -> None:
        """Release connector-specific resources."""
        return None  # pragma: no cover
