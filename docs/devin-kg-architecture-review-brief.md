# Knowledge Graph architecture review brief

Branch: `devin/datasources-nav-kg-six-item`  
Scope: `platform-api/app/services/knowledge_graph_builder.py`, `knowledge_graph_lifecycle.py`, `knowledge_graph_ai_context.py`, and the insight pipelines that consume the KG.

## 1. Current state

### 1.1 Codebase

- `knowledge_graph_builder.py` is **1,653 lines** and mixes four distinct responsibilities:
  1. graph node/edge loading and normalization (`_load_stored_graph`, `_node`, `_edge`),
  2. relationship classification and connector-style policy (`_classify_relationship`, `connectorStyle`),
  3. AI insight-card generation (`_precache_center_cards`, `_build_card`, `build_graph_payload`),
  4. snapshot read/write and version-gated cache invalidation (`build_node_centric_graph`, `rebuild_project_graph_snapshot`).
- `SNAPSHOT_PIPELINE_VERSION = "knowledge_graph_connector_styles_v3"` correctly bumps the policy and the read path auto-rebuilds stale snapshots when `pipelineVersion` does not match.
- `build_node_centric_graph_from_snapshot()` serves canvas **and** insight cards entirely from the cached `fullGraph` and `aiCardsByCenter`; it does not call the AI server.
- `knowledge_graph_lifecycle.py` is the single orchestration point:
  - `request_event_driven_rebuild()` is called by `document_processing_service.py` and `reference_library_processing.py` after document/source changes.
  - `KnowledgeGraphLifecycleManager.request_incremental_rebuild()` coalesces multiple rapid change events onto one queued build.
  - On success, `rebuild_knowledge_graph` worker calls `mark_project_insight_stale()` and, when `project_insight_event_rebuild_enabled`, enqueues `rebuild_project_insight`.
- `knowledge_graph_ai_context.py` builds the KG-derived context that `project_insight_service.py` and `home_intelligence.py` send to the AI server for Project Insight and Business Insight.

### 1.2 Verified observations from this work stream

- The connector-style classification (`_classify_relationship`) and the rendering contract (`relationshipStrength`, `connectorStyle`, `displayByDefault`, `validationStatus`, `evidenceBasis`, `evidenceSummary`) are present and consistent.
- Snapshot persistence stores `pipelineVersion`; the read path invalidates on mismatch. This is the right mechanism, but it is **only as safe as the deployed code version**.
- A cached snapshot that predates the deployed `SNAPSHOT_PIPELINE_VERSION` is rebuilt automatically on the next read. A snapshot built by a newer version that is then rolled back to an older code version will be mis-rendered until the read auto-rebuilds or `?refresh=true` is used.
- During this session a stale graph was observed live; the root cause was not the classification logic but the same deploy/cache mismatch pattern seen elsewhere: the live checkout did not have the v3 constant, so the snapshot was created under the old policy and the new frontend could not display the new tiers.

## 2. Risks

### 2.1 Concentrated churn in one file

`knowledge_graph_builder.py` is the largest service file in the platform API. Mixed concerns make review, testing, and rollback harder:

- A connector-style change (pure rendering policy) currently sits next to AI card generation and DB snapshot I/O.
- Long files increase the chance of unrelated changes being included in a hotfix.
- Unit tests must import the whole module, which can be slow and brittle.

### 2.2 KG build as the shared upstream trigger for both insight types

`rebuild_knowledge_graph` worker is the only place that marks Project Insight stale and, conditionally, enqueues Project Insight rebuild. Business Insight refresh is driven separately by `home_intelligence` routes and the `schedule_stale_insight_refresh` cron, but `home_intelligence` also consumes `knowledge_graph_ai_context`.

- If a KG build fails silently (or is retried too aggressively), both downstream insight surfaces stall.
- There is no explicit dependency graph or event bus; insight rebuilds are triggered by inline worker calls.

### 2.3 Document-family / AI metadata flow

Documents are processed, then `document_processing_service.py` calls `apply_document_family()` and `request_event_driven_rebuild()`. The KG rebuild then re-reads `ai_project_graph_nodes` / `ai_project_graph_edges`. The ordering contract is documented but not enforced by the DB or a queue.

- If `request_event_driven_rebuild` is called before the staging tables are flushed, the rebuild runs on stale data.
- Coalescing onto an already-queued build helps, but only if the build has not already started.

### 2.4 Deploy-version parity for pipeline-version-gated cache logic

`SNAPSHOT_PIPELINE_VERSION` is a runtime constant. The snapshot table stores the version used at build time. On read the code compares the stored version to the constant in the running process.

- A blue/green or rolling deploy can have two code versions serving the same snapshot table concurrently.
- Old workers can overwrite a v3 snapshot with a v2 payload, and a v3 frontend may then render a v2 graph until the next read triggers a rebuild.
- There is no environment-wide lock or migration that forces a one-time global rebuild at deploy time.

## 3. Concrete recommendations

### 3.1 Split `knowledge_graph_builder.py` into focused modules

Proposed split:

- `services/knowledge_graph/loader.py` — DB reads (`_load_stored_graph`, node/edge normalization).
- `services/knowledge_graph/classifier.py` — `_classify_relationship`, `_edge_confidence`, connector-style policy.
- `services/knowledge_graph/cards.py` — AI insight-card generation (`_build_card`, `_precache_center_cards`).
- `services/knowledge_graph/snapshot.py` — `rebuild_project_graph_snapshot`, `get_project_graph_snapshot`, version-gating.
- `services/knowledge_graph/renderer.py` — `build_graph_payload`, `build_node_centric_graph_from_snapshot`.

`knowledge_graph_builder.py` would become a thin compatibility re-export module to avoid breaking existing imports.

### 3.2 Add an explicit KG → insight event pipeline

Instead of the worker calling `mark_project_insight_stale()` and `enqueue_rebuild_project_insight()` directly:

- Publish a `knowledge_graph_rebuilt` event (via arq or a small `InsightRebuildRequest` table).
- Let separate workers consume the event for Project Insight and Business Insight.
- This decouples KG build cost from insight build cost and lets each insight type have its own retry/backoff policy.

### 3.3 Harden deploy-version parity

- At startup, `platform-api` should run a lightweight migration/health job that checks whether any snapshot has a `pipeline_version` older than `SNAPSHOT_PIPELINE_VERSION` and queues rebuilds for active projects, not wait for a user to load the page.
- Store `pipeline_version` in the response metadata so the frontend can show "graph out of date, refresh" when `pipelineVersion` differs from the expected value returned by an API version endpoint.
- Consider making `SNAPSHOT_PIPELINE_VERSION` an immutable build-time value (e.g., from `pyproject.toml` or `__version__`) rather than a hand-edited constant, to reduce the risk of a stale deploy.

### 3.4 Enforce the document → graph ordering contract

- `request_event_driven_rebuild` should verify that the staging tables (`ai_project_graph_nodes` / `ai_project_graph_edges`) for the affected project have an `updated_at` later than the build request, or accept an explicit `source_checkpoint` transaction ID.
- Add a test that simulates a document upload, asserts the staging tables are committed, then asserts the KG rebuild reads the new rows.

### 3.5 Add targeted tests for the connector-style policy

- Unit-test `_classify_relationship` with all combinations of `relationship_type`, `evidence.validation_status`, and `evidence.basis`.
- Unit-test `build_graph_payload` to assert each tier maps to the correct `connectorStyle` and `displayByDefault`.
- Add an integration test that builds a snapshot under v2, then starts a server with `SNAPSHOT_PIPELINE_VERSION = v3`, loads the graph, and verifies it auto-rebuilds and returns the new connector tiers.

## 4. Immediate next steps

1. **No code change needed now for connector styles**: the v3 constant and auto-rebuild path are correct. If a live graph still shows the old style, use `?refresh=true` on the knowledge-graph route or delete the stale snapshot row; the next load will rebuild under v3.
2. **Confirm the current live deploy** is running a checkout that contains `SNAPSHOT_PIPELINE_VERSION = "knowledge_graph_connector_styles_v3"` (it is in this branch; verify after merge/deploy).
3. **Schedule the module split** before the next KG policy change; it is the highest-leverage refactor.
4. **Add the deploy-time migration check** the next time the pipeline version is bumped.

## 5. What this branch did not change

- No logic changes to `knowledge_graph_builder.py` were made for this PR. Items 1–4 above are the existing verified behavior; only recommendations 3.1–3.5 are future work.
