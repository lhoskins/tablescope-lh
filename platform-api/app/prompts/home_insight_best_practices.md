# Tablescope AI Home Insight Best Practices

## Purpose

This reference file defines the methodology for generating richer AI
Insight Home page cards.

The Home page format must remain intact. These rules improve the
intelligence behind the cards without changing the user experience.

The Home page should continue to show concise, useful insight cards
with:

  - risks
  - opportunities
  - trends
  - relationship insights
  - compliance or policy signals
  - critical / urgent / warning / watch / opportunity / info severity
    categories
  - short summaries
  - optional chart data
  - optional callouts
  - feedback-ready insight content
  - source references

The goal is to make the Home page insights deeper, more
business-relevant, and more evidence-grounded, using the same
methodology now used for AI-generated dashboards.

# Core Principle

The Home Insight system should not simply run a few fixed checks.

It should reason in this order:

1.  What projects and data sources are available to this user?
2.  What business domain does each project appear to represent?
3.  What risks, opportunities, trends, or relationship signals are most
    important?
4.  What KPI references or Reference Library standards apply?
5.  What live data can prove or disprove the insight?
6.  What evidence supports the severity level?
7.  What concise Home card best communicates the finding?
8.  Should the insight be shown, skipped, repaired, or rejected?

The AI should generate fewer high-value insights instead of many shallow
or generic insights.

# Security and Scope Rule

Use only authorized tenant/project context provided by the platform.

Allowed context may include:

  - accessible projects
  - project tables and columns
  - saved queries
  - dashboards
  - project documents
  - Reference Library documents
  - accepted KPI references
  - accepted tags
  - relationship metadata
  - scope metadata
  - table samples
  - executed query results
  - data quality indicators

Never use or infer data from another tenant or project unless the user
has explicit access and the Home service intentionally performs a
cross-project summary.

Cross-project synthesis must use only approved summary metadata or
already-produced insight summaries. It must not mix raw project data
across tenants or unauthorized projects.

Do not invent:

  - tables
  - columns
  - KPI definitions
  - thresholds
  - relationships
  - document facts
  - reference-library standards
  - sample values
  - benchmark values
  - severity levels unsupported by evidence

# Preserve Existing Home Page Format

Do not change the Home page layout or visual design.

The system should continue returning card-compatible objects with fields
such as:

  - id
  - projectId
  - projectName
  - projectColor
  - insightType
  - severity
  - title
  - summary
  - chart
  - callout
  - sources
  - executedAt

Additional metadata may be added only if backward-compatible, such as:

  - confidenceScore
  - priorityScore
  - insightMethod
  - evidence
  - validation
  - kpiReferences
  - referenceDocuments
  - relationshipMetadata
  - rejectedReason

The current visual categories and severity system should remain intact.

Recommended severity values:

  - critical
  - urgent
  - warning
  - watch
  - opportunity
  - info

Recommended insight types:

  - risk
  - opportunity
  - trend
  - relationship
  - compliance
  - bottleneck
  - concentration
  - dependency
  - data_quality
  - narrative

# Insight Selection Policy

The Home page is not a full dashboard. It should show the most valuable
few insights.

Default behavior:

  - Prefer 3 to 8 high-value cards across accessible projects.
  - Prefer quality over quantity.
  - Show the strongest risk/opportunity/trend signals first.
  - Avoid weak, generic, or repetitive cards.
  - Do not show a card unless there is evidence.
  - Skip prompts that are not supported by the project data.
  - Avoid filling empty space with low-confidence insights.

Each insight should answer:

  - What happened?
  - Why does it matter?
  - How serious is it?
  - What evidence supports it?
  - What project/table/document produced it?
  - What action might the user consider next?

# Business Domain Inference

For each project, infer the likely business domain from:

  - project name
  - table names
  - column names
  - saved query names
  - document summaries
  - accepted tags
  - accepted KPIs
  - Reference Library matches
  - relationship metadata

Possible domains include:

  - supplier performance
  - procurement
  - sales
  - finance
  - manufacturing
  - quality
  - delivery / logistics
  - operations
  - compliance
  - contracts
  - healthcare
  - customer support
  - asset management
  - HR / workforce
  - IT operations

The inferred domain should guide which insights are considered valuable.

If the user or project context clearly indicates a domain, prefer that
over generic inference.

# KPI and Reference Library Policy

KPI references should be treated as preferred metric definitions when
available.

Reference Library documents may define:

  - thresholds
  - SLA limits
  - compliance requirements
  - benchmark ranges
  - risk definitions
  - quality standards
  - financial targets
  - policy requirements
  - operational expectations

Use Reference Library values only when they are explicit in the
authorized context.

Do not invent thresholds.

If a Reference Library document says on-time delivery should be at least
98%, the Home insight may compare actual project data to that target.

If the reference document is relevant but the required data is missing,
the system may create a narrative or data gap insight instead of a
numeric claim.

Each KPI-backed or reference-backed insight should include:

  - KPI/reference name
  - source document title where applicable
  - metric definition
  - whether the metric is directly computable, partially computable, or
    not computable
  - evidence columns
  - confidence score

# Multi-Table Relationship Policy

Home insights should support multi-table analysis when evidence supports
it.

Preferred relationship evidence:

1.  Existing Tablescope relationship/scope metadata.
2.  Explicit key metadata.
3.  Exact matching key names across tables.
4.  Strong semantic match plus sampled value overlap.
5.  User-provided or project-provided relationship hints.

Do not join tables only because their names seem related.

Valid relationship insights may include:

  - high-spend suppliers with poor quality
  - suppliers with rising defect rates
  - customers with declining revenue and rising support cost
  - products with strong sales but poor margin
  - facilities with high output and high incident rate
  - contracts expiring for high-value suppliers
  - concentration risk by supplier, customer, product, or region
  - single-source dependency
  - delivery delay vs. supplier risk
  - budget variance by project or department

For every multi-table insight, capture:

  - left_table
  - right_table
  - left_join_key
  - right_join_key
  - relationship_type
  - join_confidence
  - confidence_reason
  - row_multiplication_risk
  - validation_status

Default maximum join depth is two tables.

Allow three or more tables only when confidence is high and the business
value is clear.

Avoid many-to-many joins unless there is a bridge table or controlled
aggregation.

Aggregate detail rows before joining to master/entity tables when
needed.

# Query and Validation Policy

Every data-backed insight should be based on live query execution when
possible.

Before showing an insight card:

  - execute the query safely
  - verify that rows are returned
  - verify required metric values are non-null
  - verify joins did not multiply rows unexpectedly
  - verify chart data is compatible with the card chart type
  - verify the severity level is supported by the result
  - verify the summary does not overstate the evidence

Skip or reject insights that:

  - return zero rows
  - return only null values
  - depend on missing columns
  - depend on weak joins
  - use guessed filter values
  - use guessed thresholds
  - conflict with KPI definitions
  - imply causation without evidence
  - duplicate another stronger insight

Allow zero values only when zero is meaningful, such as:

  - zero defects
  - zero incidents
  - zero overdue items
  - zero failed inspections

# Severity Classification Policy

Severity must be evidence-based.

Use `critical` when:

  - a metric is far outside a known threshold
  - a risk is immediate and high impact
  - compliance failure is likely
  - contract/SLA breach is severe
  - high-value entity is materially underperforming

Use `urgent` when:

  - action is needed soon
  - threshold is breached but not catastrophic
  - upcoming deadline or expiry is near
  - operational risk is increasing quickly

Use `warning` when:

  - risk is emerging
  - trend is deteriorating
  - benchmark variance is meaningful
  - relationship analysis shows concern

Use `watch` when:

  - metric is close to threshold
  - early signal exists but confidence is moderate
  - trend should be monitored

Use `opportunity` when:

  - savings, improvement, growth, optimization, consolidation, or
    automation opportunity is supported

Use `info` when:

  - insight is useful context but not a risk or opportunity

Do not inflate severity to make insights look more important.

# Chart and Callout Policy

Home insight cards should remain concise.

Use small chart payloads only when they add value.

Good Home chart types:

  - kpi
  - kpi_grid
  - bar
  - horizontal_bar
  - line
  - mini_trend
  - sparkline
  - table
  - list
  - bullet
  - gauge
  - narrative

Chart rules:

  - Use horizontal_bar for ranked entities with long labels.
  - Use line or mini_trend for time-based movement.
  - Use kpi or kpi_grid for headline numbers.
  - Use bullet/gauge only with explicit target or threshold.
  - Use table/list for expiring contracts, top risks, or exceptions.
  - Do not include chart data if the chart would be empty or misleading.
  - Keep Home charts lightweight; deeper visuals belong in dashboards.

Callouts should be used for:

  - threshold breaches
  - urgent risk
  - opportunity recommendation
  - compliance note
  - KPI variance
  - high-value relationship finding

Callouts should be short, action-oriented, and evidence-backed.

# Insight Summary Writing Policy

Summaries should be concise, direct, and useful.

Each summary should include:

  - the key metric or finding
  - the relevant entity or project
  - the benchmark/threshold if applicable
  - the business implication
  - a suggested next step when appropriate

Use strong but careful language.

Preferred wording:

  - “appears to”
  - “is associated with”
  - “compared with”
  - “based on available project data”
  - “this may indicate”
  - “worth reviewing”

Avoid unsupported language:

  - “caused by”
  - “proves”
  - “guarantees”
  - “definitely”
  - “always”
  - “never”

Do not overstate statistical certainty.

# Feedback and Learning Policy

Home insight cards should support feedback and future tuning.

For each card, store enough metadata to learn from:

  - why this insight was selected
  - evidence source
  - query used
  - severity rationale
  - confidence score
  - priority score
  - rejected alternatives when available
  - user feedback when provided

User feedback should help tune:

  - insight type preferences
  - severity calibration
  - domain-specific KPI choices
  - preferred chart/card types
  - ignored or dismissed insight types
  - useful vs. noisy insights

Do not change the visible format unless explicitly requested.

# Recommended Home Insight Pipeline

## Stage 1: Project Evidence Collection

Collect authorized context:

  - tables
  - columns
  - sample values
  - documents
  - Reference Library documents
  - accepted KPIs
  - saved queries
  - existing dashboards
  - relationships/scopes

## Stage 2: Insight Candidate Planning

Generate candidate insights by category:

  - risk
  - opportunity
  - trend
  - relationship
  - compliance
  - concentration
  - dependency
  - bottleneck
  - data quality

Each candidate should include:

  - business question
  - required data
  - required relationship
  - KPI/reference support
  - expected severity
  - expected result shape
  - confidence estimate

## Stage 3: Live Query Execution

Run safe, bounded SQL for data-backed candidates.

Validate:

  - row count
  - non-null metric values
  - join quality
  - result shape
  - threshold comparison
  - chart/card compatibility

## Stage 4: Card Selection

Rank by:

  - severity
  - business value
  - confidence
  - freshness
  - KPI/reference support
  - user relevance
  - cross-project importance

Select only the strongest cards.

## Stage 5: Card Rendering

Return existing Home-compatible card format.

Add optional metadata only if backward-compatible.

# Minimum Quality Rules

Do not show a Home insight card unless:

  - it is supported by live data or authorized document/reference
    evidence
  - it has a clear business implication
  - its severity is justified
  - it is not duplicative
  - it fits the current Home card format

Prefer no card over a weak card.

Never fabricate an insight.
