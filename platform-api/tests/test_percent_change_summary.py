"""Tests for the cross-project percent-change summary service and route."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import percent_change_summary as pcs


def _project(pid: int, name: str = "Project"):
    return SimpleNamespace(id=pid, name=name)


def _card(
    insight_id: str,
    title: str,
    project_id: int,
    project_name: str = "Project",
    series=None,
):
    chart = None
    if series is not None:
        chart = {"type": "line", "data": {"series": series}}
    return {
        "insightId": insight_id,
        "id": insight_id,
        "title": title,
        "projectId": project_id,
        "projectName": project_name,
        "priorityScore": 0.9,
        "chart": chart,
    }


def _monthly_series():
    return [
        {"label": "2025-07", "value": 100},
        {"label": "2025-08", "value": 110},
        {"label": "2025-09", "value": 120},
        {"label": "2025-10", "value": 90},
        {"label": "2025-11", "value": 130},
        {"label": "2025-12", "value": 140},
        {"label": "2026-01", "value": 150},
        {"label": "2026-02", "value": 135},
        {"label": "2026-03", "value": 160},
        {"label": "2026-04", "value": 170},
        {"label": "2026-05", "value": 165},
        {"label": "2026-06", "value": 180},
    ]


def test_summary_returns_shared_canonical_periods():
    snapshot = {
        "results": [
            {
                "projectId": 1,
                "projectName": "P1",
                "insights": [
                    _card("c1", "Revenue", 1, series=_monthly_series()),
                ],
            }
        ]
    }
    request = pcs.PercentChangeSummaryRequest(
        project_ids=[1],
        interval="month",
        range="1y",
        page_size=25,
    )
    response = pcs.build_percent_change_summary(
        [_project(1, "P1")], snapshot, request
    )
    assert response.interval == "month"
    assert response.range == "1y"
    assert response.page.total_in_scope == 1
    assert response.page.total_eligible == 1
    assert response.page.total_excluded == 0
    assert len(response.rows) == 1
    row = response.rows[0]
    assert row.insight_id == "c1"
    # The latest completed period should be present and have a value.
    latest = next(p for p in response.periods if p.is_latest)
    assert latest.key in row.cells
    cell = row.cells[latest.key]
    assert cell.current_value == 180


def test_summary_excludes_non_time_series_cards():
    snapshot = {
        "results": [
            {
                "projectId": 1,
                "projectName": "P1",
                "insights": [
                    _card("c1", "Revenue", 1, series=_monthly_series()),
                    _card("c2", "Top vendors", 1, series=[
                        {"label": "Vendor A", "value": 12},
                        {"label": "Vendor B", "value": 34},
                    ]),
                ],
            }
        ]
    }
    request = pcs.PercentChangeSummaryRequest(
        project_ids=[1],
        interval="month",
        range="1y",
    )
    response = pcs.build_percent_change_summary(
        [_project(1, "P1")], snapshot, request
    )
    assert response.page.total_in_scope == 2
    assert response.page.total_eligible == 1
    assert response.page.total_excluded == 1
    assert response.excluded_by_reason["not_time_series"] == 1


def test_summary_calculates_percent_change_parity_with_transform():
    snapshot = {
        "results": [
            {
                "projectId": 1,
                "projectName": "P1",
                "insights": [
                    _card("c1", "Revenue", 1, series=_monthly_series()),
                ],
            }
        ]
    }
    request = pcs.PercentChangeSummaryRequest(
        project_ids=[1],
        interval="month",
        range="1y",
    )
    response = pcs.build_percent_change_summary(
        [_project(1, "P1")], snapshot, request
    )
    row = response.rows[0]
    # 2025-08 vs 2025-07: (110 - 100) / 100 = +10.0%
    cell = row.cells["2025-08"]
    assert cell.percent_change_ratio == pytest.approx(0.10, rel=1e-3)
    assert cell.status == "positive"
    # 2025-10 vs 2025-09: (90 - 120) / 120 = -25.0%
    cell = row.cells["2025-10"]
    assert cell.percent_change_ratio == pytest.approx(-0.25, rel=1e-3)
    assert cell.status == "negative"


def test_summary_search_filters_by_title_and_project():
    snapshot = {
        "results": [
            {
                "projectId": 1,
                "projectName": "Alpha",
                "insights": [
                    _card("c1", "Revenue", 1, series=_monthly_series()),
                    _card("c2", "Costs", 1, series=_monthly_series()),
                ],
            },
            {
                "projectId": 2,
                "projectName": "Beta",
                "insights": [
                    _card("c3", "Headcount", 2, series=_monthly_series()),
                ],
            },
        ]
    }
    request = pcs.PercentChangeSummaryRequest(
        project_ids=[1, 2],
        interval="month",
        range="1y",
        search="beta",
    )
    response = pcs.build_percent_change_summary(
        [_project(1, "Alpha"), _project(2, "Beta")], snapshot, request
    )
    assert response.page.total_in_scope == 1
    assert response.rows[0].insight_id == "c3"


def test_summary_dedup_and_pagination():
    snapshot = {
        "results": [
            {
                "projectId": 1,
                "projectName": "P1",
                "insights": [
                    _card("c1", "Revenue", 1, series=_monthly_series()),
                    _card("c1", "Revenue dup", 1, series=_monthly_series()),
                    _card("c2", "Costs", 1, series=_monthly_series()),
                ],
            }
        ]
    }
    request = pcs.PercentChangeSummaryRequest(
        project_ids=[1],
        interval="month",
        range="1y",
        page_size=1,
    )
    response = pcs.build_percent_change_summary(
        [_project(1, "P1")], snapshot, request
    )
    assert response.page.total_in_scope == 3
    assert response.page.total_eligible == 2
    assert response.page.total_excluded == 1
    assert response.excluded_by_reason["duplicate_card"] == 1
    assert len(response.rows) == 1
    assert response.page.next_cursor is not None


def test_summary_rejects_unsupported_interval():
    snapshot = {"results": []}
    request = pcs.PercentChangeSummaryRequest(
        project_ids=[1],
        interval="hour",
        range="1y",
    )
    with pytest.raises(ValueError, match="Unsupported interval"):
        pcs.build_percent_change_summary([_project(1, "P1")], snapshot, request)


def test_summary_interval_support_counts_reflect_in_scope():
    snapshot = {
        "results": [
            {
                "projectId": 1,
                "projectName": "P1",
                "insights": [
                    _card("c1", "Revenue", 1, series=_monthly_series()),
                    _card("c2", "Top vendors", 1, series=[
                        {"label": "A", "value": 1},
                        {"label": "B", "value": 2},
                    ]),
                ],
            }
        ]
    }
    request = pcs.PercentChangeSummaryRequest(
        project_ids=[1],
        interval="month",
        range="1y",
    )
    response = pcs.build_percent_change_summary(
        [_project(1, "P1")], snapshot, request
    )
    assert response.interval_support_counts["month"] == 1
    assert response.interval_support_counts["day"] == 0


def test_summary_statistics_calculated_from_valid_periods():
    snapshot = {
        "results": [
            {
                "projectId": 1,
                "projectName": "P1",
                "insights": [
                    _card("c1", "Revenue", 1, series=_monthly_series()),
                ],
            }
        ]
    }
    request = pcs.PercentChangeSummaryRequest(
        project_ids=[1],
        interval="month",
        range="1y",
    )
    response = pcs.build_percent_change_summary(
        [_project(1, "P1")], snapshot, request
    )
    row = response.rows[0]
    stats = row.statistics
    assert stats.valid_count == 11
    # 2025-11 vs 2025-10: (130 - 90) / 90 = +44.4%
    assert stats.max == pytest.approx(0.444444, rel=1e-3)
    # 2025-10 vs 2025-09: (90 - 120) / 120 = -25.0%
    assert stats.min == pytest.approx(-0.25, rel=1e-3)
    assert stats.latest == row.cells["2026-06"].percent_change_ratio
    assert stats.average == pytest.approx(
        sum(
            cell.percent_change_ratio
            for cell in row.cells.values()
            if cell.percent_change_ratio is not None
        ) / stats.valid_count,
        rel=1e-9,
    )
    # Cumulative: earliest baseline 100, latest current 180 -> 80.0%
    assert stats.cumulative_change == pytest.approx(0.80, rel=1e-3)
    assert stats.standard_deviation is not None
    assert stats.standard_deviation > 0


def test_summary_cumulative_is_first_to_last_not_sum_of_periods():
    snapshot = {
        "results": [
            {
                "projectId": 1,
                "projectName": "P1",
                "insights": [
                    _card("c1", "Revenue", 1, series=_monthly_series()),
                ],
            }
        ]
    }
    request = pcs.PercentChangeSummaryRequest(
        project_ids=[1],
        interval="month",
        range="1y",
    )
    response = pcs.build_percent_change_summary(
        [_project(1, "P1")], snapshot, request
    )
    row = response.rows[0]
    stats = row.statistics
    period_sum = sum(
        cell.percent_change_ratio
        for cell in row.cells.values()
        if cell.percent_change_ratio is not None
    )
    assert stats.cumulative_change is not None
    assert stats.cumulative_change != pytest.approx(period_sum, rel=1e-9)


def test_summary_cumulative_unavailable_for_discontinuous_series():
    series = _monthly_series()
    # Remove 2025-11 to create a gap.
    series = [p for p in series if p["label"] != "2025-11"]
    snapshot = {
        "results": [
            {
                "projectId": 1,
                "projectName": "P1",
                "insights": [
                    _card("c1", "Revenue", 1, series=series),
                ],
            }
        ]
    }
    request = pcs.PercentChangeSummaryRequest(
        project_ids=[1],
        interval="month",
        range="1y",
    )
    response = pcs.build_percent_change_summary(
        [_project(1, "P1")], snapshot, request
    )
    row = response.rows[0]
    assert row.statistics.cumulative_change is None
    assert row.statistics.valid_count == 9


def test_summary_std_dev_unavailable_when_less_than_two_observations():
    series = [
        {"label": "2025-07", "value": 100},
        {"label": "2025-08", "value": 110},
    ]
    snapshot = {
        "results": [
            {
                "projectId": 1,
                "projectName": "P1",
                "insights": [
                    _card("c1", "Revenue", 1, series=series),
                ],
            }
        ]
    }
    request = pcs.PercentChangeSummaryRequest(
        project_ids=[1],
        interval="month",
        range="1y",
    )
    response = pcs.build_percent_change_summary(
        [_project(1, "P1")], snapshot, request
    )
    row = response.rows[0]
    assert row.statistics.valid_count == 1
    assert row.statistics.standard_deviation is None


def test_summary_statistic_sorting_orders_by_latest_value():
    high_series = [
        {"label": "2025-07", "value": 100},
        {"label": "2025-08", "value": 120},
        {"label": "2025-09", "value": 144},
    ]
    low_series = [
        {"label": "2025-07", "value": 100},
        {"label": "2025-08", "value": 80},
        {"label": "2025-09", "value": 64},
    ]
    snapshot = {
        "results": [
            {
                "projectId": 1,
                "projectName": "P1",
                "insights": [
                    _card("c1", "Low", 1, series=low_series),
                    _card("c2", "High", 1, series=high_series),
                ],
            }
        ]
    }
    request = pcs.PercentChangeSummaryRequest(
        project_ids=[1],
        interval="month",
        range="1y",
        sort=pcs.SummarySort(field="statistics:latest", direction="desc"),
    )
    response = pcs.build_percent_change_summary(
        [_project(1, "P1")], snapshot, request
    )
    assert [r.title for r in response.rows] == ["High", "Low"]

    request_asc = pcs.PercentChangeSummaryRequest(
        project_ids=[1],
        interval="month",
        range="1y",
        sort=pcs.SummarySort(field="statistics:latest", direction="asc"),
    )
    response_asc = pcs.build_percent_change_summary(
        [_project(1, "P1")], snapshot, request_asc
    )
    assert [r.title for r in response_asc.rows] == ["Low", "High"]
