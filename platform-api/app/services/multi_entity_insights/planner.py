"""Multi-source, multi-entity insight planner.

Orchestrates intent detection, multi-source-first candidate selection,
relationship/cardinality validation, grain-safe SQL execution, frame
validation, method-bundle execution, and lineage persistence.
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import get_settings
from app.services.multi_entity_insights.candidate_selector import select_candidates
from app.services.multi_entity_insights.card_builder import build_entities_payload
from app.services.multi_entity_insights.contract import (
    EvidenceSynthesis,
    FrameValidationResult,
    InsightLineage,
    JoinLineage,
    MultiEntityInsightPayload,
    MultiEntityPlan,
    SourceLineage,
)
from app.services.multi_entity_insights.frame_validator import MultiEntityFrameValidator
from app.services.multi_entity_insights.intent import infer_multi_entity_intent
from app.services.multi_entity_insights.join_validator import MultiEntityJoinValidator
from app.services.multi_entity_insights.method_bundle import (
    MethodBundleExecutor,
    synthesize_evidence,
)
from app.services.multi_entity_insights.sql_builder import MultiEntitySQLBuilder

logger = logging.getLogger(__name__)


class MultiEntityPlanner:
    def __init__(
        self,
        runner: Any,
        session: Any,
        tenant_id: int,
        user_id: int,
    ) -> None:
        self.runner = runner
        self.session = session
        self.tenant_id = tenant_id
        self.user_id = user_id

    async def _resolve_names(self, plan: MultiEntityPlan) -> MultiEntityPlan:
        """Preflight: ensure at least one source resolves the requested entity names."""
        if not plan.entity.requested_names:
            return plan
        name_col = plan.entity.name_column or plan.entity.id_column
        for source in plan.sources:
            if name_col not in source.columns:
                continue
            literals = ", ".join(f"'{n.replace(chr(39), chr(39)+chr(39))}'" for n in plan.entity.requested_names)
            sql = (
                f'SELECT DISTINCT "{name_col}" FROM "{source.table}" '
                f'WHERE "{name_col}" IN ({literals}) LIMIT 10'
            )
            result = await self.runner(sql) if self.runner else None
            if result is None:
                continue
            found = {str(r.get(name_col)) for r in (result.get("rows") or []) if r.get(name_col)}
            if found:
                return plan
        # If no source resolves the names, keep the plan and let the frame
        # validator report missing entities.
        return plan

    async def _resolve_top_entities(self, plan: MultiEntityPlan) -> MultiEntityPlan:
        """For top_n selection mode, populate requested_names with the top 3 entities."""
        if plan.entity.selection_mode != "top_n" or plan.entity.requested_names:
            return plan
        name_col = plan.entity.name_column or plan.entity.id_column
        source = next(
            (s for s in plan.sources if name_col in s.columns and s.measures),
            plan.sources[0],
        )
        measure = next(
            (m for m in plan.measures if m.table == source.table),
            None,
        )
        if measure is None:
            return plan
        sql = (
            f'SELECT "{name_col}", {measure.aggregation.upper()}(CAST("{measure.column}" AS double)) AS val '
            f'FROM "{source.table}" '
            f'WHERE "{name_col}" IS NOT NULL '
            f'GROUP BY "{name_col}" '
            f'ORDER BY val DESC NULLS LAST '
            f'LIMIT 3'
        )
        result = await self.runner(sql) if self.runner else None
        if not result:
            return plan
        names = [str(r.get(name_col)) for r in result.get("rows", []) if r.get(name_col)]
        plan.entity.requested_names = names
        if len(names) < 2:
            raise ValueError("Could not resolve at least two entities for top_n selection")
        return plan

    def _build_lineage(
        self,
        plan: MultiEntityPlan,
        sql: str,
        frame: FrameValidationResult,
        synthesis: EvidenceSynthesis,
        executions: list[Any],
    ) -> InsightLineage:
        return InsightLineage(
            source_strategy=plan.source_strategy,
            sources=[
                SourceLineage(
                    table_id=s.table,
                    display_name=s.table.replace("_", " ").title(),
                    columns=s.columns,
                    source_type="table",
                )
                for s in plan.sources
            ],
            joins=[
                JoinLineage(
                    left=j.left_table,
                    right=j.right_table,
                    declared_cardinality=j.declared_cardinality,
                    observed_cardinality=j.observed_cardinality,
                    fanout_ratio=j.fanout_ratio,
                    unmatched_rate=j.unmatched_rate,
                    validation_status=j.validation_status,
                )
                for j in plan.relationships
            ],
            grain={
                "sourceGrains": {s.table: s.grain for s in plan.sources},
                "finalGrain": plan.final_grain,
            },
            filters=[f"entity_names in ({', '.join(plan.entity.requested_names)})", f"period_grain={plan.time.period_grain}"],
            aggregations=[
                {"measure": m.name, "column": m.column, "aggregation": m.aggregation}
                for m in plan.measures
            ],
            resolved_entities=[
                {"name": n, "resolved": n not in frame.missing_requested_entities}
                for n in plan.entity.requested_names
            ],
            query_hash=MultiEntitySQLBuilder(plan).query_hash(),
            executions={
                "primary": executions[0].envelope if executions else {},
                "supporting": [ex.envelope for ex in executions[1:]],
            },
            validation={
                "status": frame.status,
                "warnings": frame.warnings,
                "evidence": synthesis.status,
            },
        )

    async def _execute_candidate(self, plan: MultiEntityPlan) -> MultiEntityInsightPayload | None:
        """Validate, execute, and build a payload for one candidate plan."""
        try:
            plan = await MultiEntityJoinValidator(self.runner).validate_plan(plan)
        except ValueError as exc:
            logger.info("Multi-entity candidate rejected by join validator: %s", exc)
            return None

        plan = await self._resolve_names(plan)
        plan = await self._resolve_top_entities(plan)

        builder = MultiEntitySQLBuilder(plan)
        sql = builder.build_sql()

        if self.runner is None:
            return None
        try:
            result = await self.runner(sql)
        except Exception as exc:
            logger.info("Multi-entity SQL execution failed: %s", exc)
            return None

        frame_validator = MultiEntityFrameValidator(plan)
        frame = frame_validator.validate(result)
        if frame.status == "rejected":
            logger.info("Multi-entity frame rejected: %s", frame.reason)
            return None

        if not result or not result.get("rows"):
            return None
        columns = result.get("columns", [])
        rows = result["rows"]

        # Build the analytical question for the method engine.
        question = (
            f"Compare {', '.join(plan.entity.requested_names)} across "
            f"{', '.join(s.table for s in plan.sources)}"
        )

        executor = MethodBundleExecutor(self.session, self.tenant_id)
        executions = await executor.execute(
            plan.method_bundle,
            columns=columns,
            rows=rows,
            question=question,
        )
        synthesis = synthesize_evidence(executions, question)

        entities = build_entities_payload(
            rows,
            entity_col=plan.entity.name_column or plan.entity.id_column,
            measures=plan.measures,
        )

        lineage = self._build_lineage(plan, sql, frame, synthesis, executions)

        primary_env = executions[0].envelope if executions else None

        # Build a short narrative summary from the synthesis and entity metrics.
        summary = synthesis.summary
        if entities:
            names = [e["name"] for e in entities]
            summary = (
                f"Comparison of {', '.join(names)}: {synthesis.summary} "
                f"Evidence status: {synthesis.status}."
            )

        return MultiEntityInsightPayload(
            insight_type=f"multi_entity_{plan.intent}",
            severity="info" if synthesis.status == "supported" else "watch",
            title=plan.title,
            summary=summary,
            business_question=plan.business_question,
            chart=None,
            tables=[s.table for s in plan.sources],
            sql=sql,
            method_envelope=primary_env or {},
            supporting_envelopes=[ex.envelope for ex in executions[1:]],
            lineage=lineage,
            evidence_status=synthesis.status,
            entities=entities,
            entity_type=plan.entity.type,
            source_strategy=plan.source_strategy,
            fallback_reason=plan.source_strategy.fallback_reason,
            warnings=synthesis.warnings + frame.warnings,
        )

    async def plan_and_execute(self, question: str, tables: list[Any], relationship_hints: list[dict[str, Any]]) -> list[MultiEntityInsightPayload]:
        """Run multi-source-first planning and return successful payloads."""
        settings = get_settings()
        intent, _entity_names = infer_multi_entity_intent(question)
        if not intent:
            intent = "compare_entities"

        candidates = select_candidates(
            question,
            tables,
            relationship_hints,
            max_sources=settings.multi_entity_max_sources,
        )
        if not candidates:
            return []

        # Try candidates in ranked order, but reject any that uses fewer than
        # two sources when a higher-scoring multi-source candidate exists.
        payloads: list[MultiEntityInsightPayload] = []
        attempted: list[str] = []
        fallback_payload: MultiEntityInsightPayload | None = None
        for candidate in candidates:
            if candidate.plan is None:
                attempted.extend(candidate.rejected_reasons)
                continue
            plan = candidate.plan
            # If we already have a multi-source payload, stop at the first one.
            if payloads and len(plan.sources) >= 2:
                break
            payload = await self._execute_candidate(plan)
            if payload is None:
                attempted.append(f"{plan.analysis_id}: rejected during validation/execution")
                continue
            if len(plan.sources) >= 2:
                payloads.append(payload)
            elif fallback_payload is None:
                fallback_payload = payload

        # If no multi-source payload survived, use the single-source fallback.
        if not payloads and fallback_payload:
            return [fallback_payload]

        return payloads[:1]  # return top payload for this question


def is_multi_entity_eligible(tables: list[Any]) -> bool:
    """True when at least one source table is available."""
    return len(tables) >= 1


async def generate_multi_entity_insights(
    project: Any,
    tables: list[Any],
    relationship_hints: list[dict[str, Any]],
    runner: Any,
    *,
    session: Any,
    tenant_id: int,
    user_id: int,
    question: str = "",
) -> list[MultiEntityInsightPayload]:
    """Entry point used by Home/Project Intelligence pipelines."""
    settings = get_settings()
    if not settings.multi_entity_insights_enabled:
        return []
    if not is_multi_entity_eligible(tables):
        return []
    planner = MultiEntityPlanner(
        runner=runner,
        session=session,
        tenant_id=tenant_id,
        user_id=user_id,
    )
    q = question or "Compare the key entities across the available sources"
    return await planner.plan_and_execute(q, tables, relationship_hints)
