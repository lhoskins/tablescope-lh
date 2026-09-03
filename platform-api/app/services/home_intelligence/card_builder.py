from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.models.project import Project
from app.services.insight_confidence import evaluate_confidence
from app.services.insight_evidence_fingerprint import (
    build_evidence_fingerprint,
)
from app.services.insight_explanation import build_explanation
from app.services.presentation_engine import PresentationMode
from app.services.response_envelope import attach_envelope
from app.services.visualization_engine import (
    ChartType,
    VizCandidate,
    VizDecision,
    rank_visualizations,
)

from .query_helpers import _now_iso, _to_float, logger
from .schema_context import project_color


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
            grounding_evidence=result.get("groundingManifest") if result else None,
        )
        fp_dict = evidence_fp.to_dict()
        fp_dict["tenant_id"] = tenant_id
        card["evidenceFingerprint"] = fp_dict
        card["groundingManifest"] = result.get("groundingManifest") if result else None
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
            grounding_evidence=result.get("groundingManifest") if result else None,
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
    except Exception:
        # Candidate generation is optional for card delivery, but it is not
        # optional operationally: a debug-only message made ranking failures
        # indistinguishable from a legitimately narrow data shape in production.
        logger.exception(
            "chart candidate generation failed for insight %s (project=%s, columns=%s, rows=%s)",
            insight_id,
            project.id,
            result_columns,
            len(result_rows),
        )

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
