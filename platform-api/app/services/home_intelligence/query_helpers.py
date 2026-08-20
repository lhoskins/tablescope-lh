from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from app.models.project import Project
from app.services import deep_analysis
from app.services.teiid_sql import (
    normalize_date_casts,
)
from app.services.visualization_engine import (
    derive_shape,
)

if TYPE_CHECKING:
    from .schema_context import ProjectContext, ScopeLink, TableInfo


logger = logging.getLogger(__name__)


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
# Entity & relationship discovery (insight-first methodology)
# ─────────────────────────────────────────────────────────────────────────────

# Business entities a Home insight may reason about (per the Home Insight
# best-practices reference). Used to recognise which columns name an entity.
_ENTITY_KEYWORDS = [
    "supplier", "vendor", "customer", "client", "product", "order", "invoice",
    "facility", "location", "region", "employee", "asset", "ticket", "part",
    "material", "contract", "department", "project", "item", "sku", "account",
    "warehouse", "carrier", "plant", "site",
]

# Suffixes that mark a column as a join/identity key rather than a measure.
_KEY_SUFFIXES = ["id", "code", "number", "no", "key", "sku"]


def _is_join_key(col: str) -> bool:
    """A column whose name looks like an identity/foreign key.

    Used as join evidence: an exact key-name shared by two tables is a strong
    relationship signal (best-practices §Multi-Table Relationship Policy).
    """
    n = _norm(col)
    if not n or n in {"id", "no"}:
        # Bare "id"/"no" are too generic to match across unrelated tables.
        return any(kw in n for kw in _ENTITY_KEYWORDS) and len(n) > 2
    if any(n.endswith(s) for s in _KEY_SUFFIXES):
        return True
    return any(kw in n for kw in _ENTITY_KEYWORDS) and any(
        s in n for s in _KEY_SUFFIXES
    )


# Period/date-grain column names recognised as join evidence between two
# same-grain aggregate tables (e.g. two monthly rollups: actuals and a
# forecast). Deliberately separate from _is_join_key's entity-key patterns
# above -- a shared reporting-period column proves the tables can be safely
# aligned on a common time axis, not that they describe the same entity, so
# it is treated as a distinct, lower-confidence tier rather than folded into
# the entity-key one.
_PERIOD_KEY_NAMES = {
    "month", "week", "quarter", "year", "period", "date", "day",
    "yearmonth", "reportingperiod", "reportingmonth",
}


def _is_period_key(col: str) -> bool:
    return _norm(col) in _PERIOD_KEY_NAMES


# Audit-stamp names that happen to contain period keywords but are not the
# time-series grain we want to join on.
_AUDIT_PERIOD_EXCLUSIONS = {"created", "modified", "lastupdated", "updated", "deleted"}


def _period_grain(col: str) -> str | None:
    """Return the implied time grain ('week', 'month', etc.) of a column name."""
    n = _norm(col)
    for grain in ("week", "month", "quarter", "year", "day"):
        if grain in n:
            return grain
    if "period" in n or "fiscal" in n:
        return "period"
    return None


def _is_period_column(col: str, col_type: str, date_masks: dict[str, str] | None) -> bool:
    """A column that can serve as a time-series grain in a composite join key."""
    n = _norm(col)
    type_norm = _norm(col_type)
    # Strong signal from the database/Teiid type or a parsed date mask.
    if any(t in type_norm for t in ("timestamp", "date", "time")):
        return not any(ex in n for ex in _AUDIT_PERIOD_EXCLUSIONS)
    if date_masks and col in date_masks:
        return True
    # Name-only fallback: period keywords, but not audit stamps.
    if any(kw in n for kw in _PERIOD_KEYWORDS):
        if any(ex in n for ex in _AUDIT_PERIOD_EXCLUSIONS):
            return False
        return True
    return False


def _period_columns_for_table(
    table: TableInfo, date_masks: dict[str, str] | None
) -> list[str]:
    return [
        n for (n, ty) in table.columns if _is_period_column(n, ty, date_masks)
    ]


def _enrich_period_keys(
    cand: dict[str, Any],
    tables_by_view: dict[str, TableInfo],
    date_masks: dict[str, str] | None,
) -> dict[str, Any]:
    """Extend a relationship candidate with same-grain period equality pairs.

    When two fact tables both carry the same period column (e.g. WeekStart),
    joining on the entity key alone fans out rows across time.  Add the shared
    period column as an additional equality in the composite join key.
    """
    left = tables_by_view.get(cand["left_table"])
    right = tables_by_view.get(cand["right_table"])
    if left is None or right is None:
        cand["join_key_pairs"] = [
            {"left": cand["left_join_key"], "right": cand["right_join_key"], "is_period": False}
        ]
        return cand

    left_periods = _period_columns_for_table(left, date_masks)
    right_periods_set = set(_period_columns_for_table(right, date_masks))

    pairs: list[dict[str, Any]] = [
        {"left": cand["left_join_key"], "right": cand["right_join_key"], "is_period": False}
    ]
    period_matched = False
    for lp in left_periods:
        if lp in right_periods_set:
            pairs.append({"left": lp, "right": lp, "is_period": True})
            period_matched = True

    # If each side has period columns but none share a name, the grains likely
    # differ (e.g. weekly vs monthly).  Flag the pair so dual_line joins avoid it.
    if left_periods and right_periods_set and not period_matched:
        cand["grain_mismatch"] = True

    cand["join_key_pairs"] = pairs
    return cand


def detect_entities(tables: list[TableInfo]) -> dict[str, list[str]]:
    """Map each table view to the candidate entity columns it contains."""
    out: dict[str, list[str]] = {}
    for t in tables:
        ents = [
            c
            for c in t.column_names
            if any(kw in _norm(c) for kw in _ENTITY_KEYWORDS)
        ]
        if ents:
            out[t.view_name] = ents
    return out


def _detect_view_strict(
    sql: str | None, allowed_tables: list[str]
) -> str | None:
    """Which allowed view a query's SQL references — ``None`` when ambiguous.

    A curated scope is only trustworthy as a view-to-view link when its
    source/target query unambiguously reads a single project view. Zero or
    multiple matches are ambiguous and rejected so we never fabricate a pair.
    """
    if not sql:
        return None
    sql_upper = sql.upper()
    matches = [t for t in allowed_tables if t.upper() in sql_upper]
    return matches[0] if len(matches) == 1 else None


def _containment(left: set[str], right: set[str]) -> float:
    """Fraction of the smaller value set contained in the larger.

    A measured signal that two columns actually share values — the basis for
    upgrading confidence beyond a name match and for inferring cardinality.
    """
    if not left or not right:
        return 0.0
    small, large = (left, right) if len(left) <= len(right) else (right, left)
    return len(small & large) / len(small)


def _cardinality(
    left: set[str], right: set[str], overlap: float
) -> tuple[str, str]:
    """Infer (relationship_type, row_multiplication_risk) from value overlap."""
    if not left or not right or overlap <= 0.0:
        return "unknown", "medium"
    if overlap >= 0.8:
        return "one_to_many", "low"
    if overlap >= 0.5:
        return "one_to_many", "medium"
    return "many_to_many", "high"


def find_relationship_candidates(
    tables: list[TableInfo],
    *,
    scope_links: list[ScopeLink] | None = None,
    key_values: dict[str, dict[str, set[str]]] | None = None,
    date_masks: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Discover evidence-backed join candidates between table pairs.

    Tiered evidence, strongest first; the best evidence per table-pair wins:

    - **Tier 1 — curated scope links**: an enabled drill-down relationship
      (user-created → 0.9, AI-created → 0.85).
    - **Tier 3 — exact key-name match**: both tables expose the same join key
      (e.g. ``SupplierID``), base confidence 0.6.
    - **Tier 3.5 — shared reporting-period column**: both tables roll up by
      the same period label (e.g. ``month``), base confidence 0.5. Proves
      the tables are safe to align on a common time axis, not that they
      share an entity, so it ranks below an entity-key match.
    - **Tier 4 — differently-named join keys** whose *sampled* values overlap
      (e.g. ``SupplierCode`` vs ``VendorCode``), requiring ≥0.3 containment.

    When sampled ``key_values`` are supplied, measured containment upgrades a
    candidate's confidence and derives its cardinality / row-multiplication
    risk. Name-only matches with no key shape are still excluded so unrelated
    tables are never joined; the resolver never fabricates a pair.
    """
    key_values = key_values or {}
    by_view = {t.view_name: t for t in tables}

    # best[(sorted view pair)] -> candidate dict (higher confidence wins)
    best: dict[tuple[str, str], dict[str, Any]] = {}

    def _consider(cand: dict[str, Any]) -> None:
        _enrich_period_keys(cand, by_view, date_masks)
        lo, hi_ = sorted([cand["left_table"], cand["right_table"]])
        pair = (lo, hi_)
        prior = best.get(pair)
        if prior is None or cand["join_confidence"] > prior["join_confidence"]:
            best[pair] = cand

    def _kv(view: str, col: str) -> set[str]:
        return key_values.get(view, {}).get(_norm(col), set())

    def _measured(
        left_view: str,
        left_col: str,
        right_view: str,
        right_col: str,
        base_conf: float,
        base_reason: str,
    ) -> dict[str, Any]:
        lv, rv = _kv(left_view, left_col), _kv(right_view, right_col)
        overlap = _containment(lv, rv)
        confidence = base_conf
        reason = base_reason
        rel_type, risk = "unknown", "medium"
        if lv and rv:
            rel_type, risk = _cardinality(lv, rv, overlap)
            if overlap > confidence:
                confidence = round(overlap, 2)
            reason = (
                f"{base_reason}; measured value containment {overlap:.0%}"
            )
        return {
            "left_table": left_view,
            "right_table": right_view,
            "left_join_key": left_col,
            "right_join_key": right_col,
            "relationship_type": rel_type,
            "join_confidence": confidence,
            "confidence_reason": reason,
            "row_multiplication_risk": risk,
        }

    # Tier 1 — curated scope relationships.
    for link in scope_links or []:
        if link.left_table not in by_view or link.right_table not in by_view:
            continue
        base = 0.85 if link.created_by_ai else 0.9
        origin = "AI-suggested" if link.created_by_ai else "user-defined"
        _consider(
            _measured(
                link.left_table,
                link.left_column,
                link.right_table,
                link.right_column,
                base,
                f"curated scope relationship ({origin})",
            )
        )

    # Tier 3 — exact key-name matches across tables.
    by_key: dict[str, list[tuple[TableInfo, str]]] = {}
    for t in tables:
        for c in t.column_names:
            if _is_join_key(c):
                by_key.setdefault(_norm(c), []).append((t, c))
    for occ in by_key.values():
        for i in range(len(occ)):
            for j in range(i + 1, len(occ)):
                (lt, lc), (rt, rc) = occ[i], occ[j]
                if lt.view_name == rt.view_name:
                    continue
                _consider(
                    _measured(
                        lt.view_name,
                        lc,
                        rt.view_name,
                        rc,
                        0.6,
                        f"exact key-name match on '{lc}'",
                    )
                )

    # Tier 3.5 — shared reporting-period column (e.g. both tables roll up by
    # "month"). Lower confidence than an entity-key match: a shared period
    # alone doesn't prove the tables describe the same entity, only that
    # they're safe to align on a common time axis -- the case Tier 3's
    # entity-key patterns don't cover (e.g. a monthly actuals table and a
    # monthly forecast table with no shared entity key at all).
    by_period: dict[str, list[tuple[TableInfo, str]]] = {}
    for t in tables:
        for c in t.column_names:
            if _is_period_key(c):
                by_period.setdefault(_norm(c), []).append((t, c))
    for occ in by_period.values():
        for i in range(len(occ)):
            for j in range(i + 1, len(occ)):
                (lt, lc), (rt, rc) = occ[i], occ[j]
                if lt.view_name == rt.view_name:
                    continue
                _consider(
                    _measured(
                        lt.view_name,
                        lc,
                        rt.view_name,
                        rc,
                        0.5,
                        f"shared reporting-period column '{lc}'",
                    )
                )

    # Tier 4 — differently-named join keys with sampled value overlap.
    join_cols_by_view = {
        t.view_name: [c for c in t.column_names if _is_join_key(c)]
        for t in tables
    }
    view_names = [t.view_name for t in tables]
    for a in range(len(view_names)):
        for b in range(a + 1, len(view_names)):
            lv_name, rv_name = view_names[a], view_names[b]
            for lc in join_cols_by_view[lv_name]:
                for rc in join_cols_by_view[rv_name]:
                    if _norm(lc) == _norm(rc):
                        continue  # covered by Tier 3
                    lv, rv = _kv(lv_name, lc), _kv(rv_name, rc)
                    if not lv or not rv:
                        continue
                    overlap = _containment(lv, rv)
                    if overlap < 0.3:
                        continue
                    _consider(
                        _measured(
                            lv_name,
                            lc,
                            rv_name,
                            rc,
                            round(overlap, 2),
                            f"sampled value overlap ('{lc}' ~ '{rc}')",
                        )
                    )

    return list(best.values())


# ─────────────────────────────────────────────────────────────────────────────
# Insight card construction
# ─────────────────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


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


async def _sample_values(
    runner: QueryRunner, view_name: str
) -> tuple[dict[str, str], dict[str, set[str]]]:
    """Sample a table: (one example per column, distinct join-key values).

    The first mapping is one real example value per column, used by the planner
    to detect each column's true format (e.g. a date stored as ``"1/19/2026"``
    vs ISO). The second collects the *distinct* values seen (over the same 25
    probe rows) for columns recognised as join keys, keyed by normalised name —
    the measured evidence relationship discovery uses to score value overlap.
    Best-effort: returns ``({}, {})`` if the probe query fails.
    """
    result = await _safe_query(runner, f'SELECT * FROM "{view_name}"')
    if not result:
        return {}, {}
    samples: dict[str, str] = {}
    key_values: dict[str, set[str]] = {}
    for row in result.get("rows", [])[:25]:
        for col, val in row.items():
            if val is None:
                continue
            text = str(val).strip()
            if not text:
                continue
            samples.setdefault(col, text[:40])
            if _is_join_key(col):
                key_values.setdefault(_norm(col), set()).add(text[:80])
    return samples, key_values


# Timestamp/date normalization is shared with the query preview routes via
# app.services.teiid_sql so all SQL execution paths behave consistently.


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


def _log_skip(project: Project, generator: str, reason: str) -> None:
    """Diagnostic for a generator that produced no card, with the reason.

    Turns a silent per-project skip (no runner / no matching table / <2 periods
    / empty result) into a signal so "2 of 11 populated" becomes diagnosable
    instead of a mystery.
    """
    logger.debug(
        "home-intel skip | project=%s generator=%s reason=%s",
        getattr(project, "id", "?"), generator, reason,
    )


def _measure_col(
    table: TableInfo, *, exclude: frozenset[str] = frozenset()
) -> str | None:
    """First non-key column whose name looks like a numeric measure."""
    for c in table.column_names:
        if c in exclude or _is_join_key(c):
            continue
        if _match_col([c], _MEASURE_KEYWORDS):
            return c
    return None


_PERIOD_KEYWORDS = [
    "month", "period", "quarter", "week", "year", "fiscal", "date", "time",
]
_MEASURE_KEYWORDS = [
    "count", "qty", "quantity", "amount", "total", "sum", "duration",
    "hours", "days", "minutes", "score", "rate", "age", "volume", "num",
    "utilization", "usage", "capacity", "units", "produced", "scrapped",
    "scrap", "planned", "actual", "forecast", "demand", "onhand",
    "safety", "stock", "reject", "defect", "backorder", "shipped",
    "received",
]


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


_DIMENSION_COL_RE = re.compile(
    r"(?i)\b(period|month|year|quarter|week|date|day|fiscal)\b"
)


def _dimension_columns(columns: list[str], label_hint: str) -> set[str]:
    """Columns that are axis/dimension labels, not headline metrics.

    Keeps a grouped period/category column (e.g. a "Period" holding a year) out
    of single-row KPI tiles, where a bare year like 2026 would misleadingly
    format as "2.0K". Excludes the planner's stated label column plus any column
    whose name reads like a time dimension.
    """
    skip: set[str] = set()
    hint = (label_hint or "").strip().lower()
    for c in columns:
        if hint and c.lower() == hint:
            skip.add(c)
        elif _DIMENSION_COL_RE.search(c):
            skip.add(c)
    return skip


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


def _agg_for_measure(col: str) -> str:
    """Choose a default aggregation for a numeric measure column."""
    lower = str(col).lower()
    if any(k in lower for k in ("rate", "pct", "percent", "ratio", "score")):
        return "AVG"
    return "SUM"


def _quote(col: str) -> str:
    return f'"{col}"'


#: ``_`` is a word character, so ``\b`` never fires inside ``budget_revenue`` —
#: match on explicit separators instead.
_TARGET_COL_RE = re.compile(
    r"(?i)(^|[_\s-])(target|targets|budget|budgeted|plan|planned|goal|quota"
    r"|baseline|benchmark|standard|expected)([_\s-]|$)"
)
_YEAR_RE = re.compile(r"(19|20)\d{2}")


def _distinct_years(rows: list[dict[str, Any]], period_col: str) -> int:
    """Distinct calendar years present in a period column.

    Year-over-year needs two actual years: 24 monthly rows inside a single year
    cannot support a YoY read, and comparing them would be a lie.
    """
    years: set[str] = set()
    for r in rows:
        value = r.get(period_col)
        if value is None:
            continue
        match = _YEAR_RE.search(str(value))
        if match:
            years.add(match.group(0))
    return len(years)


def _target_measure(measures: list[str]) -> str | None:
    """The measure that reads like a plan/target/budget baseline, if any."""
    for m in measures:
        if _TARGET_COL_RE.search(str(m)):
            return m
    return None


def _first_column(result: dict[str, Any] | None) -> str | None:
    """First projected column, or None — an empty projection must not raise."""
    columns = (result or {}).get("columns") or []
    return str(columns[0]) if columns else None


async def _first_time_column(runner: QueryRunner, table: Any) -> str | None:
    """The table's period column, probed the same way the diagnostics do."""
    try:
        probe = await _safe_query(
            runner, f'SELECT * FROM {_quote(table.view_name)} LIMIT 200'
        )
    except Exception:
        return None
    if not probe or not probe.get("rows") or not probe.get("columns"):
        return None
    shape = derive_shape(probe["columns"], probe["rows"])
    return shape.time_columns[0] if shape.time_columns else None


def _period_label(rows: list[dict[str, Any]], period: str) -> str:
    """`2024-01 to 2026-01`, so a magnitude is anchored to a window."""
    values = [str(r.get(period)) for r in rows if r.get(period) is not None]
    if not values:
        return "the same period"
    return f"{values[0]} to {values[-1]}"


def _deep_analysis_sql(view_name: str, spec: deep_analysis.DeepAnalysisSpec, max_rows: int) -> str:
    """Projection for one governed analysis.

    Time-series intents aggregate to one row per period; group comparisons and
    relationships need raw rows so the method sees the distribution.
    """
    table = _quote(view_name)
    period = spec.roles.get("period")
    measure = spec.roles.get("measure")
    measure2 = spec.roles.get("measure2")
    group_by = spec.group_by

    if not measure:
        return ""
    agg = _agg_for_measure(measure)

    if spec.intent == "contribution_to_change" and period and group_by:
        return (
            f'SELECT {_quote(period)}, {_quote(group_by)}, '
            f'{agg}({_quote(measure)}) AS {_quote(measure)} FROM {table} '
            f'GROUP BY {_quote(period)}, {_quote(group_by)} '
            f'ORDER BY {_quote(period)} LIMIT {max_rows}'
        )
    if spec.intent in ("compare_multiple_groups", "compare_two_groups") and group_by:
        return (
            f'SELECT {_quote(group_by)}, {_quote(measure)} FROM {table} '
            f'WHERE {_quote(measure)} IS NOT NULL LIMIT {max_rows}'
        )
    # Two measures across a shared timeline (co-movement, actual-vs-target):
    # aggregate both per period so the method compares the series, not raw rows.
    if period and measure2:
        agg2 = _agg_for_measure(measure2)
        return (
            f'SELECT {_quote(period)}, {agg}({_quote(measure)}) AS {_quote(measure)}, '
            f'{agg2}({_quote(measure2)}) AS {_quote(measure2)} FROM {table} '
            f'GROUP BY {_quote(period)} ORDER BY {_quote(period)} LIMIT {max_rows}'
        )
    if spec.intent in ("relationship_numeric", "relationship_monotonic") and measure2:
        return (
            f'SELECT {_quote(measure)}, {_quote(measure2)} FROM {table} '
            f'WHERE {_quote(measure)} IS NOT NULL AND {_quote(measure2)} IS NOT NULL '
            f'LIMIT {max_rows}'
        )
    # Driver analysis: raw rows across every measure so the regression can
    # attribute variation.
    if spec.intent == "continuous_prediction":
        others = spec.roles.get("explanatory") or ""
        cols = ", ".join(_quote(c) for c in [measure, *others.split(",")] if c)
        return (
            f'SELECT {cols} FROM {table} '
            f'WHERE {_quote(measure)} IS NOT NULL LIMIT {max_rows}'
        )
    if period:
        return (
            f'SELECT {_quote(period)}, {agg}({_quote(measure)}) AS {_quote(measure)} '
            f'FROM {table} GROUP BY {_quote(period)} ORDER BY {_quote(period)} '
            f'LIMIT {max_rows}'
        )
    return ""


def _series_is_constant(rows: list[dict], col: str) -> bool:
    vals = [round(v, 6) for r in rows if (v := _to_float(r.get(col))) is not None]
    return len(vals) > 1 and len(set(vals)) == 1


def _extract_join_qualifiers(sql: str) -> tuple[str, str] | None:
    """Return the (left, right) table/alias qualifiers for the join ON clause."""
    parts = re.split(r'\bON\b', sql, maxsplit=1, flags=re.IGNORECASE)
    if len(parts) < 2:
        return None
    prefix = parts[0]
    sources = list(
        re.finditer(
            r'(?:FROM|JOIN)\s+("?\w+"?)(?:\s+(?:AS\s+)?("?\w+"?))?',
            prefix,
            re.IGNORECASE,
        )
    )
    if len(sources) < 2:
        return None
    left = (sources[-2].group(2) or sources[-2].group(1) or "").strip().strip('"')
    right = (sources[-1].group(2) or sources[-1].group(1) or "").strip().strip('"')
    return left, right


async def _repair_fanned_out_join(
    a: dict[str, Any],
    result: dict[str, Any],
    relationship_meta: dict[str, Any],
    date_masks: dict[str, str],
    runner: QueryRunner,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Attempt to fix a constant second series by adding the shared period equality."""
    period_pair = next(
        (p for p in relationship_meta.get("join_key_pairs", []) if p.get("is_period")),
        None,
    )
    if not period_pair:
        return None, None
    sql = a.get("sql", "")
    quals = _extract_join_qualifiers(sql)
    if not quals:
        return None, None
    left_qual, right_qual = quals
    left_period = period_pair["left"]
    right_period = period_pair["right"]
    cond = f'"{left_qual}"."{left_period}" = "{right_qual}"."{right_period}"'
    if re.search(r'\bON\b', sql, re.IGNORECASE):
        m = re.search(
            r'\bON\b(.+?)(?=\s+(?:WHERE|GROUP\s+BY|HAVING|ORDER\s+BY|LIMIT)\b|;|$)',
            sql,
            re.IGNORECASE | re.DOTALL,
        )
        if m:
            on_text = m.group(1)
            if (
                left_period.lower() in on_text.lower()
                and right_period.lower() in on_text.lower()
                and "=" in on_text
            ):
                return None, None
            new_on = on_text.rstrip() + f" AND {cond}"
            new_sql = sql[: m.start()] + "ON " + new_on + sql[m.end() :]
        else:
            return None, None
    else:
        new_sql = re.sub(
            r'(\bJOIN\s+"?\w+"?(?:\s+(?:AS\s+)?"?\w+"?)?)(?=\s+(?:WHERE|GROUP\s+BY|HAVING|ORDER\s+BY|LIMIT)\b|;|$)',
            rf'\1 ON {cond}',
            sql,
            count=1,
            flags=re.IGNORECASE,
        )
        if new_sql == sql:
            return None, None
    new_sql = normalize_date_casts(new_sql, date_masks)
    new_result, _err = await _query_with_error(runner, new_sql)
    if not new_result or not new_result.get("rows"):
        return None, None
    value2_col = a.get("value_column_2", "")
    if value2_col and _series_is_constant(new_result.get("rows", []), value2_col):
        return None, None
    return {**a, "sql": new_sql}, new_result


def _period_expression(col: str, qualifier: str, date_masks: dict[str, str]) -> str:
    mask = date_masks.get(col)
    if mask:
        return f"FORMATTIMESTAMP(PARSETIMESTAMP(\"{qualifier}\".\"{col}\", '{mask}'), 'yyyy-MM')"
    # When the date format is unknown, avoid a CAST that Teiid may reject
    # (e.g. text-backed "2025-01").  ISO date strings group and sort correctly.
    return f'"{qualifier}"."{col}"'


async def _synthesize_templated_join(
    relationship_hints: list[dict[str, Any]],
    ctx: ProjectContext,
    date_masks: dict[str, str],
    runner: QueryRunner,
    avoid_pairs: set[frozenset[str]] | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Build and run a deterministic two-table join from the top evidence pair."""
    avoid_pairs = avoid_pairs or set()
    for hint in sorted(
        relationship_hints,
        key=lambda h: float(h.get("join_confidence") or 0),
        reverse=True,
    ):
        if hint.get("grain_mismatch"):
            continue
        left_table = hint.get("left_table", "")
        right_table = hint.get("right_table", "")
        if frozenset({left_table, right_table}) in avoid_pairs:
            continue
        left_t = next((t for t in ctx.tables if t.view_name == left_table), None)
        right_t = next((t for t in ctx.tables if t.view_name == right_table), None)
        if not left_t or not right_t:
            continue
        period_pair = next(
            (p for p in hint.get("join_key_pairs", []) if p.get("is_period")),
            None,
        )
        if not period_pair:
            left_periods = _period_columns_for_table(left_t, date_masks)
            right_periods = _period_columns_for_table(right_t, date_masks)
            shared = set(left_periods) & set(right_periods)
            if shared:
                pc = next(iter(shared))
                period_pair = {"left": pc, "right": pc, "is_period": True}
            else:
                continue
        left_measure = _measure_col(left_t)
        right_measure = _measure_col(right_t)
        if not left_measure or not right_measure:
            continue
        key_conds = [
            f'"{left_table}"."{p["left"]}" = "{right_table}"."{p["right"]}"'
            for p in hint.get("join_key_pairs", [])
            if not p.get("is_period")
        ]
        if not key_conds:
            continue
        period_cond = (
            f'"{left_table}"."{period_pair["left"]}" = '
            f'"{right_table}"."{period_pair["right"]}"'
        )
        on_clause = " AND ".join([*key_conds, period_cond])
        period_expr = _period_expression(period_pair["left"], left_table, date_masks)
        sql = (
            f'SELECT {period_expr} AS "Period", '
            f'AVG(CAST("{left_table}"."{left_measure}" AS double)) AS "MetricA", '
            f'AVG(CAST("{right_table}"."{right_measure}" AS double)) AS "MetricB" '
            f'FROM "{left_table}" JOIN "{right_table}" ON {on_clause} '
            f'GROUP BY {period_expr} ORDER BY "Period"'
        )
        sql = normalize_date_casts(sql, date_masks)
        result, _err = await _query_with_error(runner, sql)
        if not result or not result.get("rows"):
            continue
        if _series_is_constant(result.get("rows", []), "MetricB"):
            continue
        analysis = {
            "id": f"templated_join_{left_table}_{right_table}",
            "category": "relationship",
            "title": f"{left_measure} and {right_measure} over {period_pair['left']}",
            "rationale": (
                f"Deterministic cross-table trend joining {left_table} and "
                f"{right_table} on the verified keys plus shared period."
            ),
            "sql": sql,
            "chart_type": "dual_line",
            "label_column": "Period",
            "value_column": "MetricA",
            "value_column_2": "MetricB",
            "severity_hint": "watch",
        }
        return analysis, result
    return None, None
