from __future__ import annotations

from typing import Any

from app.models import (
    KnowledgeGraph,
)

MAX_INCREMENTAL_AFFECTED = 50


class _ChangeSet:
    def __init__(self, items: list[dict[str, Any]]) -> None:
        self.items = items

    def has(self, scope: str) -> bool:
        return any(item.get("change_scope") == scope for item in self.items)

    def entity_types(self) -> set[str]:
        return {str(item.get("entity_type") or "unknown") for item in self.items}

    def count(self) -> int:
        return len(self.items)


class GraphImpactAnalyzer:
    """Decide whether a source change set can be handled incrementally."""

    async def analyze(
        self,
        change_set: list[dict[str, Any]],
        *,
        current_graph: KnowledgeGraph | None = None,
    ) -> dict[str, Any]:
        changes = _ChangeSet(change_set)

        if not change_set:
            return {
                "scope": "none",
                "safe_incremental": False,
                "fallback_reason": "Empty change set",
                "affected_entity_types": [],
                "affected_entity_ids": [],
            }

        if changes.has("schema"):
            return {
                "scope": "full",
                "safe_incremental": False,
                "fallback_reason": "Schema-level source changes require a full rebuild",
                "affected_entity_types": sorted(changes.entity_types()),
                "affected_entity_ids": [],
            }

        structural_types = {"data_source", "saved_query", "dashboard", "repository_connection"}
        if changes.entity_types() & structural_types:
            # A structural source change is allowed to be incremental if the
            # number of affected entities is small; otherwise fall back to full.
            if changes.count() > MAX_INCREMENTAL_AFFECTED:
                return {
                    "scope": "full",
                    "safe_incremental": False,
                    "fallback_reason": f"Too many structural source changes ({changes.count()} > {MAX_INCREMENTAL_AFFECTED})",
                    "affected_entity_types": sorted(changes.entity_types()),
                    "affected_entity_ids": [],
                }

        if changes.count() > MAX_INCREMENTAL_AFFECTED:
            return {
                "scope": "full",
                "safe_incremental": False,
                "fallback_reason": f"Too many entity changes ({changes.count()} > {MAX_INCREMENTAL_AFFECTED})",
                "affected_entity_types": sorted(changes.entity_types()),
                "affected_entity_ids": [],
            }

        if current_graph is not None and current_graph.lifecycle_status in (
            "failed",
            "missing",
            "degraded",
        ):
            return {
                "scope": "full",
                "safe_incremental": False,
                "fallback_reason": f"Current graph status is {current_graph.lifecycle_status}; a full rebuild is safer",
                "affected_entity_types": sorted(changes.entity_types()),
                "affected_entity_ids": [],
            }

        return {
            "scope": "incremental",
            "safe_incremental": True,
            "fallback_reason": None,
            "affected_entity_types": sorted(changes.entity_types()),
            "affected_entity_ids": [
                item.get("entity_id")
                for item in change_set
                if item.get("entity_id") is not None
            ],
        }


