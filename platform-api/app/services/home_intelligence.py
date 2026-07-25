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
import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.models.database_data_source import DatabaseDataSource
from app.models.file_source_meta import FileSourceMeta
from app.models.project import Project
from app.models.project_asset import ProjectAsset
from app.models.query_scope import QueryScope
from app.models.reference_library import (
    TIER_COMPANY,
    TIER_INDUSTRY,
    TIER_PROJECT,
    ReferenceDocument,
)
from app.models.saved_query import SavedQuery
from app.services import deep_analysis
from app.services.ai_governance import ai_governance_service
from app.services.analytical_method_engine import (
    EngineMode,
    data_profiler,
    get_engine_mode,
)
from app.services.analytical_method_engine import (
    analyze as analyze_methods,
)
from app.services.analytical_method_engine.intent import infer_intent
from app.services.chart_catalog import fit_ranked
from app.services.evidence_severity import gate_severity
from app.services.insight_confidence import evaluate_confidence
from app.services.insight_evidence_fingerprint import (
    build_evidence_fingerprint,
    build_plan_fingerprint,
    deduplicate_by_evidence,
    fingerprint_for_card,
)
from app.services.insight_explanation import build_explanation, infer_method
from app.services.presentation_engine import PresentationMode
from app.services.project_ai_context import build_project_ai_context
from app.services.prompt_loader import load_prompt_reference
from app.services.response_envelope import attach_envelope
from app.services.teiid_sql import (
    date_masks_from_samples,
    normalize_date_casts,
)
from app.services.visualization_engine import (
    ChartType,
    VizCandidate,
    VizDecision,
    _catalog_facts,
    _catalog_shape,
    _detect_semantic_roles,
    business_dimensions,
    derive_shape,
    rank_visualizations,
    select_visualization,
)
from app.services.visualization_engine import (
    _Shape as Shape,
)

logger = logging.getLogger(__name__)

ALL_PROMPT_TYPES = ["risk_sla", "risk_expiry", "trend_spend", "opportunity_supplier"]

# Authoritative methodology for richer Home cards (insight-first, KPI-aware,
# evidence-gated joins). Loaded once and used to ground generation.
HOME_BEST_PRACTICES_FILE = "home_insight_best_practices.md"


def home_best_practices() -> str:
    """Return the Home Insight best-practices reference text (cached)."""
    return load_prompt_reference(HOME_BEST_PRACTICES_FILE)


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
class ScopeLink:
    """A user/AI-curated drill-down relationship resolved to view names.

    Sourced from enabled ``QueryScope`` rows and mapped from saved-query ids
    onto the concrete Teiid view names the planner reasons about, so a curated
    relationship becomes strong join evidence.
    """

    left_table: str
    right_table: str
    left_column: str
    right_column: str
    created_by_ai: bool


@dataclass
class ProjectContext:
    tables: list[TableInfo]
    documents: list[DocInfo]
    scope_links: list[ScopeLink] = field(default_factory=list)


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

    scope_links: list[ScopeLink] = []
    try:
        scope_links = await _resolve_scope_links(
            session,
            project_id=project.id,
            allowed_tables=[t.view_name for t in tables],
        )
    except Exception as exc:  # fail-open: enrichment must never break context
        logger.warning(
            "Scope-link enrichment skipped for project %s: %s", project.id, exc
        )

    return ProjectContext(
        tables=tables,
        documents=documents,
        scope_links=scope_links,
    )


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


async def _resolve_scope_links(
    session: AsyncSession,
    *,
    project_id: int,
    allowed_tables: list[str],
) -> list[ScopeLink]:
    """Map this project's enabled ``QueryScope`` rows onto view-to-view links.

    Only enabled scopes for *this* project are read (never crossing project
    boundaries). Each scope's source and target saved query is resolved to a
    single allowed view via :func:`_detect_view_strict`; scopes whose SQL is
    missing, matches zero or multiple views, or self-references are skipped.
    Links are de-duplicated by (sorted view pair, normalized source field).
    """
    scopes = (
        await session.scalars(
            select(QueryScope).where(
                QueryScope.project_id == project_id,
                QueryScope.enabled.is_(True),
            )
        )
    ).all()
    if not scopes:
        return []

    query_ids = {s.query_id for s in scopes} | {
        s.target_query_id for s in scopes
    }
    queries = (
        await session.scalars(
            select(SavedQuery).where(SavedQuery.id.in_(query_ids))
        )
    ).all()
    sql_by_id = {q.id: q.sql_text for q in queries}

    links: list[ScopeLink] = []
    seen: set[tuple[str, str, str]] = set()
    for s in scopes:
        left = _detect_view_strict(sql_by_id.get(s.query_id), allowed_tables)
        right = _detect_view_strict(
            sql_by_id.get(s.target_query_id), allowed_tables
        )
        if not left or not right or left == right:
            continue
        lo, hi_ = sorted([left, right])
        key = (lo, hi_, _norm(s.source_field))
        if key in seen:
            continue
        seen.add(key)
        links.append(
            ScopeLink(
                left_table=left,
                right_table=right,
                left_column=s.source_field.strip('"'),
                right_column=s.target_field.strip('"'),
                created_by_ai=bool(s.created_by_ai),
            )
        )
    return links


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
# Severity calibration, ranking & dedup
# ─────────────────────────────────────────────────────────────────────────────

# Severity values the Home UI renders (an unknown value falls back to "info"
# client-side, but we normalise here so cards stay calibrated).
_ALLOWED_SEVERITIES = (
    "critical", "urgent", "warning", "watch", "opportunity", "info",
)
_SEVERITY_RANK = {
    "critical": 6, "urgent": 5, "warning": 4, "watch": 3,
    "opportunity": 3, "info": 1,
}


def _normalize_severity(value: Any) -> str:
    v = str(value or "").strip().lower()
    return v if v in _ALLOWED_SEVERITIES else "info"


def _card_priority(card: dict[str, Any]) -> float:
    """Score a card for ranking: severity first, then evidence strength."""
    score = _SEVERITY_RANK.get(card.get("severity", "info"), 1) * 10.0
    conf = card.get("confidenceScore")
    score += (float(conf) if isinstance(conf, int | float) else 0.5) * 3.0
    if card.get("chart"):
        score += 1.0
    if card.get("kpiReferences") or card.get("referenceDocuments"):
        score += 2.0
    if card.get("relationshipMetadata"):
        # Evidence-backed cross-table findings are the scarcest signal class;
        # weight them so they rank alongside same-severity single-table cards
        # rather than at the bottom of the page.
        score += 2.5
    pri = card.get("priorityScore")
    if isinstance(pri, int | float) and pri > 0:
        return float(pri)
    return score


def _dedupe_key(card: dict[str, Any]) -> str | None:
    """Return the canonical evidence fingerprint key for a card, if available."""
    fp = fingerprint_for_card(card)
    return fp.dedupe_key


def _pre_execution_dedupe(
    analyses: list[dict[str, Any]],
    *,
    project_id: int,
    tenant_id: int,
    tables: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Collapse planned analyses with identical intent + source scope before SQL.

    The plan LLM may rephrase the same analytical question twice; a plan
    fingerprint catches identical SQL/columns/label/value pairs even when the
    title or rationale differs.
    """
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for a in analyses:
        fp = build_plan_fingerprint(
            project_id=project_id,
            tenant_id=tenant_id,
            analysis=a,
            tables=tables,
            method_id=a.get("method"),
            source_columns=a.get("sourceColumns"),
        )
        if fp in seen:
            continue
        seen.add(fp)
        a["planFingerprint"] = fp
        unique.append(a)
    return unique


def rank_and_dedupe_cards(
    cards: list[dict[str, Any]], *, max_cards: int = 8
) -> list[dict[str, Any]]:
    """Return the strongest, de-duplicated cards (best-practices §Insight
    Selection / §Card Ranking). Duplicates that share canonical evidence
    (result set, series, or semantic interpretation) are collapsed to the
    highest-scoring one, regardless of title wording.

    Multi-table (relationship-evidence) cards are exempt from the cap: they
    are the rarest, highest-effort findings, so every one that executed and
    passed the quality gates is surfaced. Only single-table cards compete for
    the ``max_cards`` slots.
    """
    unique = deduplicate_by_evidence(cards, priority_fn=_card_priority)

    def _is_multi(c: dict[str, Any]) -> bool:
        return len(c.get("sources", {}).get("tables", [])) >= 2

    multi = [c for c in unique if _is_multi(c)]
    single = [c for c in unique if not _is_multi(c)]
    return sorted(multi + single[:max_cards], key=_card_priority, reverse=True)


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
    metadata: dict[str, Any] | None = None,
    sql: str | None = None,
    chart_type: str | None = None,
    label_column: str | None = None,
    value_column: str | None = None,
    value_column_2: str | None = None,
    insight_id: str | None = None,
    result: dict[str, Any] | None = None,
    explanation: dict[str, Any] | None = None,
    method: str | None = None,
    governance: dict[str, Any] | None = None,
    project_context: dict[str, Any] | None = None,
    method_envelope: dict[str, Any] | None = None,
    relationship_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    card: dict[str, Any] = {
        "id": f"{project.id}-{insight_type}-{int(datetime.now().timestamp() * 1000) % 100000}",
        "insightId": insight_id or uuid.uuid4().hex,
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
    # Persist the raw SQL and chart roles for data-backed cards so they can
    # be saved as dashboard widgets. Only include non-empty values; narrative-only
    # cards will omit these fields and remain ineligible for "Save to dashboard".
    if sql:
        card["sql"] = sql
    if chart_type:
        card["chartType"] = chart_type
    if label_column:
        card["labelColumn"] = label_column
    if value_column:
        card["valueColumn"] = value_column
    if value_column_2:
        card["valueColumn2"] = value_column_2
    # Backward-compatible optional metadata (confidenceScore, priorityScore,
    # insightMethod, validation, relationshipMetadata, ...). The frontend
    # ignores unknown keys, so this never affects the existing card layout.
    if metadata:
        for key, value in metadata.items():
            if value not in (None, "", [], {}):
                card[key] = value

    # Build a structured explanation from the actual analysis inputs. Callers can
    # supply a pre-built explanation; otherwise it is derived from the SQL, chart,
    # and sourceContext metadata already on the card.
    if explanation is None:
        ctx = (metadata or {}).get("sourceContext") or {}
        fields = [c for c in (ctx.get("sourceColumns") or []) if c]
        explanation = build_explanation(
            project_id=project.id,
            project_name=project.name,
            insight_type=insight_type,
            summary=summary,
            chart=chart,
            chart_type=chart_type,
            label_column=label_column,
            value_column=value_column,
            value_column_2=value_column_2,
            tables=tables,
            fields=fields,
            metric=ctx.get("metric") or value_column,
            aggregation=ctx.get("aggregation"),
            period_column=ctx.get("periodColumn") or label_column,
            filters=ctx.get("filters"),
            comparison=ctx.get("comparison"),
            result=result,
            sql=sql,
            assumptions=ctx.get("assumptions"),
            limitations=ctx.get("limitations"),
            documents=documents,
            generated_at=card["executedAt"],
            method=method,
            governance=governance,
            project_context=project_context,
        ) or {}
    if explanation:
        card["explanation"] = explanation

    # Evidence-first metadata: canonical fingerprints, structured confidence,
    # and ranked chart candidates. Computed from the actual result/chart so
    # identical evidence cannot be duplicated under a different title and
    # confidence reflects evidence quality rather than row count alone.
    tenant_id = getattr(project, "tenant_id", 0) or 0
    analysis_plan = {
        "sql": sql,
        "chart_type": chart_type,
        "label_column": label_column,
        "value_column": value_column,
        "value_column_2": value_column_2,
        "source_documents": documents,
    }
    result_columns = [str(c) for c in (result.get("columns") or [])] if result else []
    result_rows = result.get("rows") or [] if result else []

    try:
        evidence_fp = build_evidence_fingerprint(
            project_id=project.id,
            tenant_id=tenant_id,
            analysis=analysis_plan,
            result=result,
            chart=chart,
            tables=tables,
            columns=result_columns,
            label_column=label_column,
            value_column=value_column,
            value_column_2=value_column_2,
            method_id=(method_envelope or {}).get("method") or method,
            dimensions=([label_column] if label_column else []) + ([value_column_2] if value_column_2 else []),
            measures=[value_column] if value_column else [],
            period_column=label_column if chart_type in ("line", "area", "combo") else None,
            aggregations=None,
            grain=None,
            intent=chart_type,
        )
        fp_dict = evidence_fp.to_dict()
        fp_dict["tenant_id"] = tenant_id
        card["evidenceFingerprint"] = fp_dict
    except Exception as exc:
        logger.debug("evidence fingerprint failed for insight %s: %s", insight_id, exc)

    try:
        ctx = (metadata or {}).get("sourceContext") or {}
        validation = (metadata or {}).get("validation") or {}
        if validation and not validation.get("executedAt") and card.get("executedAt"):
            validation["executedAt"] = card["executedAt"]
        if not validation and result:
            validation = {
                "executionStatus": "success",
                "rowCount": len(result_rows),
                "columnsReturned": result_columns,
                "nonNullMetricCount": (
                    sum(1 for r in result_rows if _to_float(r.get(value_column) if isinstance(r, dict) else None) is not None)
                    if value_column else 0
                ),
                "executedAt": card["executedAt"],
            }
        confidence_eval = evaluate_confidence(
            validation=validation,
            method_envelope=method_envelope,
            relationship_meta=relationship_meta,
            result=result,
            source_context={
                "sourceTables": tables,
                "sourceColumns": ctx.get("sourceColumns") or result_columns,
                "periodColumn": ctx.get("periodColumn") or label_column,
                "referenceDocuments": documents,
            },
            columns=result_columns,
            rows=result_rows,
            label_column=label_column,
            value_column=value_column,
            is_document_only=(result is None and bool(documents)),
            uses_reference=bool(documents) and any(isinstance(d, str) for d in (documents or [])),
            has_project_evidence=(result is not None) or (bool(documents) and not all(isinstance(d, str) for d in (documents or []))),
            intent=chart_type,
        )
        card["confidenceEvaluation"] = confidence_eval.to_dict()
        card["confidenceScore"] = confidence_eval.score
        if card.get("explanation") and isinstance(card["explanation"], dict):
            card["explanation"]["confidence"] = {
                "level": confidence_eval.level,
                "score": confidence_eval.score,
                "basis": confidence_eval.basis,
            }
            card["explanation"]["confidenceFactors"] = [
                {"label": f.label, "status": f.status, "score": f.score, "weight": f.weight, "evidence": f.evidence}
                for f in confidence_eval.factors
            ]
            card["explanation"]["confidenceCaps"] = confidence_eval.caps
            card["explanation"]["confidenceGaps"] = confidence_eval.gaps
            card["explanation"]["whatWouldIncreaseConfidence"] = confidence_eval.what_would_increase_confidence
    except Exception as exc:
        logger.debug("confidence evaluation failed for insight %s: %s", insight_id, exc)

    try:
        if result and result_rows:
            current_chart_type = (card.get("chart") or {}).get("type")
            has_custom_rows = bool((card.get("chart") or {}).get("data", {}).get("rows"))
            # Shape-template cards carry their own visualizationDecision from the
            # template generator; honour it and do not overwrite the chart type.
            if has_custom_rows and card.get("chart", {}).get("visualizationDecision"):
                card["visualizationDecision"] = card["chart"]["visualizationDecision"]
                card["chartCandidates"] = card["chart"].get("chartCandidates", [])
            else:
                candidates = rank_visualizations(result_columns, result_rows, limit=50)
                if candidates:
                    chosen = candidates[0]
                    # Preserve legacy multi-KPI card type and shape-template rows
                    # while still offering ranked candidates in the chart picker.
                    preserve_type = current_chart_type == "kpi_grid" or has_custom_rows
                    for c in candidates:
                        match_value = c.decision.chart_type.value
                        if current_chart_type == "kpi_grid" and match_value == "kpi":
                            chosen = c
                            break
                        if match_value == current_chart_type:
                            chosen = c
                            break

                    # If the caller already built a concrete chart (e.g. risk SLA
                    # bar) but the catalog does not propose that family for this
                    # shape, inject it as the top candidate so the rendered card
                    # does not silently switch to a different chart type.
                    if (
                        current_chart_type
                        and not preserve_type
                        and chosen.decision.chart_type.value != current_chart_type
                    ):
                        try:
                            current_enum = ChartType(current_chart_type)
                        except ValueError:
                            current_enum = None
                        if current_enum is not None:
                            current_candidate = VizCandidate(
                                decision=VizDecision(
                                    chart_type=current_enum,
                                    chart_style=(card.get("chart") or {}).get("subtype") or "",
                                    x_field=label_column,
                                    y_field=value_column,
                                    y2_field=value_column_2,
                                    reason="Current inline chart preserved.",
                                ),
                                score=1.0,
                            )
                            candidates.insert(0, current_candidate)
                            chosen = current_candidate

                    card["visualizationDecision"] = chosen.decision.to_dict()
                    card["chartCandidates"] = [c.to_dict() for c in candidates[:50]]
                    if card.get("chart") and not preserve_type:
                        card["chart"]["type"] = chosen.decision.chart_type.value
                        card["chart"]["subtype"] = chosen.decision.chart_style or ""
    except Exception as exc:
        logger.debug("chart candidate generation failed for insight %s: %s", insight_id, exc)

    # M4 fast-follow (contract-only): stamp the shared ResponseEnvelope so a
    # Home card also emits the unified contract. The card keeps its bespoke
    # renderer; this is additive metadata (fail-closed) the UI ignores.
    attach_envelope(
        card,
        PresentationMode.HYBRID,
        executive_summary=summary,
        chart=chart,
        sources=[*(tables or []), *(documents or [])] or None,
    )
    return card


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
                {"label": d.isoformat(), "value": n} for d, n in upcoming[:12]
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
    if chart_type in ("scatter", "bubble"):
        # Scatter uses two numeric measures as X and Y; a label dimension is only
        # used for point names and must not consume one of the measures.
        value_col = value_hint if value_hint and value_hint in columns else _pick_columns(columns, rows, "", "")[1]
        if not value_col:
            return None
        value2_col = _pick_second_value(columns, rows, (value_col,), value_hint_2)
        if not value2_col:
            return None
        shape = derive_shape(columns, rows)
        label_col = next(
            (c.name for c in shape.columns if c.name not in (value_col, value2_col) and c.kind in ("categorical", "text")),
            None,
        )
    else:
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
            "roles": {"x": label_col or "label", "y": value_col, "y2": value2_col},
            "seriesLabels": series_labels,
        }
    # scatter / bubble -> two variables as x/y (bubble degrades to scatter when
    # no third size metric is available).
    return {
        "type": "scatter",
        "subtype": "bubble" if chart_type == "bubble" else "",
        "title": title,
        "data": {"series": series},
        "roles": {"x": value_col, "y": value2_col},
        "seriesLabels": series_labels,
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
    # Exclude the grouped dimension/period column (e.g. a "Period" year) so it is
    # never shown as a headline number — a bare year like 2026 would otherwise
    # format as a meaningless "2.0K" tile.
    if len(rows) == 1:
        row = rows[0]
        skip = _dimension_columns(columns, label_hint)
        kpis = [
            {"value": _fmt_num(v), "label": col}
            for col in columns
            if col not in skip and (v := _to_float(row.get(col))) is not None
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

    # ``kpi_grid`` is a shape-specific tile layout, not a chart family — keep it.
    if chart_type == "kpi_grid":
        kpis = [
            {"value": _fmt_num(s["value"]), "label": s["label"]} for s in series[:6]
        ]
        return {"type": "kpi_grid", "title": title, "data": {"kpis": kpis}}

    # Delegate the single-metric chart-type decision to the one Universal
    # Visualization Engine, passing the planner's pick as a hint so Home cards,
    # ask-and-run, and dashboards all resolve the same chart for the same shape.
    # The series (already shaped from the executed result) is preserved as-is.
    decision = select_visualization(
        [label_col, value_col],
        [{label_col: s["label"], value_col: s["value"]} for s in series],
        intent_hint=chart_type,
    )
    return {
        "type": decision.chart_type.value,
        "subtype": decision.chart_style,
        "title": title,
        "data": {"series": series},
        "seriesLabels": {"value": value_col},
        "roles": {"x": label_col or "label", "y": value_col},
    }


def _nice_name(col: str) -> str:
    """Human-friendly column name for insight titles."""
    return str(col).replace("_", " ").strip().title()


def _shape_scatter_label_col(shape: Shape, used: set[str]) -> str | None:
    """Pick a categorical/text label for scatter points, avoiding period axes."""
    return next(
        (
            c.name
            for c in shape.columns
            if c.name not in used and c.kind in ("categorical", "text")
        ),
        None,
    )


def _agg_for_measure(col: str) -> str:
    """Choose a default aggregation for a numeric measure column."""
    lower = str(col).lower()
    if any(k in lower for k in ("rate", "pct", "percent", "ratio", "score")):
        return "AVG"
    return "SUM"


def _quote(col: str) -> str:
    return f'"{col}"'


def _build_multi_chart(
    chart_type: str,
    title: str,
    rows: list[dict[str, Any]],
    columns: list[str],
    roles: dict[str, str],
) -> dict[str, Any]:
    """Build a chart payload using generic data rows + field roles.

    The frontend ``InsightChartView`` maps ``roles`` to ``WidgetConfig`` columns
    and renders the rows through the same ``WidgetRenderer`` used by dashboards.
    All shape-compatible chart families are ranked so the chart-suggestion modal
    can offer every viable alternative, not just the template's first choice.
    """
    ranked = rank_visualizations(columns, rows, limit=50)

    # Promote the template's intended family to the top so the preselected card
    # matches the shape that produced it, but still expose every eligible family.
    candidates = [c.to_dict() for c in ranked]
    template_index = next(
        (
            i
            for i, c in enumerate(candidates)
            if c.get("decision", {}).get("chartType") == chart_type
        ),
        None,
    )
    if template_index is not None and template_index > 0:
        intended = candidates.pop(template_index)
        candidates.insert(0, intended)
    elif not candidates:
        # Fallback: at least one candidate for the intended family.
        x_field = roles.get("x")
        y_field = roles.get("value") or roles.get("y")
        y2_field = roles.get("y2") or roles.get("group")
        candidates = [
            {
                "decision": {
                    "chartType": chart_type,
                    "chartStyle": "",
                    "xField": x_field,
                    "yField": y_field,
                    "valueFormat": "number",
                    "reason": f"Shape template generated a {chart_type} chart from the source table.",
                    "y2Field": y2_field,
                },
                "score": 1.0,
                "supported": True,
                "unsupportedReason": "",
            }
        ]

    decision = candidates[0]["decision"]

    return {
        "type": chart_type,
        "subtype": "",
        "title": title,
        "data": {"rows": rows, "columns": columns},
        "roles": roles,
        "visualizationDecision": decision,
        "chartCandidates": candidates,
    }


def _build_radar_rows(rows: list[dict[str, Any]], subject_col: str, measure_cols: list[str]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Melt a wide scorecard (subject + measures) into long radar rows."""
    long_rows: list[dict[str, Any]] = []
    for r in rows:
        subject = r.get(subject_col)
        if subject is None:
            continue
        for m in measure_cols:
            v = _to_float(r.get(m))
            if v is None:
                continue
            long_rows.append({"subject": str(subject), "metric": m, "value": round(v, 2)})
    return long_rows, {"x": "subject", "y": "value", "group": "metric"}


async def _build_radar_template(
    table: Any,
    shape: Shape,
    dims: list[str],
    measures: list[str],
    roles: dict[str, Any],
    runner: QueryRunner,
    max_rows: int,
) -> dict[str, Any] | None:
    if len(dims) < 1 or len(measures) < 3:
        return None
    subject_col = dims[0]
    measure_cols = measures[:6]
    agg = ", ".join(f'{_agg_for_measure(m)}({_quote(m)}) AS {_quote(m)}' for m in measure_cols)
    sql = f'SELECT {_quote(subject_col)}, {agg} FROM {_quote(table.view_name)} GROUP BY {_quote(subject_col)} LIMIT {max_rows}'
    result = await _safe_query(runner, sql)
    if not result or not result.get("rows"):
        return None
    long_rows, radar_roles = _build_radar_rows(result["rows"], subject_col, measure_cols)
    if not long_rows:
        return None
    title = f"{_nice_name(subject_col)} Scorecard"
    chart = _build_multi_chart("radar", title, long_rows, ["subject", "metric", "value"], radar_roles)
    return {
        "insight_type": "shape_radar",
        "group": "analysis",
        "title": title,
        "summary": f"Compare {len(measure_cols)} metrics across {len(result['rows'])} {_nice_name(subject_col)} values.",
        "chart": chart,
        "result": result,
        "sql": sql,
    }


async def _build_heatmap_template(
    table: Any,
    shape: Shape,
    dims: list[str],
    measures: list[str],
    roles: dict[str, Any],
    runner: QueryRunner,
    max_rows: int,
) -> dict[str, Any] | None:
    if len(dims) < 2 or len(measures) < 1:
        return None
    x_col, y_col = dims[0], dims[1]
    value_col = measures[0]
    agg = _agg_for_measure(value_col)
    sql = (
        f'SELECT {_quote(x_col)}, {_quote(y_col)}, {agg}({_quote(value_col)}) AS {_quote("value")} '
        f'FROM {_quote(table.view_name)} GROUP BY {_quote(x_col)}, {_quote(y_col)} LIMIT {max_rows}'
    )
    result = await _safe_query(runner, sql)
    if not result or not result.get("rows"):
        return None
    title = f"{_nice_name(value_col)} by {_nice_name(x_col)} and {_nice_name(y_col)}"
    chart = _build_multi_chart(
        "heatmap",
        title,
        result["rows"],
        result.get("columns", [x_col, y_col, "value"]),
        {"x": x_col, "y": y_col, "value": "value"},
    )
    return {
        "insight_type": "shape_heatmap",
        "group": "analysis",
        "title": title,
        "summary": f"Heatmap of {_nice_name(value_col)} across {_nice_name(x_col)} and {_nice_name(y_col)}.",
        "chart": chart,
        "result": result,
        "sql": sql,
    }


async def _build_treemap_template(
    table: Any,
    shape: Shape,
    dims: list[str],
    measures: list[str],
    roles: dict[str, Any],
    runner: QueryRunner,
    max_rows: int,
) -> dict[str, Any] | None:
    if len(dims) < 2 or len(measures) < 1:
        return None
    parent_col, child_col = dims[0], dims[1]
    value_col = measures[0]
    agg = _agg_for_measure(value_col)
    sql = (
        f'SELECT {_quote(parent_col)}, {_quote(child_col)}, {agg}({_quote(value_col)}) AS {_quote("value")} '
        f'FROM {_quote(table.view_name)} GROUP BY {_quote(parent_col)}, {_quote(child_col)} LIMIT {max_rows}'
    )
    result = await _safe_query(runner, sql)
    if not result or not result.get("rows"):
        return None
    title = f"{_nice_name(value_col)} by {_nice_name(parent_col)} / {_nice_name(child_col)}"
    chart = _build_multi_chart(
        "treemap",
        title,
        result["rows"],
        result.get("columns", [parent_col, child_col, "value"]),
        {"x": parent_col, "group": child_col, "value": "value"},
    )
    return {
        "insight_type": "shape_treemap",
        "group": "analysis",
        "title": title,
        "summary": f"Hierarchical breakdown of {_nice_name(value_col)} by {_nice_name(parent_col)} and {_nice_name(child_col)}.",
        "chart": chart,
        "result": result,
        "sql": sql,
    }


async def _build_sankey_template(
    table: Any,
    shape: Shape,
    dims: list[str],
    measures: list[str],
    roles: dict[str, Any],
    runner: QueryRunner,
    max_rows: int,
) -> dict[str, Any] | None:
    if len(measures) < 1:
        return None
    if roles.get("source") and roles.get("target"):
        source_col = roles["source"]
        target_col = roles["target"]
    elif len(dims) >= 2:
        source_col = dims[0]
        target_col = dims[1]
    else:
        return None
    value_col = roles.get("value") or measures[0]
    agg = _agg_for_measure(value_col)
    sql = (
        f'SELECT {_quote(source_col)}, {_quote(target_col)}, {agg}({_quote(value_col)}) AS {_quote("value")} '
        f'FROM {_quote(table.view_name)} GROUP BY {_quote(source_col)}, {_quote(target_col)} LIMIT {max_rows}'
    )
    result = await _safe_query(runner, sql)
    if not result or not result.get("rows"):
        return None
    title = f"Flow from {_nice_name(source_col)} to {_nice_name(target_col)}"
    chart = _build_multi_chart(
        "sankey",
        title,
        result["rows"],
        result.get("columns", [source_col, target_col, "value"]),
        {"x": source_col, "group": target_col, "value": "value"},
    )
    return {
        "insight_type": "shape_sankey",
        "group": "analysis",
        "title": title,
        "summary": f"Source-to-target flow weighted by {_nice_name(value_col)}.",
        "chart": chart,
        "result": result,
        "sql": sql,
    }


async def _build_funnel_template(
    table: Any,
    shape: Shape,
    dims: list[str],
    measures: list[str],
    roles: dict[str, Any],
    runner: QueryRunner,
    max_rows: int,
) -> dict[str, Any] | None:
    if len(dims) < 1 or len(measures) < 1:
        return None
    stage_col = roles.get("stage")
    if not stage_col:
        return None
    value_col = measures[0]
    agg = _agg_for_measure(value_col)
    sql = (
        f'SELECT {_quote(stage_col)}, {agg}({_quote(value_col)}) AS {_quote("value")} '
        f'FROM {_quote(table.view_name)} GROUP BY {_quote(stage_col)} ORDER BY {_quote("value")} DESC LIMIT {max_rows}'
    )
    result = await _safe_query(runner, sql)
    if not result or not result.get("rows"):
        return None
    title = f"{_nice_name(stage_col)} {_nice_name(value_col)} Funnel"
    chart = _build_multi_chart(
        "funnel",
        title,
        result["rows"],
        result.get("columns", [stage_col, "value"]),
        {"x": stage_col, "value": "value"},
    )
    return {
        "insight_type": "shape_funnel",
        "group": "analysis",
        "title": title,
        "summary": f"Stage progression of {_nice_name(value_col)} by {_nice_name(stage_col)}.",
        "chart": chart,
        "result": result,
        "sql": sql,
    }


async def _build_scatter_template(
    table: Any,
    shape: Shape,
    dims: list[str],
    measures: list[str],
    roles: dict[str, Any],
    runner: QueryRunner,
    max_rows: int,
) -> dict[str, Any] | None:
    if len(measures) < 2:
        return None
    x_col, y_col = measures[0], measures[1]
    label_col = _shape_scatter_label_col(shape, {x_col, y_col})
    label_select = f", {_quote(label_col)}" if label_col else ""
    sql = f'SELECT {_quote(x_col)}, {_quote(y_col)}{label_select} FROM {_quote(table.view_name)} LIMIT {max_rows}'
    result = await _safe_query(runner, sql)
    if not result or not result.get("rows"):
        return None
    title = f"{_nice_name(x_col)} vs {_nice_name(y_col)}"
    scatter_chart = _build_chart(
        "scatter",
        title,
        result,
        label_hint=label_col or "",
        value_hint=x_col,
        value_hint_2=y_col,
    )
    if not scatter_chart:
        return None
    return {
        "insight_type": "shape_scatter",
        "group": "analysis",
        "title": title,
        "summary": f"Relationship between {_nice_name(x_col)} and {_nice_name(y_col)} across {len(result['rows'])} records.",
        "chart": scatter_chart,
        "result": result,
        "sql": sql,
    }


#: A shape template only runs when the family is a genuinely good fit for the
#: probed table; below this the card would be a technically-eligible but
#: misleading chart (e.g. a heatmap over an id-like dimension).
_SHAPE_TEMPLATE_MIN_FIT = 0.5

_TEMPLATE_BUILDERS: dict[str, Any] = {
    "radar": _build_radar_template,
    "heatmap": _build_heatmap_template,
    "treemap": _build_treemap_template,
    "sankey": _build_sankey_template,
    "funnel": _build_funnel_template,
    "scatter": _build_scatter_template,
}


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
    if get_engine_mode() == EngineMode.OFF:
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
                envelope = await analyze_methods(
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


def _plan_documents(ctx: ProjectContext) -> list[dict[str, Any]]:
    """Serialize a project's documents for the analysis planner."""
    return [
        {
            "title": d.title,
            "summary": d.ai_summary or "",
            "tags": [
                str(t) for t in (d.ai_metadata.get("tags") or [])
                if isinstance(t, str | int | float)
            ],
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


async def plan_and_execute_widgets(
    project: Project,
    ctx: ProjectContext,
    runner: QueryRunner,
    *,
    tenant_id: int,
    user_id: int,
    max_analyses: int,
    granularity: int,
    session: AsyncSession | None = None,
) -> list[dict[str, Any]]:
    """Plan data analyses and execute each with the SAME robustness the analyst
    loop uses — real per-column samples in the schema, date-cast normalization,
    and LLM self-repair on a Teiid rejection.

    The dashboard-suggestion surfaces previously planned SQL without samples and
    ran it once with no repair, so a widget whose SQL hit a Teiid quirk (non-ISO
    date CAST, alias-in-GROUP BY, unsupported function) was silently dropped —
    leaving dashboards with a single widget (or none). Sharing this pipeline lets
    those widgets be repaired and survive.

    Returns the analyses that produced real rows, each augmented with the final
    ``sql`` and the executed ``result`` ({columns, rows}).
    """
    from app.services import ai_intelligence_client as ai

    if not ai.is_enabled():
        return []

    project_context: dict[str, Any] | None = None
    if session is not None:
        try:
            project_context = await build_project_ai_context(
                session,
                tenant_id=tenant_id,
                project_id=project.id,
                request_type="dashboard",
            )
        except Exception as exc:
            logger.warning(
                "Failed to build project AI context for dashboard project %s: %s",
                project.id,
                exc,
            )

    allowed_tables = [t.view_name for t in ctx.tables]
    sample_results = await asyncio.gather(
        *(_sample_values(runner, t.view_name) for t in ctx.tables)
    )
    samples_per_table = [s for (s, _) in sample_results]
    key_values_by_table = {
        t.view_name: kv
        for t, (_, kv) in zip(ctx.tables, sample_results, strict=False)
    }
    table_schema = [
        {
            "table": t.view_name,
            "storage": "text" if t.kind == "file" else "native",
            "columns": [
                {"name": n, "type": ty, "sample": samples.get(n, "")}
                for (n, ty) in t.columns
            ],
        }
        for t, samples in zip(ctx.tables, samples_per_table, strict=False)
    ]
    date_masks = date_masks_from_samples(samples_per_table)
    documents = _plan_documents(ctx)
    relationship_hints = find_relationship_candidates(
        ctx.tables,
        scope_links=ctx.scope_links,
        key_values=key_values_by_table,
        date_masks=date_masks,
    )

    plan_documents = documents
    if project_context and project_context.get("ai_context_enabled"):
        plan_documents = [
            {
                "title": "Project Business Context",
                "summary": (
                    f"Purpose: {project_context.get('project', {}).get('purpose', 'N/A')}"
                )[:1200],
                "tags": ["project_context"],
                "source": "project_context",
                "tier": "",
                "issuing_body": "",
            },
            *documents,
        ]

    analyses = await ai.plan(
        tenant_id=tenant_id,
        user_id=user_id,
        project_id=project.id,
        allowed_tables=allowed_tables,
        documents=plan_documents,
        table_schema=table_schema,
        relationship_hints=relationship_hints,
        max_analyses=max_analyses,
        granularity=granularity,
        project_context=project_context or {},
    )
    if not analyses:
        return []

    executed: list[dict[str, Any]] = []
    to_repair: list[tuple[dict[str, Any], str, str]] = []
    for a in analyses:
        sql = (a.get("sql") or "").strip()
        if not sql:
            continue  # narrative/document finding — not a chartable widget
        sql = normalize_date_casts(sql, date_masks)
        result, err = await _query_with_error(runner, sql)
        if result and result.get("rows"):
            executed.append({**a, "sql": sql, "result": result})
        elif err:
            to_repair.append((a, sql, err))

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
            fixed = normalize_date_casts(fixed, date_masks)
            result, _ = await _query_with_error(runner, fixed)
            if result and result.get("rows"):
                executed.append({**a, "sql": fixed, "result": result})

    return executed


# Analysis categories that map cleanly onto a declared engine intent. Risk and
# opportunity carry no shape information, so the engine's own inference (which
# reconciles keywords against the actual data profile) decides for those.
_CATEGORY_INTENT_HINTS: dict[str, str | None] = {
    # Explicit, unambiguous categories from the insight taxonomy route directly.
    "relationship": "relationship_numeric",
    "group-comparison": "compare_multiple_groups",
    "period-change": "compare_periods",
    "forecast": "forecast_time_series",
    "anomaly": "detect_anomalies",
    "driver": "contribution_to_change",
    "descriptive": "describe_numeric",
    # Generic card categories are resolved per-item from title/rationale + data shape
    # so a "trend" card titled "Month-over-month change" can route to compare_periods.
    "trend": None,
    "risk": None,
    "opportunity": None,
}


def _resolve_intent_hint(
    analysis: dict[str, Any], result: dict[str, Any]
) -> str | None:
    """Pick the strongest intent hint for an executed analysis.

    Explicit `_CATEGORY_INTENT_HINTS` entries win. For the generic
    ``trend``/``risk``/``opportunity`` buckets the title/rationale plus the
    actual result shape are used so Set B time-series methods (forecast,
    period-change, anomaly, change-point, contribution) can be selected.
    """
    category = str(analysis.get("category") or "").lower()
    explicit = _CATEGORY_INTENT_HINTS.get(category)
    if explicit is not None:
        return explicit
    question = " — ".join(
        str(x) for x in (analysis.get("title"), analysis.get("rationale")) if x
    )
    profile = data_profiler.profile(
        result.get("columns", []), result.get("rows", [])
    )
    return infer_intent(question, profile)


async def _attach_method_envelopes(
    session: AsyncSession | None,
    *,
    tenant_id: int,
    executed: list[dict[str, Any]],
) -> None:
    """Run the Analytical Method Engine over each executed analysis.

    Attaches the governed envelope onto the executed item (HYBRID only) so
    the card-building loop can surface it. Sequential on purpose: the engine
    reads/writes through this AsyncSession, which is not safe for concurrent
    use. Fail-closed per item — an engine problem never drops a card
    (regression guard for the earlier 6->0 incidents).
    """
    if session is None:
        return
    mode = get_engine_mode()
    if mode == EngineMode.OFF:
        return
    for item in executed:
        a = item["analysis"]
        result = item["result"]
        if not result:
            continue
        question = " — ".join(
            str(x) for x in (a.get("title"), a.get("rationale")) if x
        )
        try:
            envelope = await analyze_methods(
                session,
                tenant_id=tenant_id,
                columns=result.get("columns", []),
                rows=result.get("rows", []),
                question=question or str(a.get("category") or ""),
                intent=_resolve_intent_hint(a, result),
            )
        except Exception as exc:  # pragma: no cover - engine is fail-closed
            logger.warning(
                "Method engine skipped for analysis %s: %s", a.get("id"), exc
            )
            continue
        # Attach only envelopes that actually selected a method — a
        # "no_method" envelope on every thin aggregate would be card noise
        # (it is still audited by the engine either way).
        if (
            mode == EngineMode.HYBRID
            and envelope
            and envelope.get("method") is not None
        ):
            item["method_envelope"] = envelope


async def run_ai_intelligence(
    project: Project,
    ctx: ProjectContext,
    runner: QueryRunner,
    *,
    session: AsyncSession | None = None,
    tenant_id: int,
    user_id: int,
    max_analyses: int = 15,
    granularity: int = 3,
    plan_semaphore: asyncio.Semaphore | None = None,
) -> list[dict[str, Any]] | None:
    """LLM-driven analyst loop. Returns cards, or ``None`` to signal fallback.

    1. Ask the AI to plan high-value analyses from the real schema + documents.
    2. Execute each generated SQL against the project's real data.
    3. Ask the AI to interpret the actual results into executive findings.

    Returns ``None`` only when AI is disabled. An unavailable initial plan raises
    so streaming callers report a project failure; a valid empty plan returns [].
    """
    from app.services import ai_intelligence_client as ai

    if not ai.is_enabled():
        return None

    project_context: dict[str, Any] | None = None
    if session is not None:
        try:
            project_context = await build_project_ai_context(
                session,
                tenant_id=tenant_id,
                project_id=project.id,
                request_type="business_insight",
            )
        except Exception as exc:
            logger.warning(
                "Failed to build project AI context for project %s: %s",
                project.id,
                exc,
            )

    # Knowledge Graph grounding: give the planner the graph's risks, gaps,
    # opportunities, and recommended-but-unmeasured KPIs as HYPOTHESES to test
    # with SQL (the AI-server plan prompt enforces that framing), so planned
    # analyses target what the graph says matters instead of re-deriving
    # salience from raw schema every run. Fail-open: a missing or failed graph
    # yields an empty block, never a failed run. Capped tighter than Project
    # Insight (10 vs 20 items) to protect the plan prompt's schema budget.
    kg_context: dict[str, Any] = {}
    if session is not None:
        try:
            from app.services.knowledge_graph_ai_context import (
                collect_knowledge_graph_ai_context,
            )

            kg_context = await collect_knowledge_graph_ai_context(
                session,
                tenant_id=tenant_id,
                project_id=project.id,
                user_id=user_id,
                max_items=10,
            )
        except Exception as exc:
            logger.warning(
                "Failed to collect KG context for project %s: %s", project.id, exc
            )

    ai_call_limit = max(
        1, get_settings().home_intelligence_max_concurrent_ai_calls_per_project
    )
    ai_call_sem = asyncio.Semaphore(ai_call_limit)

    allowed_tables = [t.view_name for t in ctx.tables]
    # Pull a real example value per column so the planner can see each column's
    # actual format (date masks, numeric-vs-text) and generate valid SQL; the
    # same probe collects distinct join-key values for relationship scoring.
    sample_results = await asyncio.gather(
        *(_sample_values(runner, t.view_name) for t in ctx.tables)
    )
    samples_per_table = [s for (s, _) in sample_results]
    key_values_by_table = {
        t.view_name: kv
        for t, (_, kv) in zip(ctx.tables, sample_results, strict=False)
    }
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
    date_masks = date_masks_from_samples(samples_per_table)
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

    # Evidence-backed join candidates (best-practices §Multi-Table
    # Relationship Policy). When present, the planner is allowed to propose
    # validated two-table insights; otherwise it stays single-table.
    relationship_hints = find_relationship_candidates(
        ctx.tables,
        scope_links=ctx.scope_links,
        key_values=key_values_by_table,
        date_masks=date_masks,
    )

    context_document: dict[str, Any] | None = None
    if project_context:
        context_summary = project_context.get("project", {})
        if project_context.get("ai_context_enabled"):
            context_document = {
                "title": "Project Business Context",
                "summary": (
                    f"Purpose: {context_summary.get('purpose', 'N/A')}\n"
                    f"Function: {context_summary.get('business_function', 'N/A')}\n"
                    f"Industry: {context_summary.get('industry', 'N/A')}\n"
                    f"Timezone: {context_summary.get('timezone', 'N/A')}, "
                    f"Currency: {context_summary.get('currency', 'N/A')}, "
                    f"Cadence: {context_summary.get('reporting_cadence', 'N/A')}"
                )[:1200],
                "tags": ["project_context"],
                "source": "project_context",
                "tier": "",
                "issuing_body": "",
            }

    async def request_plan() -> list[dict[str, Any]] | None:
        plan_documents = documents
        if context_document:
            plan_documents = [context_document, *documents]
        return await ai.plan(
            tenant_id=tenant_id,
            user_id=user_id,
            project_id=project.id,
            allowed_tables=allowed_tables,
            documents=plan_documents,
            table_schema=table_schema,
            relationship_hints=relationship_hints,
            max_analyses=max_analyses,
            granularity=granularity,
            project_context=project_context or {},
            knowledge_graph_context=kg_context,
        )

    if plan_semaphore is None:
        analyses = await request_plan()
    else:
        async with plan_semaphore:
            analyses = await request_plan()
    if analyses is None:
        raise ai.AIUnavailableError("AI planning is unavailable; retry shortly.")
    if not analyses:
        return []  # AI reachable but found nothing worth surfacing

    analyses = _pre_execution_dedupe(
        analyses,
        project_id=project.id,
        tenant_id=tenant_id,
        tables=[t.view_name for t in ctx.tables],
    )

    doc_by_title = {d.title: d for d in ctx.documents}
    # Index relationship hints by the table pair so multi-table cards can carry
    # the join metadata that backs them.
    hint_by_pair: dict[frozenset[str], dict[str, Any]] = {
        frozenset({h["left_table"], h["right_table"]}): h
        for h in relationship_hints
    }

    def _relationship_meta_for(a: dict[str, Any]) -> dict[str, Any] | None:
        tables = _tables_in_sql(a.get("sql", ""), ctx.tables)
        if len(tables) < 2:
            return None
        return hint_by_pair.get(frozenset(tables[:2]))

    async def _execute_and_guard(
        a: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        """Record a successful query, dropping it if the second series is constant."""
        if (
            a.get("chart_type") in _TWO_VALUE_TYPES
            and a.get("value_column_2")
            and _series_is_constant(result.get("rows", []), a["value_column_2"])
        ):
            rel_meta = _relationship_meta_for(a)
            if rel_meta:
                repaired_a, repaired_result = await _repair_fanned_out_join(
                    a, result, rel_meta, date_masks, runner
                )
                if repaired_a and repaired_result:
                    _record_data_analysis(repaired_a, repaired_result)
            return
        _record_data_analysis(a, result)

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
            sql = normalize_date_casts(sql, date_masks)
            a["sql"] = sql
            result, err = await _query_with_error(runner, sql)
            if result and result.get("rows"):
                await _execute_and_guard(a, result)
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
        async def fix_one(sql: str, error: str) -> str | None:
            async with ai_call_sem:
                return await ai.fix_sql(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    project_id=project.id,
                    sql=sql,
                    error=error,
                    allowed_tables=allowed_tables,
                    table_schema=table_schema,
                )

        fixes = await asyncio.gather(
            *(fix_one(sql, err) for (_a, sql, err) in to_repair),
            return_exceptions=True,
        )
        for (a, orig_sql, _err), fixed in zip(to_repair, fixes, strict=True):
            if isinstance(fixed, BaseException):
                if isinstance(fixed, asyncio.CancelledError):
                    raise fixed
                logger.warning(
                    "AI SQL repair skipped for project %s: %s", project.id, fixed
                )
                continue
            if not fixed or fixed.strip() == orig_sql.strip():
                continue
            fixed = normalize_date_casts(fixed, date_masks)
            result, _ = await _query_with_error(runner, fixed)
            if result and result.get("rows"):
                await _execute_and_guard({**a, "sql": fixed}, result)

    # Deduplicate multi-table analyses by the table pair they join so a
    # model that emits two identical joins does not crowd out other evidence.
    _seen_pairs: set[frozenset[str]] = set()
    _deduped: list[dict[str, Any]] = []
    _deduped_inputs: list[dict[str, Any]] = []
    for item, inp in zip(executed, interpret_inputs, strict=True):
        pair_tables = _tables_in_sql(item["analysis"].get("sql", ""), ctx.tables)
        if len(pair_tables) >= 2:
            pair = frozenset(pair_tables[:2])
            if pair in _seen_pairs:
                continue
            _seen_pairs.add(pair)
        _deduped.append(item)
        _deduped_inputs.append(inp)
    executed = _deduped
    interpret_inputs = _deduped_inputs

    # Deterministic floor: if the plan didn't produce enough multi-table
    # relationship analyses, synthesize additional ones from the evidence list.
    relationship_floor = 0
    if relationship_hints:
        relationship_floor = 2 if granularity >= 4 else 1

    def _relationship_dual_count(items: list[dict[str, Any]]) -> int:
        return sum(
            1
            for item in items
            if item["analysis"].get("chart_type") in ("dual_line", "scatter")
            and item["analysis"].get("value_column_2")
            and len(_tables_in_sql(item["analysis"].get("sql", ""), ctx.tables)) >= 2
        )

    while _relationship_dual_count(executed) < relationship_floor:
        used_pairs = {
            frozenset(_tables_in_sql(item["analysis"].get("sql", ""), ctx.tables)[:2])
            for item in executed
            if len(_tables_in_sql(item["analysis"].get("sql", ""), ctx.tables)) >= 2
        }
        templated = await _synthesize_templated_join(
            relationship_hints, ctx, date_masks, runner, avoid_pairs=used_pairs
        )
        if not (templated and templated[0] and templated[1]):
            break
        analysis, result = templated
        assert analysis is not None and result is not None
        _record_data_analysis(analysis, result)

    if not executed:
        return []

    # Governed statistical enrichment: real effect sizes / p-values / CIs from
    # the Method Engine's executable Tier-1 methods, computed in-process
    # over the rows each analysis already executed (no extra AI-server load).
    await _attach_method_envelopes(
        session, tenant_id=tenant_id, executed=executed
    )

    # Interpret in small concurrent chunks so each LLM call stays fast and fits
    # the model context window (large single calls at Granular were the main
    # source of latency / empty results). Ollama now serves these in parallel.
    chunk_size = 4
    chunks = [
        interpret_inputs[i : i + chunk_size]
        for i in range(0, len(interpret_inputs), chunk_size)
    ]
    async def interpret_chunk(
        chunk: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]] | None:
        async with ai_call_sem:
            return await ai.interpret(
                tenant_id=tenant_id,
                user_id=user_id,
                project_id=project.id,
                analyses=chunk,
                project_context=project_context or {},
            )

    chunk_results = await asyncio.gather(
        *(interpret_chunk(chunk) for chunk in chunks),
        return_exceptions=True,
    )
    interpreted: dict[str, dict[str, Any]] = {}
    for res in chunk_results:
        if isinstance(res, BaseException):
            if isinstance(res, asyncio.CancelledError):
                raise res
            logger.warning(
                "AI interpretation chunk skipped for project %s: %s", project.id, res
            )
            continue
        if res:
            interpreted.update(res)

    # Reference Library docs are authoritative guidance, not project evidence —
    # used below to cap reference-only findings to watch severity.
    reference_titles = {
        d.title for d in ctx.documents if d.ai_metadata.get("reference_tier")
    }

    cards: list[dict[str, Any]] = []
    for item in executed:
        a = item["analysis"]
        result = item["result"]
        ins = interpreted.get(a["id"], {})

        category = a.get("category", "trend")
        if category not in ("risk", "trend", "opportunity", "relationship"):
            category = "trend"
        severity = _normalize_severity(
            ins.get("severity") or a.get("severity_hint") or "info"
        )
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
        validation: dict[str, Any] = {}
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
            rows = result.get("rows", [])
            value_col = a.get("value_column", "")
            non_null = (
                sum(1 for r in rows if _to_float(r.get(value_col)) is not None)
                if value_col
                else 0
            )
            validation = {
                "executionStatus": "success",
                "rowCount": len(rows),
                "columnsReturned": list(result.get("columns", [])),
                "nonNullMetricCount": non_null,
            }
        else:
            documents_used = list(a.get("source_documents") or [])

        # Optional, backward-compatible metadata grounded in how the card was
        # produced (best-practices §Feedback / §Card Rendering).
        is_multi_table = len(tables) >= 2
        uses_reference = bool(documents_used) and any(
            d.ai_metadata.get("reference_tier")
            for d in ctx.documents
            if d.title in documents_used
        )
        if is_multi_table:
            method = "relationship"
        elif uses_reference:
            method = "reference_backed"
        elif result is None:
            method = "reference_backed" if documents_used else "llm_planned"
        else:
            method = "llm_planned"

        # A risk/warning/critical finding needs project-specific evidence
        # (executed data or a project document). When grounded only in
        # Reference Library guidance, cap it to watch severity.
        project_docs = [t for t in documents_used if t not in reference_titles]
        has_project_evidence = result is not None or bool(project_docs)
        severity = gate_severity(severity, has_project_evidence=has_project_evidence)

        relationship_meta = None
        if is_multi_table:
            relationship_meta = hint_by_pair.get(frozenset(tables[:2]))

        confidence = ins.get("confidence")
        if not isinstance(confidence, int | float):
            # Derive a coarse confidence from evidence: data-backed with several
            # rows is more trustworthy than a thin or document-only finding.
            confidence = 0.5
            if validation.get("rowCount", 0) >= 3:
                confidence = 0.75
            if relationship_meta:
                confidence = min(confidence, relationship_meta["join_confidence"])

        # A successfully executed method envelope carries a real quality
        # verdict — prefer it over the row-count guess. (Engine quality
        # vocabulary: "reliable", or "tentative" when usable n < 15.)
        method_envelope = item.get("method_envelope")
        if method_envelope and method_envelope.get("status") == "ok":
            confidence = {"reliable": 0.9, "tentative": 0.6}.get(
                str(method_envelope.get("quality")), confidence
            )

        source_context: dict[str, Any] = {
            "metric": a.get("value_column") if result is not None else None,
            "sourceColumns": list(result.get("columns", [])) if result is not None else [],
        }
        if a.get("chart_type") in ("line", "area"):
            source_context["periodColumn"] = a.get("label_column")
        if result is not None:
            source_context["aggregation"] = "value"

        metadata: dict[str, Any] = {
            "insightMethod": method,
            "confidenceScore": round(float(confidence), 2),
            "analyticalMethod": method_envelope,
            "validation": validation,
            "sourceContext": {k: v for k, v in source_context.items() if v},
            "referenceDocuments": documents_used if uses_reference else [],
            "relationshipMetadata": {
                "leftTable": relationship_meta["left_table"],
                "rightTable": relationship_meta["right_table"],
                "leftJoinKey": relationship_meta["left_join_key"],
                "rightJoinKey": relationship_meta["right_join_key"],
                "relationshipType": relationship_meta["relationship_type"],
                "joinConfidence": relationship_meta["join_confidence"],
                "confidenceReason": relationship_meta["confidence_reason"],
                "rowMultiplicationRisk": relationship_meta[
                    "row_multiplication_risk"
                ],
            }
            if relationship_meta
            else {},
        }

        insight_id = uuid.uuid4().hex
        governance_method = infer_method(
            f"{category}_{a['id']}",
            chart_type=a.get("chart_type"),
            sql=a.get("sql"),
            documents=documents_used,
            category=category,
            method_id=method_envelope.get("method") if method_envelope else None,
        )

        effective_method: str | None = None
        governance_decision = None
        if session is not None:
            decision = await ai_governance_service.evaluate_method(
                session,
                tenant_id,
                governance_method,
                project_id=project.id,
                insight_id=insight_id,
                actor_user_id=user_id,
            )
            if not decision.allowed:
                continue
            effective_method = decision.effective_method
            governance_decision = decision

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
                metadata=metadata,
                result=result,
                sql=(a.get("sql") if result is not None else None),
                chart_type=(a.get("chart_type") if result is not None else None),
                label_column=(a.get("label_column") if result is not None else None),
                value_column=(a.get("value_column") if result is not None else None),
                value_column_2=(a.get("value_column_2") if result is not None else None),
                insight_id=insight_id,
                method=effective_method,
                governance=governance_decision.to_explanation_dict() if governance_decision else None,
                project_context=project_context,
                method_envelope=method_envelope,
                relationship_meta=relationship_meta,
            )
        )


    # Rank by severity + evidence strength and drop duplicates. Single-table
    # cards compete for the cap; multi-table cards are always surfaced.
    ranked = rank_and_dedupe_cards(cards)
    if not ranked:
        logger.info(
            "home-intel project %s AI-empty: %s analyses executed but 0 cards "
            "survived building / quality gates",
            project.id, len(executed),
        )

    def _n_tables(sql: str) -> int:
        return len(_tables_in_sql(sql, ctx.tables))

    logger.info(
        "home-intel project %s multi-table funnel: hints=%s planned=%s "
        "executed=%s surfaced=%s",
        project.id,
        len(relationship_hints),
        sum(1 for a in analyses if _n_tables(a.get("sql", "")) >= 2),
        sum(
            1 for item in executed
            if _n_tables(item["analysis"].get("sql", "")) >= 2
        ),
        sum(
            1 for c in ranked
            if len(c.get("sources", {}).get("tables", [])) >= 2
        ),
    )
    return ranked


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
