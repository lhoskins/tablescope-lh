# Devin merge/deploy instructions: fix docked AI Assistant contradicting the Project Insight page

## Branch
`fix/ai-action-proposals-insights-suite-sync` (same branch as the prior AI Action Proposals `insights`-suite sync fix; this is a follow-up commit).

## Bug report

On a project's Project Insight page, the page's own Risk card said "Budget vs actual variance is unfavorable for COGS and Opex while Revenue is favorable" (Opex variance $1,021,606.19). Asking the docked AI Assistant "Give me a summary on budget vs actual is unfavorable for COGS and OPEX" on the *same page* returned "No unfavorable budget vs actual results for COGS and OPEX are returned in the live query result provided," with an unrelated "Forecast consistently exceeds budget" card offered as a suggestion.

## Root cause (traced end-to-end, two compounding defects)

1. **The correct card was never a candidate.** `insight_card_match.py::_cards_for_projects` — which supplies every candidate the chat's insight-card matcher can possibly pick from — only read two sources: the separate Business Insight home-page cache (`BusinessInsightResult`) and the `project_insight` suite (`ProjectIntelligenceSnapshot.suite == "project_insight"`), via `insight_registry.load_project_insight_snapshot_cards`. It never read `suite == "insights"` — the suite written by `rebuild_project_insights_cards` that is what the Project Insight page's Risks/Trends/Opportunities/Analysis tabs actually render (see the prior `fix: wire AI action proposal sync into the insights-suite cards rebuild` commit on this same branch, which hit the identical gap for a different consumer). So the exact "Budget vs actual ... COGS and Opex" card the user was looking at could never be offered as a match candidate, no matter how the question was phrased.

2. **Even among the candidates it did see, matching skipped the LLM relevance check.** `conversational_analytics/__init__.py`'s call to `find_matching_insight_cards` passed `use_llm=False`, falling back to a raw keyword-overlap heuristic (`insight_card_match._data_shape_score`) instead of the LLM selector the module is designed around. That heuristic surfaced a topically-adjacent-but-wrong "Forecast" card purely on term overlap.

With the correct card invisible to the candidate pool (#1) and no LLM check to catch a wrong pick among what candidates did exist (#2), the chat had nothing to reconcile its live SQL result against and reported it as the answer.

## Fix

- `platform-api/app/services/insight_registry.py`: added `load_project_insights_suite_cards()`, reading `ProjectIntelligenceSnapshot.suite == "insights"` and parsing its flat `payload["insights"]` list (mirrors `load_project_insight_snapshot_cards`'s existing pattern for the other suite).
- `platform-api/app/services/insight_card_match.py`: `_cards_for_projects` now also calls the new loader per project, deduped against titles already seen from the cache/`project_insight` suite.
- `platform-api/app/services/conversational_analytics/__init__.py`: removed the `use_llm=False` override on the `find_matching_insight_cards` call in `execute_turn`, restoring the LLM-verified relevance check (its default).
- `platform-api/tests/test_canonical_conversations.py`: updated one test docstring that had documented the now-removed `use_llm=False` behavior as a design rationale (its actual assertion was unaffected -- that suite never enables the AI client, so the LLM branch was already unreachable there).

No frontend changes -- purely a backend candidate-pool and relevance-check fix.

## Testing performed (real, not deferred)

```
cd platform-api
python -m pytest tests/test_insight_card_match.py tests/test_canonical_conversations.py -q   # 27 passed (1 new)
python -m pytest -q                                                                            # 1947 passed, 12 failed, 4 skipped
```

New test: `test_offers_the_callers_insights_suite_snapshot_cards` in `test_insight_card_match.py` -- seeds a `suite="insights"` snapshot with a card shaped exactly like the real "Budget vs actual variance is unfavorable for COGS and Opex" risk card (title + `callout`), asks a matching question, and asserts the card is offered to the selector and selected.

The 12 full-suite failures are the same pre-existing, unrelated failures already documented in `docs/devin-ai-action-proposals-insights-suite-sync-merge-deploy.md` (billing/VPN provisioning, chart visualization defaults, percent-change stats, business-insight-phase1 staleness) -- reproduced identically before this change, confirmed unrelated by diff scope.

## Merge

```
git fetch origin fix/ai-action-proposals-insights-suite-sync
git checkout UX-design-03   # or the current default/integration branch
git merge --no-ff origin/fix/ai-action-proposals-insights-suite-sync
git push origin UX-design-03
```

## Deploy

Backend-only, no migration, no schema change. Restart/redeploy the API process (this path runs in the request handler for `/api/conversational-analytics/canonical-turns`, not a background worker).

## Post-deploy verification

1. On a project with a visible "Caution:"-labeled Risk card on its Project Insight page, open the docked AI Assistant and ask a question that names the same finding (e.g. "Give me a summary on budget vs actual is unfavorable for COGS and OPEX").
2. Confirm the response either answers consistently with the visible Risk card, or (if the live SQL genuinely differs) surfaces the *correct* matching card -- not an unrelated one -- as "EXISTING INSIGHT."
3. Note: this fix makes the correct card reachable and restores LLM-verified relevance; it does not yet make the primary answer text automatically reconcile against a contradicting matched card when both are present -- that is a separate, larger behavioral change (flagged, not in scope here).
