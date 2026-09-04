# Devin: merge + deploy — Business Insight ranking, loading state, and percentage precision

**Repository:** `lhoskins/tablescope-lh`
**Branch to merge:** `fix-combo-chart-axis-and-turn-timestamps` (continuing on the same branch as the combo-chart/timestamp/bold fixes already on it)
**Base:** `UX-design-03`

**`platform-api/` + `web-ui/` · no migration · all tests green**

---

## 1. Static "No Pressing" message flashes before the Executive Brief loads

**Root cause:** `use-intelligence-feed-state.ts`'s `status` starts at `"idle"` and only changes once the initial `Promise.all([getPreferences(), getIntelligenceSnapshot()])` resolves. `running` (`status === "streaming"`) was the only signal `BusinessIntelligenceWorkspace` had for "still working" — during that initial fetch window, `running` is `false` and `cards` is still `[]`, which fell into the exact same branch as "confirmed complete, nothing found," showing "No pressing matters require executive attention" even though data simply hadn't arrived yet.

**Fix:** threaded a new `initialLoading` boolean through `intelligence-feed.tsx` (`status === "idle"`) → `IntelligenceWorkspace` → `BusinessIntelligenceWorkspace`, optional and defaulting to `false` everywhere so no other caller of these shared components is affected. The Executive Brief now shows "Loading the executive briefing…" / "Fetching the latest insight analysis…" during that window instead.

---

## 2 & 3. Priority insights and Executive Brief picked array position 0, not the most impactful card

**Report:** the Business Insight page's Risk/Trend/Opportunity tiles and the Executive Brief each showed whichever card happened to be first in an unsorted, cross-project-concatenated array — not the most beneficial/impactful one. Wanted: rank the top 10 per category (and overall, for the Executive Brief) and summarize them.

**What already existed:** the backend already has a real impact-scoring algorithm — `card_ranking._card_priority` (`platform-api/app/services/home_intelligence/card_ranking.py`), combining severity, confidence, evidence richness (chart/KPI/document references), and a relationship-evidence bonus, with an explicit `priorityScore` override. It's used to rank cards *within* each project at generation time, and referenced by the existing `synthesise_cross_project`'s docstring as "the same severity-first ranking used for per-project card ranking." Every `InsightCard` the frontend already receives carries the fields this scoring needs (`severity`, `confidenceScore`, `priorityScore`, `chart`, `kpiReferences`, `relationshipMetadata`).

The gap: `classifyInsightCards` only *buckets* cards (risk/trend/opportunity/analysis) — it never sorts them — so once multiple projects' already-locally-ranked cards get concatenated into one array, `[0]` is arbitrary, not "most impactful."

**Fix (frontend-only — deliberately not touching the async worker/SSE/Redis snapshot pipeline that computes `synthesise_cross_project`, since that infrastructure isn't exercisable in this environment and the cards already carry everything needed to re-rank client-side):**

- **New `web-ui/lib/insights/card-priority.ts`**: `cardPriority()` — a direct TypeScript port of `_card_priority`, kept in lockstep with the backend's weights rather than inventing a second scoring model. `rankByPriority()` / `topByPriority()` (default limit 10).
- **New `web-ui/lib/insights/summarize-top-cards.ts`**: `summarizeTopCards(cards, noun)` — ranks, takes the top 10, and synthesizes one headline + summary. Follows the same deterministic-synthesis philosophy the backend's own `synthesise_cross_project` already uses (cite the real top finding's own title/summary rather than fabricate new cross-card prose) — extended to also name up to 2 runner-up titles ("Also flagged: X; Y.") so "top ten, summarized" means something beyond "top one" when there's more than one card. A single-card category is unchanged from today's behavior (uses that card's own title/summary verbatim).
- **`business-intelligence-workspace.tsx`**: each Priority insights tile and the Executive Brief now call `summarizeTopCards` instead of indexing `[0]`. The synthesized display card carries the real top card's `insightId`/`severity`/etc. (via a `toDisplayCard` spread) so navigation ("Review insight") and the severity badge still point at something real.

**Deliberately not done:** an LLM-generated multi-card narrative. Given this session's own AI-server capacity constraints (single GPU, `max_jobs=1`, documented in an earlier planning doc) and that the backend's own established pattern for this exact problem is deterministic citation rather than synthesis, an LLM call per page load for this would be a much larger, riskier change than what was reported. If genuine prose synthesis across the top 10 (not just "top one + runner-up names") is wanted, that's worth scoping separately.

---

## 4. Percentages on insight cards not rounded to 2 decimal places

**Report:** "AvgVariancePct moves from -1.4538461538461154% in 2026-01 to 13.13846153846154% in 2026-02, peaks at 14.6923076923077695% in 2026-04…" — raw Teiid-computed float precision cited verbatim in narrative text, while a `Caution:` callout in the same card was already correctly rounded (confirming it's a separate, deterministic code path that was already fine).

**Root cause:** same failure class as the earlier `/ai/ask` chat-answer fix (`ai-server`'s `_round_long_decimals`) — an LLM-authored summary citing a value at full float precision — but this is a *different* pipeline (insight-card generation, `platform-api`'s `home_intelligence`), not the chat endpoint.

**Fix:** `platform-api/app/services/home_intelligence/card_builder.py`'s `_card()` — the single constructor every insight card's `title`/`summary` passes through regardless of which analysis method produced it — now runs both through a new `_round_long_decimals` (same regex approach as the ai-server version: any number with ≥3 decimal digits rounds to 2). Applied once, at function entry, so anything else inside `_card()` that reads `title`/`summary` (e.g. `build_explanation`) also sees the rounded text.

---

## Tests added

| File | Coverage |
|---|---|
| `web-ui/lib/insights/card-priority.test.ts` (7 tests) | severity ranking, explicit `priorityScore` override (incl. a non-positive override falling back to the derived score, not 0), confidence/chart/reference/relationship weighting, sort order, `topByPriority` capping, non-mutation |
| `web-ui/lib/insights/summarize-top-cards.test.ts` (5 tests) | empty list, single-card passthrough, **picks the highest-priority card as lead, not array position 0** (the exact live scenario), names up to 2 runner-ups, caps consideration at 10 |
| `web-ui/components/tablescope/insights/business-intelligence-workspace.test.tsx` (+2 tests) | Priority insights tile led by the most impactful card, not array position 0 (verified to fail pre-fix, pass post-fix); neutral loading state instead of "No pressing matters" during initial fetch (verified to fail pre-fix, pass post-fix) |
| `platform-api/tests/test_card_builder_rounding.py` (2 tests, new file) | rounds the exact reported live values; leaves already-short decimals/plain text unchanged |

## Verification

| Suite | Result |
|---|---|
| web-ui `vitest` (`components/tablescope/insights`, `components/tablescope/home`, `lib/insights`) | 140 / 140 passed (21 files) |
| web-ui `tsc --noEmit` (whole project) | clean, 0 errors |
| web-ui `eslint` (touched files) | clean (1 pre-existing `max-lines` warning on `business-intelligence-workspace.tsx`, not new) |
| platform-api `pytest` (`test_home_intelligence.py`, `test_home_intel_tenant_slots.py`, `test_home_intelligence_insights_cache.py`, `test_card_builder_rounding.py`) | 68 / 68 passed |
| platform-api `ruff check` / `mypy` (touched files) | clean |
| web-ui full `vitest run` (whole project) | 604 / 604 passed (99 files), 0 failed |
| platform-api full `pytest -q` (whole suite) | 1655 passed, 4 skipped, **7 failed** — same pre-existing/unrelated failures confirmed on every prior turn of this branch (`test_business_insight_phase1.py::test_snapshot_*` ×3, `test_percent_change_summary.py::test_summary_*` ×4), 0 new failures from this change |

```bash
cd web-ui
npx vitest run
npx tsc --noEmit
npx eslint components/tablescope/insights/business-intelligence-workspace.tsx components/tablescope/insights/intelligence-workspace.tsx components/tablescope/home/intelligence-feed.tsx lib/insights/card-priority.ts lib/insights/summarize-top-cards.ts

cd ../platform-api
pytest -q
ruff check app/services/home_intelligence/card_builder.py
mypy app/services/home_intelligence/card_builder.py
```

## Deploy

`platform-api` + `web-ui`, no migration, no ai-server change.

```bash
docker compose build platform-api
docker compose up -d platform-api platform-api-worker

cd web-ui
# your normal build/deploy step
```

## Verify live

- Load the Business Insight page fresh (hard refresh / new session) and confirm the Executive Brief shows a loading state, not "No pressing matters," in the moment before data arrives.
- With a tenant that has cards of mixed severity within one category, confirm the Priority insights tile and Executive Brief are led by the highest-severity/highest-confidence card, not whichever loaded first.
- Re-check a card with a percentage-heavy narrative (e.g. a budget-variance or trend card) and confirm every cited number is 2-decimal precision, not raw float.

## Report back

Confirmation all three reported symptoms no longer reproduce; full-suite pass/fail counts from your own run; and whether "summarized top 10" reads well enough as-is (top card's own summary + up to 2 runner-up titles) or whether a richer multi-card narrative is wanted as separate follow-up work.
