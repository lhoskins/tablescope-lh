# Devin merge/deploy instructions: chat-created queries & dashboards ("create governed artifacts from persistent chats")

## Source
`codex/ai-action-proposals-closed-loop` @ `0a5432771e366c0c05dbc694bfc333f4e590513f` ("feat: create governed artifacts from persistent chats"), reported complete and published, 12 files changed, no migration.

That commit was **1 ahead, 13 behind `UX-design-03`** at report time -- do not merge it directly onto an old base. This doc instead points at a ready-to-merge branch built from the correct base.

## Branch to merge
`devin/merge-ai-chat-artifacts` -- created from the latest `origin/UX-design-03` (`159f2bb0`, which already includes the separately-merged `fix/ai-action-proposals-insights-suite-sync` AI Assistant fix), with the codex commit merged in via `git merge --no-ff`, plus one follow-up commit fixing issues found during validation (below). Auto-merged cleanly -- no conflicts.

## What the feature does (validated by reading the full diff, not just the summary)

Two new deterministic chat commands, both ending in an explicit confirmation step -- nothing is ever persisted from a chat turn without the user clicking through:

- **"Create a query that shows X"** (or "save this/that/the result as a query"): runs the normal ask-and-run pipeline (or, for the "save this" phrasing, reuses the immediately preceding turn's already-validated SQL/result with no new AI call), then attaches a pending `artifactProposal` to the turn. Accepting it (`POST .../turns/{id}/artifact-decision`) creates a `SavedQuery` server-side from the already-executed SQL -- never regenerates it.
- **"Create a dashboard for X"** (or "save/turn this as a dashboard"): persists only a proposal, no SQL is run from the chat turn at all. "Review & create" opens the *existing* `AIDashboardDesigner` (unchanged, already has its own query generation/validation/preview), and only once that flow completes does the chat call `artifact-decision` with the resulting dashboard id to close out the proposal.
- Both intents are recognized by a small deterministic regex grammar checked *before* the LLM classifier, so the confirmation gate is reached even when the AI service is disabled (SQL generation for a brand-new query still needs AI, by nature -- only the intent/gating decision is guaranteed deterministic).
- `artifact-decision` is idempotent (row-locked via `SELECT ... FOR UPDATE`, checked against `proposal.status` before acting) -- a double-click or retry cannot create a duplicate `SavedQuery` or re-record a dashboard id.

## Validation performed this pass

Read every changed file's full diff (not the author's summary) across both the backend intent classifier/turn-execution/route layer and the frontend confirmation card/chat screens/API client. Traced the authorization path (`require_role(Role.EDITOR)` + `_check_project_access`, the same pattern every other turn route in this file already uses), the `SavedQuery`/`Dashboard` model fields actually used, and the reused `AIDashboardDesigner` props (`mode`, `initialPrompt`, `onApplied`, `notify` all already exist on that component -- no missing integration).

**Two real issues were found and fixed** (not present in the original commit, fixed on top of it in `devin/merge-ai-chat-artifacts`):

1. **Bug**: `_SAVE_AS_QUERY`/`_SAVE_AS_DASHBOARD` only matched a bare demonstrative ("save **this** as a query") or "the `<noun>`" ("save **the result** as a query") -- never both together ("save **this result** as a query"), which is at least as natural a way to phrase the request. That phrasing fell through to the generic analytical path instead of the intended deterministic reuse-prior-turn path, silently regenerating SQL -- directly contradicting the code's own comment ("it must not ask the model to regenerate a potentially different query"). Fixed in `platform-api/app/services/conversational_analytics/intent_classification.py` by making the noun optional after the demonstrative.
2. **Broken existing test**: `project-chats-screen.tsx` now always mounts `AIDashboardDesigner` (needed for the dashboard-proposal review flow), which calls `useRouter()` unconditionally on mount. `project-chats-screen.test.tsx` had no `next/navigation` mock and started failing with "invariant expected app router to be mounted" on both of its existing tests. Fixed by adding the same mock `ai-dashboard-designer.test.tsx` already uses for its own tests.

No other correctness, security, or integration issues found. The route reuses the codebase's standard project-access pattern; `SavedQuery`/`Dashboard` field usage matches their models exactly; the frontend's dashboard-accept flow correctly calls `artifact-decision` after the designer applies its own separately-governed design, with a non-fatal toast if that follow-up call fails (dashboard still exists either way).

## Testing performed (real, this session, not deferred)

```
cd platform-api
python -m pytest tests/test_conversational_analytics.py -q       # 29 passed (8 new/updated)
python -m pytest tests/test_conversational_analytics.py \
  tests/test_canonical_conversations.py \
  tests/test_insight_card_match.py \
  tests/test_ai_dashboard_designer.py -q                          # 91 passed
python -m pytest -q                                                # 1953 passed, 12 failed, 4 skipped

cd ../web-ui
npx tsc --noEmit -p tsconfig.json                                  # clean, no errors
npx vitest run                                                     # 622 tests, 10 failed / 612 passed
```

New/updated backend tests (4 added on top of the original commit's 2): dashboard-accept with a real created `Dashboard` id (plus rejecting one from another project -- 404), `artifact_kind` mismatch (409) and missing-turn (404) on the decision endpoint, the "save this as a query" prior-turn-reuse path end to end (asserts the SQL generator is called exactly once, not twice), and a unit test pinning the demonstrative+noun phrasing fix.

The 12 backend failures and 10 frontend failures are pre-existing and unrelated: billing/VPN provisioning, chart visualization defaults, percent-change stats, business-insight-phase1 staleness (backend); `IntelligenceCard`/`ChartSuggestionDialog` missing a `QueryClientProvider` in that one test file (frontend). Confirmed by reproducing the frontend one identically on the unmodified main tree before this branch existed, and by diff-scope for the backend ones (same 12, already documented in two earlier merge/deploy docs this repo has from unrelated prior work).

## Merge

```
git fetch origin devin/merge-ai-chat-artifacts
git checkout UX-design-03   # or the current default/integration branch
git merge --no-ff origin/devin/merge-ai-chat-artifacts
git push origin UX-design-03
```

No migration. No schema change.

## Deploy

Backend + frontend change, no background worker involvement (everything runs in the request handler for `submit_turn`/`create_conversation`/`decide_artifact_proposal`). Redeploy the API and the web-ui build as usual for this repo's normal release process.

## Post-deploy verification

1. In a project's Chats page, type "Create a query that shows sales by month." Confirm a pending "AI Query" confirmation card appears below the answer with **Save query** / **Reject** buttons, and that `/projects/{id}/queries` shows nothing yet.
2. Click **Save query**. Confirm the card flips to "Created," a link to open the query appears, and the query now shows up under Project Queries.
3. Reload the same turn (or click Save query again) -- confirm it does not create a second `SavedQuery` (idempotent).
4. Ask a normal analytical question, then follow up with "Save this result as a query" (the exact phrasing the original commit's regex missed). Confirm it proposes a query grounded in the *same* SQL/result as the prior turn, not a freshly regenerated one.
5. Type "Please build a dashboard for revenue and backlog trends." Confirm a pending dashboard card appears with a **Review & create** button, and that no dashboard exists yet.
6. Click **Review & create**, complete the existing dashboard designer flow. Confirm the chat card updates to "Created" with a working link, and the dashboard exists under Project Dashboards.
7. Repeat both flows on the general `/ai` Assistant page (not just the project-scoped Chats page) to confirm the same wiring there.
