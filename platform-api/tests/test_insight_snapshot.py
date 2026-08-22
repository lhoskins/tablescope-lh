"""Tests for the ITSM insight-snapshot source SQL and aggregation.

A prior version of _SOURCE_SQL ended each template with a FROM clause
immediately followed by the closing triple-quote -- Python's tokenizer
greedily matches the first three consecutive quote
characters as the closing triple-quote delimiter, silently swallowing the
identifier's own closing quote and sending an unterminated quoted
identifier to Teiid (TEIID31100 lexical error). The unit tests around
compute_dashboard's snapshot path all mock _run_sql, so none of them ever
sent this string anywhere that would catch a SQL syntax defect -- this
module exists specifically to check the generated SQL text itself.
"""

from __future__ import annotations

from app.services.itsm_metrics.insight_snapshot import (
    _SOURCE_SQL,
    InsightAggregation,
    aggregate_insight_snapshot,
)
from app.services.itsm_metrics.models import PeriodBounds


def _formatted_statements() -> list[tuple[str, str, str]]:
    dimension_code, dimension_name = '"site_code"', '"site_name"'
    return [
        (dashboard, name, sql.format(dimension_code=dimension_code, dimension_name=dimension_name))
        for dashboard, tables in _SOURCE_SQL.items()
        for name, sql in tables.items()
    ]


class TestSourceSqlWellFormed:
    def test_every_statement_has_balanced_double_quotes(self) -> None:
        for dashboard, name, sql in _formatted_statements():
            assert sql.count('"') % 2 == 0, f"{dashboard}.{name}: unbalanced quotes in generated SQL"

    def test_every_statement_ends_with_a_properly_closed_from_clause(self) -> None:
        for dashboard, name, sql in _formatted_statements():
            last_line = [line for line in sql.splitlines() if line.strip()][-1]
            assert last_line.startswith("FROM "), f"{dashboard}.{name}: expected a trailing FROM clause"
            assert last_line.endswith('"'), f"{dashboard}.{name}: FROM clause identifier is not closed: {last_line!r}"

    def test_dimension_placeholders_survive_formatting_for_region(self) -> None:
        for dashboard, tables in _SOURCE_SQL.items():
            for name, sql in tables.items():
                formatted = sql.format(dimension_code='"region"', dimension_name='"region_name"')
                assert '"region"' in formatted
                assert '"region_name"' in formatted
                assert formatted.count('"') % 2 == 0, f"{dashboard}.{name}: unbalanced quotes for region dimension"


def _period(start: str, end: str, label: str) -> PeriodBounds:
    return PeriodBounds(start=start, end=end, label=label)


class TestAggregateIncidentInsights:
    def _tables(self) -> dict[str, list[dict]]:
        return {
            "incidents": [
                {
                    "sys_id": "INC1", "opened_at": "2026-07-05T00:00:00Z", "resolved_at": None,
                    "resolution_minutes": None, "major_incident": False, "priority": "P2",
                    "state": "Open", "category": "Software",
                    "dimension_code": "US01", "dimension_name": "United States",
                },
                {
                    "sys_id": "INC2", "opened_at": "2026-07-10T00:00:00Z",
                    "resolved_at": "2026-07-12T00:00:00Z", "resolution_minutes": 120,
                    "major_incident": True, "priority": "P1", "state": "Resolved",
                    "category": "Hardware", "dimension_code": "US01", "dimension_name": "United States",
                },
                {
                    "sys_id": "INC3", "opened_at": "2026-06-01T00:00:00Z", "resolved_at": None,
                    "resolution_minutes": None, "major_incident": False, "priority": "P3",
                    "state": "Open", "category": "Network",
                    "dimension_code": "PLZ", "dimension_name": "Plzen",
                },
            ],
            "slas": [
                {
                    "sys_id": "SLA1", "task_type": "Incident", "metric": "Resolution",
                    "has_breached": False, "end_time": "2026-07-12T00:00:00Z",
                    "dimension_code": "US01", "dimension_name": "United States",
                },
            ],
        }

    def test_metric_values_reflect_only_rows_in_the_selected_dimension_value(self) -> None:
        current = _period("2026-07-01", "2026-07-31", "Jul 2026")
        previous = _period("2026-06-01", "2026-06-30", "Jun 2026")

        aggregation = aggregate_insight_snapshot(
            dashboard_key="incident_insights", tables=self._tables(), current_period=current,
            previous_period=previous, period_key="1_year", dimension="site", dimension_value="US01",
        )
        assert isinstance(aggregation, InsightAggregation)
        # Only INC1 (open) and INC2 (resolved after month end, so open at month-end) count for US01;
        # INC3 belongs to PLZ and must be excluded once scoped to US01.
        current_backlog, previous_backlog = aggregation.metric_values["open_backlog"]
        assert current_backlog == 1  # INC1 still open at end of July
        assert previous_backlog == 0

    def test_all_sites_includes_every_site(self) -> None:
        current = _period("2026-07-01", "2026-07-31", "Jul 2026")
        previous = _period("2026-06-01", "2026-06-30", "Jun 2026")

        aggregation = aggregate_insight_snapshot(
            dashboard_key="incident_insights", tables=self._tables(), current_period=current,
            previous_period=previous, period_key="1_year", dimension="site", dimension_value=None,
        )
        current_backlog, _ = aggregation.metric_values["open_backlog"]
        assert current_backlog == 2  # INC1 (US01) + INC3 (PLZ)
        assert {opt["code"] for opt in aggregation.dimension_options} == {"US01", "PLZ"}

    def test_unsupported_dashboard_key_raises(self) -> None:
        current = _period("2026-07-01", "2026-07-31", "Jul 2026")
        try:
            aggregate_insight_snapshot(
                dashboard_key="incident", tables={}, current_period=current,
                previous_period=current, period_key=None, dimension="site", dimension_value=None,
            )
        except ValueError:
            pass
        else:
            raise AssertionError("expected ValueError for a non-insight dashboard key")
