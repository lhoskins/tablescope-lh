# Devin merge/deploy instructions: chat artifact confirmation card missing on 3 chat surfaces

## Branch
`fix/chat-artifact-card-missing-surfaces`, based on the current `UX-design-03` tip (`740d1bcd`, which already includes `devin/merge-ai-chat-artifacts` -- the "create governed artifacts from persistent chats" feature).

## Bug report

A user asked the docked Workspace AI Assistant panel to "create a dashboard for IT Incident Overview." The assistant replied "I prepared a dashboard request. Review the proposed design and its validated charts before creating anything." -- but no confirmation card, no "Review & create" button, nothing actionable appeared. The user reported: "I was expecting it to create a dashboard."

## Root cause

The chat-artifact feature (queries/dashboards proposed from a chat turn, requiring explicit accept before anything is created) was wired into exactly two chat surfaces: the general `/ai` Assistant page (`web-ui/app/ai/page.tsx`) and the project Chats page (`web-ui/components/tablescope/project/project-chats-screen.tsx`). Both render turns via `TurnBubbles` (plural, `web-ui/app/ai/turn-bubbles.tsx`), which was updated to render `ChatArtifactConfirmationCard` when a turn carries an `artifact_proposal`.

Three other chat surfaces render turns via a *different*, older component, `TurnBubble` (singular, `web-ui/components/tablescope/conversation/conversation-turn.tsx`), which was never touched by that feature:

- `web-ui/components/tablescope/project/workspace/workspace-assistant-panel.tsx` -- the docked "AI Assistant" panel present on every project page (matches the user's screenshot).
- `web-ui/components/tablescope/project/project-overview-chat.tsx` -- the Project Overview page's inline "Ask TableScope" chat.
- `web-ui/components/tablescope/project/overview-screen.tsx` -- the Overview screen's "Ask Anything" panel.

On all three, the backend correctly classifies the dashboard/query command, builds the `artifactProposal`, and returns the assistant's descriptive text -- but the frontend only ever rendered that text, with no way to act on it. Confirmed by reading `TurnBubble`'s full source: it had zero references to `artifact_proposal` or `ChatArtifactConfirmationCard`.

## Fix

- `conversation-turn.tsx`: `TurnBubble` now accepts the same optional props `TurnBubbles` already has (`conversationId`, `projectId`, `onReviewDashboard`, `onArtifactDecision`) and renders `ChatArtifactConfirmationCard` under the same condition (`turn.artifact_proposal` present, plus conversation/project context available).
- New `web-ui/components/tablescope/conversation/use-chat-dashboard-review.tsx`: a small shared hook encapsulating the "review dashboard" flow (opens the existing `AIDashboardDesigner`, calls `decideArtifactProposal` with the resulting dashboard id on completion, shows a toast on a non-fatal failure to record that decision). Extracted so the three newly-fixed surfaces don't each duplicate the modal/toast/decide wiring `project-chats-screen.tsx` and `app/ai/page.tsx` already have inline.
- `workspace-assistant-panel.tsx`, `project-overview-chat.tsx`, `overview-screen.tsx`: wired `TurnBubble` with the new props, used `useChatDashboardReview`, and added a `refreshConversation`-style callback (re-fetches the conversation/turns after an accept/reject) since each of these three manages its own local conversation state rather than react-query.

No backend changes -- this is a pure frontend wiring gap; the backend already worked correctly on all five surfaces.

## Testing performed (real, not deferred)

```
cd web-ui
npx vitest run \
  components/tablescope/conversation/conversation-turn.test.tsx \
  components/tablescope/project/workspace/workspace-assistant-panel.test.tsx \
  components/tablescope/conversation/chat-artifact-confirmation-card.test.tsx \
  app/ai/turn-bubbles.test.tsx \
  components/tablescope/project/project-chats-screen.test.tsx \
  app/ai/page.test.tsx                                    # 28 passed (2 new)

npx tsc --noEmit -p tsconfig.json                          # clean, no errors
npx vitest run                                              # 624 tests: 614 passed, 10 failed
```

New tests in `conversation-turn.test.tsx`: renders `ChatArtifactConfirmationCard` when a turn has an `artifact_proposal` and conversation/project context is supplied; does not render it when that context is absent (matches an un-wired caller, a safety net against a future new consumer forgetting to pass the props). `workspace-assistant-panel.test.tsx` needed one addition: mock `use-chat-dashboard-review` (the same way it already mocks `conversation-turn`) so its existing 11 tests don't need a `QueryClientProvider`/`next/navigation` mock to exercise a flow they aren't testing.

The 10 vitest failures are pre-existing and unrelated (`IntelligenceCard`/`ChartSuggestionDialog` missing a `QueryClientProvider` in that one test file) -- confirmed by reproducing them identically on `UX-design-03` before this branch's changes.

## Merge

```
git fetch origin fix/chat-artifact-card-missing-surfaces
git checkout UX-design-03
git merge --no-ff origin/fix/chat-artifact-card-missing-surfaces
git push origin UX-design-03
```

No migration, no backend change. Frontend-only.

## Deploy

Standard web-ui build/deploy. No backend restart needed.

## Post-deploy verification

1. Open a project's page with the docked AI Assistant panel expanded (any project page other than Chats/`/ai`). Type "create a dashboard for X."
2. Confirm a pending dashboard confirmation card now appears with a **Review & create** button (previously: only plain text, no button).
3. Click **Review & create**, complete the dashboard designer flow. Confirm the card updates to "Created" with a working link, and the dashboard exists under Project Dashboards.
4. Repeat step 1-3 for the Project Overview page's inline "Ask TableScope" chat and for its "Ask Anything" panel on the Overview screen.
5. Repeat with "create a query that shows X" instead, confirming **Save query** works the same way on all three newly-fixed surfaces.
6. Confirm the two already-working surfaces (`/ai` page, project Chats page) are unaffected.
