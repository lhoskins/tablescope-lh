from __future__ import annotations

import asyncio
import sys
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.services.analytical_method_engine import data_profiler
from app.services.analytical_method_engine.intent import infer_intent
from app.services.project_ai_context import build_project_ai_context
from app.services.teiid_sql import (
    date_masks_from_samples,
    normalize_date_casts,
)

from .query_helpers import _query_with_error, _sample_values, find_relationship_candidates, logger

if TYPE_CHECKING:
    from .query_helpers import QueryRunner
    from .schema_context import ProjectContext

_hi = sys.modules[__package__]



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
    mode = _hi.get_engine_mode()
    if mode == _hi.EngineMode.OFF:
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
            envelope = await _hi.analyze_methods(
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
            mode == _hi.EngineMode.HYBRID
            and envelope
            and envelope.get("method") is not None
        ):
            item["method_envelope"] = envelope
