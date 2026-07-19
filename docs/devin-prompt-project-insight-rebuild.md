# Devin prompt: Project Insight event-driven rebuild (full implementation)

> Run order: execute the Business Insights integration prompt
> (`devin-prompt-business-insights-integration.md`) FIRST — its merge brings in
> the `rebuild_knowledge_graph` hook this task adds a sibling to, which avoids
> a merge conflict in that function.

---

Task: Implement the Project Insight event-driven rebuild with
stale-while-revalidate hydration in `lhoskins/tablescope-lh`.

Base your work on branch `claude/validate-enhance-logic-r2fyy1` — it contains
the event-driven Knowledge Graph lifecycle and the completed Business Insights
work this builds on. The full specification is in the repo at
`docs/project-insight-event-driven-rebuild-plan.md`. Follow it exactly, with
ONE correction: the plan reserves migration 0059, but 0059 has since been
taken by `business_insight_results` — create the `is_stale` migration as
**0060** (revises 0059).

Summary of the required changes (details, file paths, and line references are
in the plan doc):

1. **Migration 0060**: add `is_stale` (bool, not null, server_default false,
   indexed) to `project_intelligence_snapshots`, and add the column to the
   `ProjectIntelligenceSnapshot` model in
   `platform-api/app/models/project_intelligence_snapshot.py`.
2. **Replace both delete-on-change invalidation sites**
   (`document_processing_service.py` and `reference_library_processing.py`)
   with mark-stale (`is_stale=True` for the tenant/project, all users, all
   suites) plus a best-effort enqueue of the new rebuild task. Keep the
   try/except fail-open pattern those sites already use.
3. **Add a third trigger** in
   `platform-api/app/tasks/workflows.py::rebuild_knowledge_graph`: after a
   build with status `"succeeded"`, mark stale + enqueue. Put it alongside the
   existing Business Insight refresh hook that is already there — same
   pattern, same best-effort guard. Do not put insight logic inside
   `KnowledgeGraphLifecycleManager`.
4. **New arq task `rebuild_project_insight` + enqueue helper** in
   `workflows.py`: deterministic job id
   `project-insight:{tenant_id}:{project_id}`, `_defer_by=60`. The task:
   (a) exits if no snapshot row for the project is stale (stale gate);
   (b) rebuilds only for users who already have a snapshot row for the
   project, most recently updated first, capped by a new setting
   `project_insight_max_rebuild_users` (default 10);
   (c) runs `build_project_insight` per user via `_worker_context` (per-user
   because acknowledgement state is merged per user), upserting the snapshot
   with `is_stale=False`;
   (d) wraps the AI-heavy section in
   `home_intel_queue.acquire_tenant_slot`/`release_tenant_slot` and maps
   retryable `AIUnavailableError` onto arq `Retry`, mirroring
   `analyze_project_intelligence`;
   (e) per-user failures are logged and skipped.
   Register the task in `WorkerSettings.functions`.
5. **Route changes** in `platform-api/app/routes/project_insight.py`:
   `GET /{project_id}/insight` includes `stale` and `generatedAt` in the
   response; `refresh=true` completion writes `is_stale=False`. Keep the
   synchronous build path for users outside the rebuild audience.
6. **Feature flag** `project_insight_event_rebuild_enabled` (default False):
   when off, mark-stale still replaces delete (strictly better than today)
   but no enqueue.
7. **Frontend**: hydrate from the snapshot; if `stale`, show a subtle
   "updating…" indicator and re-fetch until `stale=false`. Remove the
   unconditional background `refresh=true` re-run on every page open — only
   trigger it when the snapshot is stale or the user explicitly refreshes.
8. **Tests**: follow the six test cases listed in the plan doc under "Tests".
   Model your worker-task tests on
   `tests/test_business_insight_shared_cache.py` (it shows how to bind
   `SessionLocal` to the test engine and fake the Redis queue helpers) and
   use `tests/test_knowledge_graph_event_triggers.py` for the trigger-site
   pattern.

**Invariants (do not violate):** enqueue only after the triggering data
commits; every trigger is fail-open (an insight failure never fails document
processing, reference-library processing, or a KG build); coalesce via
deterministic job ids + defer + the stale gate; builds run as the snapshot's
owning user, never a synthetic admin. Preserve stable `insightId` handling —
acknowledgements are keyed by it.

**Verification:** from `platform-api/` run `pytest` (697 tests currently pass
— all must still pass plus your new ones) and `ruff check app tests`. Do not
modify the Business Insights code paths except the one hook addition in
`rebuild_knowledge_graph`.
