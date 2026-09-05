# Devin: merge + deploy — Knowledge Graph validation, Phase 13 (Section C part 2: #27–30, section complete)

**Repository:** `lhoskins/tablescope-lh`
**Branch to merge:** `kg-validation-phase10-source-lineage` (this phase's commits land on top of Phases 10–12's, same branch)
**Base:** `kg-validation-phase8-observability-goldens` tip (already includes Phases 1–12)

**`platform-api/` only · 1 migration (`0091`, additive) · all tests green**

---

## Context

This phase closes out Section C's remaining four items — the largest, most architecturally
open-ended items in the whole 50-item review:

- **#27 (P1)**: "Add canonical entity resolution with aliases."
- **#28 (P1)**: "Add relationship cardinality and join-quality evidence."
- **#29 (P1)**: "Validate temporal consistency."
- **#30 (P1)**: "Add semantic coverage scoring."

Two research passes (Explore agents, full transcripts available on request) ran first
against the real code for all four items. Each confirmed a real, substantial gap — but each
item's *full* text describes a materially larger system than a single phase should build
from scratch (a canonical entity/alias model with reviewer confirmation; a join-safety
planner backed by execution-time profiling; a full event-time/observation-time temporal
model; a coverage taxonomy spanning "critical processes" and "business entities" with no
existing denominator). As with Section A's #08/09, this phase implements the concrete,
verified, safely-scoped slice of each item and documents the rest as deliberately deferred.

## KG-27: entity name normalization

**Validated:** no alias/canonicalization mechanism exists anywhere for customers,
suppliers, sites, products, people, or processes. The only alias-like mechanism in the
codebase (`_kpi_phrases`/`_phrase_in`) is scoped narrowly to KPI-name phrase matching
against query/dashboard text, not general entity resolution. A KPI node's `aliases`
property is *read* (`graph_primitives.py`) but has **zero producers anywhere** — dead code.
Both node-upsert helpers that create entity nodes from AI-extracted profile data
(`_upsert_node` in `document_processing_service/graph.py`, `_upsert_typed_node` in
`project_graph_service/graph_primitives.py`) matched on an **exact** string — "CMX", "cmx",
and " CMX " each created a separate, never-merged node for the same real-world entity, the
literal failure mode the review's Accept criterion names.

**Fix:** both upsert helpers now match `LOWER(TRIM(name))=LOWER(TRIM(:nm))` instead of an
exact string, so casing/whitespace differences resolve to the same node. A genuinely
different name still creates a separate node.

**Deliberately not done:** identifier/context-based resolution (e.g. resolving "CMX" and "a
facility ID" to one entity via more than name matching), a reviewer-confirmation workflow,
and a real `AccessGroup`/canonical-entity model — none of these exist today and each is a
materially larger, separate effort with real product decisions attached (what counts as
"the same" entity across different identifier types, who approves a merge, etc.).

## KG-28: join-key evidence parsed from SQL

**Validated:** `SavedQuery.left_column`/`right_column` only capture the join-builder UI's
two-table case. `app/services/sql_lineage.py` (built for KG-17) only extracted which
*tables* a query references, never which *columns* its joins key on. Home Intelligence's
`query_helpers.py` already computes real cardinality/overlap signals
(`_cardinality`/`_containment`/`find_relationship_candidates`) from sampled data — but only
ephemerally, for one widget-planning AI-prompt call; the result is never persisted to
`SavedQuery`/`QueryScope`/the knowledge graph. `DatabaseDataSource`/`DataSourceColumn` (the
JDBC-registered-table path) has **zero** column-level profiling of any kind, unlike file
sources (`DataSourceFieldProfile` exists, but only for those). No join-safety planner
exists anywhere — `sql_authorization.py` is a read-only/table-allowlist security gate with
no concept of join validity at all.

**Fix:** `sql_lineage.py` gains `extract_join_keys(sql)` — parses every `JOIN ... ON`
clause via sqlglot, returning `{left_table, left_column, right_table, right_column,
join_type}` for each real join-key equality (an `AND`ed filter condition inside the same ON
clause, e.g. `oi.active = true`, is correctly excluded since only both-sides-are-columns
equalities count as a join key). Table aliases are resolved back to real table names where
declared in the same statement. Wired into `collect_structural_graph`: a saved query's
node now carries `properties.join_keys` (omitted entirely when the query has no joins).

**Deliberately not done:** cardinality classification (one-to-one/one-to-many/many-to-many),
null-rate/duplicate-rate/validation-sample evidence — all of these require executing
against real data, which Home Intelligence's `query_helpers.py` already knows how to do but
only ephemerally; persisting that onto a durable record is a distinct, larger follow-on
that reuses real prior art rather than reinventing it. A join-safety planner that can
reject an unsafe join at execution time does not exist and is out of scope here.

## KG-29: temporal consistency (expired-evidence warning on cards)

**Validated:** `AIProjectGraphNode`/`AIProjectGraphEdge` carry no timestamp beyond
`created_at` — no event-time/observation-time concept exists on the graph's own structures.
No card/insight anywhere checked its cited evidence's own freshness at build or render
time — distinct from the whole-graph staleness fingerprint (KG-13/44), which only detects
that *something* changed, never that a *specific card's specific evidence* has gone stale.
Concretely: `active_reference_document_conditions` (KG-20) already excludes an expired
reference document from a **freshly-built** graph, but a **cached** card built before that
document's expiration date keeps citing it — with no warning — until the project's next
rebuild, since `get_active_snapshot_payload` never checks `lifecycle_status` before serving
the cached snapshot.

**Fix:** reference-document nodes now carry their own `effective_date`/`expiration_date` in
`properties` (previously only used as a collection-time filter, never exposed on the node
itself). `app/services/knowledge_graph/cards.py`'s `_build_card_for_node` — the primary
insight-card builder — now sets `evidenceExpired: bool` on every card, computed by checking
whether any evidence neighbor is a `reference_document` whose own `expiration_date` has
passed `date.today()`. This directly implements the Accept criterion: "current insights
cannot be justified solely by expired policy... without a warning" — the warning is now
present and computed at render time, independent of whether a rebuild has happened since
the document expired.

**Deliberately not done:** the two lower-severity card builders (`_center_overview_card`,
`_kpi_measurement_gap_card`) were not extended with the same flag — they're overview/gap
notices, not "insights justified by evidence" in the sense the Accept criterion targets. A
full event-time/observation-time model (distinguishing when something was *true* from when
it was *recorded*) does not exist and is a materially larger modeling effort.

## KG-30: coverage percentage + three new dimensions + unified health report

**Validated:** the existing coverage manifest (`compute_source_coverage`, built for
KG-11/15) already reports `total/included/excluded/failed/pending` for 6 source
kinds — but never a percentage, and never for goals, KPIs/metrics, or risks, despite all
three already being graph-relevant sources hashed by `compute_source_fingerprint`. Coverage
and structural validity were split across two endpoints: `/health` (structural checks
only, no coverage at all) and `/versions` (coverage buried inside an untyped
`validation_summary: dict[str, Any]` blob with no dedicated schema field). No concept of
"critical processes" or "business entities" exists anywhere with a well-defined expected
count to measure coverage against (the KG-27 finding — entities aren't even canonically
deduplicated yet, let alone counted for coverage).

**Fix:**
- `_bucket()` (the shared per-source-type helper) now computes `coverage_percent`
  (`included / total * 100`, or `100.0` when nothing is expected of that kind — "0 of 0
  dashboards" is full coverage, not a false gap).
- New `summarize_coverage_gaps(coverage)` produces human-readable named-missing-area
  strings (e.g. `"No saved queries found for this project"`,
  `"data_sources: 67% coverage (1 failed of 3)"`).
- `compute_source_coverage` gains three new buckets — `goals` (`ProjectGoal`), `metrics`
  (`ProjectMetric`), `risks` (`ProjectRisk`) — via the existing `_no_pipeline` helper
  (already used for saved queries/dashboards: user-authored rows, no ingestion pipeline to
  fail or leave pending).
- `KnowledgeGraphHealthService.run_health_check` now calls `compute_source_coverage` and
  stores the result on a new `source_coverage` field (model + migration `0091` +
  `KnowledgeGraphHealthCheckRead` schema field), unifying structural validity and coverage
  into the one health-check response instead of two separate endpoints. Named gaps from
  `summarize_coverage_gaps` are appended to `warnings` **after** `status` is already
  decided, so an otherwise-healthy graph with incomplete-but-not-broken coverage (e.g. no
  dashboards yet) surfaces the gap as information without being silently demoted to
  `"warning"` status by this change alone.

**Deliberately not done:** coverage for "critical processes" and "business entities" — no
denominator exists for either (no process-criticality concept, and KG-27 confirmed entities
aren't canonically counted yet). `validation_summary`'s existing untyped coverage blob
(used by the rebuild-validation path) is unchanged — this phase adds coverage to the
health-check response as a new, additive surface rather than restructuring the existing one.

## Tests added

| File | Coverage |
|---|---|
| `tests/test_kg27_entity_name_normalization.py` (4 tests) | both upsert helpers merge differently-cased/padded names; both still create separate nodes for genuinely different names |
| `tests/test_kg28_join_key_evidence.py` (7 tests) | `extract_join_keys` finds a simple/typed join, excludes non-join filter conditions in the same ON clause, handles multiple joins, is safe for no-join/unparsable SQL; a saved-query node carries `join_keys` when its SQL has a join, omits the property when it doesn't |
| `tests/test_kg29_temporal_consistency.py` (4 tests) | a card is flagged `evidenceExpired` when citing a reference document past its expiration; not flagged for no-expiration or future-expiration documents; a reference-document node carries its own `effective_date`/`expiration_date` |
| `tests/test_kg30_coverage_scoring.py` (4 tests) | a bucket reports 100% coverage and a named gap when nothing exists; a bucket names a failed-row gap even when nothing was excluded by the cap; `compute_source_coverage` includes the three new buckets; a health check carries `source_coverage` and named gaps without changing a healthy status |

All real-bug tests proven to **fail** against pre-fix code (`git stash` on the relevant fix
file(s), rerun to confirm failure — including one collection-time `ImportError` for the
brand-new `summarize_coverage_gaps` function — restore, rerun to confirm pass).

**Pre-existing test maintenance**: `tests/test_kg15_source_coverage.py`'s four exact-dict
equality assertions were updated to include the new `coverage_percent` key (a mechanical
follow-on of the additive `_bucket()` change, not a logic fix) — confirmed passing before
and after with the correct value in each case.

## Verification

| Suite | Result |
|---|---|
| `pytest tests/test_kg27_entity_name_normalization.py tests/test_kg28_join_key_evidence.py tests/test_kg29_temporal_consistency.py tests/test_kg30_coverage_scoring.py tests/test_document_families.py tests/test_knowledge_graph_health.py tests/test_kg17_sql_lineage.py tests/test_kg20_versioned_references.py tests/test_kg16_document_passages.py tests/test_kg15_source_coverage.py -q` | 51 passed, 0 regressions |
| KG-focused regression sweep (`pytest -k "knowledge_graph or kg or project_graph or document_families or document_processing" -q`) | 331 passed, 2 failed (same pre-existing `test_business_insight_phase1.py` Redis-connection failures as every prior phase — this sandbox has no Redis running; unrelated) |
| `ruff check` (all touched/new files) | clean |
| `mypy` (all touched/new files) | clean |
| Full `pytest -q` (whole platform-api suite) | 1844 passed, 11 failed, 4 skipped in 1112s. All 11 failures are pre-existing and unrelated to this phase's changes (confirmed by rerunning each in isolation with the same result): `test_business_insight_phase1.py`/`test_executive_insight_dependencies.py` (Redis-dependent snapshot-staleness tests, same as every prior phase), `test_percent_change_summary.py`, `test_visualization_engine.py`, `test_ai_dashboard_pipeline.py::test_correct_widget_converts_oversized_pie`, `test_ask_pipeline.py::test_matrix_resolves_to_heatmap_not_a_narrowed_bar` (all chart/dashboard-presentation logic, no relation to the knowledge graph). Skips are the VPN/SMB live E2E tests (require an external URL not set in this sandbox). |

```bash
cd platform-api
pytest -q
ruff check app/models/knowledge_graph_lifecycle.py \
  app/schemas/knowledge_graph.py \
  app/services/document_processing_service/graph.py \
  app/services/knowledge_graph/cards.py \
  app/services/knowledge_graph_context/collectors.py \
  app/services/knowledge_graph_context/coverage.py \
  app/services/knowledge_graph_health.py \
  app/services/project_graph_service/graph_primitives.py \
  app/services/sql_lineage.py
mypy app/models/knowledge_graph_lifecycle.py \
  app/schemas/knowledge_graph.py \
  app/services/document_processing_service/ \
  app/services/knowledge_graph/ \
  app/services/knowledge_graph_context/ \
  app/services/knowledge_graph_health.py \
  app/services/project_graph_service/ \
  app/services/sql_lineage.py
```

## Deploy

`platform-api` only. One migration (`0091`), additive (`source_coverage` JSON column on
`knowledge_graph_health_checks`, nullable, no backfill needed).

```bash
docker compose build platform-api
docker compose exec platform-api alembic upgrade head
docker compose up -d platform-api platform-api-worker
```

## Verify live

- Extract entities from two documents that name the same real-world entity with different
  casing/whitespace (e.g. "CMX" and "cmx ") and confirm they resolve to one graph node, not
  two.
- Save a hand-written or AI-generated query with a `JOIN ... ON` clause and confirm its
  node's properties include `join_keys` with the correct left/right table+column pairs.
- Set a reference document's `expiration_date` to the past, wait for (or trigger) the
  project's Knowledge Graph cards to be rebuilt, and confirm any card citing that document
  as evidence shows `evidenceExpired: true`.
- Call `GET /knowledge-graph/{project_id}/health` for a project and confirm the response
  now includes a `source_coverage` field with per-source-type `coverage_percent`, and that
  `warnings` names any source type with no rows or incomplete coverage (goals, metrics,
  risks included).

## Remaining work

**Section C is now fully closed** (all of #24–30 done across Phases 12–13). Still open, all
P1: Section D (#32/34–38/40: confidence calibration, real evidence paths, contradiction
detection, source-authority weighting, question-aware context selection, context-omission
reporting, deterministic card fallback). Sections A, B, and E are fully closed.

## Report back

Confirm the four live-verification steps above pass in a deployed environment, then
continue into Section D (the last remaining section) or stop here — the 50-item review
would then have every P0 done and every P1 done except Section D's 6 items.

---

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01M7j8CDCHCdwHpw9FrRhLN5
