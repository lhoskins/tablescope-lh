"""Tests for _fix_glued_keywords / _prepare_sql's defense against a CASE
expression's END landing with zero whitespace before the next clause
keyword.

Live finding: a "backup failure rate" query against it_backup_jobs_CSV
failed with TEIID31100 ("Encountered ... ENDORDER ...") because the
generated SQL had "...AS double) ENDORDER BY JobMonth" -- END glued
directly onto ORDER BY with no space, which Teiid's tokenizer reads as one
unrecognized identifier instead of two valid keywords. Confirmed this
isn't introduced anywhere else in the normalization pipeline:
_cast_timestampdiff and _auto_cast_aggregates only ever insert characters
around an existing span, never remove whitespace.

Second live finding (ai_proxy_ask_and_run.py's _normalize pipeline only --
query_sql_helpers.py's _prepare_sql above never calls
rebuild_group_by_from_select, so it isn't exposed to this): a "vendor
spend" query against it_saas_vendor_register_CSV re-triggered the exact
same ENDORDER BY symptom even after the fix above ran first. Cause:
rebuild_group_by_from_select copies a SELECT-list expression's exact text
into the rebuilt GROUP BY clause, and when that expression ends in a
CASE's END with ORDER BY immediately following, one of its assembly
branches concatenates the rebuilt GROUP BY directly against the ORDER BY
clause with no separating space -- reintroducing the glue that
_fix_glued_keywords already removed, one step earlier in the same
pipeline. Fixed by running _fix_glued_keywords a second time, after
rebuild_group_by_from_select, in ai_proxy_ask_and_run.py's _normalize --
not by moving the first call to run after it instead, which was tried and
rejected: rebuild_group_by_from_select receiving still-glued input (as it
would if the earlier call moved) silently drops the ORDER BY clause
entirely rather than raising, which is a worse, silent correctness bug.

Run from ``platform-api``: ``pytest -q tests/test_fix_glued_keywords.py``.
"""

from __future__ import annotations

import pytest

from app.routes.query_sql_helpers import _fix_glued_keywords, _prepare_sql
from app.services.teiid_sql import rebuild_group_by_from_select

pytestmark = pytest.mark.anyio


def test_fixes_end_glued_to_order_by():
    # Reproduces the exact reported fragment: END immediately followed by
    # ORDER BY with no space.
    glued = (
        'SELECT CAST(COUNT(*) AS double) ENDORDER BY JobMonth '
        'FROM "it_backup_jobs_CSV"'
    )
    fixed = _fix_glued_keywords(glued)
    assert "ENDORDER" not in fixed
    assert "END ORDER BY JobMonth" in fixed


def test_fixes_end_glued_to_group_by_where_having_limit():
    assert _fix_glued_keywords("SELECT 1 ENDGROUP BY x") == "SELECT 1 END GROUP BY x"
    assert _fix_glued_keywords("SELECT 1 ENDWHERE x = 1") == "SELECT 1 END WHERE x = 1"
    assert _fix_glued_keywords("SELECT 1 ENDHAVING x = 1") == "SELECT 1 END HAVING x = 1"
    assert _fix_glued_keywords("SELECT 1 ENDLIMIT 10") == "SELECT 1 END LIMIT 10"


def test_leaves_correctly_spaced_sql_unchanged():
    sql = (
        'SELECT CASE WHEN "x" = 1 THEN 1 ELSE 0 END AS y '
        'FROM t ORDER BY y'
    )
    assert _fix_glued_keywords(sql) == sql


def test_does_not_touch_end_as_part_of_a_longer_identifier():
    # "APPEND" etc. must not be mangled -- the match requires END immediately
    # followed by one of the clause keywords, not just the substring "end".
    sql = 'SELECT "AppendOrderBy" FROM t'
    assert _fix_glued_keywords(sql) == sql


async def test_prepare_sql_applies_the_fix_end_to_end():
    glued = (
        'SELECT CASE WHEN "x" = 1 THEN CAST(COUNT(*) AS double) ELSE 0 END '
        'AS JobMonth FROM "it_backup_jobs_CSV" ENDORDER BY JobMonth'
    )
    out = await _prepare_sql(
        glued, table_schema=[], column_types={}, column_samples={}
    )
    assert "ENDORDER" not in out
    assert "END ORDER BY JobMonth" in out


def test_rebuild_group_by_from_select_reintroduces_the_glue():
    """Reproduces the second live finding directly against
    rebuild_group_by_from_select: given already-correctly-spaced input (as
    it arrives after _fix_glued_keywords' first pass), rebuilding GROUP BY
    from a CASE-ending SELECT expression immediately followed by ORDER BY
    re-glues them back together. This is the regression a caller must guard
    against with a second _fix_glued_keywords pass -- this test exists so a
    future change to rebuild_group_by_from_select's assembly logic that
    fixes this at the source doesn't silently go untested.
    """
    sql = (
        'SELECT CASE WHEN "RenewalMonth" IS NULL THEN 0 '
        'ELSE CAST("RenewalMonth" AS double) END, SUM("Spend") '
        'FROM "it_saas_vendor_register_CSV" '
        'GROUP BY CASE WHEN "RenewalMonth" IS NULL THEN 0 '
        'ELSE CAST("RenewalMonth" AS double) END '
        'ORDER BY CAST("RenewalMonth" AS double)'
    )
    out = rebuild_group_by_from_select(sql)
    assert "ENDORDER" in out, (
        "This test documents a known defect in rebuild_group_by_from_select's "
        "own output, not a desired behavior -- if this now fails, the "
        "underlying re-gluing bug was fixed at the source and the second "
        "_fix_glued_keywords pass in ai_proxy_ask_and_run.py's _normalize "
        "may be safe to remove (confirm via test_second_pass_recovers_from_"
        "rebuild_group_by_regression below still passing either way)."
    )


def test_second_pass_recovers_from_rebuild_group_by_regression():
    """The actual fix: run _fix_glued_keywords again after
    rebuild_group_by_from_select. Mirrors ai_proxy_ask_and_run.py's
    _normalize pipeline order for this pair of steps.
    """
    glued = (
        'SELECT CASE WHEN "RenewalMonth" IS NULL THEN 0 '
        'ELSE CAST("RenewalMonth" AS double) END, SUM("Spend") '
        'FROM "it_saas_vendor_register_CSV" '
        'GROUP BY CASE WHEN "RenewalMonth" IS NULL THEN 0 '
        'ELSE CAST("RenewalMonth" AS double) ENDORDER BY CAST("RenewalMonth" AS double)'
    )
    step1 = _fix_glued_keywords(glued)
    step2 = rebuild_group_by_from_select(step1)
    step3 = _fix_glued_keywords(step2)
    assert "ENDORDER" not in step3
    assert "END ORDER BY" in step3
    assert 'CAST("RenewalMonth" AS double)' in step3.split("ORDER BY", 1)[1]


def test_moving_the_first_pass_after_rebuild_silently_drops_order_by():
    """Documents why the fix is a second pass, not reordering the first one.

    If rebuild_group_by_from_select runs before any glue-fixing (as it
    would if the existing call were simply moved to after it instead of
    adding a second call), it receives SQL exactly as the model generated
    it -- already glued. \\bORDER\\s+BY\\b then never matches inside
    "ENDORDER BY" (no word boundary between END and ORDER), so
    rebuild_group_by_from_select treats the query as having no ORDER BY at
    all and drops it -- a silent correctness bug, worse than the parse
    error this whole fix targets.
    """
    still_glued = (
        'SELECT CASE WHEN "RenewalMonth" IS NULL THEN 0 '
        'ELSE CAST("RenewalMonth" AS double) END, SUM("Spend") '
        'FROM "it_saas_vendor_register_CSV" '
        'GROUP BY CASE WHEN "RenewalMonth" IS NULL THEN 0 '
        'ELSE CAST("RenewalMonth" AS double) ENDORDER BY CAST("RenewalMonth" AS double)'
    )
    out = rebuild_group_by_from_select(still_glued)
    assert "ORDER BY" not in out.upper()
