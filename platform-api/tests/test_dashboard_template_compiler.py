from datetime import date

import pytest

from app.services.dashboard_templates.compiler import compile_batch_queries, render_sql_template, validate_binding

METRICS = [
    {"key": "incident_volume", "label": "Incident volume", "entity": "incident", "aggregation": "count_distinct", "valueField": "id", "dateField": "openedAt", "unit": "count", "polarity": "lower"},
    {"key": "mttr", "label": "MTTR", "entity": "incident", "aggregation": "avg", "valueField": "resolutionHours", "dateField": "openedAt", "unit": "hours", "polarity": "lower"},
]


def test_compiler_batches_metrics_and_prior_period() -> None:
    queries = compile_batch_queries(source_mapping={"incident": "incident_view"}, field_mapping={"incident": {"id": "number", "openedAt": "opened_at", "resolutionHours": "resolution_hours", "site": "site_code"}}, metric_manifest=METRICS, dimension_config={"label": "Region", "field": "site"}, period="30_days", as_of=date(2026, 8, 15))
    assert [query.query_key for query in queries] == ["summary_incident_openedAt", "dimension_incident_openedAt"]
    assert "incident_volume__previous" in queries[0].sql_template
    assert "'2026-07-16'" in queries[0].compiled_sql
    assert 'GROUP BY "site_code"' in queries[1].compiled_sql


def test_binding_validation_reports_missing_fields() -> None:
    result = validate_binding(source_mapping={"incident": "incident_view"}, field_mapping={"incident": {"id": "number"}}, metric_manifest=METRICS, dimension_config={"field": "site"})
    assert result["valid"] is False
    assert "Map incident.openedAt." in result["errors"]
    assert "Map incident.resolutionHours." in result["errors"]


def test_renderer_escapes_values_and_rejects_unknown_tokens() -> None:
    sql = render_sql_template('SELECT * FROM "incident" WHERE opened >= {{previous_start}} {{dimension_filter}}', period_start="2026-07-16", period_end="2026-08-15", previous_start="2026-06-16", dimension_column="site", dimension_value="O'Hare")
    assert '"site" = \'O\'\'Hare\'' in sql
    with pytest.raises(ValueError, match="Unresolved"):
        render_sql_template("SELECT {{unknown}}", period_start="2026-07-16", period_end="2026-08-15", previous_start="2026-06-16")


def test_compiler_rejects_untrusted_identifiers() -> None:
    with pytest.raises(ValueError, match="Unsafe"):
        compile_batch_queries(source_mapping={"incident": "incident; DROP TABLE users"}, field_mapping={"incident": {"id": "number", "openedAt": "opened_at", "resolutionHours": "hours"}}, metric_manifest=METRICS, dimension_config={})
