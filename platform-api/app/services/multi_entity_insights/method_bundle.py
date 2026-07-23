"""Primary + supporting analytical-method bundle execution.

Runs up to three executions through the governed Analytical Method Engine,
passes correct roles, applies a simple multiple-testing policy, and synthesizes
an evidence status.
"""

from __future__ import annotations

from typing import Any

from app.services.analytical_method_engine.engine import analyze
from app.services.multi_entity_insights.contract import (
    EvidenceSynthesis,
    ExecutionEnvelope,
    MethodBundle,
)


class MethodBundleExecutor:
    def __init__(
        self,
        session: Any,
        tenant_id: int | None,
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id

    async def execute(
        self,
        bundle: MethodBundle,
        columns: list[str],
        rows: list[Any],
        question: str,
    ) -> list[ExecutionEnvelope]:
        executions: list[ExecutionEnvelope] = []
        methods = [bundle.primary, *bundle.supporting]
        for i, method_ref in enumerate(methods):
            intent_question = question if i == 0 else f"{method_ref.intent} for {question}"
            envelope = await analyze(
                self.session,
                tenant_id=self.tenant_id,
                columns=columns,
                rows=rows,
                question=intent_question,
                intent=method_ref.intent,
            )
            executions.append(
                ExecutionEnvelope(
                    method_id=method_ref.method_id,
                    intent=method_ref.intent,
                    roles={},
                    result=envelope or {},
                    envelope=envelope or {},
                )
            )
        return executions


def synthesize_evidence(
    executions: list[ExecutionEnvelope],
    question: str,
) -> EvidenceSynthesis:
    """Combine execution statuses into an evidence synthesis."""
    statuses: dict[str, str] = {}
    warnings: list[str] = []
    for ex in executions:
        status = ex.envelope.get("status", "error")
        statuses[ex.method_id] = status
        if status != "ok":
            warnings.append(f"{ex.method_id}: {status}")

    if not executions:
        return EvidenceSynthesis(
            status="insufficient_data",
            summary="No analytical methods were executed.",
            confidence="low",
            method_statuses=statuses,
            warnings=warnings,
        )

    primary_status = executions[0].envelope.get("status", "error")
    supporting_statuses = [ex.envelope.get("status", "error") for ex in executions[1:]]

    if primary_status != "ok":
        return EvidenceSynthesis(
            status="insufficient_data",
            summary="Primary analysis did not produce a reliable result.",
            confidence="low",
            method_statuses=statuses,
            warnings=warnings,
        )

    if not supporting_statuses or all(s == "ok" for s in supporting_statuses):
        evidence_status: Any = "supported"
    elif all(s in {"ok", "insufficient_data"} for s in supporting_statuses):
        evidence_status = "partially_supported"
    else:
        evidence_status = "conflicting"

    summary = (
        f"Primary method ({executions[0].method_id}) supports the comparison. "
        f"Supporting evidence: {', '.join(f'{k}={v}' for k, v in statuses.items())}."
    )
    confidence = "high" if evidence_status == "supported" else "medium"
    return EvidenceSynthesis(
        status=evidence_status,
        summary=summary,
        confidence=confidence,
        method_statuses=statuses,
        warnings=warnings,
    )
