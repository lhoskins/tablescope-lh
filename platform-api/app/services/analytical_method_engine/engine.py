"""Analytical Method Engine orchestrator.

Runs the full deterministic pipeline over an executed result set:

    profile (A) -> infer intent -> select (B) -> execute (C) -> envelope (D) -> audit

Fails closed: any error returns ``None`` (or a status envelope) and is logged;
a governance-catalog outage must never become a hard failure in the ask path.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ai_governance import ai_governance_service, infer_governance_key
from app.services.analytical_method_engine import (
    data_profiler,
    method_audit,
    method_registry,
    method_selector,
    result_envelope,
)
from app.services.analytical_method_engine.executors import ExecutorRegistry
from app.services.analytical_method_engine.intent import infer_intent

logger = logging.getLogger(__name__)


async def analyze(
    session: AsyncSession,
    *,
    tenant_id: int | None,
    columns: list[str],
    rows: list[Any],
    question: str,
    intent: str | None = None,
    audit: bool = True,
) -> dict[str, Any] | None:
    """Profile, select, execute, and envelope one result set. Never raises."""
    try:
        if not columns or not rows:
            return None

        profile = data_profiler.profile(columns, rows)
        resolved_intent = intent or infer_intent(question, profile)
        if resolved_intent is None:
            logger.debug("Analytical engine: no intent inferred; skipping")
            return None

        registry = await method_registry.get_active_registry(session)
        if registry is None:
            # No governed catalog available — engine is effectively disabled.
            logger.debug(
                "Analytical engine: intent=%s but no active catalog registry",
                resolved_intent,
            )
            return None
        registry_version = registry.get("version_id")

        selection = await method_selector.select_method(session, resolved_intent, profile)

        if selection.status != "selected" or selection.method_id is None:
            envelope = result_envelope.build(
                intent=resolved_intent, profile=profile, method=None,
                roles=selection.roles,
                selection_reasons=selection.reasons, alternatives=selection.alternatives,
                exec_result={"status": "no_method", "reason": "; ".join(selection.reasons)},
                registry_version=registry_version,
            )
            if audit:
                await method_audit.record(
                    session, tenant_id=tenant_id, event_type="no_method",
                    analysis_intent=resolved_intent, selected_method=None,
                    rejected_methods=list(selection.rejected.keys()), envelope=envelope,
                    registry_version=registry_version, reason=envelope.get("reason"),
                )
            logger.info(
                "Analytical engine: intent=%s method=None status=no_method",
                resolved_intent,
            )
            return envelope

        # Resolve the chosen catalog method through tenant AI governance.
        # Fall back to the next allowed alternative if the primary is disabled.
        chosen_method_id: str | None = None
        governance_decision = None
        if tenant_id is not None:
            candidates = [selection.method_id, *selection.alternatives]
            for candidate_id in candidates:
                method_key = infer_governance_key(
                    method_id=candidate_id, analysis_intent=resolved_intent
                )
                decision = await ai_governance_service.evaluate_method(
                    session,
                    tenant_id,
                    method_key,
                    actor_user_id=None,
                    record=False,
                )
                if decision.allowed:
                    chosen_method_id = candidate_id
                    governance_decision = decision
                    break

        if tenant_id is None:
            chosen_method_id = selection.method_id

        if chosen_method_id is None:
            envelope = result_envelope.build(
                intent=resolved_intent,
                profile=profile,
                method=registry["methods"].get(selection.method_id),
                selection_reasons=selection.reasons,
                alternatives=selection.alternatives,
                exec_result={
                    "status": "governed_blocked",
                    "reason": "Selected analytical method is disabled for this tenant.",
                },
                registry_version=registry_version,
            )
            if audit:
                await method_audit.record(
                    session,
                    tenant_id=tenant_id,
                    event_type="governed_blocked",
                    analysis_intent=resolved_intent,
                    selected_method=selection.method_id,
                    rejected_methods=list(selection.rejected.keys()),
                    envelope=envelope,
                    registry_version=registry_version,
                    reason="Selected analytical method is disabled for this tenant.",
                )
            logger.info(
                "Analytical engine: intent=%s method=%s status=governed_blocked",
                resolved_intent, selection.method_id,
            )
            return envelope

        method = registry["methods"][chosen_method_id]
        df = data_profiler.to_dataframe(columns, rows)
        exec_result = ExecutorRegistry().execute(
            method, df, selection.roles, profile,
            registry.get("policies") if registry else {},
        )
        envelope = result_envelope.build(
            intent=resolved_intent, profile=profile, method=method,
            roles=selection.roles,
            selection_reasons=selection.reasons, alternatives=selection.alternatives,
            exec_result=exec_result, registry_version=registry_version,
        )
        if governance_decision:
            envelope["governance"] = governance_decision.to_explanation_dict()
        if audit:
            event = "executed" if exec_result["status"] == "ok" else exec_result["status"]
            await method_audit.record(
                session, tenant_id=tenant_id, event_type=event,
                analysis_intent=resolved_intent, selected_method=chosen_method_id,
                rejected_methods=list(selection.rejected.keys()), envelope=envelope,
                registry_version=registry_version, reason=exec_result.get("reason"),
            )
        logger.info(
            "Analytical engine: intent=%s method=%s status=%s",
            resolved_intent, chosen_method_id, exec_result.get("status"),
        )
        return envelope
    except Exception as exc:
        logger.warning("Analytical method engine failed: %s", exc)
        return None
