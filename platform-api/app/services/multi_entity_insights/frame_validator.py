"""Post-query analytical-frame validator.

Validates that the executed result set contains exactly the requested entities,
one row per declared final grain, and no duplicate or fan-out rows.
"""

from __future__ import annotations

from typing import Any

from app.services.multi_entity_insights.contract import FrameValidationResult, MultiEntityPlan


class MultiEntityFrameValidator:
    def __init__(self, plan: MultiEntityPlan) -> None:
        self.plan = plan

    def _grain_values(self, row: dict[str, Any]) -> tuple[Any, ...]:
        return tuple(row.get(g) for g in self.plan.final_grain)

    def _entity_name_value(self, row: dict[str, Any]) -> Any:
        return row.get(self.plan.entity.name_column or self.plan.entity.id_column)

    def validate(self, result: dict[str, Any] | None) -> FrameValidationResult:
        if not result or not result.get("rows"):
            return FrameValidationResult(
                status="rejected",
                entity_count=0,
                period_count=None,
                reason="Query returned no rows",
            )

        rows = result["rows"]
        columns = result.get("columns", [])
        missing_columns = [g for g in self.plan.final_grain if g not in columns]
        if missing_columns:
            return FrameValidationResult(
                status="rejected",
                entity_count=0,
                period_count=None,
                reason=f"Missing final-grain columns: {missing_columns}",
            )

        seen_grain: set[tuple[Any, ...]] = set()
        duplicate_count = 0
        entity_values: set[Any] = set()
        for row in rows:
            grain = self._grain_values(row)
            if grain in seen_grain:
                duplicate_count += 1
            seen_grain.add(grain)
            entity_values.add(self._entity_name_value(row))

        requested = set(self.plan.entity.requested_names)
        missing_requested = sorted(requested - entity_values)

        period_col = self.plan.time.period_column
        period_count = None
        if period_col and period_col in columns:
            period_count = len({row.get(period_col) for row in rows})

        warnings: list[str] = []
        status: Any = "valid"
        if duplicate_count:
            status = "valid_with_warnings"
            warnings.append(f"{duplicate_count} duplicate final-grain rows detected")
        if missing_requested:
            status = "valid_with_warnings"
            warnings.append(
                f"Requested entities not found: {', '.join(missing_requested)}"
            )
        if len(entity_values) < 2:
            status = "rejected"
            return FrameValidationResult(
                status=status,
                entity_count=len(entity_values),
                period_count=period_count,
                duplicate_grain_rows=duplicate_count,
                missing_requested_entities=missing_requested,
                warnings=warnings,
                reason="Fewer than two resolved entities in result frame",
            )
        if len(entity_values) > 3:
            status = "rejected"
            return FrameValidationResult(
                status=status,
                entity_count=len(entity_values),
                period_count=period_count,
                duplicate_grain_rows=duplicate_count,
                missing_requested_entities=missing_requested,
                warnings=warnings,
                reason="More than three resolved entities in result frame",
            )

        return FrameValidationResult(
            status=status,
            entity_count=len(entity_values),
            period_count=period_count,
            duplicate_grain_rows=duplicate_count,
            missing_requested_entities=missing_requested,
            warnings=warnings,
        )
