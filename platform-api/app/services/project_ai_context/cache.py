
from __future__ import annotations

from typing import Any


class ProjectAIContextCache:
    """In-process cache keyed by (tenant_id, project_id, context_version)."""

    def __init__(self) -> None:
        self._cache: dict[tuple[int, int, int], dict[str, Any]] = {}

    def get(self, tenant_id: int, project_id: int, version: int) -> dict[str, Any] | None:
        return self._cache.get((tenant_id, project_id, version))

    def set(self, tenant_id: int, project_id: int, version: int, value: dict[str, Any]) -> None:
        self._cache[(tenant_id, project_id, version)] = value

    def invalidate(self, tenant_id: int, project_id: int) -> None:
        keys = [k for k in self._cache if k[0] == tenant_id and k[1] == project_id]
        for k in keys:
            del self._cache[k]



