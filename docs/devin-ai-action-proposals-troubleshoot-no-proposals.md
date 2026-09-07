# Devin: troubleshoot — Project Insight refreshes, but no AI action proposals appear

**Repository:** `lhoskins/tablescope-lh`
**Reported symptom:** Project 37. Clear-cache + refresh completes (Project Insight shows fresh, non-stale content), but **Pending review stays at 0** — no new AI action proposal is ever created.
**This is a live-environment diagnostic, not a known code bug.** The closed-loop AI action proposals feature (`docs/devin-ai-action-proposals-closed-loop-merge-deploy.md`) was validated with 1945+ passing backend tests before merge, including the exact `sync_ai_action_proposals` path this symptom touches. The two most likely causes are both **operational** (a deploy step, or a config value), not application-code defects — this runbook is designed to prove which one, with an exact command for each step, rather than guess.

**Prior:** since Project Insight itself is producing fresh content (per the reported symptom, "new insights appeared"), and Project Insight's own risk/trend/opportunity cards are themselves AI-generated, the AI server is evidently reachable and enabled in this environment for *that* call path. That makes **Step 1 (migration)** the leading hypothesis — it's the one failure mode that specifically only breaks the proposal-sync half of the refresh while leaving insight generation itself completely unaffected, exactly matching what was reported. Still work the steps in order to confirm rather than jumping straight to Fix A, since `/ai/actions/draft` is a different endpoint than whatever generates the insight cards and could in principle have its own distinct config/routing issue.

## Why this needs production access

Nothing here can be diagnosed from a git checkout — it requires reading the live database and the `platform-api-worker` container's logs for project 37's tenant. Run every step below directly against production (or whichever environment reproduces the symptom).

---

## Step 1 — Confirm the migration actually applied

`sync_ai_action_proposals` reads/writes columns that only exist as of migration `0095` (`reviewer_user_id`, `goal_id`, `primary_metric_id`, `outcome_status`, `outcome_snapshot`, `outcome_refreshed_at`, etc. on `project_actions`). If this deploy's `alembic upgrade head` step didn't run (or failed silently), every one of those queries throws — and because the call site wraps the whole thing in `except Exception: logger.exception(...); await session.rollback()`, **the Project Insight refresh itself still looks completely successful to the user** while the proposal sync fails invisibly every time. This is the single most likely cause given the exact symptom reported (insights refresh fine, proposals never appear).

```bash
docker compose exec -T platform-api alembic current
# Expected: 0095 (head)
# If it shows anything earlier (e.g. 0094), that is the root cause -- skip to "Fix A" below.
```

If it's already at `0095`, continue to Step 2.

---

## Step 2 — Check `platform-api-worker` logs for the sync call's own diagnostics

The sync runs inside the `rebuild_project_insight` arq task (`platform-api/app/tasks/workflows.py`), one call per user with a stale snapshot, immediately after that user's snapshot commits. Find the run for project 37 and grep its logs:

```bash
docker compose logs platform-api-worker --since 30m | grep -i "project 37\|project_id=37"
```

Three possible outcomes, each pointing at a different cause:

### A. You see `"AI action proposal sync failed for project 37 user <id>"` with a traceback

The sync function raised. Read the traceback:
- **`UndefinedColumnError` / `column "..." does not exist`** → confirms Step 1's migration hypothesis even if `alembic current` looked right (e.g. a second, un-migrated read replica, or a schema drift). Go to **Fix A**.
- **Any other exception** (a real code bug) → capture the full traceback and treat this as a genuine defect report, not a config issue — this would be new information the validation pass didn't see. Do not guess a fix; get the exact traceback text first.

### B. You see `"AI action proposal skipped: generator unavailable"` (and the loop stops early for that user)

This is the `AIUnavailableError` path in `ai_action_proposals.py` — the AI server was reachable-but-erroring (timeout, 5xx) for this specific run. Go to **Fix B** to confirm AI-server health, then just try another refresh; this path is transient by nature.

### C. Neither log line appears at all

This is the important, easy-to-miss case: **when the AI service is simply disabled or not configured**, `generate_action_draft()` returns `None` with **zero logging** (`ai_intelligence_client/endpoints.py`'s own docstring: "Returns `None` when the AI service is disabled or unreachable" — this path never raises, so it never hits the `except AIUnavailableError` log line either). `ai_action_proposals.py`'s loop just does `if not isinstance(draft, dict): continue` and silently moves to the next card. From the outside this looks identical to "no qualifying insight card existed" — Step 3 and Step 4 below distinguish the two.

---

## Step 3 — Confirm the AI service is actually enabled and reachable

```bash
docker compose exec -T platform-api env | grep -i "TABLESCOPE_AI_ENABLED\|TABLESCOPE_AI_API_URL"
# Both default to disabled/empty (app/config.py: tablescope_ai_enabled: bool = False,
# tablescope_ai_api_url: str = "") -- given Project Insight itself already works,
# these are almost certainly already set correctly. This step is here to rule
# the possibility out definitively, not because it's the leading suspect.

docker compose ps ai-server
docker compose exec -T platform-api curl -sf "$TABLESCOPE_AI_API_URL/health" || echo "ai-server unreachable from platform-api"
docker compose exec -T platform-api-worker env | grep -i "TABLESCOPE_AI_ENABLED\|TABLESCOPE_AI_API_URL"
# Check the WORKER's environment too, not just platform-api's -- the worker is the
# process that actually calls generate_action_draft() for background refreshes,
# and it's possible for the two services' env to have drifted apart.
```

If `TABLESCOPE_AI_ENABLED` is false or the URL is empty/unreachable **on the worker specifically**, that's Step 2 Case C's cause. Go to **Fix C**.

---

## Step 4 — If AI is confirmed healthy and enabled, inspect what the refreshed report actually contained

Only `risks`, `trends`, `opportunities`, and `analysis` cards are eligible (`ai_action_proposals.py`'s `_CARD_KEYS`), and each one needs a non-empty `title` **and** a non-empty `recommendedAction` (or a `callout.text`) — cards missing either are silently skipped, by design, not a bug.

```sql
-- Run against the platform-api database.
SELECT payload -> 'risks' AS risks,
       payload -> 'trends' AS trends,
       payload -> 'opportunities' AS opportunities,
       payload -> 'analysis' AS analysis
FROM project_intelligence_snapshots
WHERE project_id = 37 AND suite = 'project_insight'
ORDER BY updated_at DESC
LIMIT 1;
```

Inspect each card in those arrays for a `title` and either `recommendedAction`/`recommended_action` or a populated `callout.text`. If none of them have both, there was genuinely nothing eligible to propose this refresh — not a bug, but worth flagging separately if this is happening consistently (a prompt-tuning question for whatever generates these cards, out of scope for this runbook).

---

## Step 5 — Rule out dedup (a prior proposal already covers the same finding)

Dedup checks **every non-permanently-deleted** action for the project — including already-archived ones, not just active ones:

```sql
SELECT id, status, source_insight_id, source_insight_fingerprint, archived_at, deleted_at, created_at
FROM project_actions
WHERE project_id = 37
ORDER BY created_at DESC;
```

If this returns zero rows, dedup is not the cause (nothing exists to be deduped against) — this is consistent with the reported symptom ("I do not have any actions created"). If it returns rows whose `source_insight_id`/`source_insight_fingerprint` match a card from Step 4's payload, that explains it: the finding was already proposed before (possibly archived, not permanently deleted), and dedup is correctly refusing to re-propose it.

---

## Fixes

**Fix A — migration not applied.**
```bash
docker compose exec -T platform-api alembic upgrade head
docker compose exec -T platform-api alembic current   # confirm: 0095 (head)
```
No code change needed. Trigger a fresh refresh afterward (clear-cache, or wait for the next event-driven rebuild) to confirm proposals now appear.

**Fix B — AI server transient error.** No action needed beyond confirming `ai-server` is healthy (`docker compose logs ai-server --since 30m`); retry the refresh. If this recurs consistently rather than once, treat it as its own incident (AI server capacity/config), not this feature's bug.

**Fix C — AI disabled/unreachable.** Set `TABLESCOPE_AI_ENABLED=true` and a valid `TABLESCOPE_AI_API_URL` in the platform-api (and platform-api-worker, since the worker is the process that actually calls `generate_action_draft` for background refreshes) environment, then restart both services. No code change needed.

**If none of Steps 1-5 explain it** — capture: `alembic current` output, the full worker log window for project 37's refresh, the Step 4 query result, and the Step 5 query result, and treat this as a genuine defect report. Do not attempt a speculative code fix without that evidence — every code path involved here was covered by the pre-merge test suite, so a real bug at this point would be either environment-specific (worth reproducing precisely) or a gap the tests didn't cover (worth a new regression test alongside the fix).

## Report back

State which of Steps 1-5 identified the cause, which Fix (if any) was applied, and confirm a subsequent refresh for project 37 actually produces a Pending review action. If it's Fix A or C, no code/PR is needed — this is a config/ops fix, not a merge.
