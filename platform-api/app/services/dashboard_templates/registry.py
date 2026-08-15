"""Canonical semantic metric manifests used by dashboard templates."""

from copy import deepcopy

_MANIFESTS: dict[str, list[dict]] = {
    "servicenow-kpi-board": [
        {"key": "incident_volume", "label": "Incident volume", "entity": "incident", "aggregation": "count_distinct", "valueField": "id", "dateField": "openedAt", "unit": "count", "polarity": "lower"},
        {"key": "open_backlog", "label": "Open backlog", "entity": "incident", "aggregation": "count_distinct", "valueField": "id", "dateField": "openedAt", "filter": {"field": "active", "operator": "eq", "value": True}, "unit": "count", "polarity": "lower"},
        {"key": "mttr", "label": "MTTR", "entity": "incident", "aggregation": "avg", "valueField": "resolutionHours", "dateField": "resolvedAt", "unit": "hours", "polarity": "lower"},
        {"key": "resolution_sla", "label": "Resolution SLA", "entity": "incident", "aggregation": "ratio", "valueField": "id", "dateField": "resolvedAt", "numeratorFilter": {"field": "slaBreached", "operator": "eq", "value": False}, "unit": "percent", "polarity": "higher"},
        {"key": "request_volume", "label": "Request volume", "entity": "request", "aggregation": "count_distinct", "valueField": "id", "dateField": "openedAt", "unit": "count", "polarity": "lower"},
        {"key": "request_fulfillment_time", "label": "Fulfillment time", "entity": "request", "aggregation": "avg", "valueField": "fulfillmentHours", "dateField": "closedAt", "unit": "hours", "polarity": "lower"},
    ],
    "servicenow-itsm-operations": [
        {"key": "active_work", "label": "Active work", "entity": "incident", "aggregation": "count_distinct", "valueField": "id", "dateField": "openedAt", "filter": {"field": "active", "operator": "eq", "value": True}, "unit": "count", "polarity": "lower"},
        {"key": "critical_incidents", "label": "Critical incidents", "entity": "incident", "aggregation": "count_distinct", "valueField": "id", "dateField": "openedAt", "filter": {"field": "priority", "operator": "in", "value": ["1", "P1", "Critical"]}, "unit": "count", "polarity": "lower"},
        {"key": "request_backlog", "label": "Request backlog", "entity": "request", "aggregation": "count_distinct", "valueField": "id", "dateField": "openedAt", "filter": {"field": "active", "operator": "eq", "value": True}, "unit": "count", "polarity": "lower"},
    ],
    "finance-performance": [
        {"key": "revenue", "label": "Revenue", "entity": "finance", "aggregation": "sum", "valueField": "revenue", "dateField": "date", "unit": "currency", "polarity": "higher"},
        {"key": "expense", "label": "Expense", "entity": "finance", "aggregation": "sum", "valueField": "expense", "dateField": "date", "unit": "currency", "polarity": "lower"},
        {"key": "gross_margin", "label": "Gross margin", "entity": "finance", "aggregation": "ratio", "valueField": "grossProfit", "denominatorField": "revenue", "dateField": "date", "unit": "percent", "polarity": "higher"},
    ],
    "manufacturing-operations": [
        {"key": "output", "label": "Production output", "entity": "production", "aggregation": "sum", "valueField": "unitsProduced", "dateField": "date", "unit": "count", "polarity": "higher"},
        {"key": "oee", "label": "OEE", "entity": "production", "aggregation": "avg", "valueField": "oee", "dateField": "date", "unit": "percent", "polarity": "higher"},
        {"key": "downtime", "label": "Downtime", "entity": "production", "aggregation": "sum", "valueField": "downtimeHours", "dateField": "date", "unit": "hours", "polarity": "lower"},
    ],
    "sales-performance": [
        {"key": "revenue", "label": "Revenue", "entity": "sales", "aggregation": "sum", "valueField": "amount", "dateField": "date", "unit": "currency", "polarity": "higher"},
        {"key": "pipeline", "label": "Pipeline", "entity": "sales", "aggregation": "sum", "valueField": "pipelineAmount", "dateField": "date", "unit": "currency", "polarity": "higher"},
        {"key": "win_rate", "label": "Win rate", "entity": "sales", "aggregation": "ratio", "valueField": "id", "dateField": "date", "numeratorFilter": {"field": "status", "operator": "eq", "value": "Won"}, "unit": "percent", "polarity": "higher"},
    ],
    "hr-workforce-insights": [
        {"key": "headcount", "label": "Headcount", "entity": "workforce", "aggregation": "count_distinct", "valueField": "employeeId", "dateField": "date", "unit": "count", "polarity": "neutral"},
        {"key": "turnover", "label": "Turnover", "entity": "workforce", "aggregation": "ratio", "valueField": "employeeId", "dateField": "date", "numeratorFilter": {"field": "status", "operator": "eq", "value": "Terminated"}, "unit": "percent", "polarity": "lower"},
        {"key": "time_to_fill", "label": "Time to fill", "entity": "recruiting", "aggregation": "avg", "valueField": "timeToFillDays", "dateField": "filledAt", "unit": "days", "polarity": "lower"},
    ],
}


def template_metric_manifest(template_id: str) -> list[dict]:
    return deepcopy(_MANIFESTS.get(template_id, []))
