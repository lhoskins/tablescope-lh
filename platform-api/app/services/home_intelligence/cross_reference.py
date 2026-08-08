from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services import card_diagnostics, deep_analysis
from app.services.analytical_method_engine import (
    analyze as analyze_methods,
)
from app.services.visualization_engine import (
    derive_shape,
)

from .query_helpers import _agg_for_measure, _quote, _safe_query

if TYPE_CHECKING:
    from .query_helpers import QueryRunner



async def _run_cross_reference(
    session: AsyncSession,
    runner: QueryRunner,
    *,
    card_table: Any,
    card_measure: str,
    card_period: str,
    other_table: Any,
    tenant_id: int | None,
    max_rows: int,
    max_measures: int = 2,
) -> list[dict[str, Any]]:
    """Test whether another data source moves with this finding.

    "Does mfg_labor_rates show the same pattern?" is a question the system can
    answer itself, and leaving it for the reader to click was the weakest part
    of the drill-down. Both tables are aggregated onto their own period column,
    joined on the period, and the pair is handed to the governed correlation
    method. A material result is a **candidate causation factor** — positive or
    negative — which is the thing worth chasing when deciding what to do.

    Immaterial pairings produce nothing: an uncorrelated table is not evidence.
    """
    try:
        probe = await _safe_query(
            runner, f'SELECT * FROM {_quote(other_table.view_name)} LIMIT 200'
        )
    except Exception:
        return []
    if not probe or not probe.get("rows") or not probe.get("columns"):
        return []

    shape = derive_shape(probe["columns"], probe["rows"])
    if not shape.time_columns or not shape.measures:
        return []
    other_period = shape.time_columns[0]

    found: list[dict[str, Any]] = []
    for other_measure in shape.measures[:max_measures]:
        sql = _cross_reference_sql(
            card_table.view_name, card_measure, card_period,
            other_table.view_name, other_measure, other_period, max_rows,
        )
        try:
            result = await _safe_query(runner, sql)
        except Exception:
            continue
        # Correlating a handful of overlapping periods is not evidence.
        if not result or len(result.get("rows") or []) < 8:
            continue

        left, right = f"{card_measure}", f"{other_measure}__ref"
        try:
            envelope = await analyze_methods(
                session,
                tenant_id=tenant_id,
                columns=result.get("columns", []),
                rows=result.get("rows", []),
                question=(
                    f"Does {other_measure} in {other_table.view_name} move with "
                    f"{card_measure}?"
                ),
                intent="relationship_numeric",
            )
        except Exception:
            continue
        if not envelope:
            continue
        materiality = deep_analysis.assess_materiality("relationship_numeric", envelope)
        if not materiality.material:
            continue

        direction = _relationship_direction(envelope)
        found.append(
            {
                "stage": card_diagnostics.STAGE_CORROBORATE,
                "intent": "relationship_numeric",
                "title": f"{_humanize_column(other_measure)} in {other_table.view_name}",
                "question": (
                    f"Does {_humanize_column(other_measure)} in "
                    f"{other_table.view_name} move with {_humanize_column(card_measure)}?"
                ),
                "rationale": (
                    "A measure in an independent source that tracks this one is a "
                    "candidate cause or lever; one that does not rules that source out."
                ),
                "finding": f"{direction} {materiality.reason}".strip(),
                "highlight": materiality.highlight,
                "triggeredBy": f"cross-reference against {other_table.view_name}",
                "analyticalMethod": envelope,
                "sql": sql,
                "result": result,
                "presentation": {"chart": "scatter", "layers": ["regression_line"]},
                "markers": {},
                "roles": {"x": left, "y": right},
                "crossReference": other_table.view_name,
            }
        )
    return found


def _relationship_direction(envelope: dict[str, Any]) -> str:
    """Whether the other source moves with this finding or against it."""
    results = (envelope or {}).get("results")
    if not isinstance(results, dict):
        return ""
    for key in ("correlation", "estimate", "rho", "r"):
        value = results.get(key)
        if isinstance(value, int | float) and not isinstance(value, bool):
            if value > 0:
                return "Moves in the same direction \u2014 rises together."
            if value < 0:
                return "Moves in the opposite direction \u2014 one rises as the other falls."
    return ""


def _humanize_column(name: str) -> str:
    """`unit_cost` / `UnitCost` -> `Unit Cost`, for question text."""
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(name).replace("_", " "))
    return " ".join(w.capitalize() for w in spaced.split())


def _cross_reference_sql(
    left_table: str, left_measure: str, left_period: str,
    right_table: str, right_measure: str, right_period: str,
    max_rows: int,
) -> str:
    """Two measures from two tables aligned on their shared timeline."""
    left_agg = _agg_for_measure(left_measure)
    right_agg = _agg_for_measure(right_measure)
    return (
        f'SELECT a.{_quote(left_period)}, a.{_quote(left_measure)}, '
        f'b.{_quote(right_measure + "__ref")} FROM '
        f'(SELECT {_quote(left_period)}, {left_agg}({_quote(left_measure)}) '
        f'AS {_quote(left_measure)} FROM {_quote(left_table)} '
        f'GROUP BY {_quote(left_period)}) a JOIN '
        f'(SELECT {_quote(right_period)} AS {_quote(left_period)}, '
        f'{right_agg}({_quote(right_measure)}) AS {_quote(right_measure + "__ref")} '
        f'FROM {_quote(right_table)} GROUP BY {_quote(right_period)}) b '
        f'ON a.{_quote(left_period)} = b.{_quote(left_period)} '
        f'ORDER BY a.{_quote(left_period)} LIMIT {max_rows}'
    )
