"""Shared data types for repository connectors."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class ConnectionCheck:
    """A single named check produced by a connection test."""

    name: str
    status: str  # passed | failed | skipped
    message: str | None = None


@dataclass
class ConnectionTestResult:
    """Sanitized, structured result of a repository connection test."""

    success: bool
    checks: list[ConnectionCheck]
    sample: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)
    tested_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class RepositoryItem:
    """A normalized file or directory returned by a repository connector."""

    external_id: str
    name: str
    relative_path: str  # relative to effective scan root, forward-slash separated
    parent_path: str  # forward-slash separated
    item_type: str  # file | directory | symlink | other
    size: int | None = None
    created_at: datetime | None = None
    modified_at: datetime | None = None
    etag: str | None = None
    content_hash: str | None = None
    mime_type: str | None = None
    extension: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RepositoryPage:
    """One page of repository items plus a resumption checkpoint."""

    items: list[RepositoryItem]
    checkpoint: dict[str, Any] | None = None
    has_more: bool = False
