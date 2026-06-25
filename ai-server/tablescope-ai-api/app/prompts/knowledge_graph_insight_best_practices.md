# Tablescope Knowledge Graph Insight Best Practices

## Purpose

This prompt reference file defines how Tablescope builds an Insight-First
Knowledge Graph.

The Knowledge Graph is not a generic relationship map. It is a business
intelligence map that shows how documents, processes, policies, procedures,
data sources, queries, dashboards, KPIs, risks, opportunities, anomalies,
gaps, and recommendations connect.

The Knowledge Graph should help users answer:

1. Which documents govern this process?
2. Which policies, procedures, or authoritative references support this process?
3. Which KPIs are defined or referenced by documentation?
4. Which data sources, queries, and dashboards measure the process?
5. Which risks, warnings, anomalies, and opportunities are supported by evidence?
6. Which gaps exist because a required policy, procedure, control, KPI, or data
   source is missing?
7. What action should the business take next?

The Knowledge Graph should be built with the same methodology as the AI Home
page and AI Dashboard pipeline:

- evidence-first
- insight-first
- confidence-scored
- tenant/project-scoped
- business-value-driven
- validation-aware
- interactive by selected node

## Core Security Rule

Use only authorized tenant and project context provided by the platform.

Never invent:

- documents
- policies
- procedures
- tables
- columns
- dashboards
- queries
- KPIs
- thresholds
- relationships
- process names
- authoritative standards
- industry rules
- audit requirements
- business claims

A missing document, missing process, missing KPI, or missing data source may
be reported as a gap only when the gap is supported by an authoritative
reference, accepted KPI definition, policy, procedure, industry reference, or
clear project evidence.

## Graph Lenses

The Knowledge Graph supports multiple lenses.

Default lens: `insight-first`

Supported lenses:

- insight-first
- document-centric
- family-centric
- process-centric
- kpi-centric
- audit
- anomaly
- process-improvement
- compliance
- lineage
- evidence
- reference-library

Each lens changes which node becomes central and how surrounding relationships
are prioritized.

### Insight-First Lens

Center the graph around the most important business insight, risk, opportunity,
anomaly, or gap.

Prioritize:

- critical risks
- urgent warnings
- high-impact opportunities
- process gaps
- audit readiness issues
- compliance traceability gaps
- anomaly root causes
- KPI variance
- missing evidence

### Document-Centric Lens

Center the graph around a selected document.

Show: document family, governed processes, referenced entities, supported KPIs,
linked data sources, linked queries, linked dashboards, governing policies,
related documents, insight cards generated from the document's relationships.

### Process-Centric Lens

Center the graph around a selected process.

Show: governing policies, supporting procedures, related documents, KPIs that
measure the process, data sources that provide evidence, queries that calculate
metrics, dashboards that visualize performance, risks/anomalies/opportunities
related to the process, missing controls or documentation gaps.

### KPI-Centric Lens

Center the graph around a selected KPI.

Show: KPI definition, numerator / denominator sources, threshold or target
source, governing document, data source, query, dashboard, related process,
current business insight, missing data or calculation gaps.

## Node Types

Allowed node types:

```
project
document
document_family
reference_document
policy
procedure
standard
process
control
data_source
table
column
saved_query
query
dashboard
kpi
metric
threshold
benchmark
business_entity
supplier
customer
product
facility
contract
risk
warning
opportunity
anomaly
audit_finding
compliance_gap
process_gap
data_gap
gap
relationship_insight
insight
recommendation
action
```

Each node should include:

```json
{
  "graph_key": "",
  "node_type": "",
  "label": "",
  "layer": "evidence|semantic|kpi|insight|action|gap",
  "display_group": "",
  "source_type": "",
  "source_id": null,
  "summary": "",
  "confidence": 0.0,
  "severity": "",
  "business_value": "",
  "is_center_eligible": true,
  "properties": {}
}
```

## Relationship Types

Allowed relationship types:

```
belongs_to_family
references
governs
supports
defines
measures
calculated_from
derived_from
visualizes
uses
feeds
contains
mentions
applies_to
evidence_for
indicates
drives
risk_from
opportunity_from
anomaly_from
gap_from
missing_required_evidence
missing_required_policy
missing_required_procedure
missing_required_kpi
missing_required_datasource
threshold_from
benchmarked_against
linked_by_validated_join
linked_by_inferred_join
recommends
follows_from
mitigates
```

Each edge should include:

```json
{
  "from_node_key": "",
  "to_node_key": "",
  "relationship_type": "",
  "confidence": 0.0,
  "validation_status": "validated|inferred|suggested|gap|rejected",
  "evidence_summary": "",
  "evidence": {},
  "reason": ""
}
```

## Confidence Bands

Use confidence consistently:

```
0.90 - 1.00 = validated / strong
0.80 - 0.89 = strong likely
0.70 - 0.79 = useful but reviewable
0.50 - 0.69 = weak / inferred only
below 0.50  = reject
```

The default graph should show only relationships at or above 0.70 unless the
user enables inferred relationships.

## Layers and Display Groups

Group nodes into the display groups used by the UI so the canvas stays readable:

- `Supporting & Governing Documents`
- `Governing Policies / SOPs`
- `KPIs & Metrics`
- `Queries`
- `Dashboards`
- `Linked Data Sources`
- `Related Processes`
- `Related Entities`
- `Insights / Findings`
- `Recommendations`

Layer maps roughly to:

- `evidence` — documents, policies, procedures, data sources, queries, dashboards
- `semantic` — processes, entities, families
- `kpi` — KPIs, metrics, thresholds, benchmarks
- `insight` — risks, warnings, opportunities, anomalies, gaps, findings
- `action` — recommendations, actions

## Business Insight Card Policy

The right panel should show AI Home-style cards, but generated by the Knowledge
Graph pipeline.

Card categories:

- Knowledge Graph Business Insight
- Knowledge Graph Opportunity
- Knowledge Graph Risk
- Knowledge Graph Warning
- Knowledge Graph Gap
- Knowledge Graph Recommendation

Cards should explain: what the graph discovered, why it matters, evidence
supporting the claim, confidence score, related documents, related data sources,
related queries, related dashboards, related KPIs, and a recommended action.

Each card should include:

```json
{
  "id": "",
  "category": "business_insight|opportunity|risk|warning|gap|recommendation",
  "severity": "critical|urgent|warning|watch|opportunity|info",
  "title": "",
  "summary": "",
  "businessQuestion": "",
  "businessImpact": "",
  "confidence": 0.0,
  "evidencePath": [],
  "sourceDocuments": [],
  "sourceTables": [],
  "sourceQueries": [],
  "sourceDashboards": [],
  "supportedKpis": [],
  "recommendedAction": "",
  "traceToEvidence": {}
}
```

Do not show insight cards that lack evidence. Never invent a risk, opportunity,
warning, process gap, KPI, threshold, or policy requirement.

## Gap Detection Policy

The Knowledge Graph should identify gaps when authoritative evidence suggests a
process, control, KPI, data source, dashboard, or document should exist but is
missing or weakly supported.

Use only authorized evidence from: Reference Library documents, company
policies, procedures, SOPs, standards, audit requirements, accepted KPI
definitions, and industry best-practice references included in the authorized
Reference Library.

Gap types:

```
missing_process
missing_policy
missing_procedure
missing_control
missing_kpi
missing_datasource
missing_query
missing_dashboard
missing_evidence
weak_evidence
stale_documentation
unsupported_claim
low_confidence_relationship
```

For every gap return:

```json
{
  "gap_id": "",
  "gap_type": "",
  "title": "",
  "severity": "",
  "why_it_matters": "",
  "authoritative_source": "",
  "expected_evidence": "",
  "missing_or_weak_component": "",
  "affected_processes": [],
  "affected_kpis": [],
  "recommended_action": "",
  "confidence": 0.0
}
```

Do not infer a gap from generic best practice unless the best-practice reference
is present in the authorized Reference Library or provided project evidence.
Only create a gap node when there is clear evidence. Gap nodes should be
visually represented as warning or alert nodes in the graph and should connect
to the authoritative source requiring the item, the process or KPI affected, the
missing evidence category, and the recommended action.

## Selected Node Re-Centering Policy

Every graph node is an entry point into a new graph neighborhood. Every node
must be clickable.

When a user selects a node:

1. The selected node becomes the center of the graph.
2. The graph lens changes to the most appropriate lens for that node type.
3. The Knowledge Graph pipeline builds or retrieves a node-centered neighborhood.
4. The right panel updates with AI Home-style business insight cards specific to
   the selected node.
5. The graph shows only the most relevant, highest-confidence relationships first.
6. The user can expand additional lower-confidence relationships if desired.

Do not show a generic project graph when the user selected a specific document,
process, KPI, query, dashboard, data source, risk, opportunity, or business
entity.

Examples:

- Click document → document-centric graph
- Click process → process-centric graph
- Click KPI → kpi-centric graph
- Click dashboard → dashboard-lineage graph
- Click risk → insight-first evidence graph
- Click gap → gap-to-evidence graph

## Trace to Evidence Policy

Every insight, risk, opportunity, warning, anomaly, recommendation, and gap must
support Trace to Evidence.

Trace to Evidence should highlight paths from the selected insight/card to:
authoritative document, governing policy, supporting procedure, KPI definition,
data source, query, dashboard, business entity, recommendation/action.

Trace paths should be stored as ordered node keys and edge ids. Dim unrelated
nodes and show confidence values on highlighted edges.

## Pipeline

The Knowledge Graph follows the same architecture pattern as the AI Home page:

```
Project Evidence Collection
        ↓
Deterministic Graph Builder
        ↓
AI Graph Pipeline (optional enrichment)
        ↓
Graph Validator / Judge
        ↓
Graph Persistence
        ↓
Interactive Knowledge Graph UI
```

The system should not rely only on AI. Build a deterministic graph from known
project records first, then use AI to enrich and prioritize, then validate the
output before displaying or saving it.

### Stage 1: Node Neighborhood Evidence Collector

Collect only the evidence relevant to the selected center node and current lens:
center node, candidate nodes/edges, source documents/tables/queries/dashboards,
related KPIs, related entities, authoritative references, existing home/dashboard
insights, and evidence gaps.

### Stage 2: Node-Centric Graph Builder

Build the graph neighborhood around the selected node. Put the selected node at
the center, choose related nodes by lens and confidence, group nodes into display
groups, preserve only meaningful relationships, create insight nodes only when
connected to evidence, create gap nodes only when supported by authoritative
reference evidence, create recommendation nodes when there is a clear supported
action, and do not include disconnected nodes.

### Stage 3: Knowledge Graph Business Insight Card Generator

Generate right-side AI Home-style cards for the selected center node, scoped to
the selected node and its neighborhood. Every card must trace to evidence.

### Stage 4: Gap Detector

Detect missing or weak processes, documents, controls, KPIs, queries,
dashboards, and evidence based on authoritative sources.

### Stage 5: Graph Judge / Validator

Validate nodes, edges, insights, and gaps before display. Reject unsupported
insight cards, reject gap claims without authoritative support, reject
low-confidence relationships below the current threshold, deduplicate nodes and
cards, ensure every insight card can trace to evidence, and ensure every
displayed gap has a recommended action.

## Output Contract for UI

The backend should return:

```json
{
  "centerNode": {},
  "nodes": [],
  "edges": [],
  "insightCards": [],
  "gaps": [],
  "recommendedActions": [],
  "tracePaths": [],
  "stats": {},
  "generated_at": "",
  "pipeline_version": "knowledge_graph_node_centric_v2"
}
```

The UI should render: left graph controls, center interactive graph canvas,
right AI Home-style insight cards, a legend, and the Trace to Evidence
interaction. Keep backward compatibility with the current `nodes` and `edges`.

## Reference Library vs. Project Evidence (Authoritative Guidance Rule)

Reference Library documents are authoritative guidance, not live project datasource records.

Use reference documents to define standards, benchmarks, policy requirements, expected controls, and thresholds only when explicitly stated.

Do not use Reference Library documents as SQL query sources.

Do not create critical, urgent, risk, anomaly, or breach findings from reference documents alone. A risk or breach requires project-specific evidence such as data, documents, dashboards, queries, or validated graph relationships.

For empty tenants or projects with no relevant data, return an info/watch guidance card instead of a critical finding (for example: "Reference guidance available; add project data to assess compliance").
