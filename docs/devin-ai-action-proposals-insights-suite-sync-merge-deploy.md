# Devin merge/deploy instructions: wire AI action proposals to the cards users actually see

## Branch
`fix/ai-action-proposals-insights-suite-sync` (based on `docs/ai-action-proposals-troubleshoot-no-proposals`, which already includes the merged AI Action Proposals feature and the reviewer-self-assignment/async fixes from `devin/merge-ai-action-proposals`).

## Root cause (confirmed, not speculative)

Project 37's Project Insight page (`/projects/37/insight`) was showing populated risk cards with "Caution: ..." text (e.g. "Unapproved capex totals >$7.2M vs $2.7M approved"), yet Pending Review stayed at 0 no matter how many times the page was refreshed. This was traced end-to-end, frontend to backend:

1. **Frontend**: `ProjectInsightScreen` (`web-ui/components/tablescope/project-insight/project-insight-screen.tsx`) renders its Risk/Trend/Opportunity/Analysis cards from `allInsightCards`, which comes from `suggestInsights()` → `POST /api/ai/home/insights` — **not** from `projectInsightApi.get()`. The `GET /insight` call only supplies header metadata (`lastUpdatedAt`, `project.name`, `stale`).
2. **Backend routing**: `POST /api/ai/home/insights` (`home_intelligence_suggestions.py::home_insights`) enqueues `rebuild_project_insights_cards` (plural — `app/tasks/workflows.py`), which writes a `ProjectIntelligenceSnapshot` row with `suite="insights"`.
3. **The bug**: `rebuild_project_insights_cards` never called `sync_ai_action_proposals`. Only two other producers of insight cards did:
   - `rebuild_project_insight` (singular, `suite="project_insight"`) — feeds only the page's header metadata, not the visible cards.
   - `business_insight_cache.store_result` — a separate cache table (`BusinessInsightResult`) used elsewhere.

   So the exact cards a user sees and calls "actionable" (populated `callout.text`, rendered with the "Caution:" label via `calloutLabel()` in `web-ui/components/tablescope/home/intelligence-card/intelligence-card.tsx`) were **never** passed through the eligibility check in `ai_action_proposals.py`. This matches Devin's DB finding exactly: 0 eligible cards in the `project_insight` suite snapshot, 6 eligible cards in the `insights` suite snapshot that the page actually renders.

This is a pure wiring bug, not a prompt-tuning issue and not a structural "deterministic cards can't be eligible" issue — the `insights`-suite cards are AI-authored and already carry `callout`/`recommendedAction`. They only needed the sync call.

## Fix

`platform-api/app/tasks/workflows.py` — `rebuild_project_insights_cards`: after committing the `suite="insights"` snapshot, call `sync_ai_action_proposals(cards=cards, source_surface="project_insight", kg_version_id=<project's active KG version>)`, mirroring the exact pattern already used by `rebuild_project_insight` and `business_insight_cache.store_result`. Failures are caught, logged, and rolled back — consistent with the other two call sites (best-effort, must never fail the cards rebuild itself).

No changes were made to `ai_action_proposals.py`'s eligibility gate (`_action_text()` / the `if not title or not action_text: continue` check) — it was already correct for AI-authored cards; it just was never being invoked on this suite.

## Testing performed (real, not deferred)

```
cd platform-api
python -m pytest tests/test_project_insight_rebuild.py -q          # 12 passed (1 new)
python -m pytest tests/test_ai_action_proposals.py \
  tests/test_home_intelligence_insights_cache.py \
  tests/test_project_actions.py -q                                  # 22 passed
python -m pytest -q                                                 # full suite (see CI/local run before merge)
```

New test: `test_rebuild_project_insights_cards_syncs_ai_action_proposals` in `tests/test_project_insight_rebuild.py` — stubs `_run_for_project` to return a risk card shaped exactly like the real "Caution: Unapproved capex ..." card (title + `callout`), stubs `generate_action_draft`, runs `rebuild_project_insights_cards`, and asserts a `pending_review` `ProjectAction` with `source_surface="project_insight"` and 2 subtasks was created.

## Merge

```
git fetch origin fix/ai-action-proposals-insights-suite-sync
git checkout UX-design-03   # or the current default/integration branch
git merge --no-ff origin/fix/ai-action-proposals-insights-suite-sync
git push origin UX-design-03
```

## Deploy

Backend-only change, no migration, no schema change. Restart/redeploy the API and the `arq` worker process(es) that run `rebuild_project_insights_cards` (same deploy unit as the rest of the AI Action Proposals feature already in production).

```
# example — adjust to your actual deploy tooling
docker compose build platform-api worker
docker compose up -d platform-api worker
```

## Post-deploy verification (project 37, or any project with visible "Caution:"/risk cards)

1. Open `/projects/37/insight`.
2. Click **Refresh** (or **Clear cache** then wait for the reload indicator to clear) so `rebuild_project_insights_cards` runs at least once post-deploy.
3. Confirm risk cards with "Caution:" text are still showing (unchanged UI).
4. Open `/projects/37/actions` → **Pending Review** group. Expect newly created `pending_review` actions grounded on those risk cards within the same run (subject to the existing `max_new_proposals=3` per sync and AI availability).
5. Check worker logs for `AI action proposal sync failed for project 37 user ...` — should NOT appear on a successful run. If it does, the exception message identifies the next issue (separate from this fix).
