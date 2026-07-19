# Devin prompt: Business Insights integration (backend already implemented)

> Run order: execute this prompt FIRST, then the Project Insight prompt
> (`devin-prompt-project-insight-rebuild.md`) — its KG-build hook lands next
> to the Business Insight hook this merge brings in.

---

Task: Integrate and finish the Business Insights work in
`lhoskins/tablescope-lh`.

IMPORTANT: the backend for both phases is **ALREADY IMPLEMENTED** on branch
`claude/validate-enhance-logic-r2fyy1` — do NOT re-implement it. The design is
in `docs/business-insights-kg-grounding-phased-plan.md`; the implementation
commits are `131ee30` (Phase 1: KG grounding + snapshot staleness) and
`1828ffd` (Phase 2: shared per-project result cache). Your job is merge,
frontend, rollout, and verification.

## What already exists on the branch

- **Phase 1a**: `run_ai_intelligence` passes a `knowledge_graph_context` block
  (capped, fail-open) to the AI plan call; the ai-server
  (`ai-server/tablescope-ai-api`, same repo) renders it as a
  `KNOWLEDGE GRAPH HYPOTHESES` prompt section with a validate-with-SQL
  framing.
- **Phase 1b**: `GET /api/ai/home-intelligence/snapshot` now returns
  `stale: bool` and `staleProjects: [projectId strings]`.
- **Phase 2**: `business_insight_results` table (migration 0059),
  `business_insight_cache` service, cache-aware
  `analyze_project_intelligence` (serves shared cards to any user passing the
  project access check, marks them `fromCache: true`), and a
  `refresh_business_insight_result` task enqueued after successful KG builds
  (debounced, activity-gated, owner-attributed, capacity-slotted).
- **Feature flags, all default OFF** (deploy is behavior-neutral):
  `business_insight_shared_cache_enabled`,
  `business_insight_event_refresh_enabled`.

## Your tasks

1. **Merge** `claude/validate-enhance-logic-r2fyy1` into the target feature
   branch. Then from `platform-api/`: `pytest` (698 tests must pass) and
   `ruff check app tests`; from `ai-server/tablescope-ai-api/`: `pytest`
   (47 tests must pass).
2. **Frontend — Home staleness banner**: read `stale`/`staleProjects` from
   `GET /api/ai/home-intelligence/snapshot`. When stale, show a non-blocking
   banner "Data changed in N project(s) since this briefing" with the
   existing Refresh action. Do not auto-trigger an AI run from the banner.
3. **Frontend — optional polish**: results carrying `fromCache: true`
   complete almost instantly in the SSE stream; make sure the per-project
   loading states handle near-immediate completion gracefully.
4. **Deploy/rollout, in this order**:
   1. Run alembic migration 0059. Deploy platform-api, the arq worker
      (`platform-api-worker`), AND the ai-server together (the plan-prompt
      change and the platform payload field ship as a pair; each is
      backward-compatible alone, but deploy both to get the grounding
      benefit).
   2. Enable `business_insight_shared_cache_enabled`. Observe worker logs for
      `fromCache` hit rates over a few days of normal use.
   3. Then enable `business_insight_event_refresh_enabled` to complete the
      chain: data change → KG rebuild → warmed shared cards → instant Home
      refresh.
5. **Monitoring to confirm it works**: worker logs show
   `refresh_business_insight_result` runs after KG builds (skipped with
   reason `no_recent_activity` for idle tenants); a second user's Home run
   for an unchanged project completes from cache without AI calls; Home plans
   start citing graph-surfaced items (the plan prompt now contains a
   `KNOWLEDGE GRAPH HYPOTHESES` section when a project has a graph).

## Do not change

The freshness rule (active KG version match + TTL), the hypotheses-to-test
prompt framing (it is the guard against AI-derived graph nodes laundering
themselves into findings without SQL evidence), the activity gate, or the
per-tenant capacity slotting. If any test conflicts arise in the merge,
resolve toward the branch's behavior — it is the tested state.
