from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services import card_diagnostics, claim_verification
from app.services.analytical_method_engine import (
    analyze as analyze_methods,
)

from .query_helpers import _agg_for_measure, _first_column, _first_time_column, _period_label, _quote, _safe_query

if TYPE_CHECKING:
    from .query_helpers import QueryRunner
    from .schema_context import ProjectContext



async def _verify_card_claims(
    session: AsyncSession,
    runner: QueryRunner,
    *,
    card: dict[str, Any],
    ctx: ProjectContext,
    tenant_id: int | None,
    max_rows: int,
    max_claims: int = 2,
) -> list[dict[str, Any]]:
    """Put the card's own narrative to the test.

    A card writes "gross margin declined, indicating rising material costs" and
    nothing ever checks the clause after "indicating" — it is a hypothesis
    printed in the same voice as the measurement. Here the claim is extracted,
    the measure it names is located anywhere in the project (usually a different
    table from the card's own), and its trend is run through the governed engine
    over that measure's full history.

    The result leads the drill-down because a contradicted claim invalidates the
    card's story, and that is the single most useful thing the analysis can say.
    """
    claims = claim_verification.extract_claims(card, max_claims=max_claims)
    if not claims:
        return []

    # Every measure in the project is a candidate: the claim almost always names
    # something outside the table the card was built from.
    candidates: list[tuple[str, str]] = [
        (table.view_name, column)
        for table in ctx.tables
        for column in table.column_names
    ]

    steps: list[dict[str, Any]] = []
    for claim in claims:
        match = claim_verification.match_measure(claim, candidates)
        if match is None:
            steps.append(
                _claim_step(claim_verification.check_claim(
                    claim, measure=None, table=None, envelope=None
                ), sql="", result=None)
            )
            continue

        table_name, measure = match
        table = next((t for t in ctx.tables if t.view_name == table_name), None)
        if table is None:
            continue
        period = await _first_time_column(runner, table)
        if not period:
            continue

        sql = (
            f'SELECT {_quote(period)}, {_agg_for_measure(measure)}({_quote(measure)}) '
            f'AS {_quote(measure)} FROM {_quote(table_name)} '
            f'GROUP BY {_quote(period)} ORDER BY {_quote(period)} LIMIT {max_rows}'
        )
        try:
            result = await _safe_query(runner, sql)
        except Exception:
            continue
        rows = (result or {}).get("rows") or []
        if len(rows) < 4:
            continue

        try:
            envelope = await analyze_methods(
                session,
                tenant_id=tenant_id,
                columns=(result or {}).get("columns", []),
                rows=rows,
                question=f"Is {measure} trending over time?",
                intent="detect_trend",
            )
        except Exception:
            continue

        check = claim_verification.check_claim(
            claim,
            measure=measure,
            table=table_name,
            envelope=envelope,
            change_percent=claim_verification.percent_change(rows, measure),
            period_label=_period_label(rows, period),
        )
        steps.append(_claim_step(check, sql=sql, result=result, envelope=envelope))

    return steps


def _claim_step(
    check: Any,
    *,
    sql: str,
    result: dict[str, Any] | None,
    envelope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A claim check rendered as a diagnostic step."""
    return {
        "stage": card_diagnostics.STAGE_VERIFY,
        "intent": "detect_trend",
        "title": f"Claim: \u201c{check.claim.text}\u201d",
        "question": f"Does the data support \u201c{check.claim.text}\u201d?",
        "rationale": (
            "The card asserts this as a cause. Until it is measured it is a "
            "hypothesis stated in the same voice as the finding."
        ),
        "finding": check.finding,
        "highlight": check.verdict,
        "triggeredBy": "stated in the card's summary",
        "analyticalMethod": envelope or {},
        "sql": sql,
        "result": result,
        "presentation": {"chart": "line", "layers": ["regression_line"]}
        if result
        else {"chart": "table", "layers": []},
        "markers": {},
        "roles": {"x": _first_column(result), "y": check.measure} if result else {},
        "claimVerdict": check.verdict,
        "claimMeasure": check.measure,
        "claimTable": check.table,
    }
