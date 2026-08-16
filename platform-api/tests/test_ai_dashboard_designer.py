from __future__ import annotations

from app.models.file_source_meta import FileSourceMeta
from app.routes.ai_proxy_dashboard_designer import (
    _chart_recommendations,
    _missing_concepts,
    _support_status,
    _validated_chart_recommendations,
)


def _source() -> FileSourceMeta:
    return FileSourceMeta(
        id=1,
        tenant_id=33,
        owner_id=7,
        project_id=44,
        view_name="incidents",
        file_name="incidents.csv",
        vdb_type="user",
        archived=False,
    )


def test_missing_concepts_only_reports_requested_unsupported_fields() -> None:
    columns = [
        {"name": "incident_number", "type": "string"},
        {"name": "opened_at", "type": "datetime"},
        {"name": "state", "type": "string"},
        {"name": "site", "type": "string"},
    ]

    missing = _missing_concepts(
        "Show backlog, site performance, resolution SLA and assignment group",
        columns,
    )

    assert "backlog state" not in missing
    assert "site or region" not in missing
    assert "SLA performance" in missing
    assert "assignment group" in missing


def test_chart_recommendations_follow_detected_data_shape() -> None:
    recommendations = _chart_recommendations(
        [
            {"name": "opened_at", "type": "datetime"},
            {"name": "category", "type": "string"},
            {"name": "site", "type": "string"},
            {"name": "resolution_hours", "type": "decimal"},
        ]
    )
    compatible = {item["chartType"] for item in recommendations if item["compatible"]}
    assert {"kpi", "line", "horizontal_bar", "heatmap"}.issubset(compatible)


def test_executed_preview_can_validate_a_chart_when_profile_metadata_is_sparse() -> None:
    recommendations = _validated_chart_recommendations(
        [],
        {
            "widgets": [
                {
                    "status": "valid",
                    "sql": 'SELECT "site", COUNT(*) AS "count" FROM "incidents" GROUP BY "site"',
                    "chartType": "bar",
                }
            ]
        },
    )
    horizontal = next(item for item in recommendations if item["chartType"] == "horizontal_bar")
    assert horizontal["compatible"] is True
    assert "executing" in horizontal["reason"]


def test_support_status_has_three_explicit_outcomes() -> None:
    source = _source()
    valid = {
        "widgets": [
            {"status": "valid", "sql": "SELECT 1", "chartType": "kpi"}
        ]
    }
    partial = {
        "widgets": [
            {"status": "valid", "sql": "SELECT 1", "chartType": "kpi"},
            {"status": "preview_only", "sql": "SELECT 2", "chartType": "line"},
        ]
    }

    assert _support_status(sources=[], suggestion=None, missing=[]) == "not_supported"
    assert _support_status(sources=[source], suggestion=valid, missing=[]) == "fully_supported"
    assert _support_status(sources=[source], suggestion=partial, missing=[]) == "partially_supported"
    assert _support_status(sources=[source], suggestion=valid, missing=["SLA performance"]) == "partially_supported"
