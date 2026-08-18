from __future__ import annotations

from app.models.file_source_meta import FileSourceMeta
from app.routes.ai_proxy_shared import _relationship_hints


def _source(view_name: str, columns: list[tuple[str, str]]) -> FileSourceMeta:
    return FileSourceMeta(
        id=1,
        tenant_id=33,
        owner_id=7,
        project_id=44,
        view_name=view_name,
        file_name=f"{view_name}.csv",
        vdb_type="user",
        archived=False,
        column_types=[{"name": name, "type": col_type} for name, col_type in columns],
    )


def test_relationship_hints_finds_a_shared_join_key_across_two_sources() -> None:
    """Two monthly tables sharing a "month" column (e.g. actuals and a
    forecast) must surface as a join candidate -- this is exactly the shape
    an AI-Designer widget needs to combine "revenue actual vs forecast"
    into one query instead of being restricted to a single table."""
    sources = [
        _source("sales_revenue_monthly", [("month", "string"), ("actual_revenue", "decimal")]),
        _source("sales_bookings_forecast_monthly", [("month", "string"), ("forecast_revenue", "decimal")]),
    ]

    hints = _relationship_hints(sources)

    assert len(hints) == 1
    hint = hints[0]
    assert {hint["left_table"], hint["right_table"]} == {"sales_revenue_monthly", "sales_bookings_forecast_monthly"}
    assert hint["left_join_key"] == "month"
    assert hint["right_join_key"] == "month"
    assert hint["join_confidence"] > 0


def test_relationship_hints_carries_a_compound_key_when_tables_share_both_an_entity_and_period_column() -> None:
    """fin_gl_monthly vs fin_forecast_monthly: both an entity key
    (AccountNumber) and a reporting-period column (Month) are shared.

    The entity-key match wins the per-pair confidence comparison (0.6 over
    the period-key tier's 0.5), but it must still carry Month as a second
    join_key_pairs equality. A hint with only AccountNumber would let the
    SQL generator join on the entity key alone, fanning each month's GL rows
    out against every forecast month for the same account.
    """
    sources = [
        _source(
            "fin_gl_monthly",
            [("AccountNumber", "string"), ("Month", "string"), ("ActualGL", "decimal")],
        ),
        _source(
            "fin_forecast_monthly",
            [("AccountNumber", "string"), ("Month", "string"), ("ForecastUSD", "decimal")],
        ),
    ]

    hints = _relationship_hints(sources)

    assert len(hints) == 1
    hint = hints[0]
    assert hint["left_join_key"] == "AccountNumber"
    pairs = hint["join_key_pairs"]
    keys = {(p["left"], p["right"]) for p in pairs}
    assert ("AccountNumber", "AccountNumber") in keys
    assert ("Month", "Month") in keys
    assert len(pairs) == 2


def test_relationship_hints_is_empty_for_unrelated_sources() -> None:
    """No shared key -- no fabricated join. A single source, or sources with
    nothing in common, must never invent a relationship."""
    sources = [
        _source("sales_revenue_monthly", [("month", "string"), ("actual_revenue", "decimal")]),
        _source("airtravel", [("passengers", "integer"), ("year", "string")]),
    ]

    assert _relationship_hints(sources) == []
    assert _relationship_hints([sources[0]]) == []
    assert _relationship_hints([]) == []
