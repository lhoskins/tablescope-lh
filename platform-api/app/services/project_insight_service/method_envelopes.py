from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.analytical_method_engine import analyze as analyze_methods

logger = logging.getLogger(__name__)


def _infer_method_intent(card: dict[str, Any]) -> str | None:
    """Map a project-insight card's chart type/taxonomy to an analytical intent."""
    chart_type = str(card.get("chartType") or "").lower()
    insight_type = str(card.get("insightType") or "").lower()
    if chart_type in ("line", "area", "combo") or "trend" in insight_type:
        return "detect_trend"
    if chart_type in ("dual_line", "scatter") or card.get("valueColumn2"):
        return "relationship_numeric"
    # Default to a descriptive profile; the method engine will fall back to
    # Python if the data is too sparse for the R implementation.
    return "describe_numeric"


def _series_to_result(card: dict[str, Any]) -> dict[str, Any] | None:
    """Reconstruct a result set from a chart's rendered series for the method engine."""
    chart = card.get("chart") or {}
    series = chart.get("data", {}).get("series") if isinstance(chart.get("data"), dict) else None
    if not series and isinstance(chart.get("series"), list):
        series = chart["series"]
    if not isinstance(series, list) or not series:
        return None
    label_col = card.get("labelColumn") or "label"
    value_col = card.get("valueColumn") or "value"
    # If series items already look like rows, use their keys; otherwise build rows
    # from (label, value) pairs.
    if isinstance(series[0], dict):
        keys = set(series[0].keys())
        if label_col in keys and value_col in keys:
            return {"columns": list(keys), "rows": series}
        return {
            "columns": [label_col, value_col],
            "rows": [{label_col: s.get("label"), value_col: s.get("value")} for s in series],
        }
    return {
        "columns": [label_col, value_col],
        "rows": [{label_col: s[0], value_col: s[1]} for s in series],
    }


async def _attach_method_envelope_to_card(
    session: AsyncSession,
    tenant_id: int,
    card: dict[str, Any],
    runner: Any | None = None,
) -> None:
    """Run the Analytical Method Engine over one project-insight card.

    Reuses the same governed ``analyze`` path used by Business Insights so that
    project cards carry a real execution-engine envelope. When the raw query
    ``result`` is not already on the card (deterministic prompt functions do not
    keep it), the card's ``sql`` is re-executed through the project VDB runner.
    Fail-closed per card so engine issues never drop the insight.
    """
    result = card.get("result")
    if not result and runner and card.get("sql"):
        try:
            result = await runner(card["sql"])
        except Exception as exc:
            logger.debug(
                "project insight could not re-execute sql for method engine %s: %s",
                card.get("insightId"), exc,
            )
            result = None
    if not result and card.get("chart"):
        # Deterministic prompt functions do not keep the raw SQL/result, but the
        # rendered chart series is enough for the method engine to profile and
        # select a method.
        result = _series_to_result(card)
    if not result or not result.get("rows"):
        return
    columns = result.get("columns", [])
    rows = result.get("rows", [])
    if not columns or not rows:
        return
    question = " — ".join(
        str(x)
        for x in (card.get("title"), card.get("summary"))
        if x
    )
    intent = _infer_method_intent(card)
    try:
        envelope = await analyze_methods(
            session,
            tenant_id=tenant_id,
            columns=columns,
            rows=rows,
            question=question or str(card.get("insightType", "")),
            intent=intent,
        )
    except Exception as exc:  # pragma: no cover - engine is fail-closed
        logger.warning(
            "method engine skipped for project insight card %s: %s",
            card.get("insightId"), exc,
        )
        return
    if envelope and envelope.get("method") is not None:
        card["analyticalMethod"] = envelope


async def _attach_method_envelopes_to_cards(
    session: AsyncSession | None,
    tenant_id: int | None,
    cards: list[dict[str, Any]],
    runner: Any | None = None,
) -> None:
    """Attach governed method envelopes to any project cards missing them."""
    if session is None or tenant_id is None:
        return
    for card in cards:
        if isinstance(card, dict) and not card.get("analyticalMethod"):
            await _attach_method_envelope_to_card(session, tenant_id, card, runner)
