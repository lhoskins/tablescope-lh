# Devin-ready plan: split every file over 500 lines into focused sibling files

## Scope and methodology

Source: the repo-wide line-count audit (115 files over 500 lines, 49.68% of all
scanned source lines) supplied by the user, covering `platform-api`, `web-ui`,
`ai-server`, `apache-maven-3.9.6` (the Teiid VDB-management Java servlets),
`scripts`, `tests`, and `docs`.

**This plan does not reduce code.** Every split moves existing logic verbatim
into new sibling files; the original filename either becomes a thin
re-export/aggregator ("shim") or is deleted in favor of a package `__init__`
that re-exports everything, so **no other file's import statement has to
change** except where a phase explicitly calls that out.

Every file/module boundary proposed below was produced by seven parallel
codebase audits that actually read each file (grepped `class`/`def`/`@router`
boundaries, traced cross-file imports via grep, and — for the two already-split
precedents — read the actual diff) rather than guessed from filenames. Where an
audit flagged a file as not worth splitting further ("skip candidate"), that
judgment is carried forward with a lighter recommendation rather than forcing
an arbitrary cut, but every file from the source audit is still addressed
somewhere in this plan per your instruction to break everything down, not
leave anything out.

**Two things are deliberately excluded from the file-by-file phases below,
flagged instead in "Explicitly deferred" at the end:** the two seed-data JSON
files (`catalog.json`, `source_taxonomy.json` — 25k/5k lines of data, not
logic) and the standalone `docs/*.md`/prompt `.md` files. Splitting those
carries none of the "code that can break" risk this plan is designed to
sequence around, and JSON seed-data specifically would require a loader
change to reassemble multiple files — a different, smaller, lower-priority
task you can pick up any time independent of this plan.

## Conventions (apply in every phase)

**Python services (free-function files).** Precedent: `knowledge_graph_builder.py`
(1653→137 lines) was split into a package `app/services/knowledge_graph/` with
`loader.py`/`classifier.py`/`cards.py`/`snapshot.py`/`renderer.py`, and the
original filename kept as a re-export shim covering **every public and
private (`_foo`) name any other file reaches into** (commit `da7ae704`).
Follow this exactly: create a package directory, move functions into
responsibility-grouped sibling modules, and make the original filename either
a `package/__init__.py` or a thin shim file that does
`from .module_a import name1, name2, ...` for the full external-import
surface (verified per-file below via grep, not assumed).

**Python services (one large class dominates the file).** `project_context.py`
(`ProjectContextService`), `knowledge_graph_lifecycle.py`
(`KnowledgeGraphLifecycleManager`), and `ai_governance.py`
(`AIGovernanceService`) don't fit the free-function pattern — external callers
import *the class*, not individual methods. Use mixin composition instead:
split the class's methods into responsibility-grouped mixin classes in sibling
files, then recompose in the original file:
```python
class ProjectContextService(GoalsMixin, MetricsMixin, RisksMixin, CoreMixin):
    pass
```
This keeps the class's name, method surface, and import path identical for
every external caller.

**FastAPI routers.** Two sub-patterns, chosen per file based on how exposed
its private helpers are:
- **`ai_proxy.py` (platform-api) and `ai.py` (ai-server)** — both have private
  helpers reached into directly by other production files (not just tests).
  Keep the original filename as a thin **parent aggregator**: it builds
  `router = APIRouter(...)`, imports each feature's own `APIRouter` and does
  `router.include_router(sub_router)` for each, and re-exports the specific
  private helpers other production files import. This means `main.py` needs
  **zero changes** for these two files.
- **The other 15 platform-api route files** — per the routes audit, none of
  them has a private-name external importer besides `app/main.py`, which
  already lists every router individually
  (`app.include_router(x_routes.router, prefix=api_prefix)`). For these,
  split into sibling `APIRouter` files and add one `include_router` line per
  new sub-router directly in `main.py`, matching its existing style, rather
  than adding another layer of shim indirection.

**TypeScript/React components.** No prior precedent in this repo for `.tsx`
splits — use standard conventions: extract subcomponents to sibling
`ComponentName-Part.tsx` files, extract hooks to `use-thing.ts`, extract pure
helpers to `component-name-utils.ts`, extract types to
`ComponentName.types.ts`, and leave the original file as the orchestrating
container. **Never split apart a cluster of `useState` calls that read/write
each other** — several files below are flagged explicitly as
"state-machine, extract only presentational JSX / pure helpers, not state."

**TypeScript lib/data modules** (`chartRegistry.ts`, `lib/api/home-intelligence.ts`,
`lib/ui/use-project-data.ts`). Convert to a directory with an `index.ts`
barrel that re-exports every submodule, so all existing
`import { X } from "@/lib/..."` call sites — of which there are dozens for
these three files — need zero changes.

**Java servlets.** All 21 classes in this Maven project sit in one flat
package, `cloud.tablescope` — new helper classes follow that same
flat-package convention (there's already precedent: `TxtFileProcessor.java`,
`VDBLockManager.java` are existing extracted helpers). Static-friendly helpers
(pure string/XML building, no instance field dependency) become plain classes;
methods that depend on instance fields (`teiidAdminUser`, `teiidAdminPassword`,
`vdbBasePath`) get extracted into helper classes that take those values via
constructor. **Deployment mechanic is fundamentally different from every other
phase**: `wildfly/standalone/deployments/TeiidExcelImporterTest.war` is a
~37MB binary checked into git. Every Java change in this plan requires
`mvn package` under
`apache-maven-3.9.6/MyProject/project-TeiidExcelImporterTest/`, then
committing the rebuilt WAR and redeploying to WildFly — not a plain file save.
Treat Phase 7 as needing its own deploy/rollback checklist, separate from the
Python/TS phases.

**Every phase, without exception:**
1. Split the files listed.
2. Run the full existing test suite for that module (`platform-api`: pytest;
   `web-ui`: vitest/tsc; `ai-server`: pytest; Java: `mvn test` + `mvn package`).
3. Confirm every external import path identified below still resolves (grep
   for the old private/public names across the repo one more time post-split
   — the audits below are a snapshot, re-verify before merging).
4. Deploy and smoke-test the specific user-facing flow that phase touches
   (see each phase's "smoke test" line) before starting the next phase.
5. One phase = one PR. Do not stack phases in a single PR — that's the whole
   point of "phased so we don't break too many things at once."

---

## Phase 0 — Guardrail (prevents regression, no functional changes)

Add a line-count check to CI so files don't silently grow back past 500 lines:
- Python: a small script (mirroring the audit that produced the CSV) run in
  CI, warning (not failing) above 500 lines so it doesn't block legitimate
  growth but flags it for review.
- TypeScript: `eslint` `max-lines` rule (warn level) in `web-ui/.eslintrc`.
- Java: optional Checkstyle `FileLength` rule if the Maven build already runs
  Checkstyle; skip if it doesn't (not worth introducing a new build plugin
  just for this).

No files touched besides CI/lint config. Deploy risk: none.

---

## Phase 1 — Zero production coupling (scripts only)

These three files are demo-data/catalog generators with no runtime coupling
to the running product — the safest possible starting point to prove the
split pattern works before touching anything live.

**`scripts/demo_company/datasets.py`** (1307 lines) — only `generate_datasets`
is imported (by `scripts/install_demo_company.py`,
`scripts/tests/test_demo_company.py`); every `_dept` function is free to move.
Split into one file per department: `sales.py`, `manufacturing.py`,
`engineering.py`, `finance.py`, `hr.py`, `quality.py`, `procurement.py`,
`it.py`, `ehs.py`, `legal.py`, `executive.py`, with shared `_seasonal`/
`_PROJECT` in `_common.py`, and `datasets.py` kept as the thin orchestrator
re-exporting `generate_datasets`.

**`scripts/demo_company/documents.py`** (609 lines) — same import shape (only
`generate_documents` used externally). Split into `policies.py`,
`procedures.py`, `executive_reviews.py`, `business_ops.py`, sharing
`_PROJECT`/`_SYNTHETIC` from the same `_common.py` as `datasets.py`.

**`platform-api/scripts/convert_analytical_catalog.py`** (1045 lines) —
**one real constraint**: `platform-api/tests/test_r_catalog_activation.py`
imports `EXECUTABLE`, `EXECUTABLE_R`, and `build` directly by name. Move the
two big data blocks (`EXECUTABLE` ~540 lines, `EXECUTABLE_R` ~120 lines) to
`analytical_methods_data.py`; move `SHARED_POLICIES`/`SELECTION_MATRIX`/
`_GUARDRAILS`/`TIER1_HINTS`/`TIER3_HINTS`/`EXCLUDED_CATEGORIES` to
`catalog_reference_data.py`; keep `slugify`, `classify_tier`, `build`, `main`
in `convert_analytical_catalog.py`, which re-imports `EXECUTABLE`/
`EXECUTABLE_R` from the new data file so the test import keeps working
unchanged.

Smoke test: run `python scripts/install_demo_company.py` end to end (or the
existing `test_demo_company.py`) and `pytest test_r_catalog_activation.py`.

---

## Phase 2 — Low-risk platform-api services (leaf utilities, mostly public-only imports)

Order matters within this phase — earlier items have zero/near-zero external
private-name leakage; later items (`ai_governance.py`, `ai_intelligence_client.py`)
have wider fan-out and go last once the pattern is proven repeatedly.

| # | File | Split into | Notes |
|---|---|---|---|
| 1 | `project_source_resolver.py` (505) | `types.py` (`ResolverCandidate`/`ResolverResult`/`_Source`), `terms.py`, `gather.py`, `scoring.py`, orchestrator stays in main file | Already uses `# ---` banner sections — cleanest split in the batch. Shim must re-export `ResolverResult` (imported by `business_insight_project_resolver.py`) and `resolve_project_source` (imported by `project_insight_service.py`, `routes/ai_proxy.py`). |
| 2 | `knowledge_graph_context.py` (563) | `graph_primitives.py` (`_norm`/`_kpi_phrases`/`_haystack`/`_phrase_in`/`_node`/`_edge`), `collectors.py` (one `_collect_*` function per the file's existing 7 comment-delimited sections: file sources, DB sources, saved queries, dashboards, documents, KPIs, reference library), orchestrator `collect_structural_graph` stays in main file | Single external importer: `knowledge_graph/loader.py` (deferred import of `collect_structural_graph` only). Lowest-risk file in this phase. |
| 3 | `repository_scanner.py` (529) | `scan.py` (the `RepositoryScanner` class), `api.py` (`create_scan`/`list_scans`/`get_scan`/`list_items`) | Both pieces only reached by name (`RepositoryScannerError`, `create_scan`, `get_scan`, `list_items`, `list_scans`, `RepositoryScanner`) — all public, clean split. |
| 4 | `teiid_registration_service.py` (541) | `naming.py` (`sanitize_identifier`/`generate_teiid_names`/`generate_view_name`), `platform_db.py` (`_platform_db_*`), `reconcile.py` (`reconcile_database_sources`), `TeiidRegistrationService` class stays in main file | No private-name leakage; importers (`main.py`, `saas_source_service.py`, `routes/database_sources.py`, `routes/projects.py`) all use public names. |
| 5 | `file_sources.py` (703 actual — larger than the original 530 estimate) | `sanitize.py`, `naming_and_prep.py`, `format_readers.py` (`_read_csv_sample`/`_read_xlsx_sample`/`_flatten_value`/`_rows_to_csv`/`_json_to_rows`/`_xml_to_rows`), `classify.py` | Shim needs full re-export — `routes/upload.py`, `routes/projects.py`, and `file_ingestion.py` between them touch names from all four clusters. |
| 6 | `file_ingestion.py` (987) | `staging.py`, `acquisition.py`, `preview.py`, `finalize_tabular.py`, `finalize_document.py`, `jobs.py` | **Caution**: `routes/file_analysis.py` and `routes/file_imports.py` do `from app.services import file_ingestion` and reach through it as a namespace (`file_ingestion.something`), not just named imports — before trimming the shim, grep exactly which `file_ingestion.X` attributes those two route files touch and make sure every one is re-exported from the shim module's top level. |
| 7 | `document_processing_service.py` (758) | `profiling.py` (`call_document_profiler`/`_call_ai_profile`/`_hash_stored_file`), `indexing.py` (`_index_document_vectors`), `graph.py` (`_build_graph`/`_link_to_datasources`/`_upsert_node`/`_upsert_edge`), `process_document_asset` orchestrator stays in main file | Importers all use public names (`DocumentProfileError`, `call_document_profiler`, `process_document_asset`). |
| 8 | `project_graph_service.py` (577) | `graph_primitives.py`, `linking.py`, `queries.py`, `lifecycle.py` | **One private-name leak**: `routes/document_families.py` imports `_as_dict` directly — the shim must re-export it. |
| 9 | `teiid_sql.py` (1061) | `timestamps.py`, `string_filters.py`, `identifiers.py` | All-public but heavily cross-imported (`home_intelligence.py`, `routes/query.py`, `routes/ai_proxy.py`, `routes/home_intelligence.py` collectively use names from all three clusters) — shim re-exports from all three. |
| 10 | `project_ai_context.py` (591) | `context_loading.py`, `cache.py` (`ProjectAIContextCache`/`invalidate_project_ai_context`), `build_project_ai_context` + `get_governance_note` stay in main file | 7 importers, all public names (`build_project_ai_context`). |
| 11 | `analytical_method_engine/method_executor.py` (570) | `descriptive.py`, `correlation.py`, `group_comparison.py`, `categorical_tests.py`, `regression.py`, `trend_timeseries.py`, `EXECUTORS` registry + `execute()` stay in main file (it must import every executor anyway) | Cleanest, most naturally pre-grouped file in the whole audit — the statistical families are already distinct. |
| 12 | `insight_evidence_fingerprint.py` (578) | `canonicalization.py`, `fingerprint_builders.py`, `deduplication.py` | Single external importer (`home_intelligence.py`), all public names. |
| 13 | `time_series_transform.py` (653) — **before** #14 | `models.py`, `period_arithmetic.py`, `bucketing.py`, `transform_card_time_series` stays in main file | `percent_change_summary.py` imports `TimeSeriesInterval`/`transform_card_time_series` from this file — split this one first so #14 lands on a stable base. |
| 14 | `percent_change_summary.py` (678) | `models.py` (7 Pydantic models), `period_helpers.py`, `statistics.py`, `_evaluate_card` + `build_percent_change_summary` stay together in main file | Imported by `routes/home_intelligence.py`. |
| 15 | `insight_confidence.py` (547) | Light split only: `types.py` (dataclasses), `scoring_helpers.py`, `evaluator.py` (`evaluate_confidence`) | Agent flagged this as low-value to split further — it's essentially one 390-line function; do the light 3-way split and stop there. |
| 16 | `conversational_analytics.py` service (898) | `intent_classification.py`, `result_profiling.py`, `chart_field_selection.py`, `execute_turn`/`_run_analytical_turn`/`_build_explanation` stay in main file | Single importer, `routes/conversational_analytics.py` (whose own route-file split is Phase 4). |
| 17 | `deep_analysis.py` (611) — **before** #18 | `planning.py`, `materiality_gates.py` (the 9 `_material_*` functions — clean, self-contained cluster), `presentation.py` | Only importer: `home_intelligence.py`. Do before its sibling below since `home_intelligence.py`'s own split (Phase 3) will import from both. |
| 18 | `card_diagnostics.py` (830) | `diagnostics_planning.py`, `cross_reference_planning.py`, `action_proposals.py`, `envelope_extraction.py`, `group_evidence.py` | Only importer: `home_intelligence.py`. |
| 19 | `ai_intelligence_client.py` (540) — do near-last, widest fan-out in this phase | `transport.py` (`_sign_payload`/`_post`/`_retry_seconds`/`_chat_sem`/`is_enabled`/`AIUnavailableError`), `endpoints.py` (the 9 thin async wrapper functions — keep together, they're uniform) | **10 external importers** (`project_insight_service.py`, `reference_library_ai_client.py`, `conversational_analytics.py`, `home_intelligence.py`, `knowledge_graph_ai.py`, `tasks/workflows.py`, `routes/query.py`, `routes/project_actions.py`, `routes/ai_proxy.py`, `routes/home_intelligence.py`) — shim must re-export all 9 endpoint functions plus `AIUnavailableError`/`is_enabled`. Do this split in isolation with its own focused test run before moving on. |
| 20 | `ai_governance.py` (855) — do last in this phase | `registry.py` (`AnalyticalMethodDefinition`/`get_method_definition`/`get_method_label`/`list_method_definitions`/`infer_governance_key`), `AIGovernanceService` class + `ai_governance_service` singleton stay together (mixin split not needed at 490 lines for one class, but see note) | **Widest fan-in of Phase 2**: 8 importers reach `ai_governance_service`/`AIGovernanceService` directly. The registry half splits cleanly; leave the service class whole rather than risk fragmenting an 8-importer surface in the same phase as everything else — if it still feels too large after the registry split, revisit as its own mixin split later rather than rushing it here. |

Smoke test: run the platform-api test suite in full (these files feed
Business Insight, Project Insight, file upload, document processing, KG
context, repo scanning, and the analytical method engine — broad coverage,
not a single click-path).

---

## Phase 3 — The three "hub" files (class-based, wide fan-out, do carefully)

These depend on several Phase 2 outputs (visualization_engine reaches into
things home_intelligence also uses; home_intelligence imports from nearly
everything split in Phase 2), so they come after Phase 2 is fully merged and
stable, not concurrently with it.

**1. `project_context.py` (1288) + `models/project_context.py` (549).**
Mixin composition (see Conventions): `core.py`, `goals.py`, `metrics.py`
(largest sub-block, ~450 lines — split further into `metrics.py`+`targets.py`
if desired), `risks.py`, `reads.py`, recomposed as
`class ProjectContextService(GoalsMixin, MetricsMixin, RisksMixin, CoreMixin)`.
Model file splits in parallel by the same domains:
`business_context.py`/`goals.py`/`metrics.py`/`risks.py`/`audit.py` — all 9
ORM classes must still be imported somewhere so SQLAlchemy's mapper registry
sees them; update `app/models/__init__.py`'s explicit import block to cover
the new file locations. `services/project_ai_context.py` imports 5 of the 9
model classes directly (not the 2 link tables, not `AuditEvent`) — verify
those 5 re-export cleanly from wherever they land.

**2. `knowledge_graph_lifecycle.py` (1336).** Also class-dominated
(`KnowledgeGraphLifecycleManager`, ~1100 of the 1336 lines). Mixin split:
`bootstrap.py`, `rebuild_request.py`, `rebuild_execution.py` (largest, ~460
lines — the phase most likely to need its own internal sectioning even after
extraction), `state.py`, `status.py`; `GraphImpactAnalyzer` (self-contained,
only used internally) moves cleanly to `impact_analyzer.py`.
**Existing coupling to note, not created by this split**: this file already
imports private names (`_json_safe`, `_load_stored_graph`,
`_precache_center_cards`, `_snapshot_source_counts`) from the already-split
`knowledge_graph_builder` shim — preserve that dependency direction; don't
let the new lifecycle package import back into anything that would create a
cycle. 6 external files import `KnowledgeGraphLifecycleManager` and/or
`request_event_driven_rebuild` by these exact names — widest fan-in of this
phase, so run its own isolated KG-rebuild test pass before moving on.

**3. `visualization_engine.py` (1472) — do before `home_intelligence.py` below.**
Free-function split: `types.py`, `shape.py`, `heuristics.py`, `catalog.py`,
`recommend.py` (still the largest sub-module at ~700 lines — `recommend_visualizations`
itself may want its own internal sectioning). **Private-name leak**:
`home_intelligence.py` imports `ChartType`, `VizCandidate`, `VizDecision`,
`_catalog_facts`, `_catalog_shape`, `_detect_semantic_roles`,
`business_dimensions`, `derive_shape`, `rank_visualizations`,
`select_visualization`, and `_Shape as Shape` — all of these, public and
private, must be in the shim's re-export surface. Doing this split *before*
`home_intelligence.py`'s own split (next) means the new import paths are
already stable when that file gets its own treatment.

**4. `home_intelligence.py` (5012 lines — the largest file in the repo).**
The riskiest single split in this entire plan: it's the direct engine behind
Business Insight and Project Insight generation, with 5 external importers
(`project_insight_service.py`, `percent_change_summary.py`,
`tasks/workflows.py`, `routes/ai_proxy.py`, `routes/home_intelligence.py`)
reaching into both public and private names. Package
`app/services/home_intelligence/`:

| Module | Contents (approx. original line range) |
|---|---|
| `schema_context.py` | dataclasses, `gather_project_context`, relationship/period detection (99-701) |
| `card_ranking.py` | severity/priority/dedupe (701-838) |
| `card_builder.py` | `_card`, date parsing (805-1114) |
| `query_helpers.py` | `_safe_query` etc. (1114-1198) |
| `diagnostic_prompts.py` | the 4 built-in risk/trend/opportunity generators + `run_intelligence_suite` (1198-2059) |
| `chart_builder.py` | chart-spec construction (2135-2476) |
| `chart_templates.py` | radar/heatmap/treemap/sankey/funnel/scatter (2476-2800) |
| `claim_verification.py` | (2800-2953) |
| `cross_reference.py` | (2953-3097) |
| `diagnostic_orchestration.py` | `_card_diagnostic_insights`, `_run_diagnostic` (3097-3407) |
| `method_driven_insights.py` | bridges to `analytical_method_engine`/`deep_analysis` (3407-3617) |
| `shape_template_insights.py` | shape-template synthesis + join repair (3617-3888) |
| `formatting.py` | value/label formatting (3888-3994) |
| `widget_planning.py` | narrative builders + widget planning (3994-4325) |
| `orchestrator.py` | `run_ai_intelligence` (~640 lines), `synthesise_cross_project` — the file the shim primarily forwards to |

Shim (`home_intelligence.py`) re-export surface, verified by grep, not
guessed: `ALL_PROMPT_TYPES`, `ProjectContext`, `run_ai_intelligence`,
`run_intelligence_suite`, `gather_project_context`, `project_color`,
`build_dashboard_narrative`, `build_widget_explanation`,
`plan_and_execute_widgets`, `enhance_bar_readability`,
`synthesise_cross_project`, `_build_chart`, `_card_diagnostic_insights`,
`_detect_value_format`, `_method_driven_insights`, `_safe_query`,
`_shape_template_insights`. **Before merging this split**, beyond the
automated test suite, manually trigger a real Business Insight run and a real
Project Insight run end to end and confirm card output is unchanged —
automated tests won't catch every prompt/formatting nuance in a file this
central. Do not combine this with any other file's split in the same PR.

**5. `project_insight_service.py` (759)** — do immediately after
`home_intelligence.py` since it depends on it. Free-function split:
`card_normalization.py`, `method_envelopes.py`, `activity_deltas.py`,
`build_project_insight`/`_grouped_intelligence_cards`/`mark_project_insight_stale`
stay in main file. 6 external importers (`routes/project_insight.py`,
`routes/insight_feedback.py`, `routes/project_actions.py`,
`tasks/workflows.py`, `document_processing_service.py`,
`reference_library_processing.py`) — widest fan-in of this sub-item, all
public names.

Smoke test: full platform-api suite, plus a manual Business Insight run and
Project Insight run on a real project before merging each of items 1-5
individually (not batched).

---

## Phase 4 — platform-api routes layer

All 15 files register in `main.py` the same way today
(`app.include_router(x_routes.router, prefix=api_prefix)`, one line each) —
per Convention, add one `include_router` line per new sub-router directly in
`main.py` rather than another shim layer.

**Sub-phase 4a — small/isolated, do first:**
- `document_families.py` (553) → `document_families_reads.py`,
  `document_families_curation.py`, `document_families_summary.py`.
- `tenant_data_planes.py` (562) → `tenant_data_planes_crud.py`,
  `tenant_data_planes_network.py`.
- `dashboards.py` (578) → `dashboards_crud.py`, `dashboards_widget_query.py`.
  **Cross-import**: `routes/home_pins.py` imports `_build_widget_sql`
  directly — update that import path to point at
  `dashboards_widget_query.py`.
- `llm_framework.py` (611) → `llm_framework_inventory.py`,
  `llm_framework_catalog.py`, `llm_framework_artifacts.py`,
  `llm_framework_deployments.py`.
- `conversational_analytics.py` routes (564) → `conversational_analytics_conversations.py`,
  `conversational_analytics_turns.py`.
- `scope_sets.py` (683) → `scope_sets_crud.py`, `scope_sets_builder.py`
  (Scope Relationship Builder canvas). No ordering dependency on the
  `ai_proxy.py` split (Phase 5) — its lazy import of `_analyze_project_scopes`
  keeps working as long as `ai_proxy.py` continues re-exporting that name at
  the same path, which Phase 5's convention guarantees regardless of when it
  runs.
- **`query.py` (521) — do this one carefully despite its small size.** Its
  helpers (`_auto_cast_aggregates`, `_run_sql`, `_resolve_vdb_database`,
  `_execute_sql_with_repair`, `_sample_project_columns`) are the most
  cross-imported functions in the entire routes layer — reached by
  `ai_proxy.py` (4 places), `home_intelligence.py`, `query_scopes.py`,
  `scope_sets.py`, and `home_pins.py`. Extract them to a genuine
  `query_sql_helpers.py` (pure SQL-building/execution, zero FastAPI
  decorators) that both `query.py`'s own two endpoints and all five external
  importers depend on directly — do this **before** Phase 5's `ai_proxy.py`
  split, since `ai_proxy.py` is one of the five importers and should land on
  a stable base.

**Sub-phase 4b — medium:**
- `reference_library.py` (981) → `reference_library_documents.py`,
  `reference_library_project_views.py`, `reference_library_suggestions.py`.
- `database_sources.py` (812) → `database_sources_connection.py`,
  `database_sources_saved_connections.py`, `database_sources_lifecycle.py`.
  **Cross-import**: `find_query_dependencies` is imported by `routes/upload.py`
  and `routes/saas_sources.py` — land it in `database_sources_lifecycle.py`
  and update both call sites.
- `insight_feedback.py` (1066) → `insight_feedback_crud.py`,
  `insight_feedback_review.py` (the review-queue workflow), small governance
  batch endpoint folds into the review module.
- `tenants.py` (1077) → `tenants_crud.py`, `tenants_settings.py`,
  `tenants_security_policy.py`, `tenants_users.py`.

**Sub-phase 4c — biggest/most central, do last, after their service-layer
dependencies from Phase 2/3 are already split:**
- `upload.py` (1412) → `upload_core.py`, `upload_datasources.py`,
  `upload_replace.py`, `upload_versions.py` (depends on `file_sources.py`/
  `file_ingestion.py` already being split in Phase 2 — sequenced correctly).
- `home_intelligence.py` routes (1728) → `home_intelligence_suite.py`,
  `home_intelligence_snapshot.py`, `home_intelligence_suggestions.py`,
  `home_intelligence_dashboard_save.py`. **Depends on** the
  `services/home_intelligence.py` split (Phase 3) already being merged —
  `_make_runner` is imported by `routes/project_insight.py` and
  `routes/ai_proxy.py` from this route file too, so land it in
  `home_intelligence_suite.py` and update those two import sites, or
  re-export from the old filename.
- `project_actions.py` (1750) → `project_actions_crud.py`,
  `project_actions_lifecycle.py`, `project_actions_comments.py` (subtasks
  fold into lifecycle, ~200 lines, judgment call on a 4th file). Its `_shared.py`
  (helper cluster: `_require_project_access`, `_recalculate_action_progress`,
  `_apply_status_transition`, `_audit`, etc.) is the single strongest
  `_shared.py` candidate of the whole routes layer — extract that first,
  before the three feature groups.
- `projects.py` (2172 — the biggest route file, do very last in Phase 4) →
  `projects_crud.py`, `projects_aggregates.py`, `projects_datasources.py`,
  `projects_members.py`, `projects_queries.py`, `projects_metadata.py`, with
  a `projects_shared.py` for the cross-group helpers (`_visible_projects_subquery`,
  `_home_context`, `_is_project_admin`, etc.). **Cross-import**: `dashboards.py`
  imports `list_project_datasources` directly — update to point at
  `projects_datasources.py`.

Smoke test per sub-phase: the corresponding route's own test file, plus a
manual pass through the UI flow it backs (e.g. after 4c's `projects.py`
split, click through project creation, member management, and the
datasources tab).

---

## Phase 5 — AI proxy + ai-server routers (the two biggest, most central files)

These are scheduled after Phase 4's `query.py` split (a dependency of
`ai_proxy.py`) and after Phase 3's `home_intelligence.py`/`ai_governance.py`
splits are stable, since `ai_proxy.py` and `ai.py` sit downstream of almost
everything else in this plan.

**`platform-api/app/routes/ai_proxy.py` (4264 lines).** Nested-router parent
pattern (see Conventions — `main.py` needs zero changes). Extract
`ai_proxy_shared.py` **first**: `_sign_payload`, `_forward_to_ai`,
`_check_project_access`, `_detect_datasource`, `_map_chart_type`,
`_map_chart_subtype`, `_kg_context`/`_kg_context_chips` — these cross nearly
every feature group and are also imported directly by
`services/dashboard_widget.py` (`_detect_datasource`, `_map_chart_type`,
`_map_chart_subtype`) and `services/conversational_analytics.py`
(`_ask_and_run_core`, `_forward_prose_answer`). Then split into feature
routers in this order (roughly small-and-isolated → large-and-central):

| Router file | Endpoints |
|---|---|
| `ai_proxy_index.py` | `/index/document` |
| `ai_proxy_permissions.py` | `/status`, `/permissions` (AI-server-facing, distinct concern) |
| `ai_proxy_query.py` | `/query/generate`, `/project/relationships/generate` |
| `ai_proxy_scopes.py` | `/project/scope-map/generate`, `/project/scope-map/auto-create`, `_analyze_project_scopes` (imported by `routes/scope_sets.py` — must stay importable at a stable path) |
| `ai_proxy_dashboard.py` | `/dashboard/suggest` |
| `ai_proxy_query_actions.py` | `/actions/save-query`, `/actions/generate-and-save-query` |
| `ai_proxy_ask.py` | `/ask`, `/route-prompt` |
| `ai_proxy_ask_and_run.py` | `/actions/ask-and-run`, `/actions/generate-query-preview` — largest single cluster (~850 lines); `_ask_and_run_core`/`_forward_prose_answer` must stay re-exported for `conversational_analytics.py` |
| `ai_proxy_dashboard_generate.py` | `/actions/generate-and-save-dashboard` — the single largest endpoint in the file, ~450 lines |
| `ai_proxy_dashboard_suggest.py` | `/actions/suggest-dashboards` |
| `ai_proxy_dashboard_save.py` | `/actions/save-dashboard-suggestion` |
| `ai_proxy_widget_helpers.py` | `_map_widget_visual`, `_judge_widget`, `_correct_widget_chart`, `_pack_grid`, `_build_join_metadata` etc. — shared by the three dashboard-generation routers above |

Also re-export from the parent file for **tests** that import private helpers
directly (`test_ai_dashboard_pipeline.py`, `test_conversational_analytics.py`,
`test_visualization_engine.py`, `test_ai_ask_and_run.py`,
`test_ai_generation_intent.py`) — same shim, no test changes required.

**`ai-server/tablescope-ai-api/app/routers/ai.py` (4289 lines) — the largest
file in the whole repo.** Same nested-router pattern. This one is
**structurally lower-risk** than `ai_proxy.py`: only `main.py` and 6 test
files import from it — no other production file reaches in. Extract
`ai_shared.py` first (`_fix_teiid_group_by`, `_clean_sql`,
`_infer_chart_columns`, `_extract_sql` — imported directly by
`test_sql_extraction.py`, `_format_conversation_history`), then split by
feature: `ai_ask.py`, `ai_indexing.py`, `ai_relationships.py`,
`ai_query_generate.py` (note: `_catalog_table_columns` and
`_remap_tables_to_authorized` are imported directly by
`test_column_validation.py`/`test_table_remap.py` — re-export both),
`ai_dashboard.py`, `ai_intelligence_plan.py` (the single largest endpoint at
~1300 lines including its prompt-building helper cluster —
`_TEIID_FIX_JOIN_RULE`/`_TEIID_JOIN_EXCEPTION_RULE` constants referenced by
`test_kg_hypothesis_prompt.py` must stay re-exported), `ai_intelligence_fixsql.py`,
`ai_conversation.py`, `ai_intelligence_interpret.py`, `ai_knowledge_graph.py`,
`ai_project_insight.py`, `ai_scopes.py`, `ai_file_analysis.py`,
`ai_document.py` (folds in family-summarize), `ai_reference_library.py`,
`ai_actions.py`.

**`ai-server/tablescope-ai-api/app/models/schemas.py` (726 lines)** — split
to match the router split above, request+response colocated per feature
(today they're separated into "all requests" then "all responses" blocks,
~470 lines apart for the same feature). Turn into a package
`app/models/schemas/__init__.py` doing `from .schemas_ask import *` etc. for
every submodule so `app/routers/ai.py`'s large multi-name import block needs
no changes.

**Scheduling note**: `ai-server` is a separately deployed service from
`platform-api`, with an independent rollback path — if you have more than one
implementer, the `ai.py`/`schemas.py` work can run in parallel with
`ai_proxy.py` rather than strictly after it. For a single implementer working
sequentially, do `ai_proxy.py` first since platform-api is the primary
user-facing deploy.

Smoke test: full ask/dashboard-generation/intelligence-plan flows through the
UI (Ask AI, Suggest Dashboards, run a Business/Project Insight refresh) — this
phase touches literally every AI-backed feature in the product, so this is
the phase to be most conservative about batching multiple router splits into
one PR.

---

## Phase 6 — web-ui components

**6a. Admin pages** (super-admin only — smallest blast radius, safest
frontend starting point):
- `web-ui/app/admin/repositories/page.tsx` (832) → `status-badge.tsx`,
  `connection-form.tsx`, `connection-detail.tsx`, `scan-history.tsx`,
  `repository-profile.tsx`, `repository-items-browser.tsx`. Cleanest split
  in this sub-phase — no tight state coupling.
- `web-ui/app/admin/llm-framework/page.tsx` (1290) → literally 5
  independently-stateful tabs: `inventory-tables.tsx`, `register-forms.tsx`,
  `deployments-panel.tsx`, `catalog-panel.tsx`, `migrations-panel.tsx`,
  `conversions-panel.tsx`, plus shared `Section`/`StatusBadge`/format utils.
- `web-ui/app/admin/data-planes/page.tsx` (951) → `status-badge.tsx`,
  `create-tenant-form.tsx`, `bind-app-tenant-modal.tsx`,
  `delete-tenant-modal.tsx`. **Flag**: ~20 `useState` hooks currently live in
  one component and get threaded into these modals via props/callbacks —
  more invasive than the other two admin pages; extract carefully, one modal
  at a time, testing after each.

**6b. Lib/data modules** (barrel-file pattern — zero call-site changes,
unblocks later component work since many components import from these):
- `web-ui/lib/visualizations/chartRegistry.ts` (1019) → directory with
  `types.ts`, per-chart-family files (`basicCharts.ts`, `statisticalCharts.ts`,
  `hierarchicalCharts.ts`, `miscCharts.ts`), `aliases.ts`, `helpers.ts`,
  `index.ts` spreading the partials into `CHART_REGISTRY`.
- `web-ui/lib/api/home-intelligence.ts` (923) → directory with
  `insight-card-types.ts`, `streaming.ts`, `preferences.ts`, `reports.ts`,
  `suggestions.ts`, `time-series.ts`, `percent-change.ts`, `index.ts` barrel
  (48 files import from this today — the barrel makes it a zero-call-site
  change).
- `web-ui/lib/ui/use-project-data.ts` (698) → directory split by data domain:
  `shell.ts`, `queries.ts`, `dashboards.ts`, `documents.ts`, `datasources.ts`,
  `members.ts`, `knowledge-graph.ts`, `catalog.ts`, `activity.ts`, `ai.ts`,
  `index.ts` barrel (25 importers, fully independent domains, no cross-domain
  coupling found).

**6c. Self-contained / low-coupling components:**
- `web-ui/components/tablescope/sidebar.tsx` (525, 1 importer) →
  `nav-row.tsx`, `nav-group-block.tsx`, `account-menu.tsx`,
  `avatar-uploader.tsx`. Cleanest split of the entire audit.
- `web-ui/components/tablescope/project/knowledge-graph-canvas.tsx` (662, 0
  `useState` — purely presentational) → `.types.ts`, `.constants.ts`,
  `knowledge-graph-geometry-utils.ts` (pure exported helpers:
  `connectorStroke`, `rectSidePoint`, `insetPoint`, `moveToward`, `edgePath`
  — **verify `knowledge-graph-canvas.test.tsx` imports these from the new
  path**, since it tests them directly), `AlertSign.tsx`, `NodeChip.tsx`,
  `compute-layout.ts`.
- `web-ui/components/documents/DocumentsTab.tsx` (689) → `.types.ts`,
  `-utils.ts` (`formatBytes`/`statusBadge`/`fileIcon`); the two heaviest
  pieces are already `lazy()`-loaded siblings, so this is mostly a mechanical
  top-of-file extraction.
- `web-ui/components/tablescope/project/detail-views.tsx` (883) — already a
  grab-bag of 8 unrelated exported components, the most mechanical split in
  the audit: `query-result-view.tsx`, `query-builder-edit.tsx`,
  `query-builder-create.tsx`, `data-source-result-view.tsx`,
  `dashboard-detail-view.tsx`, `document-detail-view.tsx`, `query-editor.tsx`.
- `web-ui/components/tablescope/project/data-sources-screen.tsx` (842) →
  `data-sources-api.ts` (`archiveSource`/`preflightDelete`/`deleteSource`),
  `ArchiveCard.tsx`, `DeleteSourceDialog.tsx`, `SourceDetailPanel.tsx`,
  `VersionHistorySection.tsx`.
- `web-ui/components/tablescope/project/queries-screen.tsx` (641) →
  `queries-screen-utils.ts`, `ArchiveCard.tsx`, `QueryPreviewPanel.tsx`.
- `web-ui/components/tablescope/project/overview-screen.tsx` (506) — modest
  size, light split only: `ProjectHeader.tsx`, `RecentInsightsCard.tsx`,
  small `-utils.ts`.
- `web-ui/components/tablescope/home/percent-change-summary-table.tsx` (535)
  → `format-helpers.ts`, `StatCell.tsx`; leave the virtualized table itself
  intact as one cohesive rendering unit.
- `web-ui/components/tablescope/home/home-pins-grid.tsx` (557) →
  `pin-card.tsx` (`PinCard`+`PinContent`+`getPinInsightId`); leave the
  drag/resize/layout-reconciliation state machine (`HomePinsGrid` itself)
  intact — it's tightly coupled by design.
- `web-ui/components/upload/AIFileUploadWizard.tsx` (699) → `types.ts`,
  `UploadDropzone.tsx`, `FileReviewCard.tsx`.
- `web-ui/components/datasource/SaasSourceWizard.tsx` (681) and
  `web-ui/components/datasource/DatabaseTableWizard.tsx` (591) — same
  4-step-wizard shape, split identically: `types.ts` + one file per step
  (`ConnectStep.tsx`/`ObjectStep.tsx`/`FieldsStep.tsx`/`PreviewStep.tsx` for
  SaaS; `ConnectionStep.tsx`/`SchemaStep.tsx`/`TableStep.tsx`/`ColumnsStep.tsx`
  for Database), wizard keeps step-machine state + API calls.
- `web-ui/components/data-grid/TanStackDataGrid.tsx` (740) — **flag**: scope
  state (`scopesByField`) feeds column defs, the edit dialog, and the
  context menu simultaneously. Safe to extract: the scope create/edit dialog
  JSX → `ScopeDialog.tsx` (props: field/editing/target selectors + save/delete
  callbacks) and the column-visibility menu → its own subcomponent. Do **not**
  attempt to extract the drill-down/scope logic into a hook in this phase —
  treat that as a separate, more careful task if pursued at all.
- `web-ui/app/upload/page.tsx` (530) → `SourceBadge.tsx`, `types.ts`; the
  ~10 CRUD handlers are small/independent, optional follow-up to extract
  into a `useDatasourceActions()` hook but not required at this size.

**6d. Home/intelligence feed components:**
- `web-ui/components/tablescope/home/ai-suggestions.tsx` (611) — already
  visually segmented by comments, matches file boundaries exactly:
  `home-ask-box.tsx`, `query-suggestions-panel.tsx`,
  `dashboard-suggestions-panel.tsx`, `insights-panel.tsx` (exported — check
  its own external importers before moving), `types.ts`/`utils.ts`.
- `web-ui/components/tablescope/home/intelligence-card.tsx` (618, **13
  importers — widest blast radius in web-ui**) → `render-helpers.tsx`
  (`stripStars`/`renderBold`/`calloutLabel`/`buildMultiDimWidget`),
  `InsightChartView.tsx` (+`KpiGridView`+`InsightChartBlock`),
  `LoadingCard.tsx`, main `IntelligenceCard.tsx`. Convert to a directory +
  `index.ts` barrel given the fan-out, rather than a bare shim file, so all
  13 call sites need zero changes.
- `web-ui/components/tablescope/home/intelligence-feed.tsx` (624) — **flag**:
  this is a state machine (SSE event handling with ref-buffered background
  refresh, atomic commit on `"done"`), not a layout file. Extract only a
  `useIntelligenceFeedState()` hook covering the SSE/polling/selection logic,
  leave the JSX return in the main file — this is a hook-extraction task,
  scope and test it carefully rather than rushing it alongside the more
  mechanical splits in this phase.
- `web-ui/components/tablescope/project-insight/project-insight-screen.tsx`
  (616) — mostly a skip-candidate per the audit (9 `useState` + 8 query/mutation
  calls with no other large pieces). Light split only: `LoadingState.tsx`/
  `EmptyState.tsx`, `.constants.ts`.
- `web-ui/components/tablescope/project/business-context-screen.tsx` (1248)
  → `business-context-utils.ts` (~260 lines of pure formatters/tone
  functions — biggest single win here), `SummaryCards.tsx`,
  `business-context-goals-section.tsx` (`SuccessCriteriaSection` +
  `InlineGoalForm` + `KpiRow`), `business-context-risks-section.tsx`
  (`RisksSection` + `InlineRiskForm` + `RiskRow`). Main component is
  surprisingly thin (~160 lines) once these move — goals and risks are
  already self-contained sibling sections sharing only the parent's mutation
  callbacks as props.
- `web-ui/app/ai/page.tsx` (676) → `ConversationRow.tsx`, `ChatBubbles.tsx`
  (`UserBubble`/`TurnBubbles`/`TurnResult`/`MenuItem`); keep
  `AiAssistantPageInner` + the `Suspense` wrapper default export in
  `page.tsx` (route contract).
- `web-ui/components/ai/AIPanel.tsx` (841) — **verify this component has any
  live importers before investing split effort**; the audit found none. If
  it's dead code, delete it instead of splitting it (out of scope for this
  plan either way — flag to the team). If it turns out to be used via an
  alias/dynamic import, split as: `types.ts`, `utils.ts`, `AskTab.tsx`,
  `SuggestionsTab.tsx`, `SaveQueryDialog.tsx`.

**6e. Dashboard/charting:**
- `web-ui/components/dashboard/EChartsWidget.tsx` (1729) — **prime target,
  do first in this sub-phase**: ~1250 lines are pure `buildXOption`
  functions (line/bar/pie/scatter/heatmap/radar/treemap/funnel/sankey/combo/
  gauge/sunburst/tree/graph/parallel/etc.) with zero React and zero shared
  state — move wholesale to `echarts-option-builders.ts` (split further by
  chart family if that file still feels large). The remaining component is a
  thin orchestrator with only 2 `useState`.
- `web-ui/components/dashboard/WidgetConfigPanel.tsx` (719) →
  `WidgetConfigPanel.types.ts` + `WidgetConfigPanel.constants.ts` (the
  `CHART_TYPES` registry, ~80 lines, self-contained). Form-section JSX
  (Data Fields, Filters, Preview) can become presentational subcomponents
  taking `value`/`onChange` props — do this only if the 20-field flat config
  object stays a single state object passed down, not fragmented.
- `web-ui/components/dashboard/DashboardViewer.tsx` (626) →
  `DashboardViewer.types.ts`, and three extracted hooks:
  `use-widget-data.ts`, `use-drilldown.ts`, `use-dashboard-layout.ts` — each
  callback cluster has a clear single responsibility even though they share
  some state, making hook extraction safe here (unlike `intelligence-feed.tsx`
  above).

**6f. Highest state-coupling, do last:**
- `web-ui/components/tablescope/project-actions/project-actions-workspace.tsx`
  (1997) → `project-actions-workspace.constants.ts`,
  `project-actions-workspace-utils.ts`, `use-grid-template.ts`, then
  one-file-per-subcomponent for the already-independent pieces:
  `ColumnHeader.tsx`, `TimelineView.tsx`, `SummaryCard.tsx`, `Toolbar.tsx`,
  `GroupSection.tsx`, `ActionRow.tsx`, `SubtaskPanel.tsx`, `SubtaskRow.tsx`,
  `ProgressCell.tsx`, `DueCell.tsx`, `PriorityCell.tsx`, `OwnerCell.tsx`,
  `StatusCell.tsx`, `RiskCell.tsx`, `SourceCell.tsx`, `RowMenu.tsx`,
  `InlineDate.tsx`. The main component itself is only ~5 `useState` and
  well-isolated from these — despite the file's size, this is mechanical,
  not state-entangled.
- `web-ui/components/tablescope/project-actions/project-action-detail.tsx`
  (612) — do alongside the workspace file since they duplicate `Avatar` and
  status/priority label maps; consolidate into a shared
  `project-actions-shared-utils.ts` as an optional dedup (flagged, not
  required) while splitting `LabeledSelect`/`LabeledDate`/`SubtaskRow`/
  `InlineDate` into sibling files.
- `web-ui/components/scopes/ScopeBuilder.tsx` (1999, biggest file in
  web-ui) — **flag: heavily coupled local state** (25 `useState` all
  interdependent across drag/link/canvas-pan-zoom/AI-suggestions/popup
  positioning). Do **not** attempt to split the state. Only extract: `types.ts`,
  `scope-builder-utils.ts` (pure helpers), the two trivial subcomponents
  already at the bottom of the file (`Field`, `LegendItem`), and — carefully,
  as **presentational** components taking state slices + setters as props
  without moving the state itself — the visually-distinct JSX sections
  (`ScopeCanvas.tsx`, `RelationshipSetupPanel.tsx`,
  `ScopeSidebarQueryList.tsx`, `ScopePropertiesPanel.tsx`). This is the one
  file in the whole plan where "don't force a split" applies most strongly —
  a partial split (types/utils/trivial subcomponents only) is an acceptable,
  lower-risk outcome if the presentational extraction proves too invasive
  once you're inside the code.

Smoke test: this phase has no single flow — after each sub-phase, click
through the specific screens it touched (e.g. after 6f, exercise Project
Actions board view, action detail, and Scope Builder end to end) before
starting the next sub-phase. Run `tsc --noEmit` and the full vitest suite
after every individual file split, not just per sub-phase.

---

## Phase 7 — Java servlets (WildFly deploy, independent release process)

Schedule this phase independently of Phases 1-6's timing — it has a
fundamentally different deploy mechanic (WAR rebuild + redeploy, not a file
save) and underpins every data-source/VDB operation in the platform, so treat
it with its own release checklist regardless of where else you are in this
plan.

**`VDBManagementServlet.java` (2041 lines).** Extract, in the flat
`cloud.tablescope` package:
- `VDBXmlBuilder` — all XML-string-building methods (`updateFilePaths`,
  `updateFilePathsAbsolute`, `buildServiceNowModelBlock`,
  `buildServiceNowTranslatorBlock`, `buildSalesforceModelBlock`,
  `buildPhysicalModelBlock`, `xmlEncode`, `insertBefore`, `insertBeforeFirst`,
  `removeModelBlock`, `removeTranslatorBlock`, `removeViewStmt`) — static-friendly,
  no instance-field dependency.
- `WildFlyCliHelper` — `runCli`, `runCliChecked`, `ensureDataSource`,
  `dataSourceExists`, `driverNameFor`, `ensureSalesforceConnectionFactory`,
  `removeSalesforceConnectionFactory`, `isSalesforceTranslator`,
  `salesforceResourceAdapterName`, `normalizeSalesforceSoapUrl` —
  static-friendly.
- `VDBFileLocator` — `findVDBFile`, `deleteVDBFile`, `validateFolderExists`,
  `createFolderIfNotExists`, `setFolderPermissions`, `readFile`, `writeFile`
  — **needs `vdbBasePath` via constructor** (currently an instance field).
- `TeiidDeployHelper` — `deployVDBToTeiid` — **needs `teiidAdminUser`/
  `teiidAdminPassword` via constructor**.
- Keep on the servlet: `init`, `doOptions`, `doPost`, and the five action
  methods (`createVDB`, `deleteVDB`, `updateVDBCredentials`, `redeployVDB`,
  `checkVDBStatus`, `createDatabaseSource`) — these touch
  `HttpServletRequest`/`Response` directly and now call into the four helper
  classes above.

**`TeiidExcelImporterTest.java` (1242 lines).** Extract:
- `ExcelColumnReader` — `getColumnNamesFromStream`, `getColumnNames`,
  `getWorkbook` (near-duplicated header-parsing logic between the two — move
  both as-is per "don't reduce code"; dedup only if you separately choose to).
- `VDBXmlEditHelper` — `updateVDB`, `insertBefore`, `insertAfter`,
  `removeForeignTableAndView`, `removeTxtView`, `generateArchiveFileName`,
  `readFromFile`, `writeToFile`.
- `VDBFileLocator` (this file's version has hardcoded path literals, not a
  `vdbBasePath` field — more standalone than the servlet's own) —
  `findVDBFileForOrg`, `findVDBFileForUser`, `findVDBFileForShared`,
  `autoProvisionUserVDB`.
- `TeiidDeployHelper` — `deployVDB`, `invalidateTeiidCache` (hardcoded
  `localhost/9990/admin/admin`, fully static-movable).
- Keep on the servlet: `doPost` only (the sole method touching
  `HttpServletRequest`/`Part` directly).

**`VDBMigrationServlet.java` (726 lines) — cleanest of the three, no mutable
instance state (only `static final` constants).** Extract:
- `VDBDDLExtractor` — `detectFileType`, `extractDDLFromText`,
  `extractForeignTableDDLFromText`, `extractViewDDLFromText`,
  `extractDDLBlock`, `DDLResult`.
- `VDBXmlTextEditor` — `updateFilePaths`, `extractRelativePath`,
  `addDDLToVDBText`, `removeDDLFromVDBText`, `ensureCDATASections`,
  `readVdbAsText`, `writeVdbAsText`.
- `VDBFileLocator`/`TeiidDeployHelper` — `findUserVDBPath`,
  `findSharedVDBPath`, `redeployVDB` (constants can be duplicated as static
  finals on the new class, or passed via a small config object).
- `VDBMigrationOrchestrator` — `migrateToSharedVDB`, `migrateToPrivateVDB`,
  `MigrationResult`, called from `doPost`.
- Keep on the servlet: `doPost` only.

**Deploy checklist for every one of the three files above:**
1. `mvn package` under `apache-maven-3.9.6/MyProject/project-TeiidExcelImporterTest/`.
2. Confirm the build produces a new WAR with no compile errors from the
   extraction.
3. Run `mvn test` if there's existing Java test coverage; if not, this phase
   leans harder on manual verification (step 5).
4. Commit the rebuilt `wildfly/standalone/deployments/TeiidExcelImporterTest.war`
   binary and redeploy to WildFly.
5. **Manual smoke test before considering any of the three files "done"**:
   file upload + VDB creation (`TeiidExcelImporterTest`), a database-source
   connection + Salesforce/ServiceNow source registration
   (`VDBManagementServlet`), and — if you have a VDB migration scenario
   available — a shared/private VDB migration (`VDBMigrationServlet`). These
   servlets have essentially no automated test coverage per the audit, so
   this manual pass is the primary safety net, not a formality.

Do the three files one at a time, one WAR rebuild/redeploy cycle each — do
not batch multiple servlet splits into a single WAR rebuild.

---

## Explicitly deferred (in scope per the audit, out of scope for active work)

- **`platform-api/app/seed_data/analytical_methods/catalog.json`** (25,267
  lines) and **`source_taxonomy.json`** (5,325 lines) — these are data, not
  logic. Splitting them requires a loader change (reassembling N files back
  into one structure at load time), which is a real code change with its own
  risk, for a file that never executes and therefore can't "break" the
  running product the way the files above can. Revisit only if you
  specifically want smaller diffs when this seed data changes — not required
  by "files that can break things."
- **`docs/*.md` and `*/prompts/*.md`** (8 doc files, 6 prompt files) — pure
  content, no import graph, no runtime risk. Splitting these is a documentation
  reorganization, not a code-safety task; do it independently of this plan
  whenever it's convenient, in any order, with no phase sequencing required.
- **Large test files** (`test_home_intelligence.py`, `test_insight_feedback.py`,
  `test_knowledge_graph.py`, `test_billing.py`, `test_ai_ask_and_run.py`,
  `test_mfa.py`, `test_scope_sets.py`, `test_conversational_analytics.py`,
  `test_project_insight.py`, `test_knowledge_graph_event_triggers.py`,
  `test_card_diagnostics.py`, plus `tests/e2e/specs/run-004.spec.ts` and
  `full-run-t1-t9.spec.ts`, and `tests/e2e/fixtures/scenarios.json`) — split
  each of these opportunistically **alongside the phase that splits its
  corresponding production file** (e.g. `test_home_intelligence.py` when
  Phase 3 touches `home_intelligence.py`), not as a standalone phase. A test
  file split carries zero production risk on its own, so there's no reason
  to sequence it separately from the code it tests.

---

## Summary: every file from the audit, mapped to a phase

| Phase | Files |
|---|---|
| 0 | (CI/lint config only, no source files) |
| 1 | `datasets.py`, `documents.py` (demo_company), `convert_analytical_catalog.py` |
| 2 | `project_source_resolver.py`, `knowledge_graph_context.py`, `repository_scanner.py`, `teiid_registration_service.py`, `file_sources.py`, `file_ingestion.py`, `document_processing_service.py`, `project_graph_service.py`, `teiid_sql.py`, `project_ai_context.py`, `method_executor.py`, `insight_evidence_fingerprint.py`, `time_series_transform.py`, `percent_change_summary.py`, `insight_confidence.py`, `conversational_analytics.py` (service), `deep_analysis.py`, `card_diagnostics.py`, `ai_intelligence_client.py`, `ai_governance.py` |
| 3 | `project_context.py` + model, `knowledge_graph_lifecycle.py`, `visualization_engine.py`, `home_intelligence.py` (service), `project_insight_service.py` |
| 4 | `document_families.py`, `tenant_data_planes.py`, `dashboards.py`, `llm_framework.py`, `conversational_analytics.py` (routes), `scope_sets.py`, `query.py`, `reference_library.py`, `database_sources.py`, `insight_feedback.py`, `tenants.py`, `upload.py`, `home_intelligence.py` (routes), `project_actions.py`, `projects.py` |
| 5 | `ai_proxy.py`, `ai-server/.../routers/ai.py`, `ai-server/.../models/schemas.py` |
| 6 | `admin/repositories/page.tsx`, `admin/llm-framework/page.tsx`, `admin/data-planes/page.tsx`, `chartRegistry.ts`, `lib/api/home-intelligence.ts`, `lib/ui/use-project-data.ts`, `sidebar.tsx`, `knowledge-graph-canvas.tsx`, `DocumentsTab.tsx`, `detail-views.tsx`, `data-sources-screen.tsx`, `queries-screen.tsx`, `overview-screen.tsx`, `percent-change-summary-table.tsx`, `home-pins-grid.tsx`, `AIFileUploadWizard.tsx`, `SaasSourceWizard.tsx`, `DatabaseTableWizard.tsx`, `TanStackDataGrid.tsx`, `upload/page.tsx`, `ai-suggestions.tsx`, `intelligence-card.tsx`, `intelligence-feed.tsx`, `project-insight-screen.tsx`, `business-context-screen.tsx`, `ai/page.tsx`, `AIPanel.tsx`, `EChartsWidget.tsx`, `WidgetConfigPanel.tsx`, `DashboardViewer.tsx`, `project-actions-workspace.tsx`, `project-action-detail.tsx`, `ScopeBuilder.tsx` |
| 7 | `VDBManagementServlet.java`, `TeiidExcelImporterTest.java`, `VDBMigrationServlet.java` |
| Deferred | `catalog.json`, `source_taxonomy.json`, 8 `docs/*.md`, 6 prompt `.md` files, 11 large test files, 2 e2e spec files, `scenarios.json` |
