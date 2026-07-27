"""Shared ask pipeline for every conversational surface.

The AI Assistant, the Business-Insight ask box and the Project-Insight ask box
all answer the same kind of question against the same data, but they did not
share a pipeline:

* ``ask-and-run`` picked a chart through ``_suggest_visualization`` and then
  **collapsed it onto five families** (``_ASK_AND_RUN_SURFACE``: kpi, table,
  line, bar, pie). Scatter became a table; heatmap, boxplot, sunburst and the
  rest were not in the map at all, so they fell through to a table too.
* ``conversational_analytics`` never imported the visualization engine — it
  consumed whatever narrowed suggestion ask-and-run had already produced.
* Neither path ran the Analytical Method Engine, so chat answers carried no R
  execution and no provenance, while insight cards did.

This module is the one place all three surfaces resolve an answer's
presentation. It reuses the same chart-fit ranking the insight cards use (so a
question and a card about the same data agree on the chart), keeps the chart +
data-table contract chat already relies on, and exposes the analytical intent so
callers can run the governed R-first method engine over the answer.

Pure and dependency-light so it is unit-testable without a database, an LLM or
the R service.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.services.visualization_engine import (
    ChartType,
    rank_visualizations,
)

logger = logging.getLogger(__name__)

#: Families a conversational surface renders through the shared chart renderer.
#: This is intentionally NOT a narrowing map — every family the renderer knows is
#: allowed. It exists only so an unrenderable family degrades to a table rather
#: than producing a blank bubble.
_CHAT_RENDERABLE: frozenset[str] = frozenset(ct.value for ct in ChartType)

#: How many alternative charts the "change chart" picker offers in chat.
CHAT_CHART_SUGGESTIONS = 6


@dataclass
class AskPresentation:
    """The resolved presentation for one conversational answer."""

    chart: dict[str, Any]
    candidates: list[dict[str, Any]] = field(default_factory=list)
    #: Analytical intent the caller should hand to the method engine, when the
    #: question implies one. ``None`` means "no governed method applies".
    intent: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "chart": self.chart,
            "chartCandidates": self.candidates,
            "analysisIntent": self.intent,
        }


def resolve_presentation(
    columns: list[str],
    rows: list[Any],
    *,
    intent_hint: str | None = None,
    suggestion_limit: int = CHAT_CHART_SUGGESTIONS,
) -> AskPresentation:
    """Choose the chart for a conversational answer using the insight ranker.

    Returns the best-fit chart plus ranked alternatives, so chat gets the same
    "chart that fits the data" behaviour — and the same chart-suggestion list —
    as an insight card. A result with no plottable shape resolves to a table,
    which is a first-class answer here, not a failure.
    """
    if not columns or not rows:
        return AskPresentation(chart={"type": "table"})

    try:
        ranked = rank_visualizations(
            columns, rows, intent_hint=intent_hint, limit=max(suggestion_limit, 1)
        )
    except Exception:  # pragma: no cover - presentation must never break an answer
        logger.exception("ask pipeline: chart ranking failed; falling back to table")
        return AskPresentation(chart={"type": "table"})

    if not ranked:
        return AskPresentation(chart={"type": "table"})

    best = ranked[0]
    chart = chart_config(best.decision, columns)
    candidates = [
        c.to_dict()
        for c in ranked
        if c.decision.chart_type.value in _CHAT_RENDERABLE
    ]
    return AskPresentation(chart=chart, candidates=candidates[:suggestion_limit])


def chart_config(decision: Any, columns: list[str]) -> dict[str, Any]:
    """Map an engine decision onto the chat surface's chart contract.

    The contract chat already renders is ``{type, subtype?, labelColumn?,
    valueColumns?, metricField?}``; this keeps it byte-compatible while allowing
    the full family vocabulary through.
    """
    chart_type = getattr(decision.chart_type, "value", str(decision.chart_type))
    if chart_type not in _CHAT_RENDERABLE:
        return {"type": "table"}

    config: dict[str, Any] = {"type": chart_type}
    if getattr(decision, "chart_style", ""):
        config["subtype"] = decision.chart_style
    if decision.x_field and decision.x_field in columns:
        config["labelColumn"] = decision.x_field
    value_columns = [
        c for c in (decision.y_field, getattr(decision, "y2_field", None))
        if c and c in columns
    ]
    if value_columns:
        config["valueColumns"] = value_columns
    if chart_type == "kpi" and decision.y_field in columns:
        config["metricField"] = decision.y_field
    if getattr(decision, "top_n", None):
        config["topN"] = decision.top_n
    if getattr(decision, "value_format", None):
        config["valueFormat"] = decision.value_format
    return config


# ── Asking about an insight card ─────────────────────────────────────────────


@dataclass
class InsightFollowUp:
    """Context that turns a question into a follow-up about a specific card."""

    question: str
    #: Grounding text handed to the LLM so the answer continues the card's story.
    context: str
    #: SQL the card was built from, when it had any — the follow-up narrows this
    #: rather than starting from the whole project.
    base_sql: str | None = None
    #: Intent of the card's governed analysis, so a follow-up can re-run or
    #: refine the same method rather than guessing a new one.
    intent: str | None = None


def build_insight_followup(
    question: str, card: dict[str, Any] | None
) -> InsightFollowUp:
    """Ground a question in the insight card the user is asking about.

    Without this, "why did that happen?" asked from a card is answered against
    the whole project and loses the card's metric, period and method. Here the
    card's title, summary, SQL and analytical provenance become the context, so
    follow-ups genuinely dig into that finding.
    """
    if not card:
        return InsightFollowUp(question=question, context="")

    lines: list[str] = []
    title = card.get("title")
    if title:
        lines.append(f"The user is asking about this insight: {title}")
    summary = card.get("summary")
    if summary:
        lines.append(f"Insight summary: {summary}")

    envelope = card.get("analyticalMethod") or card.get("method_envelope") or {}
    intent = None
    if isinstance(envelope, dict) and envelope:
        intent = envelope.get("intent")
        method = envelope.get("method")
        engine = str(envelope.get("executionEngine") or "").lower()
        if method:
            lines.append(
                f"It was produced by the governed method '{method}'"
                + (" executed in R." if engine == "r" else ".")
            )
        n = envelope.get("usableN") or envelope.get("n")
        if n:
            lines.append(f"That analysis used {n} observations.")
        warnings = envelope.get("warnings") or []
        if isinstance(warnings, list) and warnings:
            lines.append("Caveats already known: " + "; ".join(str(w) for w in warnings[:3]))

    sources = card.get("sources") or {}
    tables = sources.get("tables") if isinstance(sources, dict) else None
    if tables:
        lines.append("Source tables: " + ", ".join(str(t) for t in tables[:5]))

    lines.append(
        "Answer the user's question about THIS insight. Break the same metric "
        "down further or explain the drivers behind it; do not change the "
        "subject to an unrelated metric."
    )

    return InsightFollowUp(
        question=question,
        context="\n".join(lines),
        base_sql=(card.get("sql") or None),
        intent=intent,
    )


def followup_prompt(followup: InsightFollowUp) -> str:
    """The question as the LLM should receive it, with card grounding prepended.

    The card's own query is included when it has one: a follow-up should start
    from the rows the finding was computed on — filtering them further, joining
    another source to them, or aggregating them differently — rather than
    generating an unrelated query that answers about a different population.
    """
    if not followup.context and not followup.base_sql:
        return followup.question
    parts = []
    if followup.context:
        parts.append(followup.context)
    if followup.base_sql:
        parts.append(
            "This is the query the insight was computed from. Build on it — "
            "extend, filter, join or re-aggregate it — rather than starting "
            "over, so the answer describes the same population:\n"
            f"```sql\n{followup.base_sql}\n```"
        )
    parts.append(f"Question: {followup.question}")
    return "\n\n".join(parts)
