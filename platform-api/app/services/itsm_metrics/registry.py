"""Central ITSM metric registry for the five ServiceNow dashboard presets.

Every KPI used by a dashboard, drill-down, or AI prompt should be defined here.
Status values:
- measured: value can be computed from source columns as described.
- calculated: value is derived from other measured metrics.
- proxy: value is an approximation or proxy where the exact source field is absent.
- not_implemented: definition captured, but SQL/column mapping is not yet verified.
"""

from __future__ import annotations

from .models import FilterSpec, MetricDefinition

_BASE_SNAPSHOT = [
    FilterSpec(column="site_code", operator="neq", value="GLOBAL"),
]


_INCIDENT_METRICS: list[MetricDefinition] = [
    MetricDefinition(
        key="incident_volume",
        label="Incident volume",
        dashboard="incident",
        order=1,
        kind="event_period",
        table="01_incidents_CSV",
        date_field="opened_at",
        aggregation="distinct",
        unit="count",
        precision=0,
        polarity="neutral",
        drill_down_dimensions=["site_code", "priority", "category", "assignment_group_sys_id"],
    ),
    MetricDefinition(
        key="incident_rate",
        label="Incident rate",
        dashboard="incident",
        order=2,
        kind="ratio_period",
        table="01_incidents_CSV",
        date_field="opened_at",
        value_expression="""SELECT CASE WHEN population > 0 THEN 100.0 * incident_count / population ELSE 0 END AS value
FROM (
  SELECT COUNT(DISTINCT i.sys_id) AS incident_count, MAX(CAST(i.site_employee_population AS double)) AS population
  FROM {table} i
  WHERE CAST(i.opened_at AS double) >= {start} AND CAST(i.opened_at AS double) <= {end} AND i.site_code <> 'GLOBAL' AND {site_filter}
) t""",
        unit="percent",
        precision=1,
        polarity="lower_is_better",
        status="proxy",
        drill_down_dimensions=["site_code"],
        note="Uses MAX(site_employee_population) on the incident row; site population should be supplied by a dimension table in a future pass.",
    ),
    MetricDefinition(
        key="mean_response",
        label="Mean response",
        dashboard="incident",
        order=3,
        kind="duration_period",
        table="01_incidents_CSV",
        date_field="opened_at",
        numerator="first_response_minutes",
        unit="minutes",
        precision=1,
        polarity="lower_is_better",
        drill_down_dimensions=["site_code", "priority"],
    ),
    MetricDefinition(
        key="mttr",
        label="MTTR",
        dashboard="incident",
        order=4,
        kind="duration_period",
        table="01_incidents_CSV",
        date_field="resolved_at",
        numerator="resolution_minutes",
        unit="minutes",
        precision=1,
        polarity="lower_is_better",
        drill_down_dimensions=["site_code", "priority", "category"],
    ),
    MetricDefinition(
        key="median_resolution",
        label="Median resolution",
        dashboard="incident",
        order=5,
        kind="duration_period",
        table="01_incidents_CSV",
        date_field="resolved_at",
        numerator="resolution_minutes",
        value_expression="""SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY CAST(resolution_minutes AS double)) AS value
FROM {table}
WHERE CAST(resolved_at AS double) >= {start} AND CAST(resolved_at AS double) <= {end}
  AND resolution_minutes IS NOT NULL AND {site_filter}""",
        unit="minutes",
        precision=1,
        polarity="lower_is_better",
        status="proxy",
        note="PERCENTILE_CONT may need a Teiid-compatible approximation if the native aggregate is unavailable.",
    ),
    MetricDefinition(
        key="mean_restore",
        label="Mean restore",
        dashboard="incident",
        order=6,
        kind="duration_period",
        table="01_incidents_CSV",
        date_field="resolved_at",
        numerator="business_duration_minutes",
        unit="minutes",
        precision=1,
        polarity="lower_is_better",
        status="proxy",
    ),
    MetricDefinition(
        key="fcr_proxy",
        label="FCR proxy",
        dashboard="incident",
        order=7,
        kind="ratio_period",
        table="01_incidents_CSV",
        date_field="resolved_at",
        value_expression="""SELECT CASE WHEN resolved_count > 0 THEN 100.0 * fcr_count / resolved_count ELSE 0 END AS value
FROM (
  SELECT
    COUNT(DISTINCT CASE WHEN state IN ('Resolved', 'Closed') THEN sys_id END) AS resolved_count,
    COUNT(DISTINCT CASE WHEN state IN ('Resolved', 'Closed') AND reopen_count = 0 AND reassign_count = 0 THEN sys_id END) AS fcr_count
  FROM {table}
  WHERE CAST(resolved_at AS double) >= {start} AND CAST(resolved_at AS double) <= {end} AND {site_filter}
) t""",
        unit="percent",
        precision=1,
        polarity="higher_is_better",
        status="proxy",
        drill_down_dimensions=["site_code", "priority"],
    ),
    MetricDefinition(
        key="reassignment_rate",
        label="Reassignment rate",
        dashboard="incident",
        order=8,
        kind="ratio_period",
        table="01_incidents_CSV",
        date_field="opened_at",
        value_expression="""SELECT CASE WHEN total > 0 THEN 100.0 * reassigned / total ELSE 0 END AS value
FROM (
  SELECT COUNT(DISTINCT sys_id) AS total,
         COUNT(DISTINCT CASE WHEN reassign_count > 0 THEN sys_id END) AS reassigned
  FROM {table}
  WHERE CAST(opened_at AS double) >= {start} AND CAST(opened_at AS double) <= {end} AND {site_filter}
) t""",
        unit="percent",
        precision=1,
        polarity="lower_is_better",
        drill_down_dimensions=["site_code", "assignment_group_sys_id"],
    ),
    MetricDefinition(
        key="average_assignments",
        label="Average assignments",
        dashboard="incident",
        order=9,
        kind="duration_period",
        table="01_incidents_CSV",
        date_field="resolved_at",
        numerator="reassign_count",
        unit="count",
        precision=1,
        polarity="lower_is_better",
        status="proxy",
    ),
    MetricDefinition(
        key="reopen_rate",
        label="Reopen rate",
        dashboard="incident",
        order=10,
        kind="ratio_period",
        table="01_incidents_CSV",
        date_field="resolved_at",
        value_expression="""SELECT CASE WHEN resolved_count > 0 THEN 100.0 * reopened / resolved_count ELSE 0 END AS value
FROM (
  SELECT COUNT(DISTINCT CASE WHEN state IN ('Resolved', 'Closed') THEN sys_id END) AS resolved_count,
         COUNT(DISTINCT CASE WHEN state IN ('Resolved', 'Closed') AND reopen_count > 0 THEN sys_id END) AS reopened
  FROM {table}
  WHERE CAST(resolved_at AS double) >= {start} AND CAST(resolved_at AS double) <= {end} AND {site_filter}
) t""",
        unit="percent",
        precision=1,
        polarity="lower_is_better",
        drill_down_dimensions=["site_code", "priority"],
    ),
    MetricDefinition(
        key="major_incidents",
        label="Major incidents",
        dashboard="incident",
        order=11,
        kind="event_period",
        table="01_incidents_CSV",
        date_field="opened_at",
        filters=[FilterSpec(column="major_incident", operator="eq", value=True)],
        aggregation="distinct",
        unit="count",
        precision=0,
        polarity="neutral",
        drill_down_dimensions=["site_code", "priority"],
    ),
    MetricDefinition(
        key="major_incident_mttr",
        label="Major incident MTTR",
        dashboard="incident",
        order=12,
        kind="duration_period",
        table="01_incidents_CSV",
        date_field="resolved_at",
        numerator="resolution_minutes",
        filters=[FilterSpec(column="major_incident", operator="eq", value=True)],
        unit="minutes",
        precision=1,
        polarity="lower_is_better",
    ),
    MetricDefinition(
        key="open_backlog",
        label="Open backlog",
        dashboard="incident",
        order=13,
        kind="snapshot_eom",
        table="01_incidents_CSV",
        date_field="opened_at",
        state_field="state",
        aggregation="distinct",
        unit="count",
        precision=0,
        polarity="lower_is_better",
        drill_down_dimensions=["site_code", "priority", "assignment_group_sys_id"],
    ),
    MetricDefinition(
        key="backlog_older_than_30_days",
        label="Backlog older than 30 days",
        dashboard="incident",
        order=14,
        kind="snapshot_eom",
        table="01_incidents_CSV",
        date_field="opened_at",
        state_field="state",
        value_expression="""SELECT COUNT(DISTINCT sys_id) AS value
FROM {table}
WHERE CAST(opened_at AS double) <= {end} - 2592000
  AND (CAST(resolved_at AS double) IS NULL OR CAST(resolved_at AS double) > {end})
  AND {site_filter}""",
        unit="count",
        precision=0,
        polarity="lower_is_better",
        status="proxy",
    ),
    MetricDefinition(
        key="average_open_age",
        label="Average open age",
        dashboard="incident",
        order=15,
        kind="duration_period",
        table="01_incidents_CSV",
        date_field="opened_at",
        value_expression="""SELECT AVG(({end} - CAST(opened_at AS double)) / 86400.0) AS value
FROM {table}
WHERE CAST(opened_at AS double) <= {end}
  AND (resolved_at IS NULL OR CAST(resolved_at AS double) > {end})
  AND {site_filter}""",
        unit="days",
        precision=1,
        polarity="lower_is_better",
        status="proxy",
    ),
    MetricDefinition(
        key="resolution_sla",
        label="Resolution SLA",
        dashboard="incident",
        order=16,
        kind="ratio_period",
        table="01_incidents_CSV",
        date_field="resolved_at",
        value_expression="""SELECT CASE WHEN total > 0 THEN 100.0 * (total - breached) / total ELSE 0 END AS value
FROM (
  SELECT COUNT(DISTINCT sl.sys_id) AS total,
         COUNT(DISTINCT CASE WHEN sl.breached = true THEN sl.sys_id END) AS breached
  FROM "02_task_slas_CSV" sl
  JOIN "03_sla_definitions_CSV" sd ON sl.sla_definition_sys_id = sd.sys_id
  JOIN "01_incidents_CSV" i ON sl.task_sys_id = i.sys_id AND sl.task_type = 'Incident'
  WHERE sd.\"type\" IN ('Resolution', 'resolution')
    AND CAST(i.resolved_at AS double) >= {start} AND CAST(i.resolved_at AS double) <= {end}
    AND {site_filter}
) t""",
        unit="percent",
        precision=1,
        polarity="higher_is_better",
        status="not_implemented",
        drill_down_dimensions=["site_code", "priority"],
        note="SLA definition type values need verification before enabling.",
    ),
    MetricDefinition(
        key="sla_breach_rate",
        label="SLA breach rate",
        dashboard="incident",
        order=17,
        kind="ratio_period",
        table="01_incidents_CSV",
        date_field="resolved_at",
        value_expression="""SELECT CASE WHEN total > 0 THEN 100.0 * breached / total ELSE 0 END AS value
FROM (
  SELECT COUNT(DISTINCT sl.sys_id) AS total,
         COUNT(DISTINCT CASE WHEN sl.breached = true THEN sl.sys_id END) AS breached
  FROM "02_task_slas_CSV" sl
  JOIN "03_sla_definitions_CSV" sd ON sl.sla_definition_sys_id = sd.sys_id
  JOIN "01_incidents_CSV" i ON sl.task_sys_id = i.sys_id AND sl.task_type = 'Incident'
  WHERE CAST(i.resolved_at AS double) >= {start} AND CAST(i.resolved_at AS double) <= {end}
    AND {site_filter}
) t""",
        unit="percent",
        precision=1,
        polarity="lower_is_better",
        status="not_implemented",
        note="SLA definition type values need verification before enabling.",
    ),
    MetricDefinition(
        key="knowledge_reuse",
        label="Knowledge reuse",
        dashboard="incident",
        order=18,
        kind="ratio_period",
        table="01_incidents_CSV",
        date_field="resolved_at",
        value_expression="""SELECT CASE WHEN resolved_count > 0 THEN 100.0 * with_knowledge / resolved_count ELSE 0 END AS value
FROM (
  SELECT COUNT(DISTINCT CASE WHEN state IN ('Resolved', 'Closed') THEN sys_id END) AS resolved_count,
         COUNT(DISTINCT CASE WHEN state IN ('Resolved', 'Closed') AND knowledge_used = true THEN sys_id END) AS with_knowledge
  FROM {table}
  WHERE CAST(resolved_at AS double) >= {start} AND CAST(resolved_at AS double) <= {end} AND {site_filter}
) t""",
        unit="percent",
        precision=1,
        polarity="higher_is_better",
        status="proxy",
    ),
]


_SERVICE_REQUEST_METRICS: list[MetricDefinition] = [
    MetricDefinition(key="request_volume", label="Request volume", dashboard="service_request", order=1, kind="event_period", table="07_requests_CSV", date_field="requested_date", aggregation="distinct", unit="count", precision=0, polarity="neutral", drill_down_dimensions=["site_code", "request_type"]),
    MetricDefinition(key="requested_items", label="Requested items", dashboard="service_request", order=2, kind="event_period", table="08_requested_items_CSV", date_field="opened_at", aggregation="distinct", unit="count", precision=0, polarity="neutral"),
    MetricDefinition(key="catalog_tasks", label="Catalog tasks", dashboard="service_request", order=3, kind="event_period", table="09_catalog_tasks_CSV", date_field="opened_at", aggregation="distinct", unit="count", precision=0, polarity="neutral"),
    MetricDefinition(key="average_fulfillment", label="Average fulfillment", dashboard="service_request", order=4, kind="duration_period", table="07_requests_CSV", date_field="closed_at", numerator="request_fulfillment_minutes", unit="minutes", precision=1, polarity="lower_is_better"),
    MetricDefinition(key="median_fulfillment", label="Median fulfillment", dashboard="service_request", order=5, kind="duration_period", table="07_requests_CSV", date_field="closed_at", numerator="request_fulfillment_minutes", unit="minutes", precision=1, polarity="lower_is_better", status="proxy"),
    MetricDefinition(key="request_sla", label="Request SLA", dashboard="service_request", order=6, kind="ratio_period", table="07_requests_CSV", date_field="closed_at", value_expression="""SELECT CASE WHEN total > 0 THEN 100.0 * met / total ELSE 0 END AS value FROM (SELECT COUNT(DISTINCT sys_id) AS total, COUNT(DISTINCT CASE WHEN fulfillment_sla_met = true THEN sys_id END) AS met FROM {table} WHERE CAST(closed_at AS double) >= {start} AND CAST(closed_at AS double) <= {end} AND {site_filter}) t""", unit="percent", precision=1, polarity="higher_is_better"),
    MetricDefinition(key="request_backlog", label="Request backlog", dashboard="service_request", order=7, kind="snapshot_eom", table="07_requests_CSV", date_field="requested_date", aggregation="distinct", unit="count", precision=0, polarity="lower_is_better"),
    MetricDefinition(key="backlog_older_than_30_days_requests", label="Backlog older than 30 days", dashboard="service_request", order=8, kind="snapshot_eom", table="07_requests_CSV", date_field="requested_date", value_expression="""SELECT COUNT(DISTINCT sys_id) AS value FROM {table} WHERE CAST(requested_date AS double) <= {end} - 2592000 AND (closed_at IS NULL OR CAST(closed_at AS double) > {end}) AND {site_filter}""", unit="count", precision=0, polarity="lower_is_better", status="proxy"),
    MetricDefinition(key="open_requested_items", label="Open requested items", dashboard="service_request", order=9, kind="snapshot_eom", table="08_requested_items_CSV", date_field="opened_at", aggregation="distinct", unit="count", precision=0, polarity="lower_is_better"),
    MetricDefinition(key="open_catalog_tasks", label="Open catalog tasks", dashboard="service_request", order=10, kind="snapshot_eom", table="09_catalog_tasks_CSV", date_field="opened_at", aggregation="distinct", unit="count", precision=0, polarity="lower_is_better"),
    MetricDefinition(key="overdue_tasks", label="Overdue tasks", dashboard="service_request", order=11, kind="snapshot_eom", table="09_catalog_tasks_CSV", date_field="opened_at", value_expression="SELECT NULL AS value", unit="count", precision=0, polarity="lower_is_better", status="not_implemented"),
    MetricDefinition(key="satisfaction", label="Satisfaction", dashboard="service_request", order=12, kind="duration_period", table="07_requests_CSV", date_field="closed_at", numerator="satisfaction_score", unit="percent", precision=1, polarity="higher_is_better", status="proxy"),
    MetricDefinition(key="catalog_value", label="Catalog value", dashboard="service_request", order=13, kind="event_period", table="08_requested_items_CSV", date_field="opened_at", aggregation="sum", numerator="price", unit="currency", precision=0, polarity="neutral", status="proxy"),
    MetricDefinition(key="value_per_fulfilled_request", label="Value per fulfilled request", dashboard="service_request", order=14, kind="ratio_period", table="08_requested_items_CSV", date_field="closed_at", value_expression="SELECT NULL AS value", unit="currency", precision=0, polarity="neutral", status="not_implemented"),
]


_AVAILABILITY_METRICS: list[MetricDefinition] = [
    MetricDefinition(key="estimated_availability", label="Estimated availability", dashboard="availability", order=1, kind="ratio_period", table="15_service_outages_CSV", date_field="begin", value_expression="""SELECT CASE WHEN total_minutes > 0 THEN GREATEST(0, 100.0 - (100.0 * unplanned_minutes / total_minutes)) ELSE 100.0 END AS value FROM (SELECT COALESCE(SUM(CASE WHEN planned = false THEN duration_minutes END), 0) AS unplanned_minutes, COALESCE(SUM(duration_minutes), 0) AS total_minutes FROM {table} WHERE CAST(begin AS double) >= {start} AND CAST(begin AS double) <= {end} AND {site_filter}) t""", unit="percent", precision=3, polarity="higher_is_better", target=99.9),
    MetricDefinition(key="service_interruptions", label="Service interruptions", dashboard="availability", order=2, kind="event_period", table="15_service_outages_CSV", date_field="begin", aggregation="distinct", unit="count", precision=0, polarity="lower_is_better"),
    MetricDefinition(key="unplanned_outages", label="Unplanned outages", dashboard="availability", order=3, kind="event_period", table="15_service_outages_CSV", date_field="begin", filters=[FilterSpec(column="planned", operator="eq", value=False)], aggregation="distinct", unit="count", precision=0, polarity="lower_is_better"),
    MetricDefinition(key="planned_outages", label="Planned outages", dashboard="availability", order=4, kind="event_period", table="15_service_outages_CSV", date_field="begin", filters=[FilterSpec(column="planned", operator="eq", value=True)], aggregation="distinct", unit="count", precision=0, polarity="neutral"),
    MetricDefinition(key="unplanned_downtime", label="Unplanned downtime", dashboard="availability", order=5, kind="duration_period", table="15_service_outages_CSV", date_field="begin", numerator="duration_minutes", filters=[FilterSpec(column="planned", operator="eq", value=False)], unit="minutes", precision=0, polarity="lower_is_better"),
    MetricDefinition(key="planned_downtime", label="Planned downtime", dashboard="availability", order=6, kind="duration_period", table="15_service_outages_CSV", date_field="begin", numerator="duration_minutes", filters=[FilterSpec(column="planned", operator="eq", value=True)], unit="minutes", precision=0, polarity="neutral"),
    MetricDefinition(key="mean_time_to_repair", label="Mean time to repair", dashboard="availability", order=7, kind="duration_period", table="15_service_outages_CSV", date_field="end", numerator="duration_minutes", filters=[FilterSpec(column="planned", operator="eq", value=False)], unit="minutes", precision=1, polarity="lower_is_better"),
    MetricDefinition(key="users_affected", label="Users affected", dashboard="availability", order=8, kind="event_period", table="15_service_outages_CSV", date_field="begin", aggregation="sum", numerator="users_affected", unit="count", precision=0, polarity="lower_is_better"),
    MetricDefinition(key="business_impact_minutes", label="Business-impact minutes", dashboard="availability", order=9, kind="event_period", table="15_service_outages_CSV", date_field="begin", aggregation="sum", numerator="business_impact_minutes", unit="minutes", precision=0, polarity="lower_is_better", status="proxy"),
    MetricDefinition(key="availability_target", label="Availability target", dashboard="availability", order=10, kind="ratio_period", table="15_service_outages_CSV", date_field="begin", value_expression="SELECT AVG(CAST(availability_target_pct AS double)) AS value FROM {table} WHERE CAST(begin AS double) >= {start} AND CAST(begin AS double) <= {end} AND {site_filter}", unit="percent", precision=3, polarity="higher_is_better"),
    MetricDefinition(key="incident_linked_outages", label="Incident-linked outages", dashboard="availability", order=11, kind="event_period", table="15_service_outages_CSV", date_field="begin", filters=[FilterSpec(column="task_type", operator="eq", value="Incident")], aggregation="distinct", unit="count", precision=0, polarity="lower_is_better"),
    MetricDefinition(key="change_linked_outages", label="Change-linked outages", dashboard="availability", order=12, kind="event_period", table="15_service_outages_CSV", date_field="begin", filters=[FilterSpec(column="task_type", operator="eq", value="Change Request")], aggregation="distinct", unit="count", precision=0, polarity="lower_is_better"),
]


_PRODUCTIVITY_METRICS: list[MetricDefinition] = [
    MetricDefinition(key="active_analysts", label="Active analysts", dashboard="productivity", order=1, kind="event_period", table="09_catalog_tasks_CSV", date_field="closed_at", aggregation="distinct", numerator="assigned_to_user_sys_id", unit="count", precision=0, polarity="neutral", status="proxy"),
    MetricDefinition(key="tickets_per_analyst", label="Tickets per analyst", dashboard="productivity", order=2, kind="ratio_period", table="01_incidents_CSV", date_field="opened_at", value_expression="SELECT NULL AS value", unit="count", precision=1, polarity="neutral", status="not_implemented"),
    MetricDefinition(key="resolutions_per_analyst", label="Resolutions per analyst", dashboard="productivity", order=3, kind="ratio_period", table="01_incidents_CSV", date_field="resolved_at", value_expression="SELECT NULL AS value", unit="count", precision=1, polarity="higher_is_better", status="not_implemented"),
    MetricDefinition(key="resolution_rate", label="Resolution rate", dashboard="productivity", order=4, kind="ratio_period", table="01_incidents_CSV", date_field="opened_at", value_expression="SELECT NULL AS value", unit="percent", precision=1, polarity="higher_is_better", status="not_implemented"),
    MetricDefinition(key="backlog_per_analyst", label="Backlog per analyst", dashboard="productivity", order=5, kind="ratio_period", table="01_incidents_CSV", date_field="opened_at", value_expression="SELECT NULL AS value", unit="count", precision=1, polarity="lower_is_better", status="not_implemented"),
    MetricDefinition(key="mean_response_prod", label="Mean response", dashboard="productivity", order=6, kind="duration_period", table="01_incidents_CSV", date_field="opened_at", numerator="first_response_minutes", unit="minutes", precision=1, polarity="lower_is_better"),
    MetricDefinition(key="mean_resolution_prod", label="Mean resolution", dashboard="productivity", order=7, kind="duration_period", table="01_incidents_CSV", date_field="resolved_at", numerator="resolution_minutes", unit="minutes", precision=1, polarity="lower_is_better"),
    MetricDefinition(key="resolution_sla_prod", label="Resolution SLA", dashboard="productivity", order=8, kind="ratio_period", table="01_incidents_CSV", date_field="resolved_at", value_expression="SELECT NULL AS value", unit="percent", precision=1, polarity="higher_is_better", status="not_implemented"),
    MetricDefinition(key="fcr_proxy_prod", label="FCR proxy", dashboard="productivity", order=9, kind="ratio_period", table="01_incidents_CSV", date_field="resolved_at", value_expression="SELECT NULL AS value", unit="percent", precision=1, polarity="higher_is_better", status="not_implemented"),
    MetricDefinition(key="transfer_proxy", label="Transfer proxy", dashboard="productivity", order=10, kind="ratio_period", table="01_incidents_CSV", date_field="resolved_at", value_expression="SELECT NULL AS value", unit="percent", precision=1, polarity="lower_is_better", status="not_implemented"),
    MetricDefinition(key="knowledge_reuse_prod", label="Knowledge reuse", dashboard="productivity", order=11, kind="ratio_period", table="01_incidents_CSV", date_field="resolved_at", value_expression="SELECT NULL AS value", unit="percent", precision=1, polarity="higher_is_better", status="not_implemented"),
    MetricDefinition(key="reopen_rate_prod", label="Reopen rate", dashboard="productivity", order=12, kind="ratio_period", table="01_incidents_CSV", date_field="resolved_at", value_expression="SELECT NULL AS value", unit="percent", precision=1, polarity="lower_is_better", status="not_implemented"),
    MetricDefinition(key="self_service_intake", label="Self-service intake", dashboard="productivity", order=13, kind="ratio_period", table="07_requests_CSV", date_field="requested_date", value_expression="SELECT NULL AS value", unit="percent", precision=1, polarity="higher_is_better", status="not_implemented"),
    MetricDefinition(key="monitoring_intake", label="Monitoring intake", dashboard="productivity", order=14, kind="ratio_period", table="01_incidents_CSV", date_field="opened_at", value_expression="SELECT NULL AS value", unit="percent", precision=1, polarity="lower_is_better", status="not_implemented"),
]


_PROBLEM_METRICS: list[MetricDefinition] = [
    MetricDefinition(key="problems_identified", label="Problems identified", dashboard="problem", order=1, kind="event_period", table="04_problems_CSV", date_field="opened_at", aggregation="distinct", unit="count", precision=0, polarity="neutral"),
    MetricDefinition(key="problems_resolved", label="Problems resolved", dashboard="problem", order=2, kind="event_period", table="04_problems_CSV", date_field="resolved_at", filters=[FilterSpec(column="state", operator="in", value=["Resolved", "Closed"])], aggregation="distinct", unit="count", precision=0, polarity="higher_is_better"),
    MetricDefinition(key="problem_backlog", label="Problem backlog", dashboard="problem", order=3, kind="snapshot_eom", table="04_problems_CSV", date_field="opened_at", state_field="state", aggregation="distinct", unit="count", precision=0, polarity="lower_is_better"),
    MetricDefinition(key="open_backlog_age", label="Open backlog age", dashboard="problem", order=4, kind="duration_period", table="04_problems_CSV", date_field="opened_at", value_expression="""SELECT AVG(({end} - CAST(opened_at AS double)) / 86400.0) AS value FROM {table} WHERE CAST(opened_at AS double) <= {end} AND (resolved_at IS NULL OR CAST(resolved_at AS double) > {end}) AND {site_filter}""", unit="days", precision=1, polarity="lower_is_better", status="proxy"),
    MetricDefinition(key="mean_time_to_resolve", label="Mean time to resolve", dashboard="problem", order=5, kind="duration_period", table="04_problems_CSV", date_field="resolved_at", numerator="resolution_minutes", unit="minutes", precision=1, polarity="lower_is_better"),
    MetricDefinition(key="root_cause_rate", label="Root-cause rate", dashboard="problem", order=6, kind="ratio_period", table="04_problems_CSV", date_field="resolved_at", value_expression="""SELECT CASE WHEN total > 0 THEN 100.0 * with_root_cause / total ELSE 0 END AS value FROM (SELECT COUNT(DISTINCT sys_id) AS total, COUNT(DISTINCT CASE WHEN root_cause IS NOT NULL THEN sys_id END) AS with_root_cause FROM {table} WHERE CAST(resolved_at AS double) >= {start} AND CAST(resolved_at AS double) <= {end} AND {site_filter}) t""", unit="percent", precision=1, polarity="higher_is_better"),
    MetricDefinition(key="known_error_rate", label="Known-error rate", dashboard="problem", order=7, kind="ratio_period", table="04_problems_CSV", date_field="resolved_at", value_expression="""SELECT CASE WHEN total > 0 THEN 100.0 * known / total ELSE 0 END AS value FROM (SELECT COUNT(DISTINCT sys_id) AS total, COUNT(DISTINCT CASE WHEN known_error = true THEN sys_id END) AS known FROM {table} WHERE CAST(resolved_at AS double) >= {start} AND CAST(resolved_at AS double) <= {end} AND {site_filter}) t""", unit="percent", precision=1, polarity="higher_is_better"),
    MetricDefinition(key="workaround_coverage", label="Workaround coverage", dashboard="problem", order=8, kind="ratio_period", table="04_problems_CSV", date_field="resolved_at", value_expression="""SELECT CASE WHEN total > 0 THEN 100.0 * with_workaround / total ELSE 0 END AS value FROM (SELECT COUNT(DISTINCT sys_id) AS total, COUNT(DISTINCT CASE WHEN workaround IS NOT NULL THEN sys_id END) AS with_workaround FROM {table} WHERE CAST(resolved_at AS double) >= {start} AND CAST(resolved_at AS double) <= {end} AND {site_filter}) t""", unit="percent", precision=1, polarity="higher_is_better"),
    MetricDefinition(key="linked_incidents", label="Linked incidents", dashboard="problem", order=9, kind="event_period", table="01_incidents_CSV", date_field="opened_at", filters=[FilterSpec(column="problem_sys_id", operator="is_not_null")], aggregation="distinct", unit="count", precision=0, polarity="neutral"),
    MetricDefinition(key="incident_problem_coverage", label="Incident problem coverage", dashboard="problem", order=10, kind="ratio_period", table="01_incidents_CSV", date_field="opened_at", value_expression="""SELECT CASE WHEN total > 0 THEN 100.0 * linked / total ELSE 0 END AS value FROM (SELECT COUNT(DISTINCT sys_id) AS total, COUNT(DISTINCT CASE WHEN problem_sys_id IS NOT NULL THEN sys_id END) AS linked FROM {table} WHERE CAST(opened_at AS double) >= {start} AND CAST(opened_at AS double) <= {end} AND {site_filter}) t""", unit="percent", precision=1, polarity="higher_is_better"),
    MetricDefinition(key="repeat_incident_rate", label="Repeat incident rate", dashboard="problem", order=11, kind="ratio_period", table="01_incidents_CSV", date_field="opened_at", value_expression="SELECT NULL AS value", unit="percent", precision=1, polarity="lower_is_better", status="not_implemented"),
    MetricDefinition(key="average_problem_age", label="Average problem age", dashboard="problem", order=12, kind="duration_period", table="04_problems_CSV", date_field="resolved_at", value_expression="SELECT AVG(CAST(resolution_minutes AS double)) / 1440.0 AS value FROM {table} WHERE CAST(resolved_at AS double) >= {start} AND CAST(resolved_at AS double) <= {end} AND {site_filter}", unit="days", precision=1, polarity="lower_is_better"),
    MetricDefinition(key="problems_in_rca", label="Problems in RCA", dashboard="problem", order=13, kind="snapshot_eom", table="04_problems_CSV", date_field="opened_at", state_field="state", filters=[FilterSpec(column="state", operator="in", value=["Root Cause Analysis", "RCA"])], aggregation="distinct", unit="count", precision=0, polarity="lower_is_better", status="proxy"),
    MetricDefinition(key="fix_in_progress", label="Fix in progress", dashboard="problem", order=14, kind="snapshot_eom", table="04_problems_CSV", date_field="opened_at", state_field="state", filters=[FilterSpec(column="state", operator="in", value=["Fix in Progress", "Work in Progress"])], aggregation="distinct", unit="count", precision=0, polarity="neutral", status="proxy"),
]


_CHARTS: dict[str, list[tuple[str, str, str]]] = {
    "incident": [
        ("monthly_incident_volume", "Monthly incident volume", "opened_at"),
        ("incident_category_mix", "Incident category mix", "category"),
    ],
    "service_request": [
        ("monthly_request_demand", "Monthly request demand", "requested_date"),
        ("catalog_demand_by_category", "Catalog demand by category", "category"),
    ],
    "availability": [
        ("monthly_estimated_availability", "Monthly estimated availability", "begin"),
        ("outage_root_causes", "Outage root causes", "root_cause"),
    ],
    "productivity": [
        ("workload_by_group", "Workload by assignment group", "assignment_group_sys_id"),
        ("workload_vs_sla", "Workload versus resolution SLA", "assignment_group_sys_id"),
    ],
    "problem": [
        ("problems_identified_trend", "Problems identified trend", "opened_at"),
        ("root_cause_distribution", "Root-cause distribution", "root_cause"),
    ],
}


def _attach_chart_group_bys(metrics: list[MetricDefinition], dashboard: str) -> list[MetricDefinition]:
    chart_defs = _CHARTS.get(dashboard, [])
    if not chart_defs:
        return metrics
    first_two = metrics[:2]
    rest = metrics[2:]
    updated: list[MetricDefinition] = []
    for i, m in enumerate(first_two):
        if i < len(chart_defs):
            updated.append(MetricDefinition(**{**m.__dict__, "group_by": chart_defs[i][2], "label": chart_defs[i][1]}))
        else:
            updated.append(m)
    return updated + rest


_REGISTRY: dict[str, list[MetricDefinition]] = {
    "incident": _attach_chart_group_bys(_INCIDENT_METRICS, "incident"),
    "service_request": _attach_chart_group_bys(_SERVICE_REQUEST_METRICS, "service_request"),
    "availability": _attach_chart_group_bys(_AVAILABILITY_METRICS, "availability"),
    "productivity": _attach_chart_group_bys(_PRODUCTIVITY_METRICS, "productivity"),
    "problem": _attach_chart_group_bys(_PROBLEM_METRICS, "problem"),
}

_VALID_DASHBOARDS = set(_REGISTRY.keys())


def get_dashboard_metrics(dashboard: str) -> list[MetricDefinition]:
    if dashboard not in _VALID_DASHBOARDS:
        raise ValueError(f"Unknown ITSM dashboard: {dashboard}")
    return sorted(_REGISTRY[dashboard], key=lambda m: m.order)


def get_metric(dashboard: str, metric_key: str) -> MetricDefinition | None:
    for m in get_dashboard_metrics(dashboard):
        if m.key == metric_key:
            return m
    return None


def list_dashboards() -> list[str]:
    return sorted(_VALID_DASHBOARDS)
