
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .scoring_helpers import _basis_from_factors, _coverage_fraction, _gap_text, _level_for_score, _pct_non_null
from .types import (
    _CAP_DOCUMENT_ONLY,
    _CAP_FEW_ROWS,
    _CAP_HIGH_JOIN_RISK,
    _CAP_TENTATIVE_METHOD,
    _HIGH,
    CONFIDENCE_VERSION,
    ConfidenceEvaluation,
    ConfidenceFactor,
)


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
    grounding_evidence: dict[str, Any] | None = None,
) -> ConfidenceEvaluation:
    """Return a deterministic, evidence-based confidence evaluation.

    The score is the weighted sum of eleven evidence factors (weights total 1.0).
    Grounding coverage, source freshness, and corroboration raise the cost of
    ungrounded answers so execution success alone cannot reach 'high'. Hard caps
    then clamp the score for document-only findings, tentative methods, high
    join risk, or very small samples.
    """
    validation = validation or {}
    method_envelope = method_envelope or {}
    source_context = source_context or {}
    has_grounding = bool(grounding_evidence)
    result_rows = rows or ((result.get("rows") or []) if result else [])
    result_columns = [str(c) for c in (columns or (result.get("columns") if result else []) or [])]
    row_count = int(validation.get("rowCount") or len(result_rows) or 0)
    execution_status = str(validation.get("executionStatus") or "").lower()

    # Method envelope normalisation: ``confidence`` is a legacy alias for ``quality``.
    method_status_raw = method_envelope.get("status") or (
        "ok" if method_envelope.get("quality") or method_envelope.get("confidence") else None
    )
    method_status = str(method_status_raw or "").lower()
    method_quality = str(
        method_envelope.get("quality") or method_envelope.get("confidence") or ""
    ).lower()
    method_id = method_envelope.get("method")

    factors: list[ConfidenceFactor] = []
    caps: list[str] = []
    gaps: list[str] = []

    # 1. Execution grounding (0.20 legacy / 0.15 when grounding evidence is active)
    exec_weight = 0.15 if has_grounding else 0.20
    if execution_status in ("success", "ok") and row_count > 0:
        exec_score = 1.0
        exec_status = "passed"
        exec_evidence = f"Query executed successfully and returned {row_count} rows."
    elif execution_status in ("success", "ok") and row_count == 0:
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
            weight=exec_weight,
            evidence=exec_evidence,
        )
    )

    # 2. Data sufficiency (0.15)
    if is_document_only:
        suff_score = 0.4
        suff_status = "partial"
        suff_evidence = "Finding is derived from documents; no query rows to evaluate."
        caps.append("document_only")
    elif row_count == 0:
        suff_score = 0.0
        suff_status = "failed"
        suff_evidence = "No rows to support the finding."
    elif row_count >= 12:
        suff_score = 1.0
        suff_status = "passed"
        suff_evidence = f"{row_count} rows provide a robust sample."
    elif row_count >= 3:
        # Small-but-usable sample; enough to surface a signal but not strong.
        suff_score = 0.4
        suff_status = "partial"
        suff_evidence = f"{row_count} rows are available; a larger sample would strengthen confidence."
    else:
        suff_score = 0.2
        suff_status = "partial"
        suff_evidence = f"Only {row_count} rows; the sample is very small."
        caps.append("few_rows")
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
        # No metric column was specified; do not penalise the factor.
        dq_score = 1.0
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

    # 4. Analytical validation (0.15 legacy / 0.10 when grounding evidence is active)
    analytical_weight = 0.10 if has_grounding else 0.15
    if method_status == "ok" and method_quality in ("reliable", "validated", "significant"):
        av_score = 1.0
        av_status = "passed"
        av_evidence = f"Analytical method '{method_id}' validated the result as {method_quality}."
    elif method_status == "ok" and method_quality == "tentative":
        av_score = 0.55
        av_status = "partial"
        av_evidence = f"Analytical method '{method_id}' produced a tentative result."
        caps.append("tentative_method")
    elif method_status == "ok":
        # Method ran without a clear quality verdict; do not award full credit.
        av_score = 0.0
        av_status = "failed"
        av_evidence = f"Analytical method '{method_id}' ran but did not report a quality verdict."
    else:
        av_score = 0.0
        av_status = "failed"
        av_evidence = "No statistical validation was run; confidence relies on query execution alone."
        gaps.append("Run a governed analytical method to validate the finding.")
    factors.append(
        ConfidenceFactor(
            code="analytical_validation",
            label="Analytical validation",
            status=av_status,
            score=av_score,
            weight=analytical_weight,
            evidence=av_evidence,
        )
    )

    # 5. Lineage completeness (0.10)
    lineage_tables = (
        source_context.get("sourceTables") or source_context.get("tables") or []
    ) if source_context else []
    lineage_fields = (
        source_context.get("sourceColumns") or source_context.get("fields") or result_columns or []
    ) if source_context else result_columns or []
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
    join_risk_score = None
    rel_risk = ""
    join_conf: float | int | None = None
    if relationship_meta:
        join_risk_score = relationship_meta.get("joinRiskScore")
        rel_risk = str(relationship_meta.get("rowMultiplicationRisk") or "").lower()
        join_conf = relationship_meta.get("joinConfidence")

    high_join_risk = (
        relationship_meta
        and (
            (isinstance(join_risk_score, int | float) and join_risk_score >= 0.5)
            or rel_risk in ("high", "unknown")
        )
    )
    if relationship_meta:
        if high_join_risk:
            rel_score = 0.0
            rel_status = "failed"
            rel_evidence = "Join carries high fan-out or containment uncertainty."
            caps.append("high_join_risk")
        elif rel_risk == "medium":
            rel_score = 0.55
            rel_status = "partial"
            rel_evidence = "Join has acceptable containment but medium fan-out risk."
            caps.append("Join fan-out risk caps confidence at medium.")
        elif rel_risk == "low" and isinstance(join_conf, int | float) and join_conf >= 0.85:
            rel_score = 1.0
            rel_status = "passed"
            rel_evidence = "Join has measured containment and low fan-out risk."
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

    # 8. Grounding coverage (0.05 when grounded, not applicable otherwise)
    cov_weight = 0.05 if has_grounding else 0.0
    if grounding_evidence:
        passages = grounding_evidence.get("passages") or []
        kg_nodes = grounding_evidence.get("kg_nodes") or grounding_evidence.get("kgNodes") or []
        kpis = grounding_evidence.get("kpis") or []
        passage_count = grounding_evidence.get("passage_count") or grounding_evidence.get("passageCount") or len(passages)
        kg_node_count = grounding_evidence.get("kg_node_count") or grounding_evidence.get("kgNodeCount") or len(kg_nodes)
        kpi_count = grounding_evidence.get("kpi_count") or grounding_evidence.get("kpiCount") or len(kpis)
        cov_score = min(1.0, passage_count * 0.08 + kg_node_count * 0.12 + kpi_count * 0.15)
        if cov_score >= 0.7:
            cov_status = "passed"
            cov_evidence = f"Grounding evidence covers {passage_count} passages, {kg_node_count} graph nodes, {kpi_count} KPIs."
        elif cov_score >= 0.3:
            cov_status = "partial"
            cov_evidence = f"Grounding evidence is limited: {passage_count} passages, {kg_node_count} graph nodes, {kpi_count} KPIs."
        else:
            cov_status = "failed"
            cov_evidence = "Grounding evidence is insufficient to support the answer."
            caps.append("insufficient_grounding")
    else:
        cov_score = 1.0
        cov_status = "not_applicable"
        cov_evidence = "Grounding evidence is not required for this pipeline."
    factors.append(
        ConfidenceFactor(
            code="grounding_coverage",
            label="Grounding coverage",
            status=cov_status,
            score=cov_score,
            weight=cov_weight,
            evidence=cov_evidence,
        )
    )

    # 9. Source freshness (0.05 when grounded, not applicable otherwise)
    fresh_weight = 0.05 if has_grounding else 0.0
    if grounding_evidence:
        fresh_score = 0.0
        fresh_status = "failed"
        fresh_evidence = "No grounding evidence timestamp is available."
        retrieved_at = grounding_evidence.get("retrieved_at") or grounding_evidence.get("retrievedAt")
        if retrieved_at:
            try:
                if isinstance(retrieved_at, str):
                    retrieved_dt = datetime.fromisoformat(retrieved_at.replace("Z", "+00:00"))
                elif isinstance(retrieved_at, datetime):
                    retrieved_dt = retrieved_at
                else:
                    retrieved_dt = None
                if retrieved_dt:
                    age_hours = (datetime.now(UTC) - retrieved_dt).total_seconds() / 3600
                    if age_hours <= 1:
                        fresh_score = 1.0
                        fresh_status = "passed"
                        fresh_evidence = f"Grounding evidence retrieved {age_hours:.0f} minutes ago."
                    elif age_hours <= 24:
                        fresh_score = 0.7
                        fresh_status = "partial"
                        fresh_evidence = f"Grounding evidence is {age_hours:.0f} hours old."
                    else:
                        fresh_score = 0.4
                        fresh_status = "partial"
                        fresh_evidence = f"Grounding evidence is {age_hours:.0f} hours old."
            except Exception:
                fresh_evidence = "Grounding evidence timestamp could not be parsed."
        else:
            caps.append("no_retrieval_timestamp")
    else:
        fresh_score = 1.0
        fresh_status = "not_applicable"
        fresh_evidence = "Source freshness is not evaluated for this pipeline."
    factors.append(
        ConfidenceFactor(
            code="source_freshness",
            label="Source freshness",
            status=fresh_status,
            score=fresh_score,
            weight=fresh_weight,
            evidence=fresh_evidence,
        )
    )

    # 10. Corroboration as a retrieval-quality score (0.05)
    reference_docs = source_context.get("referenceDocuments") if source_context else []
    has_reference = bool(reference_docs) or uses_reference
    if grounding_evidence:
        passages = grounding_evidence.get("passages") or []
        has_project = any((p.get("source_type") or p.get("sourceType")) == "project_asset" for p in passages)
        has_ref_grounding = any((p.get("source_type") or p.get("sourceType")) == "reference_library" for p in passages)
        methods = {
            p.get("retrieval_method") or p.get("retrievalMethod")
            for p in passages
            if p.get("retrieval_method") or p.get("retrievalMethod")
        }
        cor_score = 0.0
        if has_project:
            cor_score += 0.5
        if has_ref_grounding or has_reference:
            cor_score += 0.3
        if ("vector" in methods and "lexical" in methods) or "hybrid" in methods:
            cor_score += 0.2
        elif methods:
            cor_score += 0.1
        cor_score = min(1.0, cor_score)
        if cor_score >= 0.8:
            cor_status = "passed"
            cor_evidence = "Project data is corroborated by multiple grounded sources."
        elif cor_score >= 0.4:
            cor_status = "partial"
            cor_evidence = "Finding is partially corroborated by grounded sources."
            caps.append("partial_corroboration")
        else:
            cor_status = "failed"
            cor_evidence = "No corroborating grounded evidence."
            caps.append("no_corroboration")
    elif has_project_evidence and has_reference:
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

    # 11. Recency (0.05)
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

    # Weighted score: sum every factor's weighted contribution. Weights total 1.0,
    # so the score is interpretable as a proportion of maximum possible confidence.
    raw_score = sum(factor.score * factor.weight for factor in factors)

    # Apply hard caps.
    if is_document_only or not has_project_evidence:
        raw_score = min(raw_score, _CAP_DOCUMENT_ONLY)
        caps.append("document_only")
    if method_quality == "tentative":
        raw_score = min(raw_score, _CAP_TENTATIVE_METHOD)
    if high_join_risk:
        raw_score = min(raw_score, _CAP_HIGH_JOIN_RISK)
    if row_count < 3 and not is_document_only:
        raw_score = min(raw_score, _CAP_FEW_ROWS)
        caps.append("few_rows")

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
    elif final_score < _HIGH:
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
