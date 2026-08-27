"""Regression coverage for _TEIID_RULES_COMMON's date-function guidance.

Live incident: the "backup job failure rate over time" investigation
sub-question generated SQL that failed twice:

  TEIID30492 [...] "Date" cannot be used outside of aggregate functions
  since they are not present in a GROUP BY clause.
  TEIID30070 The function 'FORMATTIMESTAMP(..."Date", 'yyyy-MM')' is a
  valid function form, but the arguments do not match a known type
  signature.

_TEIID_RULES_COMMON (used by both ai_intelligence_plan.py's SQL-shape
prompt and ai_intelligence_repair_step.py's repair prompt) only ever told
the model to build a time-trend grouping with FORMATTIMESTAMP -- with no
branch for a column whose real schema type is already `date` (Teiid's
FORMATTIMESTAMP requires a `timestamp` argument; a `date` argument raises
exactly TEIID30070). Fixed by adding an explicit type-check-first rule:
FORMATDATE for a `date` column, FORMATTIMESTAMP for a `timestamp` column,
and PARSETIMESTAMP/CAST only for text-backed columns holding date-like
text. Also strengthened the GROUP BY-must-match-SELECT rule to call out
that fixing the date expression's wrapping must be mirrored into GROUP
BY/ORDER BY in the same rewrite -- the oscillation between the two errors
across 3 repair attempts is consistent with the model fixing one without
re-syncing the other.

Run from ``tablescope-ai-api``: ``pytest -q``.
"""

from __future__ import annotations

from app.routers.ai_intelligence_repair_step import _repair_step_prompt
from app.routers.ai_shared import _TEIID_RULES_COMMON, _TEIID_SQL_RULES


def test_rules_tell_the_model_to_check_column_type_before_choosing_a_date_function():
    assert "FORMATDATE" in _TEIID_RULES_COMMON
    assert "already `date`" in _TEIID_RULES_COMMON
    assert "already `timestamp`" in _TEIID_RULES_COMMON


def test_rules_warn_formattimestamp_on_a_date_column_fails():
    assert "TEIID30070" in _TEIID_RULES_COMMON


def test_rules_require_group_by_to_mirror_an_edited_date_expression():
    assert "character-for-character" in _TEIID_RULES_COMMON
    assert "GROUP BY (and ORDER BY" in _TEIID_RULES_COMMON


def test_teiid_sql_rules_includes_the_common_block():
    assert "FORMATDATE" in _TEIID_SQL_RULES


def test_repair_step_prompt_calls_out_group_by_order_by_sync():
    from app.models.schemas import IntelligenceRepairSQLStepRequest

    req = IntelligenceRepairSQLStepRequest(
        tenant_id=1,
        user_id=1,
        project_id=1,
        sql='SELECT FORMATTIMESTAMP("Date", \'yyyy-MM\'), SUM(1) '
        'FROM "it_backup_jobs_CSV"',
        error="TEIID30492 ... not present in a GROUP BY clause",
        allowed_tables=["it_backup_jobs_CSV"],
        table_schema=[],
        known_columns=[],
        signature="test",
    )
    prompt = _repair_step_prompt(req)
    assert "character-for-character" in prompt
    assert "GROUP BY and ORDER BY" in prompt
