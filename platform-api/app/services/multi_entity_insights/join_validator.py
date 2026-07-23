"""Relationship and observed-cardinality preflight validator.

Runs bounded preflight SQL against a Teiid runner to verify declared
cardinality and detect one-to-many or many-to-many fan-out before the
analytical query is executed.
"""

from __future__ import annotations

from typing import Any

from app.services.multi_entity_insights.contract import (
    JoinValidationResult,
    MultiEntityPlan,
    RelationshipSpec,
)

# Reject if the child-side pre-aggregation would duplicate parent rows by >10%.
_FANOUT_REJECTION_THRESHOLD = 1.10


def _quote(value: Any) -> str:
    """Quote a SQL identifier."""
    return '"' + str(value).replace('"', '""') + '"'


def _safe_float(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class MultiEntityJoinValidator:
    """Deterministic join validator for multi-source plans."""

    def __init__(self, runner: Any) -> None:
        self.runner = runner

    async def _run_one(
        self, sql: str
    ) -> dict[str, Any] | None:
        if self.runner is None:
            return None
        try:
            return await self.runner(sql)
        except Exception:
            return None

    def _row_count_sql(self, table: str) -> str:
        return f"SELECT COUNT(*) AS n FROM {_quote(table)}"

    def _distinct_sql(self, table: str, keys: list[str]) -> str:
        key_expr = ", ".join(_quote(k) for k in keys)
        return f"SELECT COUNT(DISTINCT {key_expr}) AS distinct_keys FROM {_quote(table)}"

    def _duplicate_side_sql(self, table: str, keys: list[str]) -> str:
        key_expr = ", ".join(_quote(k) for k in keys)
        return (
            f"SELECT COUNT(*) AS duplicate_rows FROM ("
            f"SELECT {key_expr} FROM {_quote(table)} "
            f"GROUP BY {key_expr} HAVING COUNT(*) > 1"
            f") AS _dup"
        )

    def _join_cardinality_sql(
        self,
        left: str,
        left_keys: list[str],
        right: str,
        right_keys: list[str],
        period_keys: list[tuple[str, str]] | None = None,
    ) -> str:
        left_quoted = _quote(left)
        right_quoted = _quote(right)
        join_conds = [
            f"{_quote(left)}.{_quote(lk)} = {_quote(right)}.{_quote(rk)}"
            for lk, rk in zip(left_keys, right_keys, strict=False)
        ]
        if period_keys:
            join_conds.extend(
                f"{_quote(left)}.{_quote(lp)} = {_quote(right)}.{_quote(rp)}"
                for lp, rp in period_keys
            )
        return (
            f"SELECT "
            f"COUNT(*) AS joined_rows, "
            f"COUNT(DISTINCT {', '.join(f'{_quote(left)}.{_quote(k)}' for k in left_keys)}) AS distinct_left, "
            f"COUNT(DISTINCT {', '.join(f'{_quote(right)}.{_quote(k)}' for k in right_keys)}) AS distinct_right "
            f"FROM {left_quoted} "
            f"JOIN {right_quoted} ON {' AND '.join(join_conds)}"
        )

    async def validate_relationship(
        self,
        rel: RelationshipSpec,
        period_keys: list[tuple[str, str]] | None = None,
    ) -> JoinValidationResult:
        left = rel.left_table
        right = rel.right_table
        left_keys = rel.left_key
        right_keys = rel.right_key

        left_count = await self._run_one(self._row_count_sql(left))
        right_count = await self._run_one(self._row_count_sql(right))
        left_distinct = await self._run_one(self._distinct_sql(left, left_keys))
        right_distinct = await self._run_one(self._distinct_sql(right, right_keys))

        left_n = int((left_count.get("rows") or [{}])[0].get("n", 0)) if left_count else 0
        right_n = int((right_count.get("rows") or [{}])[0].get("n", 0)) if right_count else 0
        left_d = int((left_distinct.get("rows") or [{}])[0].get("distinct_keys", 0)) if left_distinct else 0
        right_d = int((right_distinct.get("rows") or [{}])[0].get("distinct_keys", 0)) if right_distinct else 0

        # Detect duplicates on the declared "one" side.
        duplicate_result = await self._run_one(self._duplicate_side_sql(left, left_keys))
        duplicates_one_side = int(
            (duplicate_result.get("rows") or [{}])[0].get("duplicate_rows", 0)
        ) if duplicate_result else 0

        # Observed cardinality from the join itself.
        join_result = await self._run_one(
            self._join_cardinality_sql(left, left_keys, right, right_keys, period_keys)
        )
        if join_result and join_result.get("rows"):
            row = join_result["rows"][0]
            joined_rows = int(row.get("joined_rows", 0))
            distinct_left = int(row.get("distinct_left", 0))
            distinct_right = int(row.get("distinct_right", 0))
            fanout = joined_rows / max(distinct_left, 1) if distinct_left else None
            unmatched = (distinct_left - distinct_right) / max(distinct_left, 1) if distinct_left else None
        else:
            joined_rows = 0
            distinct_left = 0
            distinct_right = 0
            fanout = None
            unmatched = None

        # Determine observed cardinality.
        observed: Any = None
        if fanout is not None:
            if fanout <= 1.05:
                observed = "one_to_one"
            elif fanout <= _FANOUT_REJECTION_THRESHOLD:
                observed = "one_to_many"
            else:
                observed = "many_to_many"

        status: Any = "valid"
        reason: str | None = None
        if duplicates_one_side and rel.declared_cardinality in {"one_to_one", "one_to_many"}:
            status = "valid_with_warnings"
            reason = f"Duplicate keys on {left} ({duplicates_one_side} groups)"
        if observed == "many_to_many":
            status = "rejected"
            reason = f"Many-to-many fan-out detected (fanout_ratio={fanout:.2f})"
        elif fanout is not None and fanout > _FANOUT_REJECTION_THRESHOLD:
            status = "rejected"
            reason = f"Row multiplication risk exceeds threshold (fanout_ratio={fanout:.2f})"

        return JoinValidationResult(
            status=status,
            reason=reason,
            observed_cardinality=observed,
            fanout_ratio=fanout,
            unmatched_rate=unmatched,
            left_row_count=left_n,
            right_row_count=right_n,
            left_key_distinct=left_d,
            right_key_distinct=right_d,
            duplicates_on_one_side=duplicates_one_side,
        )

    async def validate_plan(self, plan: MultiEntityPlan) -> MultiEntityPlan:
        """Run preflight checks on all plan relationships and update the plan.

        Raises ``ValueError`` if any relationship is rejected.
        """
        validated_rels: list[RelationshipSpec] = []
        period_keys: list[tuple[str, str]] = []
        if plan.time.period_column:
            period_keys = [(plan.time.period_column, plan.time.period_column)]

        for rel in plan.relationships:
            result = await self.validate_relationship(rel, period_keys=period_keys or None)
            if result.status == "rejected":
                raise ValueError(
                    f"Join between {rel.left_table} and {rel.right_table} rejected: {result.reason}"
                )
            validated_rels.append(
                RelationshipSpec(
                    left_table=rel.left_table,
                    right_table=rel.right_table,
                    left_key=rel.left_key,
                    right_key=rel.right_key,
                    declared_cardinality=rel.declared_cardinality,
                    observed_cardinality=result.observed_cardinality,
                    fanout_ratio=result.fanout_ratio,
                    unmatched_rate=result.unmatched_rate,
                    validation_status=result.status,
                    rejection_reason=result.reason,
                )
            )
        plan.relationships = validated_rels
        return plan
