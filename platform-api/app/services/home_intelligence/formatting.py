from __future__ import annotations

import re
from typing import Any


def _fmt_num(v: float) -> str:
    if abs(v) >= 1_000_000:
        return f"{v / 1_000_000:.1f}M"
    if abs(v) >= 1_000:
        return f"{v / 1_000:.1f}K"
    if v == int(v):
        return str(int(v))
    return f"{v:.2f}"


# ── Dashboard readability + explanation layer ────────────────────────────────
# Deterministic, data-grounded helpers that make a generated dashboard readable:
# they pick sensible value formats, rank/limit categorical bars, switch ID-like
# category charts to horizontal bars, and derive plain-English explanations from
# the *executed* results (never LLM prose, never placeholder text).

_PCT_COL_RE = re.compile(
    r"(?i)\b(rate|pct|percent|percentage|ratio|share|on[_ -]?time|utiliz\w*|"
    r"defect[_ ]?rate|yield|compliance)\b"
)
_CURRENCY_COL_RE = re.compile(
    r"(?i)\b(revenue|cost|spend|spending|price|amount|sales|value|budget|usd|"
    r"dollars?)\b"
)
_COUNT_COL_RE = re.compile(
    r"(?i)\b(count|qty|quantity|units?|number|orders?|shipments?|items?|"
    r"records?|inspections?|defects?)\b"
)
# Labels that read like IDs/codes (suppliers, SKUs, part numbers) get jumbled on
# a vertical x-axis, so those charts read better as horizontal bars.
_ID_LABEL_RE = re.compile(
    r"(?i)(sup|sku|id|code|part|item|vendor|customer|prod)[-_ ]?\w*\d"
)


def _detect_value_format(value_label: str, series: list[dict[str, Any]]) -> str:
    """Classify a metric's format: ``percent`` | ``currency`` | ``count`` | ``number``."""
    name = value_label or ""
    if _PCT_COL_RE.search(name):
        return "percent"
    if _CURRENCY_COL_RE.search(name):
        return "currency"
    if _COUNT_COL_RE.search(name):
        return "count"
    values = [
        s["value"]
        for s in series
        if isinstance(s.get("value"), int | float)
    ]
    # Fractions in [0,1] (that aren't all 0/1) read as percentages.
    if (
        values
        and all(0.0 <= v <= 1.0 for v in values)
        and any(v not in (0.0, 1.0) for v in values)
    ):
        return "percent"
    return "number"


def _fmt_value(v: float, fmt: str) -> str:
    """Format a single metric value for display per its detected format."""
    if fmt == "percent":
        pct = v * 100 if abs(v) <= 1.0 else v
        return f"{pct:.1f}%"
    if fmt == "currency":
        return f"${_fmt_num(v)}"
    if fmt == "count":
        return f"{round(v):,}"
    return _fmt_num(v)


def _looks_like_id_labels(labels: list[str]) -> bool:
    """True when most labels are ID/code-like (jumble on a vertical axis)."""
    if not labels:
        return False
    idish = sum(
        1
        for lbl in labels
        if _ID_LABEL_RE.search(lbl)
        or len(lbl) >= 12
        or any(ch.isdigit() for ch in lbl)
    )
    return idish >= max(1, int(len(labels) * 0.5))


def enhance_bar_readability(chart: dict[str, Any]) -> dict[str, Any]:
    """Rank a categorical bar chart highest-first, cap at Top 10, go horizontal.

    Only plain ``bar`` charts are touched — time-series lines, KPI grids, donuts
    and two-metric charts keep their shape. Returns the (mutated) chart.
    """
    if chart.get("type") != "bar":
        return chart
    series = chart.get("data", {}).get("series") or []
    if len(series) < 2:
        return chart
    ranked = sorted(
        series, key=lambda s: s.get("value") or 0, reverse=True
    )[:10]
    chart["data"]["series"] = ranked
    labels = [str(s.get("label", "")) for s in ranked]
    if len(ranked) > 5 or _looks_like_id_labels(labels):
        chart["subtype"] = "horizontal_bar"
    return chart


def build_widget_explanation(
    chart: dict[str, Any], value_label: str, fmt: str
) -> str:
    """Derive a 1-2 sentence explanation from the executed data.

    Grounded in the real series/KPIs - states what the chart shows, what stands
    out, and what to do next. Returns "" when there is nothing to describe (the
    caller omits an explanation rather than showing a placeholder).
    """
    ctype = chart.get("type")
    if ctype == "kpi_grid":
        kpis = chart.get("data", {}).get("kpis") or []
        if not kpis:
            return ""
        parts = ", ".join(f"{k['label']} is {k['value']}" for k in kpis[:3])
        return f"Current headline figures: {parts}."
    series = chart.get("data", {}).get("series") or []
    if not series:
        return ""
    metric = value_label or "the metric"
    if ctype == "line":
        first, last = series[0], series[-1]
        fv = first.get("value") or 0
        lv = last.get("value") or 0
        direction = (
            "increased" if lv > fv else "decreased" if lv < fv else "held steady"
        )
        return (
            f"{metric} {direction} from {_fmt_value(fv, fmt)} "
            f"({first.get('label')}) to {_fmt_value(lv, fmt)} "
            f"({last.get('label')}). Watch whether the trend continues."
        )
    top = max(series, key=lambda s: s.get("value") or 0)
    return (
        f"{top.get('label')} leads on {metric} at "
        f"{_fmt_value(top.get('value') or 0, fmt)} across the {len(series)} "
        f"shown. Review the highest-ranked items first."
    )


def build_dashboard_narrative(
    widgets: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build an executive summary, key findings and actions from the widgets.

    Everything is derived from each widget's already-computed explanation and
    ranked series, so the narrative always matches what the charts actually show.
    """
    findings: list[str] = []
    actions: list[str] = []
    for w in widgets:
        exp = (w.get("explanation") or "").strip()
        if exp:
            findings.append(exp.split(". ")[0].rstrip(".") + ".")
        chart = w.get("chart") or {}
        series = chart.get("data", {}).get("series") or []
        if chart.get("type") == "bar" and series:
            top = max(series, key=lambda s: s.get("value") or 0)
            actions.append(
                f'Investigate {top.get("label")} in "{w.get("title")}".'
            )
    base = f"This dashboard summarizes {len(widgets)} analyses of the project's data."
    summary = f"{base} {findings[0]}" if findings else base
    return {
        "summary": summary,
        "keyFindings": findings[:5],
        "recommendedActions": actions[:5],
    }
