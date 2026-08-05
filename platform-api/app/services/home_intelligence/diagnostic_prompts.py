from __future__ import annotations

import re
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.services.ai_governance import ai_governance_service
from app.services.insight_explanation import infer_method

from .card_builder import _card
from .formatting import _fmt_num
from .query_helpers import (
    _ENTITY_KEYWORDS,
    _MEASURE_KEYWORDS,
    _PERIOD_KEYWORDS,
    _find_table,
    _is_join_key,
    _log_skip,
    _match_col,
    _measure_col,
    _safe_query,
    _to_float,
    logger,
)

if TYPE_CHECKING:
    from .query_helpers import QueryRunner
    from .schema_context import DocInfo, ProjectContext, TableInfo



# ─────────────────────────────────────────────────────────────────────────────
# Date parsing for expiry scan
# ─────────────────────────────────────────────────────────────────────────────

_DATE_PATTERNS = [
    "%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%B %d, %Y", "%b %d, %Y",
    "%d %B %Y", "%d %b %Y", "%Y/%m/%d", "%m-%d-%Y",
]
_DATE_RE = re.compile(
    r"\b(\d{4}-\d{1,2}-\d{1,2}|\d{1,2}/\d{1,2}/\d{4}|"
    r"[A-Z][a-z]{2,8}\s+\d{1,2},?\s+\d{4}|\d{1,2}\s+[A-Z][a-z]{2,8}\s+\d{4})\b"
)
_EXPIRY_KEYS = [
    "expiry_date", "expiration_date", "expiration", "expires", "expiry",
    "end_date", "renewal_date", "valid_until", "termination_date",
]


def _parse_date(value: str) -> date | None:
    value = value.strip().rstrip(".")
    for fmt in _DATE_PATTERNS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _extract_expiry(doc: DocInfo) -> date | None:
    """Best-effort extraction of a contract expiry date from a document."""
    meta = doc.ai_metadata or {}
    for key in _EXPIRY_KEYS:
        val = meta.get(key)
        if isinstance(val, str):
            d = _parse_date(val)
            if d:
                return d
    # Scan the AI summary for a date near expiry/renewal language.
    text = doc.ai_summary or ""
    if text and re.search(r"expir|renew|terminat|valid until|end date", text, re.I):
        for m in _DATE_RE.finditer(text):
            d = _parse_date(m.group(1))
            if d:
                return d
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Prompt implementations
# ─────────────────────────────────────────────────────────────────────────────

async def _risk_sla(
    project: Project, ctx: ProjectContext, runner: QueryRunner
) -> dict | None:
    found = _find_table(
        ctx.tables,
        [
            ["lead_time", "leadtime", "delivery_days", "transit", "days_to_deliver",
             "lead time", "ship_days"],
        ],
    )
    if not found:
        # No SLA/lead-time column — fall back to a domain-agnostic risk grounded
        # in any threshold/target breach or breach-style status category.
        return await _risk_threshold(project, ctx, runner)
    table, cols = found
    lead_col = cols[0]
    period_col = _match_col(
        table.column_names, ["month", "period", "date", "week", "quarter"]
    )
    supplier_col = _match_col(table.column_names, ["supplier", "vendor", "carrier"])

    chart_data: list[dict] = []
    avg_recent: float | None = None
    sql: str | None = None
    if runner is not None and period_col:
        sql = (
            f'SELECT "{period_col}" AS period, '
            f'AVG(CAST("{lead_col}" AS double)) AS avg_lead '
            f'FROM "{table.view_name}" GROUP BY "{period_col}" '
            f'ORDER BY "{period_col}"'
        )
        res = await _safe_query(runner, sql)
        if res and res["rows"]:
            for r in res["rows"][-6:]:
                v = _to_float(r.get("avg_lead"))
                if v is not None:
                    chart_data.append({"label": str(r.get("period")), "value": round(v, 1)})
            if chart_data:
                avg_recent = chart_data[-1]["value"]

    if avg_recent is None and runner is not None:
        res = await _safe_query(
            runner, f'SELECT AVG(CAST("{lead_col}" AS double)) AS a FROM "{table.view_name}"'
        )
        if res and res["rows"]:
            avg_recent = _to_float(res["rows"][0].get("a"))

    if avg_recent is None:
        # The lead-time column matched but held no numeric data; still try the
        # domain-agnostic risk fallback before giving up.
        _log_skip(project, "risk_sla", "lead-time column had no numeric data")
        return await _risk_threshold(project, ctx, runner)

    # SLA threshold default of 14 days (common contractual term).
    threshold = 14.0
    breach = avg_recent > threshold
    severity = "critical" if avg_recent > threshold * 1.5 else (
        "urgent" if breach else "watch"
    )
    sup_label = f" for {supplier_col}" if supplier_col else ""
    title = (
        "Delivery lead time exceeds SLA threshold"
        if breach
        else "Delivery lead time within SLA"
    )
    summary = (
        f"Average delivery lead time is **{avg_recent:.1f} days**"
        f"{sup_label} — the typical SLA threshold is **{threshold:.0f} days**. "
        + ("This is over the limit." if breach else "This is within the limit.")
    )
    chart = (
        {
            "type": "bar",
            "title": "Lead time trend (days)",
            "data": {
                "series": chart_data,
                "threshold": threshold,
            },
        }
        if chart_data
        else None
    )
    callout = (
        {
            "type": "risk",
            "text": f"Average **{avg_recent:.1f} days** exceeds the **{threshold:.0f}-day** SLA threshold.",
        }
        if breach
        else None
    )
    return _card(
        project, "risk_sla", severity, title, summary,
        chart=chart, callout=callout, tables=[table.view_name],
        sql=sql if chart else None,
        chart_type="bar" if chart else None,
        label_column="period" if chart else None,
        value_column="avg_lead" if chart else None,
        result=res,
        metadata={
            "sourceContext": {
                "metric": lead_col,
                "aggregation": "avg",
                "periodColumn": period_col,
                "sourceColumns": [
                    c for c in (lead_col, period_col, supplier_col) if c
                ],
            }
        },
    )


# Threshold/target-style columns a measure can be compared against, and
# status/flag columns plus the values that read as a breach. Kept small and
# reused via ``_match_col`` (name substring match) rather than hard-coding SQL.
_THRESHOLD_KEYWORDS = [
    "threshold", "target", "limit", "sla", "goal", "benchmark", "quota",
    "cap", "ceiling", "tolerance", "max", "min", "budget", "plan", "forecast",
    "standard", "baseline", "allowance",
]
_STATUS_KEYWORDS = [
    "status", "state", "flag", "result", "outcome", "disposition",
    "condition", "stage", "health", "compliance", "phase",
]
_BREACH_VALUES = [
    "breach", "fail", "late", "overdue", "reject", "error", "critical",
    "expired", "noncompliant", "non-compliant", "delinquent", "at risk",
    "at_risk", "escalate", "delay", "cancel", "past due", "past_due",
    "violation", "missed", "unpaid", "default", "backorder", "out of stock",
    "outofstock", "on hold", "blocked", "flagged", "urgent", "pending",
]


def _severity_for_rate(rate: float) -> str:
    """Map a breach percentage onto the risk severity scale."""
    if rate >= 50:
        return "critical"
    if rate >= 20:
        return "urgent"
    if rate >= 5:
        return "warning"
    return "watch"


async def _risk_measure_vs_threshold(
    project: Project, ctx: ProjectContext, runner: QueryRunner
) -> dict | None:
    """A numeric measure compared against a paired target/threshold column."""
    for t in ctx.tables:
        threshold_col = _match_col(t.column_names, _THRESHOLD_KEYWORDS)
        if threshold_col is None:
            continue
        measure_col = _measure_col(t, exclude=frozenset({threshold_col}))
        if measure_col is None:
            continue
        res = await _safe_query(
            runner,
            f'SELECT COUNT(*) AS total, '
            f'SUM(CASE WHEN CAST("{measure_col}" AS double) > '
            f'CAST("{threshold_col}" AS double) THEN 1 ELSE 0 END) AS breaches '
            f'FROM "{t.view_name}"',
        )
        if not res or not res["rows"]:
            continue
        total = _to_float(res["rows"][0].get("total"))
        breaches = _to_float(res["rows"][0].get("breaches"))
        if total is None or total < 1 or breaches is None:
            continue
        rate = breaches / total * 100
        severity = _severity_for_rate(rate)
        title = (
            f"{measure_col} exceeds {threshold_col} in {rate:.0f}% of records"
            if breaches
            else f"{measure_col} within {threshold_col}"
        )
        summary = (
            f"**{int(breaches)} of {int(total)}** records have **{measure_col}** "
            f"above **{threshold_col}** (**{rate:.0f}%**) in {t.view_name}."
        )
        callout = (
            {
                "type": "risk",
                "text": f"{rate:.0f}% of records exceed their {threshold_col}.",
            }
            if breaches
            else None
        )
        chart = {
            "type": "bar",
            "title": f"{measure_col} vs {threshold_col}",
            "data": {
                "series": [
                    {"label": "Within", "value": int(total - breaches)},
                    {"label": "Breached", "value": int(breaches)},
                ]
            },
        }
        return _card(
            project, "risk_threshold", severity, title, summary,
            chart=chart, callout=callout, tables=[t.view_name],
            chart_type="bar",
            result=res,
            metadata={
                "sourceContext": {
                    "metric": measure_col,
                    "aggregation": "COUNT",
                    "sourceColumns": [measure_col, threshold_col],
                }
            },
        )
    return None


async def _risk_status_breach(
    project: Project, ctx: ProjectContext, runner: QueryRunner
) -> dict | None:
    """A status/flag categorical with a measurable share of breach-style values."""
    for t in ctx.tables:
        status_col = _match_col(t.column_names, _STATUS_KEYWORDS)
        if status_col is None:
            continue
        sql = (
            f'SELECT "{status_col}" AS status, COUNT(*) AS n '
            f'FROM "{t.view_name}" GROUP BY "{status_col}" ORDER BY n DESC'
        )
        res = await _safe_query(runner, sql)
        if not res or not res["rows"]:
            continue
        total = 0.0
        bad = 0.0
        bad_labels: list[str] = []
        for r in res["rows"]:
            n = _to_float(r.get("n")) or 0.0
            total += n
            label = str(r.get("status") or "")
            if label and _match_col([label], _BREACH_VALUES):
                bad += n
                bad_labels.append(label)
        if total < 1 or not bad_labels:
            continue
        rate = bad / total * 100
        severity = _severity_for_rate(rate)
        listed = ", ".join(f"**{lbl}**" for lbl in bad_labels[:4])
        title = f"{rate:.0f}% of {t.view_name} in a risk status"
        summary = (
            f"**{int(bad)} of {int(total)}** records in {t.view_name} are in a "
            f"risk status ({listed}) — **{rate:.0f}%** by {status_col}."
        )
        callout = {
            "type": "risk",
            "text": f"{rate:.0f}% flagged via {status_col} ({listed}).",
        }
        chart = {
            "type": "bar",
            "title": f"{status_col} distribution",
            "data": {
                "series": [
                    {
                        "label": str(r.get("status")),
                        "value": int(_to_float(r.get("n")) or 0),
                    }
                    for r in res["rows"][:8]
                ]
            },
        }
        return _card(
            project, "risk_threshold", severity, title, summary,
            chart=chart, callout=callout, tables=[t.view_name],
            sql=sql,
            chart_type="bar",
            label_column="status",
            value_column="n",
            result=res,
            metadata={
                "sourceContext": {
                    "metric": status_col,
                    "aggregation": "COUNT",
                    "sourceColumns": [status_col],
                }
            },
        )
    return None


async def _risk_threshold(
    project: Project, ctx: ProjectContext, runner: QueryRunner
) -> dict | None:
    """Domain-agnostic risk fallback grounded in executed data.

    When no SLA/lead-time column exists, quantify risk from either (a) a numeric
    measure breaching a paired target/threshold column, or (b) a status/flag
    categorical carrying breach-style values. Returns ``None`` only when neither
    is present in the project's real data.
    """
    if runner is None:
        _log_skip(project, "risk_threshold", "no runner")
        return None
    card = await _risk_measure_vs_threshold(project, ctx, runner)
    if card is not None:
        return card
    card = await _risk_status_breach(project, ctx, runner)
    if card is None:
        _log_skip(
            project, "risk_threshold",
            "no threshold/target breach or breach-style status column",
        )
    return card


async def _risk_expiry(
    project: Project, ctx: ProjectContext, runner: QueryRunner
) -> dict | None:
    today = date.today()
    expiring: list[tuple[str, date]] = []
    for doc in ctx.documents:
        d = _extract_expiry(doc)
        if d is not None and 0 <= (d - today).days <= 90:
            expiring.append((doc.title, d))
    if not expiring:
        # No governing documents with expiry dates — fall back to trending
        # records approaching any future-dated column in the project's data.
        return await _risk_upcoming(project, ctx, runner)
    expiring.sort(key=lambda x: x[1])
    soonest = expiring[0][1]
    days = (soonest - today).days
    severity = "urgent" if days <= 30 else "watch"
    n = len(expiring)
    title = f"{n} contract{'s' if n != 1 else ''} expire within 90 days"
    listed = ", ".join(f"**{name}** ({d.isoformat()})" for name, d in expiring[:4])
    summary = (
        f"{n} document{'s' if n != 1 else ''} with upcoming expiry dates. "
        f"Soonest in **{days} day{'s' if days != 1 else ''}**: {listed}."
    )
    return _card(
        project, "risk_expiry", severity, title, summary,
        documents=[name for name, _ in expiring],
        result={
            "columns": ["document", "expiry"],
            "rows": [
                {"document": name, "expiry": d.isoformat()}
                for name, d in expiring
            ],
        },
    )


# Columns whose values represent a future-facing date a record is approaching.
_FUTURE_DATE_KEYWORDS = [
    "expiry", "expire", "expiration", "renewal", "renew", "end_date",
    "enddate", "end date", "due", "deadline", "valid_until", "valid until",
    "effective", "termination", "maturity", "review_date", "next_", "scheduled",
]


async def _risk_upcoming(
    project: Project, ctx: ProjectContext, runner: QueryRunner
) -> dict | None:
    """Record-based fallback for upcoming/expiring dates in project data.

    Trends the count of records approaching any future-dated column (grouped by
    date) so a project with a due/renewal/end-date column still surfaces a
    grounded expiry-style risk even without governing documents. Requires >=2
    upcoming periods (a trend); omits gracefully otherwise.
    """
    if runner is None:
        _log_skip(project, "risk_upcoming", "no runner")
        return None
    table: TableInfo | None = None
    date_col: str | None = None
    for t in ctx.tables:
        dc = _match_col(t.column_names, _FUTURE_DATE_KEYWORDS)
        if dc is not None:
            table, date_col = t, dc
            break
    if table is None or date_col is None:
        _log_skip(project, "risk_upcoming", "no future-dated column")
        return None
    sql = (
        f'SELECT "{date_col}" AS period, COUNT(*) AS n '
        f'FROM "{table.view_name}" GROUP BY "{date_col}" ORDER BY "{date_col}"'
    )
    res = await _safe_query(runner, sql)
    if not res or not res["rows"]:
        _log_skip(project, "risk_upcoming", "empty result")
        return None
    today = date.today()
    upcoming: list[tuple[date, int]] = []
    for r in res["rows"]:
        d = _parse_date(str(r.get("period") or ""))
        n = _to_float(r.get("n"))
        if d is not None and n is not None and d >= today:
            upcoming.append((d, int(n)))
    if len(upcoming) < 2:
        _log_skip(project, "risk_upcoming", "<2 upcoming periods")
        return None
    upcoming.sort(key=lambda x: x[0])
    total = sum(n for _, n in upcoming)
    soonest = upcoming[0][0]
    days = (soonest - today).days
    within_90 = sum(n for d, n in upcoming if (d - today).days <= 90)
    severity = "urgent" if days <= 30 else "watch"
    title = f"{total} records approaching {date_col}"
    summary = (
        f"**{total}** records have an upcoming **{date_col}** in "
        f"{table.view_name} — soonest in **{days} day"
        f"{'s' if days != 1 else ''}**"
        + (f", **{within_90}** within 90 days." if within_90 else ".")
    )
    chart = {
        "type": "line",
        "title": f"Upcoming {date_col} by date",
        "data": {
            "series": [
                {"label": d.isoformat(), "value": n} for d, n in upcoming[:24]
            ]
        },
    }
    return _card(
        project, "risk_upcoming", severity, title, summary,
        chart=chart, tables=[table.view_name],
        sql=sql,
        chart_type="line",
        label_column="period",
        value_column="n",
        result=res,
        metadata={
            "sourceContext": {
                "metric": date_col,
                "aggregation": "COUNT",
                "periodColumn": date_col,
                "sourceColumns": [date_col],
            }
        },
    )


async def _trend_metric(
    project: Project, ctx: ProjectContext, runner: QueryRunner
) -> dict | None:
    """Domain-agnostic period-over-period trend for a non-financial project.

    Finds any table with a time/period column and trends a numeric measure over
    it (SUM) — or, when no obvious measure exists, the record volume (COUNT) per
    period. This keeps the Trends surface grounded in the project's real data
    (e.g. incidents opened per month) instead of always being a spend narrative.
    """
    if runner is None:
        return None
    table: TableInfo | None = None
    period_col: str | None = None
    for t in ctx.tables:
        pc = _match_col(t.column_names, _PERIOD_KEYWORDS)
        if pc is not None:
            table, period_col = t, pc
            break
    if table is None or period_col is None:
        return None

    measure_col: str | None = None
    for c in table.column_names:
        if c == period_col or _is_join_key(c):
            continue
        if _match_col([c], _MEASURE_KEYWORDS):
            measure_col = c
            break

    if measure_col:
        agg_sql = f'SUM(CAST("{measure_col}" AS double))'
        metric_label = measure_col
        measure_phrase = f"Total {metric_label}"
    else:
        agg_sql = "COUNT(*)"
        metric_label = "Records"
        measure_phrase = "Record volume"

    def _trend_sql(agg: str) -> str:
        return (
            f'SELECT "{period_col}" AS period, {agg} AS metric '
            f'FROM "{table.view_name}" GROUP BY "{period_col}" '
            f'ORDER BY "{period_col}"'
        )

    sql = _trend_sql(agg_sql)
    res = await _safe_query(runner, sql)
    if (not res or not res["rows"]) and measure_col is not None:
        # The chosen column wasn't actually numeric — fall back to record volume
        # so a mis-typed measure never suppresses the trend entirely.
        measure_col = None
        metric_label = "Records"
        measure_phrase = "Record volume"
        sql = _trend_sql("COUNT(*)")
        res = await _safe_query(runner, sql)
    if not res or not res["rows"]:
        return None
    series: list[dict] = []
    for r in res["rows"]:
        v = _to_float(r.get("metric"))
        if v is not None and r.get("period") is not None:
            series.append({"label": str(r.get("period")), "value": round(v, 2)})
    if len(series) < 2:
        return None

    recent = series[-12:]
    last = series[-1]["value"]
    prev = series[-2]["value"]
    pct = ((last - prev) / prev * 100) if prev else None

    def fmt(v: float) -> str:
        return f"{v:,.0f}" if (abs(v) >= 1 or v == 0) else f"{v:,.2f}"

    if pct is None:
        severity = "informational"
        title = f"{metric_label} trend"
        summary = (
            f"{measure_phrase} in {table.view_name} is **{fmt(last)}** in the "
            f"latest period ({series[-1]['label']})."
        )
    else:
        direction = "up" if pct > 0 else ("down" if pct < 0 else "flat")
        severity = "warning" if abs(pct) > 15 else "watch"
        title = (
            f"{metric_label} steady period-over-period"
            if direction == "flat"
            else f"{metric_label} {direction} {abs(pct):.0f}% period-over-period"
        )
        summary = (
            f"{measure_phrase} moved from **{fmt(prev)}** ({series[-2]['label']}) "
            f"to **{fmt(last)}** ({series[-1]['label']}) — "
            f"**{abs(pct):.0f}% {direction}** in {table.view_name}."
        )

    chart = {
        "type": "line",
        "title": f"{metric_label} over {period_col}",
        "data": {"series": recent},
    }
    comparison = (
        {
            "type": "period_over_period",
            "baselineValue": prev,
            "currentValue": last,
            "baselineLabel": series[-2]["label"],
            "currentLabel": series[-1]["label"],
            "field": measure_col or "Records",
        }
        if prev is not None
        else None
    )
    return _card(
        project, "trend_metric", severity, title, summary,
        chart=chart, tables=[table.view_name],
        sql=sql,
        chart_type="line",
        label_column="period",
        value_column="metric",
        result=res,
        metadata={
            "sourceContext": {
                "metric": measure_col or "",
                "aggregation": "SUM" if measure_col else "COUNT",
                "periodColumn": period_col,
                "sourceColumns": [c for c in (measure_col, period_col) if c],
                "comparison": comparison,
            }
        },
    )


async def _trend_spend(
    project: Project, ctx: ProjectContext, runner: QueryRunner
) -> dict | None:
    if runner is None:
        return None
    found = _find_table(
        ctx.tables,
        [
            ["amount", "spend", "cost", "total", "revenue", "price", "value",
             "budget", "expense"],
        ],
    )
    if not found:
        # No monetary measure — fall back to a domain-agnostic period-over-period
        # trend (any numeric measure, else record volume) so the Trends surface
        # reflects the project's real data instead of only ever being about spend.
        return await _trend_metric(project, ctx, runner)
    table, cols = found
    amount_col = cols[0]
    budget_col = _match_col(table.column_names, ["budget", "forecast", "target", "plan"])
    period_col = _match_col(
        table.column_names, ["month", "period", "date", "quarter", "week"]
    )

    res = await _safe_query(
        runner,
        f'SELECT SUM(CAST("{amount_col}" AS double)) AS total FROM "{table.view_name}"',
    )
    if not res or not res["rows"]:
        return None
    actual = _to_float(res["rows"][0].get("total"))
    if actual is None or actual == 0:
        return None

    budget: float | None = None
    pres: dict[str, Any] | None = None
    if budget_col and budget_col != amount_col:
        bres = await _safe_query(
            runner,
            f'SELECT SUM(CAST("{budget_col}" AS double)) AS b FROM "{table.view_name}"',
        )
        if bres and bres["rows"]:
            budget = _to_float(bres["rows"][0].get("b"))

    def fmt_money(v: float) -> str:
        if abs(v) >= 1_000_000:
            return f"${v / 1_000_000:.2f}M"
        if abs(v) >= 1_000:
            return f"${v / 1_000:.0f}K"
        return f"${v:,.0f}"

    kpis: list[dict] = [{"value": fmt_money(actual), "label": "Actual spend"}]
    severity = "watch"
    summary: str
    if budget and budget > 0:
        variance = actual - budget
        pct = variance / budget * 100
        kpis.append({"value": fmt_money(budget), "label": "Budget"})
        kpis.append({
            "value": fmt_money(abs(variance)),
            "label": "Over budget" if variance > 0 else "Under budget",
            "delta": f"{'▲' if variance > 0 else '▼'} {abs(pct):.0f}%",
        })
        severity = "urgent" if pct > 10 else "watch"
        summary = (
            f"Total spend is **{fmt_money(actual)}** against a budget of "
            f"**{fmt_money(budget)}** — **{abs(pct):.0f}% "
            f"{'over' if variance > 0 else 'under'}** budget."
        )
    else:
        summary = f"Total spend is **{fmt_money(actual)}** across {table.view_name}."
        if period_col:
            pres = await _safe_query(
                runner,
                f'SELECT "{period_col}" AS period, '
                f'SUM(CAST("{amount_col}" AS double)) AS s '
                f'FROM "{table.view_name}" GROUP BY "{period_col}" '
                f'ORDER BY "{period_col}"',
            )
            if pres and len(pres["rows"]) >= 2:
                last = _to_float(pres["rows"][-1].get("s"))
                prev = _to_float(pres["rows"][-2].get("s"))
                if last is not None and prev and prev != 0:
                    pct = (last - prev) / prev * 100
                    kpis.append({"value": fmt_money(prev), "label": "Prior period"})
                    kpis.append({
                        "value": f"{abs(pct):.0f}%",
                        "label": "Change",
                        "delta": f"{'▲' if pct > 0 else '▼'}",
                    })
                    severity = "urgent" if abs(pct) > 15 else "watch"
                    summary = (
                        f"Latest-period spend is **{fmt_money(last)}**, "
                        f"**{abs(pct):.0f}% {'up' if pct > 0 else 'down'}** vs the prior period."
                    )

    title = "Spend tracking over budget" if severity == "urgent" else "Spend overview"
    chart = {"type": "kpi_grid", "title": "Spend", "data": {"kpis": kpis}}
    result_for_card = pres if pres and len(pres.get("rows", [])) >= 2 else res
    return _card(
        project, "trend_spend", severity, title, summary,
        chart=chart, tables=[table.view_name],
        chart_type="kpi_grid",
        result=result_for_card,
        metadata={
            "sourceContext": {
                "metric": amount_col,
                "aggregation": "SUM",
                "periodColumn": period_col,
                "sourceColumns": [
                    c for c in (amount_col, budget_col, period_col) if c
                ],
            }
        },
    )


async def _opportunity_supplier(
    project: Project, ctx: ProjectContext, runner: QueryRunner
) -> dict | None:
    found = _find_table(
        ctx.tables,
        [
            ["supplier", "vendor", "carrier"],
            ["on_time", "ontime", "delivery", "score", "rating", "performance",
             "fulfillment"],
        ],
    )
    if runner is None:
        _log_skip(project, "opportunity_supplier", "no runner")
        return None
    if not found:
        # No supplier + score/rate columns — fall back to a generic top/bottom
        # performer opportunity over any entity dimension + numeric measure.
        return await _opportunity_top_performer(project, ctx, runner)
    table, cols = found
    supplier_col, metric_col = cols[0], cols[1]
    sql = (
        f'SELECT "{supplier_col}" AS supplier, '
        f'AVG(CAST("{metric_col}" AS double)) AS metric '
        f'FROM "{table.view_name}" GROUP BY "{supplier_col}" '
        f'ORDER BY metric DESC'
    )
    res = await _safe_query(runner, sql)
    if not res or not res["rows"]:
        return await _opportunity_top_performer(project, ctx, runner)
    top = [
        (str(r.get("supplier")), _to_float(r.get("metric")))
        for r in res["rows"][:3]
        if _to_float(r.get("metric")) is not None
    ]
    if not top:
        return await _opportunity_top_performer(project, ctx, runner)
    names = ", ".join(f"**{n}** ({v:.0f})" for n, v in top)
    summary = (
        f"Top performers on {metric_col}: {names}. "
        "Consolidating volume with the strongest suppliers could reduce costs."
    )
    best_name = top[0][0]
    callout = {
        "type": "opportunity",
        "text": f"Consider negotiating volume tiers with **{best_name}** — your top performer on {metric_col}.",
    }
    return _card(
        project, "opportunity_supplier", "opportunity",
        f"{len(top)} top-performing suppliers identified", summary,
        callout=callout, tables=[table.view_name],
        sql=sql,
        chart_type="bar",
        label_column="supplier",
        value_column="metric",
        result=res,
        metadata={
            "sourceContext": {
                "metric": metric_col,
                "aggregation": "AVG",
                "sourceColumns": [
                    c for c in (supplier_col, metric_col) if c
                ],
            }
        },
    )


async def _opportunity_top_performer(
    project: Project, ctx: ProjectContext, runner: QueryRunner
) -> dict | None:
    """Generic top/bottom performer opportunity over any entity + measure.

    Ranks any entity dimension by the average of a numeric measure and surfaces
    the leaders and the spread to the weakest — so a non-supplier project still
    gets a grounded opportunity. Requires >=2 distinct entities.
    """
    if runner is None:
        _log_skip(project, "opportunity_supplier", "no runner")
        return None
    for t in ctx.tables:
        dim_col = _match_col(t.column_names, _ENTITY_KEYWORDS)
        if dim_col is None:
            continue
        measure_col = _measure_col(t, exclude=frozenset({dim_col}))
        if measure_col is None:
            continue
        sql = (
            f'SELECT "{dim_col}" AS entity, '
            f'AVG(CAST("{measure_col}" AS double)) AS metric '
            f'FROM "{t.view_name}" GROUP BY "{dim_col}" ORDER BY metric DESC'
        )
        res = await _safe_query(runner, sql)
        if not res or not res["rows"]:
            continue
        ranked: list[tuple[str, float]] = []
        for r in res["rows"]:
            v = _to_float(r.get("metric"))
            if v is not None:
                ranked.append((str(r.get("entity")), v))
        if len(ranked) < 2:
            continue
        top = ranked[:3]
        best_name, best_val = ranked[0]
        worst_name, worst_val = ranked[-1]
        names = ", ".join(f"**{n}** ({_fmt_num(v)})" for n, v in top)
        summary = (
            f"Top performers on {measure_col} by {dim_col}: {names}. "
            f"The gap from **{best_name}** to **{worst_name}** "
            f"(**{_fmt_num(best_val)}** vs **{_fmt_num(worst_val)}**) is an "
            f"opportunity to lift the rest toward the leader."
        )
        callout = {
            "type": "opportunity",
            "text": (
                f"Study what makes **{best_name}** the leader on "
                f"{measure_col} and replicate it across {dim_col}."
            ),
        }
        chart = {
            "type": "bar",
            "title": f"{measure_col} by {dim_col}",
            "data": {"series": [{"label": n, "value": round(v, 2)} for n, v in top]},
        }
        return _card(
            project, "opportunity_performance", "opportunity",
            f"Top performers by {measure_col} identified", summary,
            chart=chart, callout=callout, tables=[t.view_name],
            sql=sql,
            chart_type="bar",
            label_column="entity",
            value_column="metric",
            result=res,
            metadata={
                "sourceContext": {
                    "metric": measure_col,
                    "aggregation": "AVG",
                    "sourceColumns": [dim_col, measure_col],
                }
            },
        )
    _log_skip(project, "opportunity_supplier", "no entity+measure table")
    return None


_PROMPT_FUNCS = {
    "risk_sla": _risk_sla,
    "risk_expiry": _risk_expiry,
    "trend_spend": _trend_spend,
    "opportunity_supplier": _opportunity_supplier,
}


async def run_intelligence_suite(
    project: Project,
    ctx: ProjectContext,
    prompt_types: list[str],
    runner: QueryRunner = None,
    *,
    session: AsyncSession | None = None,
    tenant_id: int | None = None,
    user_id: int | None = None,
) -> list[dict[str, Any]]:
    """Run the requested prompt types against a project's real data.

    Deterministic fallback path: each built-in prompt is grounded in the
    project's real tables/documents and skips cleanly when the data isn't there.
    The primary path is :func:`run_ai_intelligence` (LLM-driven).
    """
    if runner is None:
        logger.info(
            "home-intel suite | project=%s runner=None "
            "(VDB unreachable — all generators will skip) prompts=%s",
            project.id, prompt_types,
        )
    cards: list[dict[str, Any]] = []
    populated: list[str] = []
    skipped: list[str] = []
    for pt in prompt_types:
        fn = _PROMPT_FUNCS.get(pt)
        if fn is None:
            continue

        # Enforce tenant AI governance for built-in prompt types.  Each prompt is
        # a deterministic expression of one analytical method; if that method is
        # disabled for the tenant the prompt is skipped instead of fabricated.
        if session is not None and tenant_id is not None:
            method_key = infer_method(pt)
            decision = await ai_governance_service.evaluate_method(
                session,
                tenant_id,
                method_key,
                project_id=project.id,
                actor_user_id=user_id,
            )
            if not decision.allowed:
                skipped.append(pt)
                logger.debug(
                    "home-intel generator | project=%s prompt=%s skipped by AI governance",
                    project.id, pt,
                )
                continue

        try:
            card = await fn(project, ctx, runner)
        except Exception as exc:
            logger.warning("prompt %s failed for project %s: %s", pt, project.id, exc)
            card = None
        if card is not None:
            cards.append(card)
            populated.append(f"{pt}->{card.get('insightType', pt)}")
        else:
            skipped.append(pt)
        logger.debug(
            "home-intel generator | project=%s prompt=%s -> %s",
            project.id, pt, card.get("insightType") if card else None,
        )
    logger.info(
        "home-intel suite | project=%s ran=%d populated=%d [%s] skipped=%d [%s]",
        project.id, len(populated) + len(skipped), len(populated),
        ", ".join(populated), len(skipped), ", ".join(skipped),
    )
    return cards
