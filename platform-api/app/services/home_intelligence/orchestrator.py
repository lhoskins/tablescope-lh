from __future__ import annotations

import asyncio
import re
import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.project import Project
from app.services.ai_governance import ai_governance_service
from app.services.evidence_severity import gate_severity
from app.services.insight_explanation import infer_method
from app.services.project_ai_context import build_project_ai_context
from app.services.prompt_loader import load_prompt_reference
from app.services.teiid_sql import (
    date_masks_from_samples,
    normalize_date_casts,
)

from .card_builder import _card
from .card_ranking import (
    _card_priority,
    _normalize_severity,
    _pre_execution_dedupe,
    rank_and_dedupe_cards,
)
from .chart_builder import _build_chart
from .query_helpers import (
    _TWO_VALUE_TYPES,
    _query_with_error,
    _repair_fanned_out_join,
    _sample_values,
    _series_is_constant,
    _synthesize_templated_join,
    _tables_in_sql,
    _to_float,
    find_relationship_candidates,
    logger,
)
from .widget_planning import _attach_method_envelopes

if TYPE_CHECKING:
    from .query_helpers import QueryRunner
    from .schema_context import ProjectContext


ALL_PROMPT_TYPES = ["risk_sla", "risk_expiry", "trend_spend", "opportunity_supplier"]

# Authoritative methodology for richer Home cards (insight-first, KPI-aware,
# evidence-gated joins). Loaded once and used to ground generation.
HOME_BEST_PRACTICES_FILE = "home_insight_best_practices.md"


def home_best_practices() -> str:
    """Return the Home Insight best-practices reference text (cached)."""
    return load_prompt_reference(HOME_BEST_PRACTICES_FILE)


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
    grounding_sink: dict[str, Any] | None = None,
) -> list[dict[str, Any]] | None:
    """LLM-driven analyst loop. Returns cards, or ``None`` to signal fallback.

    1. Ask the AI to plan high-value analyses from the real schema + documents.
    2. Execute each generated SQL against the project's real data.
    3. Ask the AI to interpret the actual results into executive findings.

    Returns ``None`` only when AI is disabled. An unavailable initial plan raises
    so streaming callers report a project failure; a valid empty plan returns [].

    KG-50: when a caller passes ``grounding_sink`` (a plain dict), this
    writes ``grounding_sink["kg_grounding"]`` -- the KG version + evidence ids
    that grounded this run's plan -- so the caller can attach it to its own
    response envelope. An output parameter rather than a return-type change:
    this function's cards-or-None return is depended on by more than one
    caller (this module's own report-building reuse included), so widening it
    to a tuple would ripple further than this item's concrete ask.
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
                surface="business_insights",
            )
            if kg_context.get("grounding_status") == "unavailable":
                # KG-39: distinguish "the graph legitimately has nothing yet"
                # from "grounding failed" -- this plan proceeds without KG
                # hypotheses either way (fail-open by design), but that must
                # be visible to operators, not indistinguishable from a
                # quiet, healthy empty result.
                logger.warning(
                    "Business Insights for project %s proceeding WITHOUT "
                    "Knowledge Graph grounding (context collection failed)",
                    project.id,
                )
        except Exception as exc:
            logger.warning(
                "Failed to collect KG context for project %s: %s", project.id, exc
            )

    if grounding_sink is not None:
        grounding_sink["kg_grounding"] = kg_context.get("kg_grounding")

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

    async def _execute_plan(plan_analyses: list[dict[str, Any]]) -> None:
        """Run a set of planned analyses against the project data, repair SQL
        failures, and append successful/document-grounded results to the
        executed/interpret_inputs buffers."""
        to_repair: list[tuple[dict[str, Any], str, str]] = []
        for a in plan_analyses:
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

        if not to_repair:
            return

        # Self-repair: feed each rejected query + its exact engine error to the
        # SQL self-repair agent (concurrently, one decision each -- this
        # planning pass repairs many analyses at once, a batch shape that
        # doesn't fit the bounded per-query loop the chat/saved-query paths
        # use), then re-run the corrected SQL. A decision other than an
        # outright rewrite (asking to inspect a column, or giving up) is
        # treated as "could not fix in one attempt", same as an empty
        # response would have been.
        async def fix_one(sql: str, error: str) -> str | None:
            async with ai_call_sem:
                decision = await ai.repair_sql_step(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    project_id=project.id,
                    sql=sql,
                    error=error,
                    allowed_tables=allowed_tables,
                    table_schema=table_schema,
                    known_columns=[],
                )
                if decision and decision.get("action") == "rewrite":
                    return decision.get("sql") or None
                return None

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

    if analyses:
        await _execute_plan(analyses)

    # Deduplicate multi-table analyses by the table pair they join so a
    # model that emits two identical joins does not crowd out other evidence.
    def _deduplicate() -> None:
        nonlocal executed, interpret_inputs
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

    _deduplicate()

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

    # Multi-step deepen: feed first-pass results back into the planner so it can
    # ask follow-up questions (root cause, anomalies, cross-cutting insights)
    # and generate richer, evidence-based analyses.
    if executed:
        _analysis_defaults = {
            "id": "",
            "category": "trend",
            "title": "",
            "rationale": "",
            "sql": "",
            "chart_type": "bar",
            "label_column": "",
            "value_column": "",
            "value_column_2": "",
            "severity_hint": "watch",
            "source_documents": [],
        }
        first_pass: list[dict[str, Any]] = []
        for item in executed:
            a = item["analysis"]
            result = item.get("result")
            normalized_analysis = {
                k: a.get(k, v) for k, v in _analysis_defaults.items()
            }
            first_pass.append(
                {
                    "analysis": normalized_analysis,
                    "row_count": len(result.get("rows", [])) if result else 0,
                    "columns": result.get("columns", []) if result else [],
                    "rows": (result.get("rows", []) or [])[:8] if result else [],
                    "error": "",
                }
            )
        try:
            deepen_analyses = await ai.plan(
                tenant_id=tenant_id,
                user_id=user_id,
                project_id=project.id,
                allowed_tables=allowed_tables,
                documents=documents,
                table_schema=table_schema,
                relationship_hints=relationship_hints,
                max_analyses=4,
                granularity=granularity,
                project_context=project_context or {},
                knowledge_graph_context=kg_context,
                first_pass=first_pass,
            )
        except Exception as exc:
            logger.warning(
                "AI deepen planning failed for project %s: %s", project.id, exc
            )
            deepen_analyses = None
        if deepen_analyses:
            await _execute_plan(deepen_analyses)
            _deduplicate()

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
    """Synthesize an executive headline/body from the single most material
    insight across every analyzed project.

    The headline and body are the real title/summary of whichever insight
    ranks highest tenant-wide -- the same severity-first ranking used for
    per-project card ranking (see ``card_ranking._card_priority``) -- instead
    of a generic activity count ("AI analyzed N projects and surfaced M
    insights"), which said nothing about what was actually found. A note is
    appended when a named entity recurs across more than one project's
    insights, since that is a genuine cross-project signal no single card
    would otherwise surface.

    ``summaries`` is ``[{projectId, projectName, insights: [card, ...]}]``
    where each ``card`` carries at least ``title``/``summary`` and the same
    ``severity``/``priorityScore``/etc. fields used for ranking.
    Returns ``{headline, body, projectIds}`` or ``None`` if too little to say.
    """
    active = [s for s in summaries if s.get("insights")]
    if len(active) < 1:
        return None
    project_ids = [str(s["projectId"]) for s in active]

    ranked = [card for s in active for card in s["insights"]]
    if not ranked:
        return None
    top = max(ranked, key=_card_priority)
    headline = str(top.get("title") or "").strip()
    body = str(top.get("summary") or "").strip()
    if not headline or not body:
        return None

    # Look for a vendor/supplier name appearing in multiple projects' insights.
    shared_note = ""
    name_re = re.compile(r"\*\*([A-Z][A-Za-z0-9 .&'-]{2,40})\*\*")
    by_name: dict[str, set[str]] = {}
    for s in active:
        names: set[str] = set()
        for card in s["insights"]:
            for m in name_re.finditer(str(card.get("summary") or "")):
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

    return {"headline": headline, "body": body + shared_note, "projectIds": project_ids}
