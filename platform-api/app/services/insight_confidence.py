"""Evidence-based confidence evaluation for generated insight cards.

Confidence is derived from deterministic factors tied to the quality of the
evidence, not from row count alone. The evaluator returns a structured
confidence package (score, level, basis, factors, caps, gaps) that the Explain
panel can render without guessing.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

CONFIDENCE_VERSION = 1


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, str):
        s = value.strip().replace(",", "").replace("$", "").replace("%", "")
        if not s:
            return None
        try:
            n = float(s)
            return n if math.isfinite(n) else None
        except ValueError:
            return None
    return None


def _pct_non_null(rows: list[Any], value_col: str | None) -> float:
    if not rows or not value_col:
        return 0.0
    total = len(rows)
    non_null = sum(1 for r in rows if _to_float(r.get(value_col) if isinstance(r, dict) else None) is not None)
    return non_null / total if total else 0.0


def _coverage_fraction(periods: list[Any]) -> float:
    """Rough period-continuity heuristic: count of unique periods / range size.

    Works for year/month/quarter labels. Returns 1.0 when continuity cannot be
    assessed.
    """
    if not periods:
        return 1.0
    try:
        nums = sorted({float(p) for p in periods if _to_float(p) is not None})
    except (TypeError, ValueError):
        return 1.0
    if len(nums) < 2:
        return 1.0
    span = nums[-1] - nums[0]
    if span <= 0:
        return 1.0
    return min(1.0, len(nums) / (span + 1))


@dataclass
class ConfidenceFactor:
    code: str
    label: str
    status: str  # passed | partial | failed | not_applicable
    score: float  # 0..1
    weight: float
    evidence: str


@dataclass
class ConfidenceEvaluation:
    version: int = CONFIDENCE_VERSION
    score: float = 0.0
    level: str = "low"  # low | medium | high
    basis: str = ""
    factors: list[ConfidenceFactor] = field(default_factory=list)
    caps: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    what_would_increase_confidence: str = ""
    evaluator_version: str = "evidence-v1"
    evaluated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _level_for_score(score: float) -> str:
    if score >= 0.80:
        return "high"
    if score >= 0.60:
        return "medium"
    return "low"


def _basis_from_factors(
    factors: list[ConfidenceFactor], caps: list[str]
) -> str:
    passed = [f for f in factors if f.status == "passed" and f.score >= 0.75]
    if passed:
        names = [f.label for f in passed]
        base = (
            "Confidence is high because: " + "; ".join(names) + "."
        )
    else:
        partial = [f for f in factors if f.status == "partial"]
        if partial:
            base = (
                "Confidence is medium. Supporting factor: "
                + partial[0].label
                + "."
            )
        else:
            base = "Confidence is low: the evidence is thin or incomplete."
    if caps:
        base += " " + caps[0]
    return base


def _gap_text(factor: ConfidenceFactor) -> str | None:
    if factor.status == "passed":
        return None
    if factor.code == "data_sufficiency":
        return "Collect more rows or a longer time range."
    if factor.code == "data_quality":
        return "Reduce null or malformed values in the metric columns."
    if factor.code == "analytical_validation":
        return "Run a statistical method (trend, anomaly, comparison) that the engine can validate."
    if factor.code == "period_integrity":
        return "Fill missing periods so the time series is continuous."
    if factor.code == "relationship_safety":
        return "Verify join keys resolve uniquely or add a curated scope link."
    if factor.code == "lineage_completeness":
        return "Add source metadata or a saved query to ground the finding."
    if factor.code == "corroboration":
        return "Corroborate with a document reference or secondary data source."
    if factor.code == "execution_grounding":
        return "Ensure the query executes and returns a usable result."
    if factor.status == "failed":
        return f"{factor.label} is insufficient."
    return None


def evaluate_confidence(
    *,
    validation: dict[str, Any] | None = None,
    method_envelope: dict[str, Any] | None = None,
    relationship_meta: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
    source_context: dict[str, Any] | None = None,
    columns: list[str] | None = None,
    rows: list[Any] | None = None,
    label_column: str | None = None,
    value_column: str | None = None,
    is_document_only: bool = False,
    uses_reference: bool = False,
    has_project_evidence: bool = True,
    intent: str | None = None,
) -> ConfidenceEvaluation:
    """Return a deterministic, evidence-based confidence evaluation."""
    validation = validation or {}
    method_envelope = method_envelope or {}
    source_context = source_context or {}
    result_rows = rows or ((result.get("rows") or []) if result else [])
    row_count = int(validation.get("rowCount") or len(result_rows) or 0)
    execution_status = validation.get("executionStatus")
    method_status = str(method_envelope.get("status") or "").lower()
    method_quality = str(method_envelope.get("quality") or "").lower()
    method_id = method_envelope.get("method")

    factors: list[ConfidenceFactor] = []
    caps: list[str] = []
    gaps: list[str] = []

    # 1. Execution grounding (0.20)
    if execution_status == "success" and row_count > 0:
        exec_score = 1.0
        exec_status = "passed"
        exec_evidence = f"Query executed successfully and returned {row_count} rows."
    elif execution_status == "success" and row_count == 0:
        exec_score = 0.0
        exec_status = "failed"
        exec_evidence = "Query executed but returned no rows."
        caps.append("Zero rows cap confidence to low.")
    else:
        exec_score = 0.0
        exec_status = "failed"
        exec_evidence = "No executed query result is available."
        caps.append("No executable evidence cap.")
    factors.append(
        ConfidenceFactor(
            code="execution_grounding",
            label="Execution grounding",
            status=exec_status,
            score=exec_score,
            weight=0.20,
            evidence=exec_evidence,
        )
    )

    # 2. Data sufficiency (0.15)
    if is_document_only:
        suff_score = 0.4
        suff_status = "partial"
        suff_evidence = "Finding is derived from documents; no query rows to evaluate."
        caps.append("Document-only evidence caps confidence at medium.")
    elif row_count == 0:
        suff_score = 0.0
        suff_status = "failed"
        suff_evidence = "No rows to support the finding."
    elif row_count >= 12:
        suff_score = 1.0
        suff_status = "passed"
        suff_evidence = f"{row_count} rows provide a robust sample."
    elif row_count >= 3:
        suff_score = 0.6 + (row_count - 3) * (0.4 / 9)
        suff_status = "partial"
        suff_evidence = f"{row_count} rows are available; a larger sample would strengthen confidence."
    else:
        suff_score = 0.2
        suff_status = "partial"
        suff_evidence = f"Only {row_count} rows; the sample is very small."
        caps.append("Small sample size caps confidence.")
    factors.append(
        ConfidenceFactor(
            code="data_sufficiency",
            label="Data sufficiency",
            status=suff_status,
            score=suff_score,
            weight=0.15,
            evidence=suff_evidence,
        )
    )

    # 3. Data quality (0.15)
    non_null_rate = _pct_non_null(result_rows, value_column)
    if value_column:
        if non_null_rate >= 0.95:
            dq_score = 1.0
            dq_status = "passed"
            dq_evidence = f"{non_null_rate:.0%} of {value_column} values are non-null."
        elif non_null_rate >= 0.70:
            dq_score = 0.7
            dq_status = "partial"
            dq_evidence = f"{non_null_rate:.0%} of {value_column} values are non-null; missing values are present."
            gaps.append("Fill missing metric values or filter nulls.")
        else:
            dq_score = 0.3
            dq_status = "partial"
            dq_evidence = f"Only {non_null_rate:.0%} of {value_column} values are non-null."
            caps.append("High null rate caps confidence.")
    else:
        dq_score = 0.5
        dq_status = "not_applicable"
        dq_evidence = "No metric column was specified."
    factors.append(
        ConfidenceFactor(
            code="data_quality",
            label="Data quality",
            status=dq_status,
            score=dq_score,
            weight=0.15,
            evidence=dq_evidence,
        )
    )

    # 4. Analytical validation (0.15)
    if method_status == "ok" and method_quality in ("reliable", "significant"):
        av_score = 1.0
        av_status = "passed"
        av_evidence = f"Analytical method '{method_id}' validated the result as {method_quality}."
    elif method_status == "ok" and method_quality == "tentative":
        av_score = 0.55
        av_status = "partial"
        av_evidence = f"Analytical method '{method_id}' produced a tentative result."
        caps.append("Tentative method caps confidence at medium.")
    elif method_status == "ok":
        av_score = 0.75
        av_status = "partial"
        av_evidence = f"Analytical method '{method_id}' ran but did not report a quality verdict."
    else:
        av_score = 0.4
        av_status = "partial"
        av_evidence = "No statistical validation was run; confidence relies on query execution alone."
        gaps.append("Run a governed analytical method to validate the finding.")
    factors.append(
        ConfidenceFactor(
            code="analytical_validation",
            label="Analytical validation",
            status=av_status,
            score=av_score,
            weight=0.15,
            evidence=av_evidence,
        )
    )

    # 5. Lineage completeness (0.10)
    lineage_tables = (source_context.get("sourceTables") or source_context.get("tables") or []) if source_context else []
    lineage_fields = (source_context.get("sourceColumns") or source_context.get("fields") or []) if source_context else []
    if lineage_tables and lineage_fields:
        lin_score = 1.0
        lin_status = "passed"
        lin_evidence = f"Lineage includes tables {', '.join(str(t) for t in lineage_tables[:3])} and {len(lineage_fields)} field(s)."
    elif lineage_tables:
        lin_score = 0.6
        lin_status = "partial"
        lin_evidence = f"Source table(s) known ({', '.join(str(t) for t in lineage_tables[:3])}) but column lineage is incomplete."
    else:
        lin_score = 0.2
        lin_status = "failed"
        lin_evidence = "Source lineage is not recorded."
        caps.append("Missing source lineage caps confidence.")
    factors.append(
        ConfidenceFactor(
            code="lineage_completeness",
            label="Lineage completeness",
            status=lin_status,
            score=lin_score,
            weight=0.10,
            evidence=lin_evidence,
        )
    )

    # 6. Relationship safety (0.10)
    rel_risk = str(relationship_meta.get("rowMultiplicationRisk") or "").lower() if relationship_meta else ""
    join_conf = relationship_meta.get("joinConfidence") if relationship_meta else None
    if relationship_meta:
        if rel_risk == "low" and isinstance(join_conf, (int, float)) and join_conf >= 0.85:
            rel_score = 1.0
            rel_status = "passed"
            rel_evidence = "Join has measured containment and low fan-out risk."
        elif rel_risk == "medium":
            rel_score = 0.55
            rel_status = "partial"
            rel_evidence = "Join has acceptable containment but medium fan-out risk."
            caps.append("Join fan-out risk caps confidence at medium.")
        else:
            rel_score = 0.3
            rel_status = "partial"
            rel_evidence = "Join carries fan-out or containment uncertainty."
            caps.append("Join uncertainty caps confidence.")
    else:
        rel_score = 1.0
        rel_status = "not_applicable"
        rel_evidence = "Single-source insight; no join risk to evaluate."
    factors.append(
        ConfidenceFactor(
            code="relationship_safety",
            label="Relationship safety",
            status=rel_status,
            score=rel_score,
            weight=0.10,
            evidence=rel_evidence,
        )
    )

    # 7. Period integrity (0.05)
    period_col = (
        source_context.get("periodColumn")
        if source_context
        else None
    )
    if period_col and result_rows:
        periods = [r.get(period_col) for r in result_rows if isinstance(r, dict)]
        coverage = _coverage_fraction(periods)
        if coverage >= 0.90:
            pi_score = 1.0
            pi_status = "passed"
            pi_evidence = f"Time periods are continuous ({coverage:.0%} coverage)."
        elif coverage >= 0.60:
            pi_score = 0.6
            pi_status = "partial"
            pi_evidence = f"Time coverage is partial ({coverage:.0%})."
            caps.append("Partial period coverage caps confidence at medium.")
        else:
            pi_score = 0.3
            pi_status = "partial"
            pi_evidence = "Time periods are sparse or non-sequential."
            caps.append("Sparse time coverage caps confidence.")
    else:
        pi_score = 1.0
        pi_status = "not_applicable"
        pi_evidence = "No period column was identified."
    factors.append(
        ConfidenceFactor(
            code="period_integrity",
            label="Period integrity",
            status=pi_status,
            score=pi_score,
            weight=0.05,
            evidence=pi_evidence,
        )
    )

    # 8. Corroboration (0.05)
    reference_docs = source_context.get("referenceDocuments") if source_context else []
    has_reference = bool(reference_docs) or uses_reference
    if has_project_evidence and has_reference:
        cor_score = 1.0
        cor_status = "passed"
        cor_evidence = "Project data is corroborated by a reference document."
    elif has_reference:
        cor_score = 0.45
        cor_status = "partial"
        cor_evidence = "Finding relies on reference documents without project data corroboration."
        caps.append("Reference-only evidence caps confidence at low/medium.")
    elif has_project_evidence:
        cor_score = 0.8
        cor_status = "passed"
        cor_evidence = "Finding is grounded in project data."
    else:
        cor_score = 0.2
        cor_status = "failed"
        cor_evidence = "No project evidence or reference document available."
        caps.append("No corroborating evidence cap.")
    factors.append(
        ConfidenceFactor(
            code="corroboration",
            label="Corroboration",
            status=cor_status,
            score=cor_score,
            weight=0.05,
            evidence=cor_evidence,
        )
    )

    # 9. Recency (0.05)
    executed_at = validation.get("executedAt") if validation else None
    if executed_at:
        rec_score = 1.0
        rec_status = "passed"
        rec_evidence = "Result has a recorded execution timestamp."
    else:
        rec_score = 0.7
        rec_status = "partial"
        rec_evidence = "No execution timestamp recorded."
    factors.append(
        ConfidenceFactor(
            code="recency",
            label="Recency",
            status=rec_status,
            score=rec_score,
            weight=0.05,
            evidence=rec_evidence,
        )
    )

    # Weighted score.
    total_weight = sum(f.weight for f in factors if f.status != "not_applicable")
    if total_weight <= 0:
        raw_score = 0.0
    else:
        weighted_sum = sum(f.weight * f.score for f in factors if f.status != "not_applicable")
        raw_score = weighted_sum / total_weight

    # Apply hard caps.
    if is_document_only or not has_project_evidence:
        raw_score = min(raw_score, 0.55)
        caps.append("Document-only or missing project evidence caps confidence at medium/low.")
    if method_quality == "tentative":
        raw_score = min(raw_score, 0.74)
    if row_count < 3 and not is_document_only:
        raw_score = min(raw_score, 0.49)
        caps.append("Fewer than 3 rows cap confidence to low.")
    if rel_risk in ("high", "unknown") and relationship_meta:
        raw_score = min(raw_score, 0.55)

    final_score = round(max(0.0, min(1.0, raw_score)), 3)
    level = _level_for_score(final_score)

    # Build readable basis and gaps.
    basis = _basis_from_factors(factors, caps)
    for factor in factors:
        gap = _gap_text(factor)
        if gap:
            gaps.append(gap)
    gaps = sorted(set(gaps))
    caps = sorted(set(caps))

    what_would = ""
    if gaps:
        what_would = "To raise confidence: " + " ".join(gaps)
    elif final_score < 0.80:
        what_would = "To raise confidence to high: add a validated analytical method, fill missing periods, and document source lineage."

    return ConfidenceEvaluation(
        version=CONFIDENCE_VERSION,
        score=final_score,
        level=level,
        basis=basis,
        factors=factors,
        caps=caps,
        gaps=gaps,
        what_would_increase_confidence=what_would,
        evaluator_version="evidence-v1",
        evaluated_at=datetime.now(UTC).isoformat(),
    )
