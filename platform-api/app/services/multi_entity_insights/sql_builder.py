"""Grain-safe multi-source SQL builder.

Each fact/source table is independently aggregated to its declared grain before
any join. The final SELECT joins aggregate CTEs on entity id (+ period) and
filters to the requested named entities. Ratio-of-sums measures are computed in
the outer query to avoid fan-out duplication.
"""

from __future__ import annotations

import hashlib
import json

from app.services.multi_entity_insights.contract import MeasureSpec, MultiEntityPlan, SourceSpec


class MultiEntitySQLBuilder:
    def __init__(self, plan: MultiEntityPlan) -> None:
        self.plan = plan

    def _quote(self, identifier: str) -> str:
        return '"' + str(identifier).replace('"', '""') + '"'

    def _literal(self, value: str) -> str:
        return "'" + str(value).replace("'", "''") + "'"

    def _alias(self, table: str) -> str:
        return next(
            (s.alias or f"{s.table}_agg" for s in self.plan.sources if s.table == table),
            table[:3].lower(),
        )

    def _period_expression(self, alias: str, period_col: str | None) -> str:
        if not period_col:
            return "NULL"
        # Use the period column as-is; callers can normalize date casts through
        # the existing teiid_sql pipeline.
        return f"{self._quote(alias)}.{self._quote(period_col)}"

    def _build_cte(self, source: SourceSpec) -> tuple[str, list[MeasureSpec]]:
        alias = source.alias or f"{source.table}_agg"
        grain = [self._quote(alias) + "." + self._quote(g) for g in source.grain]
        entity_col = self.plan.entity.id_column
        name_col = self.plan.entity.name_column or entity_col
        selects = [f"{self._quote(alias)}.{self._quote(entity_col)} AS {self._quote(entity_col)}"]
        if name_col != entity_col and name_col in source.columns:
            selects.append(f"{self._quote(alias)}.{self._quote(name_col)} AS {self._quote(name_col)}")
        if source.grain and len(source.grain) > 1:
            period_col = source.grain[1]
            selects.append(f"{self._quote(alias)}.{self._quote(period_col)} AS {self._quote(period_col)}")

        source_measures: list[MeasureSpec] = []
        for m in self.plan.measures:
            if m.table == source.table:
                source_measures.append(m)
                if m.derived_expression:
                    selects.append(f"{m.derived_expression} AS {self._quote(m.name)}")
                elif m.numerator_column and m.denominator_column:
                    selects.append(
                        f"SUM({self._quote(alias)}.{self._quote(m.numerator_column)}) AS {self._quote(m.name + '_num')}, "
                        f"SUM({self._quote(alias)}.{self._quote(m.denominator_column)}) AS {self._quote(m.name + '_den')}"
                    )
                else:
                    agg = m.aggregation.upper()
                    col = self._quote(alias) + "." + self._quote(m.column)
                    selects.append(f"{agg}(CAST({col} AS double)) AS {self._quote(m.name)}")

        group_by = ", ".join(grain)
        return (
            f"{self._quote(alias)} AS (\n"
            f"  SELECT {', '.join(selects)}\n"
            f"  FROM {self._quote(source.table)} {self._quote(alias)}\n"
            f"  GROUP BY {group_by}\n"
            f")",
            source_measures,
        )

    def _build_final_select(self, cte_aliases: list[str]) -> str:
        entity_col = self.plan.entity.id_column
        name_col = self.plan.entity.name_column or entity_col
        period_col = self.plan.time.period_column

        first_alias = cte_aliases[0]
        selects = [
            f"{self._quote(first_alias)}.{self._quote(entity_col)} AS {self._quote(entity_col)}",
        ]
        if name_col != entity_col:
            selects.append(f"{self._quote(first_alias)}.{self._quote(name_col)} AS {self._quote(name_col)}")
        if period_col:
            selects.append(
                f"{self._quote(first_alias)}.{self._quote(period_col)} AS {self._quote(period_col)}"
            )

        for m in self.plan.measures:
            if m.numerator_column and m.denominator_column:
                selects.append(
                    f"{self._quote(m.name + '_num')} / NULLIF({self._quote(m.name + '_den')}, 0) "
                    f"AS {self._quote(m.name)}"
                )
            else:
                selects.append(f"{self._quote(m.name)}")

        from_clause = self._quote(first_alias)
        for i, alias in enumerate(cte_aliases[1:], start=1):
            prev_alias = cte_aliases[i - 1]
            on_conds = [
                f"{self._quote(prev_alias)}.{self._quote(entity_col)} = {self._quote(alias)}.{self._quote(entity_col)}"
            ]
            if period_col:
                on_conds.append(
                    f"{self._quote(prev_alias)}.{self._quote(period_col)} = {self._quote(alias)}.{self._quote(period_col)}"
                )
            from_clause += f"\n  LEFT JOIN {self._quote(alias)} ON {' AND '.join(on_conds)}"

        # Filter to requested entity names using the name column.
        name_literals = ", ".join(self._literal(n) for n in self.plan.entity.requested_names)
        where = f"WHERE {self._quote(first_alias)}.{self._quote(name_col)} IN ({name_literals})"

        order_by = f"{self._quote(first_alias)}.{self._quote(entity_col)}"
        if period_col:
            order_by += f", {self._quote(first_alias)}.{self._quote(period_col)}"

        return (
            f"SELECT {', '.join(selects)}\n"
            f"FROM {from_clause}\n"
            f"{where}\n"
            f"ORDER BY {order_by}"
        )

    def build_sql(self) -> str:
        """Return the aggregate-before-join SQL for the plan."""
        ctes: list[str] = []
        for source in self.plan.sources:
            cte, _ = self._build_cte(source)
            ctes.append(cte)
        cte_aliases = [s.alias or f"{s.table}_agg" for s in self.plan.sources]
        final = self._build_final_select(cte_aliases)
        return "WITH\n" + ",\n".join(ctes) + "\n" + final

    def query_hash(self) -> str:
        """Stable SHA-256 hash for lineage."""
        payload = json.dumps({
            "sql": self.build_sql(),
            "entity_names": self.plan.entity.requested_names,
            "final_grain": self.plan.final_grain,
        }, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()
