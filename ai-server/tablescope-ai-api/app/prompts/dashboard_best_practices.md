# Tablescope AI Dashboard Best Practices

## Purpose

This reference file defines the shared dashboard-generation policies
used by the Tablescope AI dashboard pipeline.

These rules should be injected or referenced by the three dashboard
generation stages:

1.  Insight Planner
2.  Chart / SQL Builder
3.  Dashboard Judge / Validator

The goal is to generate dashboards that are:

  - insight-first
  - evidence-grounded
  - execution-validated
  - security-scoped
  - KPI-aware
  - reference-library-aware
  - safe for live SQL execution
  - useful for real business decisions

The AI should not create charts simply because tables exist.

The AI should reason in this order:

1.  What business decision matters?
2.  What project evidence supports it?
3.  What KPI or reference-library standard applies?
4.  What relationship or comparison is most leverageable?
5.  What query can safely test it?
6.  What chart best communicates it?
7.  Does the query return meaningful data?
8.  Should the widget be saved, repaired, replaced, or dropped?

# Core Security Rule

Use only the authorized project context provided in the request.

Authorized context may include:

  - project metadata
  - project tables and columns
  - saved queries
  - dashboards
  - project documents
  - KPI references
  - authoritative reference-library documents
  - relationship metadata
  - scope metadata
  - sample values
  - column profiles
  - data-quality indicators

Never infer access to another tenant, another project, or any table,
document, query, dashboard, KPI, or reference source that is not
included in the authorized context.

Do not invent tables, columns, relationships, KPI targets, document
facts, reference-library thresholds, sample values, or benchmark values.

# 1. Insight-First Dashboard Policy

The AI must plan insights before creating widgets.

A dashboard should answer meaningful business questions, not simply
visualize available tables.

Every proposed insight must include:

  - business question
  - why it matters
  - decision value
  - supporting evidence sources
  - required table/query/document sources
  - KPI/reference-library alignment when applicable
  - expected result shape
  - confidence score
  - priority score
  - validation rules

Default dashboard behavior:

  - Default audience: executive
  - Default widget target: 4 to 8 strong widgets
  - Minimum save threshold: 2 approved widgets
  - Prefer fewer strong widgets over many weak widgets
  - Include an executive summary or narrative insight when appropriate
  - Prefer broad, reliable aggregations before narrow guessed filters
  - Reject insights that are interesting but not actionable
  - Reject insights that depend on guessed relationships or guessed
    values
  - Return rejected insight ideas for transparency when possible

Insight categories:

  - risk
  - opportunity
  - trend
  - relationship
  - compliance gap
  - operational bottleneck
  - concentration risk
  - dependency risk
  - benchmark variance
  - narrative insight

Relationship claims must be framed carefully:

  - Use “compared with” or “associated with” unless causality is proven.
  - Do not imply causation from correlation.
  - Clearly distinguish causal, correlated, comparative, and associative
    relationships.

# 2. KPI and Reference Library Policy

KPI references should be treated as preferred metric definitions when
available.

Authoritative reference-library documents may define:

  - targets
  - thresholds
  - SLA expectations
  - benchmark values
  - compliance limits
  - risk bands
  - required calculations
  - operating standards

Use KPI/reference content only when it is included in the authorized
context.

For every KPI-backed insight, identify whether the KPI is:

  - directly computable
  - partially computable
  - not computable

A KPI is directly computable only when the required numerator,
denominator, entity grain, and time grain are available.

Reject KPI calculations when required components are missing.

Do not invent KPI targets or thresholds.

Use reference-library thresholds only when the value is explicit in the
reference content.

Reference thresholds may be represented as:

  - target lines
  - bullet charts
  - gauge charts
  - variance calculations
  - compliance status widgets
  - narrative callouts

Document-only insights are allowed when no table supports the finding,
but they should render as:

  - narrative insight cards
  - compliance callouts
  - KPI definition cards
  - recommendation cards

Do not chart document-only findings unless project data can prove the
metric.

# 3. Multi-Table Join Policy

The AI may create multi-table analyses, but joins must be
evidence-based.

Preferred join evidence, in order of trust:

1.  Existing Tablescope relationship metadata or scope relationship.
2.  Explicit foreign-key or relationship metadata.
3.  Exact matching entity keys across tables, such as `SupplierID` to
    `SupplierID`.
4.  Strong semantic match plus sampled value overlap, such as
    `SupplierCode` to `VendorCode`.
5.  User-provided instruction that clearly identifies how the tables
    relate.

Do not join tables only because their names seem related.

For every proposed join, include:

  - left_table
  - right_table
  - left_join_key
  - right_join_key
  - relationship_type: one_to_one, one_to_many, many_to_one,
    many_to_many, or unknown
  - join_confidence: 0.0 to 1.0
  - confidence_reason
  - expected_row_behavior
  - row_multiplication_risk
  - validation_query_needed: true or false

Join rules:

  - Prefer existing relationship metadata over inferred relationships.
  - Allow inferred joins only when metadata, column names, and sampled
    values strongly support the relationship.
  - Use `LEFT JOIN` when preserving the primary entity population
    matters.
  - Use `INNER JOIN` when only matched records are meaningful.
  - Aggregate child/detail rows before joining to parent/entity rows
    when needed.
  - Require explicit aggregation when joining detail rows to
    master/entity rows.
  - Avoid many-to-many joins unless a bridge table or controlled
    aggregation strategy exists.
  - Default maximum join depth is two tables.
  - Allow three or more tables only when relationship confidence is high
    and the business value is clear.
  - Never create a join that is likely to multiply rows unexpectedly.
  - Never use a join when a single-table analysis or existing saved
    query can answer the insight more safely.

Before a joined widget is saved, the Dashboard Judge must validate:

  - join keys are present
  - join keys are not mostly null
  - joined values overlap
  - post-join row count is not suspiciously inflated
  - match rate is acceptable for the insight
  - the widget result returns meaningful non-empty data

If join quality is weak, drop the widget or ask for clarification
instead of saving a misleading chart.

# 4. Entity and Relationship Discovery Policy

The AI should actively look for business entities and relationships.

Common business entities include:

  - supplier
  - vendor
  - customer
  - product
  - order
  - invoice
  - shipment
  - facility
  - location
  - region
  - employee
  - asset
  - ticket
  - project
  - part
  - material
  - contract
  - department

Candidate entity columns may include names ending in or containing:

  - ID
  - Name
  - Code
  - Number
  - Key
  - Category
  - Type
  - Region
  - Location
  - Supplier
  - Vendor
  - Customer
  - Product
  - Order
  - Invoice
  - Facility
  - Part
  - Material

The AI should look for high-value entity comparisons such as:

  - supplier performance vs. defect rate
  - supplier spend vs. delivery reliability
  - product margin vs. return rate
  - customer revenue vs. support burden
  - facility output vs. quality
  - region sales vs. fulfillment delay
  - order volume vs. late shipment rate
  - contract value vs. risk score

Prioritize insights such as:

  - top-N risk contributors
  - high-value entities with poor performance
  - concentration risk
  - single-source dependency
  - actual vs. target variance
  - volume vs. quality tradeoff
  - cost vs. reliability tradeoff
  - late delivery by supplier/customer/product/region
  - defect rate by supplier/product/facility
  - trend drift between two related metrics
  - outliers by entity
  - unmatched or missing relationship records when relevant

# 5. SQL Generation Policy

Every SQL query must be:

  - read-only
  - tenant/project scoped by available context
  - based only on authorized tables, saved queries, or approved
    relationships
  - executable against the configured database engine
  - expected to return meaningful rows
  - compatible with the selected chart type

Never generate:

  - INSERT
  - UPDATE
  - DELETE
  - DROP
  - ALTER
  - CREATE
  - TRUNCATE
  - MERGE
  - GRANT
  - REVOKE
  - unsafe function calls
  - unbounded raw dumps
  - SELECT *

Every SELECT expression must have a stable alias.

Aliases should be simple:

  - no spaces
  - no punctuation
  - no reserved words
  - preferably PascalCase or snake_case

Widget mappings must exactly match SQL aliases after normalization:

  - x_column
  - y_column
  - label_column
  - value_column
  - value_column_2
  - series_column
  - target_column

Avoid risky WHERE filters unless:

  - the user explicitly requested the filter
  - sample/profile context proves the value exists
  - the filter is required by a KPI/reference definition

Prefer existing saved queries when they already answer the insight.

Use custom SQL when existing saved queries are insufficient.

Default SQL complexity:

  - one SQL statement per widget
  - prefer one or two tables
  - avoid deeply nested SQL
  - avoid CTEs by default for Teiid unless proven reliable
  - use aggregation before joining when needed
  - include validation metadata for complex joins

# 6. Teiid / Text-Backed Data Policy

When the database uses Teiid and project data comes from CSV/file
imports, assume columns may be text-backed even when they represent
numbers or dates.

Rules:

  - Quote table and column names when required by engine syntax.
  - Never use MySQL-only functions such as DATE_FORMAT, MONTH(), or
    YEAR().
  - Use Teiid-compatible date and time functions.
  - For numeric arithmetic, comparisons, SUM, AVG, MIN, MAX, or numeric
    sorting, cast numeric text-backed columns safely.
  - Do not cast categorical labels such as status, type, name, category,
    country, or severity as numbers.
  - For text date columns, parse using the sample format when provided.
  - Do not cast slash dates directly to date unless the engine supports
    it and the sample format proves compatibility.
  - GROUP BY must repeat the full SELECT expression when the engine does
    not support alias references in GROUP BY.
  - Do not use SELECT *.

When unsure whether a text-backed column is numeric, use sample values
and column profile metadata. If numeric status is uncertain, avoid
arithmetic on that column.

# 7. Chart Selection Policy

The chart type must be selected based on the insight and the result
shape.

Supported chart families may include:

  - kpi
  - kpi_grid
  - vertical_bar
  - horizontal_bar
  - stacked_bar
  - grouped_bar
  - line
  - area
  - dual_line
  - pie
  - donut
  - table
  - pivot_table
  - heatmap
  - scatter
  - bubble
  - treemap
  - waterfall
  - funnel
  - gauge
  - bullet
  - radar
  - sparkline_table
  - narrative_insight

Chart rules:

  - Use kpi or kpi_grid for executive headline numbers.
  - Use horizontal_bar for ranked entities with long labels, such as
    suppliers, customers, products, facilities, regions, or categories.
  - Use vertical_bar for compact category comparisons or period
    buckets.
  - Use grouped_bar for side-by-side metric comparison across
    categories.
  - Use stacked_bar for composition across category or time.
  - Use line only for real time/period trends.
  - Use dual_line for two related metrics over the same time grain.
  - Use area for cumulative or volume-over-time patterns.
  - Use pie or donut only for true part-to-whole distributions with 2 to
    8 slices.
  - Use table for operational detail that supports action.
  - Use heatmap for two-dimensional intensity patterns.
  - Use scatter or bubble for relationship/correlation-style
    comparisons.
  - Use gauge or bullet only when an explicit target, threshold, or
    benchmark exists.
  - Use waterfall for variance decomposition or contribution-to-change.
  - Use funnel for stage conversion or drop-off.
  - Use narrative_insight when the finding is document-driven or better
    explained in prose than charted.

Chart correction rules:

  - Convert vertical_bar to horizontal_bar when category labels are
    long.
  - Convert pie/donut to horizontal_bar when slices exceed 8 or ranking
    matters more than share-of-total.
  - Convert line to bar when x-axis is categorical.
  - Convert bar to line when x-axis is a true time period.
  - Reject line charts with fewer than 3 periods unless the user
    specifically requested a small comparison.
  - Reject scatter/bubble charts with too few points.
  - Reject gauge/bullet charts without a target.
  - Reject heatmaps without two dimensions and one numeric measure.
  - Reject stacked/grouped charts without a series column.

# 8. Widget Validation Policy

Every widget SQL must execute before the dashboard is saved.

Drop widgets that:

  - return zero rows
  - return only null metric values
  - have missing configured chart columns
  - have SQL execution errors that cannot be repaired
  - have result shape incompatible with the chart type
  - are duplicate or redundant
  - are technically valid but not business-useful
  - depend on weak or unvalidated joins
  - conflict with KPI definitions
  - imply unsupported causality
  - use guessed reference targets or thresholds

Repair widgets when:

  - the SQL is valid but aliases need normalization
  - chart type should be changed based on result shape
  - x/y/value column mappings can be safely corrected
  - SQL can be fixed with a small engine-compatible repair
  - a better chart subtype can be selected without changing the insight

Recommended repair limits:

  - one SQL repair attempt
  - one chart-mapping/chart-type repair attempt
  - then drop if still invalid

Allow zero values only when zero is meaningful, such as:

  - zero defects
  - zero incidents
  - zero overdue items
  - zero failed inspections

Reject all-zero widgets when the metric is not meaningful or likely
indicates a bad query.

# 9. Join Quality Validation Policy

For every joined widget, validate join quality before approval.

Required checks:

  - join keys exist in both sources
  - join keys are not mostly null
  - sampled values overlap
  - match rate is acceptable
  - row count does not explode after join
  - aggregation prevents one-to-many duplication
  - final result returns meaningful rows
  - relationship claim is phrased accurately

Compare pre-join and post-join row counts when possible.

Reject or warn when:

  - post-join row count is suspiciously inflated
  - match rate is too low
  - too many primary records are dropped
  - join keys have poor overlap
  - many-to-many join is uncontrolled
  - entity grain is ambiguous

Low match rate is allowed only when the insight is specifically about
unmatched records, missing records, or coverage gaps.

# 10. Dashboard Save Policy

A generated dashboard should be saved only when enough widgets survive
validation.

Default save rules:

  - Save only if at least 2 meaningful widgets survive.
  - Target 4 to 8 approved widgets.
  - Save one-widget dashboards only when the user explicitly requests a
    single chart or KPI.
  - Run a second planning pass if too many widgets fail validation.
  - Ask for clarification when fewer than 2 widgets survive and no safe
    replacement is possible.
  - Preserve rejected widget details for debugging.
  - Save validation metadata in the dashboard config.
  - Create an audit log with generated SQL, execution status, row count,
    validation result, and final decision.
  - Produce a dashboard quality score before saving.

The dashboard should be useful even if it has fewer widgets than
requested.

Never save empty dashboards.

Never save dashboards full of weak placeholder charts.

# 11. Recommended Validation Metadata

For each widget, store validation metadata such as:

    {
      "execution_status": "success|failed|repaired|dropped",
      "row_count": 0,
      "columns_returned": [],
      "non_null_metric_count": 0,
      "chart_type_original": "",
      "chart_type_final": "",
      "sql_original": "",
      "sql_final": "",
      "join_used": false,
      "join_confidence": null,
      "join_match_rate": null,
      "row_multiplication_ratio": null,
      "business_usefulness_score": 0,
      "validation_warnings": [],
      "drop_reason": ""
    }

For the overall dashboard, store:

    {
      "ai_generated": true,
      "dashboard_quality_score": 0,
      "approved_widget_count": 0,
      "dropped_widget_count": 0,
      "repair_count": 0,
      "generation_pipeline_version": "insight_first_v1",
      "rejected_insights": [],
      "validation_summary": ""
    }

# 12. Stage-Specific Usage

## Insight Planner

The Insight Planner should use this file to:

  - infer business domain
  - identify high-value business questions
  - detect entities
  - propose relationships
  - align insights with KPI references
  - align insights with reference-library documents
  - rank insights by decision value
  - reject weak or unsupported ideas

The planner should not write final widget SQL unless required by the
current implementation.

## Chart / SQL Builder

The Chart / SQL Builder should use this file to:

  - create safe executable SQL
  - choose chart types
  - use joins only when evidence supports them
  - aggregate detail data before joining
  - map SQL aliases to widget fields
  - include formatting and drilldown metadata
  - reject widgets that cannot be safely queried

## Dashboard Judge / Validator

The Dashboard Judge should use this file to:

  - execute every widget before save
  - validate row counts and metric values
  - validate join quality
  - repair chart mappings when safe
  - change chart type when needed
  - drop empty, weak, misleading, or duplicate widgets
  - preserve validation metadata
  - decide whether the dashboard should be saved
