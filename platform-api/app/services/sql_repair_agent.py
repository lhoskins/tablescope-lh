"""Shared SQL self-repair agent loop.

Drives ``ai_intelligence_client.repair_sql_step`` in a bounded decision loop
-- rewrite the query, ask to see one specific column's real sample value/
type first, or give up -- so every caller that needs to recover from an
engine-rejected query gets identical repair behavior and bounds instead of
each hand-rolling its own retry loop. Used by the chat ask-and-run path
(``ai_proxy_ask_and_run.py``) and the saved-query/dashboard execution path
(``query_sql_helpers.py``); the home-intelligence batch planners
(``orchestrator.py``, ``widget_planning.py``) call
``ai_intelligence_client.repair_sql_step`` directly instead -- they repair
many analyses in parallel, one attempt each, a fundamentally different shape
that doesn't fit this per-query bounded loop.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import HTTPException

from app.services import ai_intelligence_client as ai

# Real engine round-trips a failing query gets.
_MAX_EXECUTE_ATTEMPTS = 3
# Total agent decision calls across the whole repair (shared across every
# execute attempt, not per-attempt) -- bounds cost/latency even though most
# of the budget is cheap "inspect_column" info round-trips, not full
# rewrite+re-execute cycles.
_MAX_REPAIR_STEPS = 5

_READONLY_START_RE = re.compile(r"^(?:SELECT|WITH)\b", re.IGNORECASE)
_LEADING_SQL_COMMENT_RE = re.compile(
    r"^(?:\s*(?:--[^\n]*\n|/\*.*?\*/))+", re.DOTALL
)


def is_read_only_select(sql: str) -> bool:
    """True only for a single read-only statement (defense-in-depth vs prose).

    The AI server already strips prose, but this guard guarantees natural-
    language text is never forwarded to Teiid as SQL even if it misbehaves.
    """
    body = _LEADING_SQL_COMMENT_RE.sub("", (sql or "").strip()).lstrip()
    return bool(_READONLY_START_RE.match(body))


async def run_repair_loop(
    *,
    initial_sql: str,
    tenant_id: int,
    user_id: int,
    project_id: int,
    allowed_tables: list[str],
    table_schema: list[dict[str, Any]],
    column_samples: dict[str, str],
    column_types: dict[str, str],
    normalize: Callable[[str], Awaitable[str]],
    execute: Callable[[str], Awaitable[dict[str, Any]]],
    is_unfixable_error: Callable[[str], bool] | None = None,
    max_execute_attempts: int = _MAX_EXECUTE_ATTEMPTS,
    max_repair_steps: int = _MAX_REPAIR_STEPS,
) -> tuple[dict[str, Any] | None, str, str]:
    """Normalize + execute ``initial_sql``; repair via the SQL self-repair
    agent on failure, then retry.

    ``normalize`` applies the caller's own deterministic rewrite pipeline to
    a candidate SQL string before it is executed -- callers differ here
    (chat ask-and-run and saved-query execution use different rewrite
    sets), so this stays a caller-supplied hook rather than something this
    module hardcodes. ``execute`` runs the (already-normalized) SQL and
    raises ``HTTPException`` with the engine's error in ``.detail`` on
    failure -- exactly what both existing execution helpers already do, so
    both plug in directly.

    ``is_unfixable_error``, when given, short-circuits the repair agent for
    errors no rewrite could ever fix -- a bad gateway, a genuinely missing
    table/column, a source outage. Asking the model to rewrite the query
    cannot resolve those and only wastes a call.

    Returns ``(result_or_none, final_sql, last_error)``. ``result`` is
    ``None`` only when every attempt fails, in which case ``final_sql`` is
    the last SQL attempted and ``last_error`` is the engine's last message.
    """
    known_columns: dict[str, dict[str, str]] = {}
    total_steps = 0
    current = initial_sql
    last_error = ""

    for attempt in range(max_execute_attempts):
        current = await normalize(current)
        try:
            result = await execute(current)
            return result, current, ""
        except HTTPException as exc:
            last_error = str(exc.detail)

        if is_unfixable_error and is_unfixable_error(last_error):
            break
        if attempt >= max_execute_attempts - 1:
            break

        rewritten: str | None = None
        while total_steps < max_repair_steps:
            total_steps += 1
            try:
                decision = await ai.repair_sql_step(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    project_id=project_id,
                    sql=current,
                    error=last_error,
                    allowed_tables=allowed_tables,
                    table_schema=table_schema,
                    known_columns=[
                        {"column": col, **info}
                        for col, info in known_columns.items()
                    ],
                )
            except ai.AIUnavailableError:
                # The AI service dropped mid-repair -- stop retrying rather
                # than let this propagate uncaught (this loop's contract is
                # to never raise) and report the last real engine error.
                decision = None

            action = (decision or {}).get("action")
            if decision is None or action == "give_up":
                break
            if action == "inspect_column":
                column = decision.get("column") or ""
                if not column or column in known_columns:
                    # No column named, or the agent re-asked for something
                    # it was already told -- stop instead of spinning
                    # through the remaining step budget on repeats.
                    break
                known_columns[column] = {
                    "table": decision.get("table") or "",
                    "sample": column_samples.get(column, ""),
                    "type": column_types.get(column, ""),
                }
                continue  # ask again with the newly revealed column, same failing SQL
            if action == "rewrite":
                rewritten = decision.get("sql") or ""
                break

        if not rewritten:
            break
        normalized = rewritten.strip().rstrip(";")
        if (
            not normalized
            or normalized == current.strip().rstrip(";")
            or not is_read_only_select(normalized)
        ):
            break
        current = normalized

    return None, current, last_error
