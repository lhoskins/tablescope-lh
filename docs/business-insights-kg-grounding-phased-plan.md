# Implementation plan: Business Insights — KG grounding, staleness, shared results

Repository: `lhoskins/tablescope-lh` (platform-api). Builds on the event-driven
Knowledge Graph lifecycle and complements
`project-insight-event-driven-rebuild-plan.md`.

## Goal

Two phases:

- **Phase 1 (cheap, independently shippable):** ground the Business Insight
  analyst loop in Knowledge Graph context, and stamp the Home snapshot with a
  "data changed since this briefing" staleness signal derived from KG builds.
  No new background AI runs.
- **Phase 2 (structural):** make per-project analysis results a shared,
  tenant-scoped cache keyed by KG version, so a project's analysis is computed
  once per data change instead of once per user — which is what finally makes
  event-driven background refresh affordable for Home.

Target end-state chain:

```
documents → knowledge graph → shared per-project insight results → per-user Home assembly
```

## Current state (verified)

- Runs are user-initiated: `/home-intelligence/stream`
  (`app/routes/home_intelligence.py:309`) enqueues one durable arq job per
  project (`analyze_project_intelligence`, `app/tasks/workflows.py`), with
  per-tenant slots, retry-on-AI-contention, and self-timeouts. Workers write
  results to Redis and persist the per-user `IntelligenceSnapshot`
  (merge-safe, one row per user).
- The analyst loop (`home_intelligence.run_ai_intelligence`, ~line 2202)
  grounds in `gather_project_context` (tables + documents + reference docs)
  and `build_project_ai_context` (goals/metrics/risks) — but **not** the KG.
  Home is the only AI surface not reading
  `collect_knowledge_graph_ai_context` (Project Insight and dashboard/query
  generation both do).
- The KG lifecycle records `last_successful_build_at` and an activated
  version id per project — a free freshness signal.

## Phase 1

### 1a. KG grounding of the analyst loop

In `run_ai_intelligence` (`app/services/home_intelligence.py`), next to the
existing `build_project_ai_context` call:

```python
kg_context = await collect_knowledge_graph_ai_context(
    session, tenant_id=tenant_id, project_id=project.id,
    user_id=user_id, max_items=10,
)
```

- Fail-open (the collector already returns an empty block on any failure or
  an empty graph) — a missing/failed KG must never block a Home run.
- `max_items=10` (tighter than Project Insight's 20) to protect the plan
  prompt's schema budget.
- Pass it into the **plan** request payload as `knowledge_graph_context`
  (same field name Project Insight uses).
- **Hypotheses-to-test framing (the critical part):** the AI-server plan
  prompt must instruct: *"the knowledge graph surfaces these risks, gaps,
  opportunities, and recommended-but-unmeasured KPIs; treat them as
  hypotheses — plan analyses whose SQL validates, quantifies, or refutes them
  against the real data. Never assert a graph item as a finding without a
  query result behind it."* This prevents AI-derived graph nodes from
  laundering themselves into insights (the echo-chamber risk); findings still
  come only from executed SQL. Note: the prompt lives in the **ai-server**
  component — coordinate that change alongside this one; the platform-api
  side only adds the context field, which the AI server ignores until its
  prompt uses it (safe to ship independently).
- Do not add KG context to the interpret step; grounding the planner is the
  win, and interpret prompts are per-analysis and budget-sensitive.

### 1b. Staleness stamp on the Home snapshot

Computed at read time — **no migration, no background jobs**:

- In `GET /home-intelligence/snapshot` (`home_intelligence.py:468`): load the
  user's snapshot; for the projects in its payload, query `KnowledgeGraph`
  rows and compare `last_successful_build_at` (fallback: the KG
  `updated_at` / current fingerprint mismatch) against the snapshot's
  `updated_at`. Respond with:
  - `staleProjects: [projectId, ...]` — projects whose KG rebuilt after the
    snapshot was written;
  - `stale: bool` — any of the above.
- Frontend: when `stale`, show a non-blocking banner — "Data changed in N
  project(s) since this briefing" — with the existing Refresh action. No
  automatic AI run.
- Cost: one indexed query per snapshot read.

### Phase 1 tests

1. `run_ai_intelligence` includes `knowledge_graph_context` in the plan
   payload when a graph exists, and an empty block (not an error) when it
   doesn't (monkeypatch the AI client, assert the payload).
2. Snapshot endpoint returns `stale=false` when no KG build postdates the
   snapshot, `stale=true` + correct `staleProjects` when one does.
3. A KG collector exception does not fail the run (existing fail-open path).

## Phase 2 — shared per-project results

### Decision gate (confirm with product before building)

Sharing analysis results across users assumes **project membership is the
visibility boundary** — everyone who can open a project may see the same
cards. Today each run executes SQL as the requesting user; if any per-user,
row-level, or visibility-scoped data differences exist *within* a project,
shared results would leak. Verified assumption to confirm: `_has_access` is
project-level and card content does not vary by user. If it does vary,
Phase 2 must key the cache by visibility cohort instead — decide first.

### 2a. Schema (migration `0060`)

New table `business_insight_results`:

| column | notes |
|---|---|
| `tenant_id`, `project_id` | FK, indexed |
| `granularity` | int; part of the key |
| `kg_version_id` | nullable FK to `knowledge_graph_versions` — the graph the result was built against |
| `source_fingerprint` | the KG fingerprint at build time (covers projects with no KG version yet) |
| `payload` | JSONB — the cards list (`ProjectResult` shape used in run results) |
| `built_by` | user id the SQL ran as (project owner for background builds) |
| unique | `(tenant_id, project_id, granularity)` |

### 2b. Cache-aware worker

In `analyze_project_intelligence` (`app/tasks/workflows.py`), before running
`_run_for_project`:

- Look up `business_insight_results` for `(project, granularity)`. **Fresh**
  means: `kg_version_id` equals the project's currently active KG version
  (or fingerprints match) **and** age < `business_insight_result_ttl_seconds`
  (default 24h, a safety net for data paths no fingerprint watches).
- Fresh hit → write the cached cards to the run's Redis result store and
  finalize as today. Near-zero AI cost; the user's SSE completes in seconds.
- Miss/stale → run the analysis as today, then upsert the cache row with the
  active KG version + fingerprint. All existing capacity controls (tenant
  slots, retries, self-timeout) stay exactly as they are.
- Per-user synthesis (`synthesise_cross_project`) still runs per run — it
  must reflect that user's project set. It is one AI call over summaries;
  acceptable.

### 2c. Event-driven refresh (the affordable version)

- In `rebuild_knowledge_graph` (worker), after a successful build for a
  project: enqueue `refresh_business_insight_result` (deterministic job id
  `bi-result:{tenant}:{project}`, `_defer_by=120`) — a new task that re-runs
  the analysis once at the default granularity, attributed to the **project
  owner** (`resolve_representative_user`), and upserts the cache. Guard it
  with an activity gate: skip unless some user ran Home for this tenant
  within `business_insight_refresh_activity_days` (default 7) — check
  `IntelligenceSnapshot.updated_at` — so idle tenants consume zero AI.
- Net effect: a data change triggers exactly one analysis per project
  regardless of user count; every user's next Home open (or the Phase 1
  stale banner's Refresh) assembles from warm results.
- Optional later: auto-push — after refreshing results, rewrite affected
  users' `IntelligenceSnapshot` rows so even the banner disappears. Defer
  until cache hit rates are proven.

### 2d. Rollout & controls

- Feature flags: `business_insight_shared_cache_enabled` (2b) and
  `business_insight_event_refresh_enabled` (2c) — ship 2b first, observe hit
  rates, then enable 2c.
- New settings: `business_insight_result_ttl_seconds`,
  `business_insight_refresh_activity_days`.
- Register the new task in `WorkerSettings.functions`; verify `job_timeout`.

### Phase 2 tests

1. Cache hit: worker writes cached cards to the run store without calling
   `_run_for_project` (monkeypatch + assert).
2. Cache invalidated by a newer KG version; TTL expiry forces a rerun.
3. `refresh_business_insight_result`: activity gate skips idle tenants;
   deterministic job id coalesces; owner attribution.
4. End-to-end: KG build success → refresh enqueued → cache updated → a
   subsequent run for a *different user* hits the cache.

## Invariants

- KG context in prompts is hypotheses, never asserted findings — insights
  remain grounded in executed SQL.
- Everything downstream of the KG fires only after a build **activates**
  (never mid-build), and every trigger is fail-open and coalesced.
- Shared results are served only through the existing project access check;
  the cache never widens visibility.
- Background AI work is bounded by tenant activity and per-tenant capacity
  slots — a data-change storm cannot outspend today's interactive load.

## Sequencing

1. Phase 1a + 1b together (small; 1a needs the ai-server prompt change).
2. Project Insight plan (separate doc) — independent, can run in parallel.
3. Phase 2 decision gate → 2a/2b → observe → 2c.
