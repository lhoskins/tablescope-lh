from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.models.project import Project
from app.services.chart_catalog import fit_ranked
from app.services.visualization_engine import (
    _catalog_facts,
    _catalog_shape,
    _detect_semantic_roles,
    business_dimensions,
    derive_shape,
)

from .card_builder import _card
from .chart_templates import _SHAPE_TEMPLATE_MIN_FIT, _TEMPLATE_BUILDERS
from .query_helpers import _quote, _safe_query

if TYPE_CHECKING:
    from .query_helpers import QueryRunner
    from .schema_context import ProjectContext



async def _shape_template_insights(
    project: Project,
    ctx: ProjectContext,
    runner: QueryRunner,
    *,
    max_per_table: int = 2,
    max_total: int = 6,
    max_rows: int = 200,
) -> list[dict[str, Any]]:
    """Generate extra insight cards from raw table shapes that support richer charts.

    Probes each real table, classifies its columns, then iterates over the
    markdown-driven chart catalog to run the highest-scoring SQL template whose
    builder exists. New families appear automatically when (a) the catalog
    declares them eligible and (b) a builder is added here.
    """
    if runner is None:
        return []
    cards: list[dict[str, Any]] = []

    for table in ctx.tables:
        if len(cards) >= max_total:
            break

        try:
            probe = await _safe_query(runner, f'SELECT * FROM {_quote(table.view_name)} LIMIT 50')
        except Exception:
            continue
        if not probe or not probe.get("rows"):
            continue

        columns = probe.get("columns", [])
        rows = probe.get("rows", [])
        if not columns:
            continue

        shape = derive_shape(columns, rows)
        semantic_roles = _detect_semantic_roles(columns, rows) if columns else {}
        catalog_summary = _catalog_shape(shape, rows, semantic_roles)
        # Rank by per-dataset fit confidence, not the family's base score: a
        # table with two dimensions is *eligible* for a heatmap, but a heatmap
        # is only a good fit when both cardinalities are moderate. Base-score
        # ordering made nearly every Deeper-analysis card a heatmap.
        catalog_facts = _catalog_facts(shape, rows)
        eligible = [
            rule
            for rule, confidence in fit_ranked(catalog_summary, catalog_facts)
            if confidence >= _SHAPE_TEMPLATE_MIN_FIT
        ]

        # Only business-meaningful dimensions may drive a Deeper-analysis card.
        # Falling back to identifier columns produced charts keyed on order ids
        # and SKUs — technically renderable, analytically worthless. A table
        # with nothing but keys and periods simply yields no shape card.
        dims = business_dimensions(shape, rows)
        if not dims and not shape.measures:
            continue
        measures = shape.measures

        generated: list[dict[str, Any]] = []
        for rule in eligible:
            if len(generated) >= max_per_table:
                break
            builder = _TEMPLATE_BUILDERS.get(rule.family)
            if not builder:
                continue
            g = await builder(table, shape, dims, measures, semantic_roles, runner, max_rows)
            if g:
                generated.append(g)

        for g in generated[:max_per_table]:
            card = _card(
                project,
                g["insight_type"],
                "informational",
                g["title"],
                g["summary"],
                chart=g["chart"],
                result=g["result"],
                tables=[table.view_name],
                sql=g["sql"],
            )
            if card:
                card["group"] = g.get("group", "analysis")
                cards.append(card)
                if len(cards) >= max_total:
                    break

    return cards
