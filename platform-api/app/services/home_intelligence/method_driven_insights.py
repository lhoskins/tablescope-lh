from __future__ import annotations

import sys
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.services import deep_analysis
from app.services.visualization_engine import (
    business_dimensions,
    derive_shape,
)

from .card_builder import _card
from .chart_builder import _build_chart
from .query_helpers import _deep_analysis_sql, _distinct_years, _quote, _safe_query, _target_measure, logger

if TYPE_CHECKING:
    from .query_helpers import QueryRunner
    from .schema_context import ProjectContext

_hi = sys.modules[__package__]



async def _method_driven_insights(
    project: Project,
    ctx: ProjectContext,
    runner: QueryRunner,
    session: AsyncSession | None,
    *,
    tenant_id: int | None,
    max_per_table: int = 4,
    max_total: int = 10,
    max_rows: int = 5000,
) -> list[dict[str, Any]]:
    """Deeper analysis driven by governed analytical methods, not table shapes.

    For each table we ask :mod:`deep_analysis` which analytical *intents* the
    business columns can support, execute each through the Analytical Method
    Engine (the same governed path Business Insights use, so R-first execution,
    tenant governance and provenance all apply), and keep only results that
    clear the materiality gate. A method that ran cleanly but found nothing
    produces no card — that is what makes this section deeper rather than
    padded.

    Fail-closed per analysis: an engine problem skips one card, never the run.
    """
    if runner is None or session is None:
        return []
    if _hi.get_engine_mode() == _hi.EngineMode.OFF:
        return []

    cards: list[dict[str, Any]] = []
    for table in ctx.tables:
        if len(cards) >= max_total:
            break
        try:
            probe = await _safe_query(
                runner, f'SELECT * FROM {_quote(table.view_name)} LIMIT 200'
            )
        except Exception:
            continue
        if not probe or not probe.get("rows") or not probe.get("columns"):
            continue

        columns = probe["columns"]
        rows = probe["rows"]
        shape = derive_shape(columns, rows)
        period_col = shape.time_columns[0] if shape.time_columns else None
        dims = business_dimensions(shape, rows)
        period_count = 0
        if period_col:
            period_count = len(
                {str(r.get(period_col)) for r in rows if r.get(period_col) is not None}
            )

        distinct_years = _distinct_years(rows, period_col) if period_col else 0
        target_col = _target_measure(shape.measures)
        # A target/budget column is a baseline to compare against, not a KPI to
        # analyse in its own right.
        measures = [m for m in shape.measures if m != target_col]

        specs = deep_analysis.plan_deep_analyses(
            table_title=table.view_name,
            period_column=period_col,
            measures=measures,
            dimensions=dims,
            row_count=shape.row_count,
            period_count=period_count,
            distinct_years=distinct_years,
            target_column=target_col,
            max_per_table=max_per_table,
        )

        for spec in specs:
            if len(cards) >= max_total:
                break
            if spec.intent == "continuous_prediction":
                spec = replace(
                    spec,
                    roles={**spec.roles, "explanatory": ",".join(measures[1:5])},
                )
            sql = _deep_analysis_sql(table.view_name, spec, max_rows)
            if not sql:
                continue
            try:
                result = await _safe_query(runner, sql)
            except Exception:
                continue
            if not result or not result.get("rows"):
                continue

            try:
                envelope = await _hi.analyze_methods(
                    session,
                    tenant_id=tenant_id,
                    columns=result.get("columns", []),
                    rows=result.get("rows", []),
                    question=spec.question,
                    intent=spec.intent,
                )
            except Exception as exc:  # pragma: no cover - engine is fail-closed
                logger.warning(
                    "deep analysis: engine failed for %s/%s: %s",
                    table.view_name, spec.intent, exc,
                )
                continue
            if not envelope:
                continue

            materiality = deep_analysis.assess_materiality(spec.intent, envelope)
            if not materiality.material:
                logger.debug(
                    "deep analysis: %s on %s suppressed — %s",
                    spec.intent, table.view_name, materiality.reason,
                )
                continue

            presentation = deep_analysis.spec_presentation(spec)
            chart = _build_chart(
                presentation["chart"],
                spec.title,
                result,
                label_hint=spec.group_by or spec.roles.get("period", ""),
                value_hint=spec.roles.get("measure", ""),
                value_hint_2=spec.roles.get("measure2", ""),
            )
            card = _card(
                project,
                f"analysis_{spec.intent}",
                "informational",
                spec.title,
                deep_analysis.card_summary(spec, materiality, envelope),
                chart=chart,
                result=result,
                tables=[table.view_name],
                sql=sql,
            )
            if not card:
                continue
            card["group"] = "analysis"
            # Provenance: the R Analytics badge and Explain panel read this.
            card["analyticalMethod"] = envelope
            card["method_envelope"] = envelope
            if presentation["layers"]:
                card["analyticalLayers"] = presentation["layers"]
            if materiality.highlight:
                card["evidenceHighlight"] = materiality.highlight
            cards.append(card)

    return cards
