# Implementation plan: Project Insight event-driven rebuild + instant hydration

Repository: `lhoskins/tablescope-lh` (platform-api). Builds on the event-driven
Knowledge Graph lifecycle (see `kg-event-driven-rebuilds-devin-brief.md`).

## Goal

Replace today's delete-on-change invalidation with **mark-stale +
background rebuild (stale-while-revalidate)** so the Project Insight page
always hydrates instantly from a snapshot, and the snapshot refreshes itself
in the worker whenever the project's data actually changes — extending the
established producer chain by one stage:

```
documents → knowledge graph → project insight
```

## Current state (verified)

- `GET /projects/{id}/insight` (`app/routes/project_insight.py:105`) serves the
  `ProjectIntelligenceSnapshot` if present, else builds synchronously on the
  request path via `build_project_insight` (`app/services/project_insight_service.py`).
  The client re-runs with `refresh=true` in the background.
- Snapshots are per `(tenant_id, user_id, project_id, suite)`
  (`app/models/project_intelligence_snapshot.py`), suites `"project_insight"`
  and `"insights"` (the latter written by `POST /home/insights`).
- Invalidation deletes rows: `document_processing_service.py` (~line 240,
  suite-wide per project) and `reference_library_processing.py` (~line 279).
  The next visitor then pays full AI latency on the request path.
- The report already grounds in KG context (`collect_knowledge_graph_ai_context`),
  so a KG version activation is the natural upstream freshness signal.
- Insight identity: cards prefer a stable server-generated `insightId`
  (`project_insight_service.py:227`), and acknowledgements are keyed
  `(project_id, insight_id)` with content snapshotted at review time — so
  background regeneration does not corrupt the Reviewed list. Preserve this.

## Design

### 1. Schema: staleness flag (migration `0059`)

Add to `project_intelligence_snapshots`:

- `is_stale: bool, nullable=False, server_default=false, index=True`

No other schema changes. `updated_at` (TimestampMixin) already records build
time.

### 2. Mark stale instead of delete

Replace both `delete(ProjectIntelligenceSnapshot)` sites with an update that
sets `is_stale=True` for the affected `(tenant, project)` (all users, all
suites), plus a best-effort enqueue of the rebuild task (section 3). Wrap in
the same try/except the deletes use today. The read route keeps serving the
stale payload immediately, now with a `stale: true` field in the response so
the UI can show "refreshing…".

Trigger sites (mark stale + enqueue, all fail-open):

1. `document_processing_service.process_document_asset` — the existing
   invalidation block (step 5 aftermath).
2. `reference_library_processing` — the existing tenant/project-scoped
   invalidation block. (Reference-library changes do NOT flow through the KG
   fingerprint, so this direct trigger is required.)
3. **KG version activation** — in `app/tasks/workflows.py::rebuild_knowledge_graph`,
   after a build succeeds, mark stale + enqueue for that project. This covers
   every source the KG fingerprint watches (data sources, queries, dashboards,
   goals/metrics/risks, repository scans, SaaS syncs) without wiring each one
   individually. Put the hook in the worker task, not in
   `KnowledgeGraphLifecycleManager`, to keep the lifecycle module free of
   insight dependencies.

Duplicate triggers are harmless: the deterministic job id + the task's own
stale-gate (section 3) coalesce them.

### 3. Worker task: `rebuild_project_insight`

In `app/tasks/workflows.py`:

- `enqueue_rebuild_project_insight(*, tenant_id, project_id)` using
  `_job_id=f"project-insight:{tenant_id}:{project_id}"` and `_defer_by=60`
  (seconds) so bursts (multi-file upload → several KG builds) coalesce into
  one rebuild after the dust settles.
- `rebuild_project_insight(ctx, *, tenant_id, project_id)`:
  1. **Stale gate:** exit immediately if no snapshot row for the project has
     `is_stale=True` (a fresher run already handled it).
  2. **Audience:** rebuild only for users who already have a snapshot row for
     this project (they have visited the page) — this is the recency policy,
     no new tracking needed. Cap at a setting
     `project_insight_max_rebuild_users` (default 10), most recently
     `updated_at` first. Everyone else falls back to the on-demand request
     path unchanged.
  3. For each audience user, sequentially (no fan-out): run
     `build_project_insight` with a worker context for that user (reuse
     `_worker_context` from workflows.py — acknowledgement state is per-user
     merged, which is why the build is per-user), upsert the snapshot with
     `is_stale=False`. Per-user failures are logged and skipped; the loop
     continues.
  4. Respect AI capacity: acquire the existing per-tenant slot
     (`home_intel_queue.acquire_tenant_slot`) around the AI-heavy section, and
     honor `AIUnavailableError.retryable` with arq `Retry`, mirroring
     `analyze_project_intelligence`.
- Register in `WorkerSettings.functions`.

### 4. Route changes (`project_insight.py`)

- `GET /{project_id}/insight`: include `stale` (from `is_stale`) and
  `generatedAt` (from `updated_at`) in the response. When `refresh=true`
  completes, write the snapshot with `is_stale=False` (unchanged flow
  otherwise). Keep the synchronous path for users outside the rebuild
  audience.
- Frontend: replace the unconditional background `refresh=true` re-run with:
  hydrate; if `stale`, show a subtle "updating…" indicator and poll the GET
  (or re-fetch after a delay) until `stale=false`. This removes today's
  every-page-open AI run for users whose snapshot is already fresh — a net
  AI-cost *reduction*.

### 5. Invariants (carry over from the KG work)

- Producer-before-consumer: enqueue only after the triggering data is
  committed. The KG-activation trigger inherits this by construction.
- All triggers fail-open; an insight failure never fails document processing,
  reference-library processing, or a KG build.
- Coalescing everywhere: deterministic job ids + defer window + stale gate.
- Headless attribution: builds run as the snapshot's owning user (their
  acknowledgement view), not as a synthetic admin.

## Tests (`tests/test_project_insight_rebuild.py`)

1. Document processing marks snapshots stale (not deleted) and enqueues
   (captured enqueue, no Redis).
2. KG build success in `rebuild_knowledge_graph` marks stale + enqueues.
3. `rebuild_project_insight` stale-gate no-ops when nothing is stale.
4. Rebuild refreshes only users with existing snapshot rows, clears
   `is_stale`, respects the user cap, and continues past a per-user failure
   (monkeypatch `build_project_insight`).
5. GET returns `stale=true` payload after invalidation, `stale=false` after
   rebuild.
6. Acknowledged insight ids survive a background regeneration (stable
   `insightId` merge).

## Rollout

- Feature flag `project_insight_event_rebuild_enabled` (default off). When
  off: mark-stale still replaces delete (safe, strictly better), but no
  enqueue — behavior degrades to today's lazy rebuild with a visible stale
  flag.
- Verify worker `job_timeout` covers `audience × one report build`.
- Watch AI-server load after enabling; tune `_defer_by` and the user cap.

## Open decisions

1. Should the `"insights"` suite (Home's per-project card cache) share this
   rebuild, or is it superseded by Business Insights Phase 2? Recommend:
   mark it stale here, let Phase 2 own its refresh.
2. Audience cap default (10) — confirm against real member counts.
