from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.services import card_diagnostics, deep_analysis
from app.services.visualization_engine import (
    _Shape as Shape,
)
from app.services.visualization_engine import (
    business_dimensions,
    derive_shape,
)

from .claim_verification import _verify_card_claims
from .cross_reference import _run_cross_reference
from .query_helpers import _deep_analysis_sql, _quote, _safe_query, logger

if TYPE_CHECKING:
    from .query_helpers import QueryRunner
    from .schema_context import ProjectContext

_hi = sys.modules[__package__]



#: How many cards a single run will dissect. Each dissected card executes up to
#: ``max_steps`` governed methods on top of its own query, so this is the knob
#: that trades insight coverage against run time. The old hard-coded 4 meant
#: most cards in a busy project never got a drill-down at all.
_DIAGNOSTIC_CARD_BUDGET_DEFAULT = 24


def _diagnostic_card_budget() -> int:
    """Cards to dissect per run, overridable when a tenant's runs get slow."""
    raw = os.getenv("INSIGHT_DIAGNOSTIC_CARD_BUDGET")
    try:
        value = int(raw) if raw else _DIAGNOSTIC_CARD_BUDGET_DEFAULT
    except ValueError:
        return _DIAGNOSTIC_CARD_BUDGET_DEFAULT
    return max(1, value)


async def _card_diagnostic_insights(
    project: Project,
    ctx: ProjectContext,
    runner: QueryRunner,
    session: AsyncSession | None,
    *,
    tenant_id: int | None,
    cards: list[dict[str, Any]],
    max_cards: int | None = None,
    max_steps: int = 5,
    max_cross_refs: int = 3,
    max_rows: int = 5000,
) -> list[dict[str, Any]]:
    """Dissect existing Risk/Trend/Opportunity cards and propose actions.

    This is the purpose of Deeper analysis: take a finding the user already
    cares about and work it — where is it concentrated, when did it shift, what
    explains it, where is it heading — then propose what to do. Scanning tables
    for whatever was computable produced interchangeable period comparisons
    instead of answers.

    Diagnostics attach to the ORIGINATING card (so the section reads as a
    drill-down of that finding) and each card gets grounded action proposals
    plus follow-up questions for its ask box.

    Fail-closed per card: a diagnostic problem never drops the original card.
    """
    if runner is None or session is None or not cards:
        return []
    if _hi.get_engine_mode() == _hi.EngineMode.OFF:
        return []
    if max_cards is None:
        max_cards = _diagnostic_card_budget()

    produced: list[dict[str, Any]] = []
    examined = 0
    for card in cards:
        if examined >= max_cards:
            break
        if card_diagnostics.card_family(card) is None:
            continue

        table = _card_primary_table(card, ctx)
        if table is None:
            continue
        try:
            probe = await _safe_query(
                runner, f'SELECT * FROM {_quote(table.view_name)} LIMIT 200'
            )
        except Exception:
            continue
        if not probe or not probe.get("rows") or not probe.get("columns"):
            continue

        columns, rows = probe["columns"], probe["rows"]
        shape = derive_shape(columns, rows)
        period_col = shape.time_columns[0] if shape.time_columns else None
        dims = business_dimensions(shape, rows)
        period_count = (
            len({str(r.get(period_col)) for r in rows if r.get(period_col) is not None})
            if period_col
            else 0
        )
        examined += 1

        specs = card_diagnostics.plan_card_diagnostics(
            card,
            metric=_card_metric(card, shape),
            dimensions=dims,
            period_column=period_col,
            period_count=period_count,
            row_count=shape.row_count,
            related_measures=shape.measures,
            max_steps=max_steps,
        )

        findings: dict[str, Any] = {}
        diagnostics: list[dict[str, Any]] = []

        # Check the card's own assertions first. "indicating rising material
        # costs" is a hypothesis printed beside the measurement; if it is wrong,
        # everything below it is reasoning about a story that does not hold.
        try:
            diagnostics.extend(
                await _verify_card_claims(
                    session, runner, card=card, ctx=ctx,
                    tenant_id=tenant_id, max_rows=max_rows,
                )
            )
        except Exception as exc:  # claim checking is best-effort
            logger.warning("claim verification failed for %s: %s", card.get("title"), exc)
        for spec in specs:
            envelope, result, sql, roles = await _run_diagnostic(
                session, runner, table, spec, shape, tenant_id, max_rows
            )
            if envelope is None:
                continue
            materiality = deep_analysis.assess_materiality(spec.intent, envelope)
            if not materiality.material:
                continue
            findings.update(card_diagnostics.extract_findings(spec.intent, envelope))
            # The chart family comes from the intent, not from the caller: an
            # anomaly step is a period-ordered line with its flagged points
            # marked, and rendering it as a ranked bar reorders the timeline.
            presentation = deep_analysis.evidence_presentation(spec.intent)
            markers = card_diagnostics.extract_markers(spec.intent, envelope)
            evidence, evidence_roles = result, roles
            finding = materiality.reason

            # A group comparison hands the method raw rows (Welch's ANOVA needs
            # the within-group spread) but must not chart them: that plotted
            # individual records, repeating one work centre down the axis. Fold
            # to one ranked entry per group so the leading bar names the segment.
            if spec.intent in card_diagnostics.GROUP_EVIDENCE_INTENTS and spec.group_by:
                measure = str((roles or {}).get("y") or "")
                grouped, columns, marked = card_diagnostics.summarise_group_evidence(
                    (result or {}).get("rows") or [], spec.group_by, measure
                )
                if grouped:
                    evidence = {"columns": columns, "rows": grouped}
                    evidence_roles = {"x": spec.group_by, "y": measure}
                    presentation = {"chart": "bar", "layers": []}
                    markers = (
                        {"anomalyIndices": [marked]} if marked is not None else {}
                    )
                    # "Groups differ significantly (p=0.000)" reports that a
                    # test rejected its null hypothesis; it does not say where
                    # to go. Name the segment.
                    lead = card_diagnostics.describe_group_leader(
                        grouped, spec.group_by, measure, marked=marked
                    )
                    if lead and marked is not None:
                        finding = f"{lead} {materiality.reason}"
                        findings["top_segment"] = grouped[marked][spec.group_by]

            diagnostics.append(
                {
                    "stage": spec.stage,
                    "intent": spec.intent,
                    "title": spec.title,
                    "question": spec.question,
                    "rationale": spec.rationale,
                    "finding": finding,
                    "highlight": materiality.highlight,
                    "triggeredBy": spec.triggered_by,
                    "analyticalMethod": envelope,
                    "sql": sql,
                    "result": evidence,
                    "presentation": presentation,
                    "markers": markers,
                    "roles": evidence_roles,
                }
            )

        if not diagnostics:
            continue

        # Answer the cross-reference questions instead of listing them. A
        # measure in an independent source that tracks this finding is a
        # candidate cause or lever — the thing a reader actually needs when
        # deciding what to do about it.
        card_measure = _card_metric(card, shape)
        if period_col and card_measure:
            for other in ctx.tables:
                if len(diagnostics) >= max_steps + max_cross_refs:
                    break
                if other.view_name == table.view_name:
                    continue
                try:
                    diagnostics.extend(
                        await _run_cross_reference(
                            session, runner,
                            card_table=table,
                            card_measure=card_measure,
                            card_period=period_col,
                            other_table=other,
                            tenant_id=tenant_id,
                            max_rows=max_rows,
                        )
                    )
                except Exception as exc:  # cross-referencing is best-effort
                    logger.warning(
                        "cross-reference %s x %s failed: %s",
                        table.view_name, other.view_name, exc,
                    )

        # A period comparison is re-checked against what the diagnostics
        # actually found, so a detected shift can justify one the card's text
        # alone did not.
        card["diagnostics"] = diagnostics
        card["proposedActions"] = [
            a.to_dict() for a in card_diagnostics.propose_actions(card, findings)
        ]
        card["suggestedQuestions"] = card_diagnostics.suggested_followups(
            card, dimensions=dims
        )
        card["crossReferences"] = [
            {"kind": r.kind, "name": r.name, "question": r.question, "rationale": r.rationale}
            for r in card_diagnostics.plan_cross_references(
                card,
                tables=[tbl.view_name for tbl in ctx.tables],
                documents=_context_documents(ctx),
            )
        ]
        produced.append(card)

    return produced


def _card_primary_table(card: dict[str, Any], ctx: ProjectContext) -> Any | None:
    """The table a card was built from, matched against the project's tables."""
    sources = card.get("sources") or {}
    names = [str(t) for t in (sources.get("tables") or [])] if isinstance(sources, dict) else []
    for name in names:
        for table in ctx.tables:
            if table.view_name == name:
                return table
    return ctx.tables[0] if ctx.tables else None


def _card_metric(card: dict[str, Any], shape: Shape) -> str | None:
    """The measure a card is about, preferring what the card itself names."""
    for key in ("metric", "valueColumn"):
        value = card.get(key)
        if value and str(value) in shape.measures:
            return str(value)
    return shape.measures[0] if shape.measures else None


def _context_documents(ctx: ProjectContext) -> list[dict[str, Any]]:
    """Project documents exposed for cross-referencing, best-effort."""
    docs = getattr(ctx, "documents", None) or []
    out: list[dict[str, Any]] = []
    for doc in docs[:20]:
        if isinstance(doc, dict):
            out.append(doc)
        else:
            title = getattr(doc, "title", None) or getattr(doc, "name", None)
            if title:
                out.append({"title": str(title), "summary": str(getattr(doc, "summary", "") or "")})
    return out


async def _run_diagnostic(
    session: AsyncSession,
    runner: QueryRunner,
    table: Any,
    spec: Any,
    shape: Shape,
    tenant_id: int | None,
    max_rows: int,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str, dict[str, str]]:
    """Execute one diagnostic step through the governed method engine.

    Returns the envelope, the evidence rows, the SQL, and the column *roles* —
    the chart must know which column is the period and which the measure rather
    than guessing by position, or a step whose projection puts the measure first
    is plotted against the wrong axis.
    """
    measure = _card_metric({}, shape)
    if not measure:
        return None, None, "", {}
    period = shape.time_columns[0] if shape.time_columns else None
    pseudo = deep_analysis.DeepAnalysisSpec(
        intent=spec.intent,
        title=spec.title,
        question=spec.question,
        roles={
            k: v
            for k, v in (
                ("period", period),
                ("measure", measure),
                ("measure2", shape.measures[1] if len(shape.measures) > 1 else None),
            )
            if v
        },
        group_by=spec.group_by,
    )
    # What the projection actually plots: the group comparison is measured
    # across segments, everything else across the timeline.
    roles = {
        k: v
        for k, v in (
            ("x", spec.group_by if spec.group_by else period),
            ("y", measure),
            ("y2", pseudo.roles.get("measure2")),
        )
        if v
    }
    sql = _deep_analysis_sql(table.view_name, pseudo, max_rows)
    if not sql:
        return None, None, "", roles
    try:
        result = await _safe_query(runner, sql)
        if not result or not result.get("rows"):
            return None, None, sql, roles
        envelope = await _hi.analyze_methods(
            session,
            tenant_id=tenant_id,
            columns=result.get("columns", []),
            rows=result.get("rows", []),
            question=spec.question,
            intent=spec.intent,
        )
        return envelope, result, sql, roles
    except Exception as exc:  # pragma: no cover - diagnostics are fail-closed
        logger.warning("diagnostic %s failed on %s: %s", spec.intent, table.view_name, exc)
        return None, None, sql, roles
