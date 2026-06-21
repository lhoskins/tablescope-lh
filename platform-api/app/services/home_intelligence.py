"""Home AI Intelligence — diagnostic prompt suite over real project data.

For each accessible project, a fixed suite of diagnostic prompts runs against the
project's real data sources and documents and returns ``InsightCard`` dicts. The
analysis is deterministic and defensive: when a project lacks the data a prompt
needs (e.g. no financial table), that prompt is *skipped* rather than fabricated.
A lightweight cross-project synthesis runs over the prose summaries only — never
raw data — so project isolation is never breached.

The four built-in prompt types:
- ``risk_sla``            delivery lead-time vs SLA threshold  (bar chart)
- ``risk_expiry``         contracts expiring within 90 days    (document list)
- ``trend_spend``         actual vs budget / prior-period spend (kpi grid)
- ``opportunity_supplier`` top supplier performance / savings   (prose + callout)
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.database_data_source import DatabaseDataSource
from app.models.file_source_meta import FileSourceMeta
from app.models.project import Project
from app.models.project_asset import ProjectAsset
from app.models.reference_library import (
    TIER_COMPANY,
    TIER_INDUSTRY,
    TIER_PROJECT,
    ReferenceDocument,
)

logger = logging.getLogger(__name__)

ALL_PROMPT_TYPES = ["risk_sla", "risk_expiry", "trend_spend", "opportunity_supplier"]

_PROJECT_COLORS = [
    "#185FA5", "#0F6E56", "#7A4FB5", "#B5642F", "#2F7DB5", "#9A2F5E",
]


def project_color(project_id: int) -> str:
    return _PROJECT_COLORS[project_id % len(_PROJECT_COLORS)]


# ─────────────────────────────────────────────────────────────────────────────
# Project context
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TableInfo:
    view_name: str
    columns: list[tuple[str, str]] = field(default_factory=list)  # (name, type)
    kind: str = "file"  # "file" | "db"

    @property
    def column_names(self) -> list[str]:
        return [c[0] for c in self.columns]


@dataclass
class DocInfo:
    title: str
    ai_summary: str | None
    ai_metadata: dict[str, Any]


@dataclass
class ProjectContext:
    tables: list[TableInfo]
    documents: list[DocInfo]


async def gather_project_context(
    session: AsyncSession, project: Project
) -> ProjectContext:
    """Collect a project's real tables (with columns) and documents."""
    tables: list[TableInfo] = []

    files = (
        await session.scalars(
            select(FileSourceMeta).where(
                FileSourceMeta.project_id == project.id,
                FileSourceMeta.archived.is_(False),
            )
        )
    ).all()
    for f in files:
        cols: list[tuple[str, str]] = []
        for c in f.column_types or []:
            name = c.get("name") or c.get("column") or c.get("field_name")
            if name:
                cols.append((str(name), str(c.get("type", "string"))))
        tables.append(TableInfo(view_name=f.view_name, columns=cols, kind="file"))

    db_sources = (
        await session.scalars(
            select(DatabaseDataSource)
            .where(
                DatabaseDataSource.project_id == project.id,
                DatabaseDataSource.archived.is_(False),
            )
            .options(selectinload(DatabaseDataSource.columns))
        )
    ).all()
    for ds in db_sources:
        cols = [
            (c.column_name, str(c.teiid_type_override or c.data_type or "string"))
            for c in ds.columns
        ]
        tables.append(
            TableInfo(view_name=ds.teiid_view_name, columns=cols, kind="db")
        )

    assets = (
        await session.scalars(
            select(ProjectAsset).where(ProjectAsset.project_id == project.id)
        )
    ).all()
    documents = [
        DocInfo(
            title=a.title or a.original_filename or a.filename,
            ai_summary=a.ai_summary,
            ai_metadata=a.ai_metadata or {},
        )
        for a in assets
    ]

    # Reference Library docs in scope (industry = global, company = this tenant,
    # project = this project) so Home analyses can ground in governed standards
    # and policies, not just the project's own uploads.
    ref_docs = (
        await session.scalars(
            select(ReferenceDocument)
            .where(
                ReferenceDocument.status == "active",
                ReferenceDocument.ai_summary.isnot(None),
                or_(
                    ReferenceDocument.tier == TIER_INDUSTRY,
                    and_(
                        ReferenceDocument.tier == TIER_COMPANY,
                        ReferenceDocument.tenant_id == project.tenant_id,
                    ),
                    and_(
                        ReferenceDocument.tier == TIER_PROJECT,
                        ReferenceDocument.project_id == project.id,
                    ),
                ),
            )
            .order_by(ReferenceDocument.updated_at.desc())
            .limit(40)
        )
    ).all()
    for r in ref_docs:
        documents.append(
            DocInfo(
                title=r.title,
                ai_summary=r.ai_summary,
                ai_metadata={
                    "reference_tier": r.tier,
                    "issuing_body": r.issuing_body or "",
                    "domain_tag": r.domain_tag or "",
                },
            )
        )

    return ProjectContext(tables=tables, documents=documents)


# ─────────────────────────────────────────────────────────────────────────────
# Column / table detection helpers
# ─────────────────────────────────────────────────────────────────────────────

def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _match_col(columns: list[str], keywords: list[str]) -> str | None:
    """Return the first column whose name contains any keyword."""
    for col in columns:
        n = _norm(col)
        for kw in keywords:
            if _norm(kw) in n:
                return col
    return None


def _find_table(
    tables: list[TableInfo], required: list[list[str]]
) -> tuple[TableInfo, dict[int, str]] | None:
    """Find the first table that has a column matching every required group.

    ``required`` is a list of keyword-groups; a table qualifies only if each
    group matches at least one of its columns. Returns the table plus the
    resolved column per group index.
    """
    for t in tables:
        resolved: dict[int, str] = {}
        ok = True
        for i, group in enumerate(required):
            col = _match_col(t.column_names, group)
            if col is None:
                ok = False
                break
            resolved[i] = col
        if ok:
            return t, resolved
    return None


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
# Insight card construction
# ─────────────────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _card(
    project: Project,
    insight_type: str,
    severity: str,
    title: str,
    summary: str,
    *,
    chart: dict | None = None,
    callout: dict | None = None,
    tables: list[str] | None = None,
    documents: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": f"{project.id}-{insight_type}-{int(datetime.now().timestamp() * 1000) % 100000}",
        "projectId": str(project.id),
        "projectName": project.name,
        "projectColor": project_color(project.id),
        "insightType": insight_type,
        "severity": severity,
        "title": title,
        "summary": summary,
        "chart": chart,
        "callout": callout,
        "sources": {"tables": tables or [], "documents": documents or []},
        "executedAt": _now_iso(),
    }


# Type signature for the Teiid query runner injected by the route layer.
QueryRunner = Any  # async (view_name, sql) -> {"columns": [...], "rows": [...]}


async def _safe_query(runner: QueryRunner, sql: str) -> dict[str, Any] | None:
    if runner is None:
        return None
    try:
        return await runner(sql)
    except Exception as exc:
        logger.info("home-intelligence query skipped: %s", exc)
        return None


async def _sample_values(runner: QueryRunner, view_name: str) -> dict[str, str]:
    """Return one real example value per column for a table.

    The planner uses these to detect each column's true format (e.g. a date
    stored as ``"1/19/2026"`` vs ISO, or whether text is numeric) so it can
    CAST/parse correctly. Best-effort: returns ``{}`` if the probe query fails.
    """
    result = await _safe_query(runner, f'SELECT * FROM "{view_name}"')
    if not result:
        return {}
    samples: dict[str, str] = {}
    for row in result.get("rows", [])[:25]:
        for col, val in row.items():
            if col in samples:
                continue
            if val is None:
                continue
            text = str(val).strip()
            if text:
                samples[col] = text[:40]
    return samples


_SLASH_DATE_RE = re.compile(r"^\d{1,2}/\d{1,2}/(\d{4}|\d{2})$")


def _date_masks_from_samples(
    samples_per_table: list[dict[str, str]]
) -> dict[str, str]:
    """Map each date column (by name) to a Teiid PARSETIMESTAMP mask.

    Only columns whose example value is a slash date (e.g. ``"1/19/2026"``)
    need a mask — ISO dates cast cleanly and are left alone.
    """
    masks: dict[str, str] = {}
    for samples in samples_per_table:
        for col, val in samples.items():
            if col in masks:
                continue
            if _SLASH_DATE_RE.match(val):
                year = val.rsplit("/", 1)[-1]
                masks[col] = "M/d/yyyy" if len(year) == 4 else "M/d/yy"
    return masks


def _normalize_date_casts(sql: str, date_masks: dict[str, str]) -> str:
    """Rewrite ``CAST("col" AS date|timestamp)`` to ``PARSETIMESTAMP("col",
    'mask')`` for slash-date columns, so time-bucketed SQL runs on Teiid even
    when the model casts a non-ISO text date (which Teiid rejects)."""
    for col, mask in date_masks.items():
        pat = re.compile(
            r'CAST\(\s*"' + re.escape(col) + r'"\s+AS\s+(?:date|timestamp)\s*\)',
            re.IGNORECASE,
        )
        sql = pat.sub(f"PARSETIMESTAMP(\"{col}\", '{mask}')", sql)
    return sql


async def _query_with_error(
    runner: QueryRunner, sql: str
) -> tuple[dict[str, Any] | None, str | None]:
    """Run a query, returning ``(result, None)`` on success or
    ``(None, error_text)`` when the engine rejects it (so it can be repaired)."""
    if runner is None:
        return None, None
    try:
        return await runner(sql), None
    except Exception as exc:
        logger.info("home-intelligence query failed (will attempt repair): %s", exc)
        return None, str(exc)


def _to_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(str(value).replace(",", "").replace("$", "").strip())
    except (ValueError, TypeError):
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
        return None
    table, cols = found
    lead_col = cols[0]
    period_col = _match_col(
        table.column_names, ["month", "period", "date", "week", "quarter"]
    )
    supplier_col = _match_col(table.column_names, ["supplier", "vendor", "carrier"])

    chart_data: list[dict] = []
    avg_recent: float | None = None
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
        return None

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
    )


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
        return None
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
    )


async def _trend_spend(
    project: Project, ctx: ProjectContext, runner: QueryRunner
) -> dict | None:
    found = _find_table(
        ctx.tables,
        [
            ["amount", "spend", "cost", "total", "revenue", "price", "value",
             "budget", "expense"],
        ],
    )
    if not found or runner is None:
        return None
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
    return _card(
        project, "trend_spend", severity, title, summary,
        chart=chart, tables=[table.view_name],
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
    if not found or runner is None:
        return None
    table, cols = found
    supplier_col, metric_col = cols[0], cols[1]
    res = await _safe_query(
        runner,
        f'SELECT "{supplier_col}" AS supplier, '
        f'AVG(CAST("{metric_col}" AS double)) AS metric '
        f'FROM "{table.view_name}" GROUP BY "{supplier_col}" '
        f'ORDER BY metric DESC',
    )
    if not res or not res["rows"]:
        return None
    top = [
        (str(r.get("supplier")), _to_float(r.get("metric")))
        for r in res["rows"][:3]
        if _to_float(r.get("metric")) is not None
    ]
    if not top:
        return None
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
    )


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
) -> list[dict[str, Any]]:
    """Run the requested prompt types against a project's real data.

    Deterministic fallback path: each built-in prompt is grounded in the
    project's real tables/documents and skips cleanly when the data isn't there.
    The primary path is :func:`run_ai_intelligence` (LLM-driven).
    """
    cards: list[dict[str, Any]] = []
    for pt in prompt_types:
        fn = _PROMPT_FUNCS.get(pt)
        if fn is None:
            continue
        try:
            card = await fn(project, ctx, runner)
        except Exception as exc:
            logger.warning("prompt %s failed for project %s: %s", pt, project.id, exc)
            card = None
        if card is not None:
            cards.append(card)
    return cards


# ─────────────────────────────────────────────────────────────────────────────
# AI-driven analyst loop  (plan -> execute real SQL -> interpret)
# ─────────────────────────────────────────────────────────────────────────────

def _tables_in_sql(sql: str, tables: list[TableInfo]) -> list[str]:
    """Return the project view names referenced by a SQL string."""
    found: list[str] = []
    for t in tables:
        if re.search(rf'(?<![A-Za-z0-9_]){re.escape(t.view_name)}(?![A-Za-z0-9_])', sql):
            found.append(t.view_name)
    return found


def _pick_columns(
    columns: list[str], rows: list[dict[str, Any]], label_hint: str, value_hint: str
) -> tuple[str | None, str | None]:
    """Resolve the label (category) and value (numeric) columns for a chart."""
    value_col: str | None = None
    if value_hint and value_hint in columns:
        value_col = value_hint
    else:
        for col in columns:
            numeric = [r for r in rows if _to_float(r.get(col)) is not None]
            if rows and len(numeric) >= max(1, len(rows) // 2):
                value_col = col
                break
    label_col: str | None = None
    if label_hint and label_hint in columns and label_hint != value_col:
        label_col = label_hint
    else:
        for col in columns:
            if col != value_col:
                label_col = col
                break
    return label_col, value_col


_PERIOD_RE = re.compile(
    r"^\s*("
    r"\d{4}([-/]\d{1,2}([-/]\d{1,2})?)?"  # 2024, 2024-01, 2024-01-31
    r"|q[1-4][\s-]?\d{2,4}"  # Q1 2024
    r"|\d{4}[\s-]?q[1-4]"  # 2024-Q1
    r"|w(eek)?[\s-]?\d{1,2}"  # week 5 / w5
    r"|(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"  # month names
    r")\s*$",
    re.IGNORECASE,
)


def _is_period_label(values: list[str]) -> bool:
    """Heuristic: do most labels look like ordered time periods (-> line chart)?"""
    if len(values) < 3:
        return False
    hits = sum(1 for v in values if _PERIOD_RE.match(str(v)))
    return hits >= max(3, int(len(values) * 0.6))


def _looks_like_share(label_col: str, series: list[dict[str, Any]]) -> bool:
    """Heuristic: is this a parts-of-a-whole breakdown (-> donut chart)?

    True when there are a handful of distinct positive categories whose label
    column reads like a dimension (category/type/status/segment/region/...).
    """
    if not (3 <= len(series) <= 8):
        return False
    if any(s["value"] < 0 for s in series):
        return False
    keys = (
        "categor", "type", "status", "segment", "region", "channel", "class",
        "group", "tier", "rating", "priority", "department", "mode", "method",
        "reason", "country", "state", "industry",
    )
    return any(k in label_col.lower() for k in keys)


# Chart families the Home can render — these map 1:1 onto the dashboard's
# WidgetRenderer catalog, so Intelligence cards use the exact same charts as
# dashboards. ``kpi_grid`` keeps its lightweight tile renderer; ``none`` yields
# a text-only executive card. Each entry maps a planner hint -> (type, subtype).
_CHART_ALIASES: dict[str, tuple[str, str]] = {
    "bar": ("bar", ""),
    "column": ("bar", "column"),
    "horizontal_bar": ("bar", "horizontal_bar"),
    "stacked_bar": ("bar", "stacked_bar"),
    "waterfall": ("bar", "waterfall"),
    "line": ("line", ""),
    "smooth_line": ("line", "smooth_line"),
    "step_line": ("line", "step_line"),
    "area": ("area", ""),
    "pie": ("pie", ""),
    "donut": ("pie", "donut"),
    "gauge": ("pie", "gauge"),
    "radar": ("radar", ""),
    "radial_bar": ("radial_bar", ""),
    "treemap": ("treemap", ""),
    "funnel": ("funnel", ""),
    # New planner types with no dedicated renderer yet — degrade to the nearest
    # existing visual so a card always renders rather than breaking.
    "bullet": ("pie", "gauge"),  # single metric vs target ~ gauge
    "heatmap": ("bar", ""),  # magnitude across categories (color dim dropped)
    "sparkline_table": ("line", ""),  # per-entity trend ~ a trend line
}

# Planner chart types that compare two metrics; handled specially because they
# need a second numeric column rather than the default {label, value} series.
_TWO_VALUE_TYPES = frozenset({"dual_line", "scatter", "bubble"})


def _pick_second_value(
    columns: list[str],
    rows: list[dict[str, Any]],
    used: tuple[str | None, ...],
    value_hint_2: str,
) -> str | None:
    """Resolve a second numeric column distinct from the already-used ones."""
    if value_hint_2 and value_hint_2 in columns and value_hint_2 not in used:
        return value_hint_2
    for col in columns:
        if col in used:
            continue
        numeric = [r for r in rows if _to_float(r.get(col)) is not None]
        if rows and len(numeric) >= max(1, len(rows) // 2):
            return col
    return None


def _two_value_chart(
    chart_type: str,
    title: str,
    columns: list[str],
    rows: list[dict[str, Any]],
    label_hint: str,
    value_hint: str,
    value_hint_2: str,
) -> dict[str, Any] | None:
    """Build a two-metric chart (dual_line / scatter / bubble).

    Returns ``None`` when a second numeric column can't be resolved, so the
    caller can fall back to a single-value chart instead of dropping the card.
    """
    label_col, value_col = _pick_columns(columns, rows, label_hint, value_hint)
    if not value_col:
        return None
    value2_col = _pick_second_value(
        columns, rows, (value_col, label_col), value_hint_2
    )
    if not value2_col:
        return None
    series: list[dict[str, Any]] = []
    for r in rows[:24]:
        v = _to_float(r.get(value_col))
        v2 = _to_float(r.get(value2_col))
        if v is None or v2 is None:
            continue
        series.append(
            {
                "label": str(r.get(label_col)) if label_col else "",
                "value": round(v, 2),
                "value2": round(v2, 2),
            }
        )
    if not series:
        return None
    series_labels = {"value": value_col, "value2": value2_col}
    if chart_type == "dual_line":
        # Two metrics over a shared (time) axis -> combo (bar + overlay line).
        return {
            "type": "combo",
            "subtype": "bar_line",
            "title": title,
            "data": {"series": series},
            "roles": {"x": "label", "y": "value", "y2": "value2"},
            "seriesLabels": series_labels,
        }
    # scatter / bubble -> two variables as x/y (bubble degrades to scatter when
    # no third size metric is available).
    return {
        "type": "scatter",
        "subtype": "bubble" if chart_type == "bubble" else "",
        "title": title,
        "data": {"series": series},
        "roles": {"x": "value", "y": "value2"},
        "seriesLabels": series_labels,
    }


def _chart(
    chart_type: str, title: str, series: list[dict[str, Any]]
) -> dict[str, Any]:
    """Wrap a {label,value} series as a dashboard-compatible chart dict."""
    wtype, subtype = _CHART_ALIASES.get(chart_type, ("bar", ""))
    return {
        "type": wtype,
        "subtype": subtype,
        "title": title,
        "data": {"series": series},
    }


def _build_chart(
    chart_type: str,
    title: str,
    result: dict[str, Any],
    label_hint: str,
    value_hint: str,
    value_hint_2: str = "",
) -> dict[str, Any] | None:
    """Pick the best visual for a real query result (shape-aware, never faked).

    The planner's ``chart_type`` is treated as a hint chosen from the dashboard
    chart catalog; the actual result shape validates/overrides it so insights
    aren't all rendered as bars:
      - single row / few headline numbers -> KPI tiles
      - ordered time-period labels         -> line (trend)
      - parts-of-a-whole categories        -> donut/pie (mix)
      - everything else with categories    -> the planner's pick, else bar
    ``chart_type == "none"`` (or no usable numeric data) -> text-only card.
    """
    columns = result.get("columns", [])
    rows = result.get("rows", [])
    if not rows or not columns:
        return None

    # Planner explicitly wants a narrative (text + highlights) card.
    if chart_type in ("none", "text", "callout"):
        return None

    # Single-row result with one or more numeric columns -> KPI tiles. This also
    # covers a single headline number, which reads better as a tile than a bar.
    if len(rows) == 1:
        row = rows[0]
        kpis = [
            {"value": _fmt_num(v), "label": col}
            for col in columns
            if (v := _to_float(row.get(col))) is not None
        ]
        if kpis:
            return {"type": "kpi_grid", "title": title, "data": {"kpis": kpis[:6]}}
        return None

    # Two-metric charts (dual_line / scatter / bubble) need a second numeric
    # column; build that shape when one is available, else fall through to the
    # single-value handling below so the card still renders.
    if chart_type in _TWO_VALUE_TYPES:
        two = _two_value_chart(
            chart_type, title, columns, rows, label_hint, value_hint, value_hint_2
        )
        if two is not None:
            return two

    label_col, value_col = _pick_columns(columns, rows, label_hint, value_hint)
    if not label_col or not value_col:
        return None
    series: list[dict[str, Any]] = []
    for r in rows[:12]:
        v = _to_float(r.get(value_col))
        if v is None:
            continue
        series.append({"label": str(r.get(label_col)), "value": round(v, 2)})
    if not series:
        return None

    labels = [s["label"] for s in series]

    if chart_type == "kpi_grid":
        kpis = [
            {"value": _fmt_num(s["value"]), "label": s["label"]} for s in series[:6]
        ]
        return {"type": "kpi_grid", "title": title, "data": {"kpis": kpis}}
    # Time series almost always reads best as a trend line.
    if _is_period_label(labels):
        return _chart("line", title, series)
    # Honour an explicit, valid planner pick from the catalog.
    if chart_type in _CHART_ALIASES:
        return _chart(chart_type, title, series)
    # Otherwise infer: parts-of-a-whole -> donut, else comparison bar.
    if _looks_like_share(label_col, series):
        return _chart("donut", title, series)
    return _chart("bar", title, series)


def _fmt_num(v: float) -> str:
    if abs(v) >= 1_000_000:
        return f"{v / 1_000_000:.1f}M"
    if abs(v) >= 1_000:
        return f"{v / 1_000:.1f}K"
    if v == int(v):
        return str(int(v))
    return f"{v:.2f}"


async def run_ai_intelligence(
    project: Project,
    ctx: ProjectContext,
    runner: QueryRunner,
    *,
    tenant_id: int,
    user_id: int,
    max_analyses: int = 15,
    granularity: int = 3,
) -> list[dict[str, Any]] | None:
    """LLM-driven analyst loop. Returns cards, or ``None`` to signal fallback.

    1. Ask the AI to plan high-value analyses from the real schema + documents.
    2. Execute each generated SQL against the project's real data.
    3. Ask the AI to interpret the actual results into executive findings.

    Returns ``None`` when the AI server is unavailable or proposes nothing
    usable, so the caller can fall back to the deterministic suite.
    """
    from app.services import ai_intelligence_client as ai

    if not ai.is_enabled():
        return None

    allowed_tables = [t.view_name for t in ctx.tables]
    # Pull a real example value per column so the planner can see each column's
    # actual format (date masks, numeric-vs-text) and generate valid SQL.
    samples_per_table = await asyncio.gather(
        *(_sample_values(runner, t.view_name) for t in ctx.tables)
    )
    table_schema = [
        {
            "table": t.view_name,
            # File/CSV columns are imported by Teiid as TEXT regardless of the
            # logical type shown, so the LLM must CAST them for any math/date op.
            "storage": "text" if t.kind == "file" else "native",
            "columns": [
                {"name": n, "type": ty, "sample": samples.get(n, "")}
                for (n, ty) in t.columns
            ],
        }
        for t, samples in zip(ctx.tables, samples_per_table, strict=False)
    ]
    # Deterministic safety net: even if the model casts a non-ISO text date
    # (which Teiid rejects), rewrite it to PARSETIMESTAMP before executing.
    date_masks = _date_masks_from_samples(samples_per_table)
    documents = [
        {
            "title": d.title,
            "summary": d.ai_summary or "",
            "tags": [
                str(t) for t in (d.ai_metadata.get("tags") or [])
                if isinstance(t, str | int | float)
            ],
            # Distinguish governed Reference Library standards from the
            # project's own uploaded assets so the planner can ground risk
            # and compliance findings in them and cite them explicitly.
            "source": (
                "reference_library"
                if d.ai_metadata.get("reference_tier")
                else "project"
            ),
            "tier": str(d.ai_metadata.get("reference_tier") or ""),
            "issuing_body": str(d.ai_metadata.get("issuing_body") or ""),
        }
        for d in ctx.documents
    ]

    analyses = await ai.plan(
        tenant_id=tenant_id,
        user_id=user_id,
        project_id=project.id,
        allowed_tables=allowed_tables,
        documents=documents,
        table_schema=table_schema,
        max_analyses=max_analyses,
        granularity=granularity,
    )
    if analyses is None:
        return None  # AI unreachable -> fall back
    if not analyses:
        return []  # AI reachable but found nothing worth surfacing

    doc_by_title = {d.title: d for d in ctx.documents}

    # Execute each analysis against real data; gather interpret inputs.
    executed: list[dict[str, Any]] = []
    interpret_inputs: list[dict[str, Any]] = []

    def _record_data_analysis(a: dict[str, Any], result: dict[str, Any]) -> None:
        executed.append({"analysis": a, "result": result})
        interpret_inputs.append(
            {
                "id": a["id"],
                "category": a.get("category", "trend"),
                "title": a.get("title", ""),
                "rationale": a.get("rationale", ""),
                "chart_type": a.get("chart_type", "bar"),
                "columns": result.get("columns", []),
                "rows": result.get("rows", [])[:20],
                "row_count": len(result.get("rows", [])),
                "document_context": "",
            }
        )

    # Queries the engine rejected on the first pass — repaired below.
    to_repair: list[tuple[dict[str, Any], str, str]] = []
    for a in analyses:
        sql = (a.get("sql") or "").strip()
        if sql:
            sql = _normalize_date_casts(sql, date_masks)
            result, err = await _query_with_error(runner, sql)
            if result and result.get("rows"):
                _record_data_analysis(a, result)
            elif err:
                to_repair.append((a, sql, err))
            # else: ran but returned no rows -> skip, never fabricate
        else:
            # Document-grounded finding — supply the doc text for interpretation.
            titles = a.get("source_documents") or []
            doc_ctx_parts: list[str] = []
            for title in titles:
                d = doc_by_title.get(title)
                if d and d.ai_summary:
                    doc_ctx_parts.append(f"{d.title}: {d.ai_summary}")
            if not doc_ctx_parts:
                continue
            executed.append({"analysis": a, "result": None})
            interpret_inputs.append(
                {
                    "id": a["id"],
                    "category": a.get("category", "trend"),
                    "title": a.get("title", ""),
                    "rationale": a.get("rationale", ""),
                    "chart_type": "none",
                    "columns": [],
                    "rows": [],
                    "row_count": 0,
                    "document_context": "\n".join(doc_ctx_parts)[:3000],
                }
            )

    # Self-repair: feed each rejected query + its exact engine error back to the
    # LLM (concurrently), then re-run the corrected SQL. Turns Teiid quirks
    # (wrong CAST, alias-in-GROUP BY, unsupported function, wrong-table column)
    # into rendered cards instead of silently dropped analyses.
    if to_repair:
        fixes = await asyncio.gather(
            *(
                ai.fix_sql(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    project_id=project.id,
                    sql=sql,
                    error=err,
                    allowed_tables=allowed_tables,
                    table_schema=table_schema,
                )
                for (_a, sql, err) in to_repair
            )
        )
        for (a, orig_sql, _err), fixed in zip(to_repair, fixes, strict=True):
            if not fixed or fixed.strip() == orig_sql.strip():
                continue
            fixed = _normalize_date_casts(fixed, date_masks)
            result, _ = await _query_with_error(runner, fixed)
            if result and result.get("rows"):
                _record_data_analysis({**a, "sql": fixed}, result)

    if not executed:
        return []

    # Interpret in small concurrent chunks so each LLM call stays fast and fits
    # the model context window (large single calls at Granular were the main
    # source of latency / empty results). Ollama now serves these in parallel.
    chunk_size = 4
    chunks = [
        interpret_inputs[i : i + chunk_size]
        for i in range(0, len(interpret_inputs), chunk_size)
    ]
    chunk_results = await asyncio.gather(
        *(
            ai.interpret(
                tenant_id=tenant_id,
                user_id=user_id,
                project_id=project.id,
                analyses=chunk,
            )
            for chunk in chunks
        )
    )
    interpreted: dict[str, dict[str, Any]] = {}
    for res in chunk_results:
        if res:
            interpreted.update(res)

    cards: list[dict[str, Any]] = []
    for item in executed:
        a = item["analysis"]
        result = item["result"]
        ins = interpreted.get(a["id"], {})

        category = a.get("category", "trend")
        if category not in ("risk", "trend", "opportunity", "relationship"):
            category = "trend"
        severity = ins.get("severity") or a.get("severity_hint") or "info"
        if severity not in ("critical", "urgent", "watch", "opportunity", "info"):
            severity = "info"
        title = ins.get("title") or a.get("title") or "Insight"
        summary = ins.get("summary") or a.get("rationale") or ""
        if not summary:
            continue  # nothing meaningful to show

        callout = None
        if ins.get("callout_text"):
            ctype = ins.get("callout_type") or (
                "opportunity" if category == "opportunity" else "risk"
            )
            callout = {"type": ctype, "text": ins["callout_text"]}
        elif ins.get("recommendation"):
            callout = {
                "type": "opportunity" if category == "opportunity" else "risk",
                "text": ins["recommendation"],
            }

        chart = None
        tables: list[str] = []
        documents_used: list[str] = []
        if result is not None:
            chart = _build_chart(
                a.get("chart_type", "bar"),
                a.get("title", ""),
                result,
                a.get("label_column", ""),
                a.get("value_column", ""),
                a.get("value_column_2", ""),
            )
            tables = _tables_in_sql(a.get("sql", ""), ctx.tables)
        else:
            documents_used = list(a.get("source_documents") or [])

        cards.append(
            _card(
                project,
                f"{category}_{a['id']}",
                severity,
                title,
                summary,
                chart=chart,
                callout=callout,
                tables=tables,
                documents=documents_used,
            )
        )

    return cards


# ─────────────────────────────────────────────────────────────────────────────
# Cross-project synthesis (prose summaries only — never raw data)
# ─────────────────────────────────────────────────────────────────────────────

def synthesise_cross_project(
    summaries: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Synthesize a headline across projects from prose summaries only.

    ``summaries`` is ``[{projectId, projectName, insightSummaries: [str, ...]}]``.
    Returns ``{headline, body, projectIds}`` or ``None`` if too little to say.
    """
    active = [s for s in summaries if s.get("insightSummaries")]
    if len(active) < 1:
        return None
    project_ids = [str(s["projectId"]) for s in active]
    n_projects = len(active)
    n_insights = sum(len(s["insightSummaries"]) for s in active)

    # Look for a vendor/supplier name appearing in multiple projects' summaries.
    shared_note = ""
    name_re = re.compile(r"\*\*([A-Z][A-Za-z0-9 .&'-]{2,40})\*\*")
    by_name: dict[str, set[str]] = {}
    for s in active:
        names: set[str] = set()
        for text in s["insightSummaries"]:
            for m in name_re.finditer(text):
                names.add(m.group(1).strip())
        for nm in names:
            by_name.setdefault(nm.lower(), set()).add(str(s["projectId"]))
    cross = [nm for nm, pids in by_name.items() if len(pids) > 1]
    if cross:
        shared_note = (
            f" The same entity appears across multiple projects "
            f"({', '.join(sorted(set(c.title() for c in cross))[:3])}), "
            "which may warrant a consolidated review."
        )

    headline = (
        f"AI analyzed {n_projects} active project"
        f"{'s' if n_projects != 1 else ''} and surfaced {n_insights} "
        f"insight{'s' if n_insights != 1 else ''} requiring attention"
    )
    body = (
        "Real-time diagnostic queries ran across "
        + ", ".join(f"{s['projectName']}" for s in active)
        + ". Each project's data remains isolated — results are surfaced to you "
        "as the authorized user." + shared_note
    )
    return {"headline": headline, "body": body, "projectIds": project_ids}
