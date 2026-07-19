# Devin brief: integrate event-driven Knowledge Graph rebuilds

Repository: `lhoskins/tablescope-lh`. The backend work is **complete** on branch
`claude/validate-enhance-logic-r2fyy1` (commit `dfc0f75`), based on
`feature/sprint-08-knowledge-graph-lifecycle`. All 683 platform-api tests pass,
including 12 new ones in
`platform-api/tests/test_knowledge_graph_event_triggers.py`.
**Do not re-implement; merge and build on it.**

## Background

The change closes the gaps between the sprint-08 KG lifecycle system and the
"rebuild without user intervention" design:

- Stale graphs were detected (fingerprint-drift cron) but never rebuilt.
- No data-change event (document processed, SaaS sync) triggered a rebuild.
- Incremental rebuilds re-cached the previous snapshot's graph, so a
  document-triggered incremental build would have activated a version missing
  that document.
- `file_hash` was stored but never used to skip reprocessing unchanged files.
- There was no project-wide reprocess cascade.

## 1. Merge

Merge `claude/validate-enhance-logic-r2fyy1` into
`feature/sprint-08-knowledge-graph-lifecycle`. No DB migrations are involved —
the change touches only these files:

- `platform-api/app/services/knowledge_graph_lifecycle.py` — headless
  (no-request-context) rebuild requests, `requested_by` attribution,
  incremental-request coalescing, incremental rebuilds now reload stored graph
  rows, new `request_event_driven_rebuild()` helper, new
  `resolve_representative_user()`.
- `platform-api/app/tasks/workflows.py` — `evaluate_stale_graphs` cron now
  auto-enqueues rebuilds for drifted projects; `sync_saas_object` triggers a
  rebuild after sync; new `reprocess_project` task + `enqueue_reprocess_project`
  (deterministic job id `reprocess:{tenant}:{project}`);
  `enqueue_rebuild_knowledge_graph` uses job id `kg-build:{build_id}`.
- `platform-api/app/services/document_processing_service.py` —
  `process_document_asset` now takes `force` and `trigger_graph_rebuild`
  kwargs, returns `"processed" | "skipped_unchanged" | "failed"`, gates on the
  SHA-256 `file_hash`, and triggers a KG rebuild as terminal step 9.
- `platform-api/app/routes/project_assets.py` —
  `POST .../assets/{asset_id}/ai/process` gained `force` (default `true`,
  preserving existing Reprocess-button behavior); new
  `POST /projects/{project_id}/assets/reprocess?force=` endpoint that enqueues
  the project-wide cascade.

After merging, run from `platform-api/`:

```bash
pytest
ruff check app tests
```

Both must be clean.

## 2. Deployment checks (no code changes expected)

- The `platform-api-worker` (arq, `WorkerSettings` in
  `app/tasks/workflows.py`) must be running — all new behavior executes there.
  Cron entries for `evaluate_stale_graphs` (every 15 min) already exist and now
  auto-rebuild.
- Verify `job_timeout` is sufficient for `reprocess_project` on the largest
  project (documents × AI profiling + one graph rebuild); raise it if worker
  logs show timeouts.

## 3. Frontend wiring (net-new work)

- Add a project-level "Reprocess all documents" action calling
  `POST /api/projects/{id}/assets/reprocess` (optionally `?force=true`).
  Response is `{status: "queued" | "already_running", job_id}` — show a toast
  for `already_running`.
- In `DocumentsTab`, the per-asset Reprocess still forces by default; if adding
  an "only if changed" option, call it with `?force=false` and handle assets
  whose `ai_status` remains `"profiled"` (the skip happened; no reprocess
  occurred).
- The KG page needs no changes: it reads the active lifecycle version, and
  rebuilds now happen automatically after document processing, SaaS syncs,
  repository scans, and fingerprint drift.

## 4. Deferred item — decide with product before implementing

Table-to-table relationship persistence: `/project/relationships/generate`
(in `platform-api/app/routes/ai_proxy.py`) returns suggestions but writes no
edges, so those relationships never reach the graph. If product wants them
persisted:

1. Write accepted suggestions into `ai_project_graph_edges` (mirror
   `_upsert_edge` in `document_processing_service.py`, edge type e.g.
   `related_table`, with confidence).
2. Call `request_event_driven_rebuild()` from
   `app/services/knowledge_graph_lifecycle.py` afterward — never rebuild the
   graph before the edges are committed.

Do not make the graph trigger relationship generation; the graph is strictly a
downstream consumer of documents, relationships, and view families.

## Invariants to preserve

- Producer-before-consumer ordering: a KG rebuild must only be requested after
  the source rows (`ai_project_graph_nodes` / `ai_project_graph_edges`,
  staging tables) are committed.
- Event triggers are best-effort and fail-open: a graph-lifecycle failure must
  never fail the data-change flow that triggered it.
- Rebuild requests coalesce (queued builds are reused; arq job ids are
  deterministic) so bursts of changes produce one rebuild, not N.
- Headless rebuilds are attributed to a representative user (project owner) so
  AI enrichment still runs; without a `requested_by` user a build produces a
  structural-only snapshot with no insight cards.
