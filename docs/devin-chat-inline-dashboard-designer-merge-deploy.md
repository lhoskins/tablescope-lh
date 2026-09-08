# Devin merge/deploy instructions: generate and refine AI dashboards inline in chat

## Branch
`feat/chat-inline-dashboard-designer`, based on `UX-design-03` at `52218ac9` (already includes `devin/merge-ai-chat-artifacts` and `fix/chat-artifact-card-missing-surfaces`).

## Feature request

The user asked for chat-driven dashboard creation with no separate guided wizard: "I want to be able to tell it to create an IT Incident dashboard and based on the related data sources for IT incidents, the LLM would give it instructions on the dashboard based on best practices," plus "When I send the conversation a dashboard should appear with create button in the chat. if it not right I should be able to add or delete by typing additional information."

Concretely:
- Typing "create an IT Incident dashboard" in any chat surface should profile the project's data sources and propose a best-practice chart set inline, with a **Create** button on the proposal card -- no modal.
- A follow-up message while the proposal is pending (e.g. "also add backlog by priority") should regenerate the design to reflect it, still inline.
- Clicking **Create** should persist the dashboard directly.

## Design decision confirmed with the user

Asked how a follow-up like "remove the SLA chart" should update the preview: **regenerate the whole set** (the follow-up is combined with the original prompt and the full design is re-picked from scratch), rather than surgically editing one widget. This governs the whole refinement implementation below.

## Scoping note (not separately confirmed -- flag for correction if wrong)

The request also asked for "the ability to tell it to create a specific chart the same as the AI guided." This is mapped to the **existing** `create_query` / `CREATE_QUERY` single-chart-in-chat flow, which already previews one chart inline with a Save button and requires no changes here. If the intent was instead "add one more widget to an already-existing dashboard from chat," that is a different, unbuilt flow -- say so and it can be scoped separately.

## What changed

Backend reuses the existing domain-aware dashboard engine (`_DOMAIN_CONCEPTS` / `review_dashboard_design` / `apply_dashboard_design` in `app/routes/ai_proxy_dashboard_designer.py`) instead of building new AI logic -- that engine already infers the domain (itsm/finance/manufacturing) from the prompt and project columns and proposes charts against it; the only gap was that chat never called it.

- **`app/services/conversational_analytics/__init__.py`**
  - `_artifact_proposal()` extended to carry a `dashboardDesign` payload (`{suggestion, widgets, supportStatus, ...}`) alongside the existing `title`/`description`.
  - New `_propose_dashboard(session, context, turn, *, project_id, prompt, governance)`: requires `Role.EDITOR` via `has_role` (the enclosing route only requires Viewer, so this closes a privilege gap for chat-triggered dashboard creation specifically); calls `review_dashboard_design(...)` directly as a function (bypassing FastAPI `Depends`, an established pattern in this codebase); on `not_supported` returns an explanatory message with no proposal; otherwise returns a full proposal listing the proposed charts.
  - `CREATE_DASHBOARD` branch in `execute_turn` now detects whether the immediately-preceding turn (`sequence - 1`) is a still-`pending` dashboard proposal. If so, the new message is folded onto the original prompt (`f"{original_prompt}\n\nAdditional instruction: {new_message}"`) and `_propose_dashboard` is called again, regenerating the whole design. Otherwise it's a fresh proposal from the raw message.
- **`app/routes/conversational_analytics_turns.py`** (`decide_artifact_proposal`)
  - New default path (no `asset_id` supplied): validates the stored proposal's `dashboardDesign.suggestion`, builds `DashboardDesignApplyRequest` from it, and calls `apply_dashboard_design(...)` directly to create and persist the dashboard in one step. The old `asset_id`-supplied path (record a pre-created dashboard) is kept for backward compatibility.
  - `apply_dashboard_design` does its own `await session.commit()`, which expires every object in the session under `expire_on_commit=True` -- including `conversation`/`turn`, which this function never otherwise touches. Fixed by capturing `project_id`, `conversation.id`, and `turn.user_message` into local variables *before* calling it, and using the locals for every subsequent read (URL building, the final log line, the response) instead of re-reading expired ORM attributes, which would otherwise raise `MissingGreenlet`.
- **Frontend** (`web-ui/lib/api/conversational-analytics.ts`, `chat-artifact-confirmation-card.tsx`, `conversation-turn.tsx`, `app/ai/turn-bubbles.tsx`)
  - `ChatArtifactConfirmationCard` now renders the proposed widget list (title, chart type, business question) and a partial-support caveat when `supportStatus` is `partially_supported`, with a single **Create** / **Save query** button that calls `decideArtifactProposal(..., {decision: "accept"})` directly for both dashboards and queries.
  - Removed the `onReviewDashboard` prop and the modal-opening branch entirely -- accepting a dashboard proposal no longer opens `AIDashboardDesigner`.
  - Deleted `use-chat-dashboard-review.tsx` (the modal-driving hook added for the previous fix), now unused.
  - `project-chats-screen.tsx` and `app/ai/page.tsx` invalidate the `["project", projectId, "dashboards"]` query key on any artifact decision, since dashboard creation now happens inline with no separate modal-driven invalidation.

No migration; no new endpoints; both routes exercised here already existed.

## Testing performed (real, not deferred)

```
cd platform-api
python -m pytest -q tests/test_conversational_analytics.py    # 33 passed
python -m pytest -q tests/test_conversational_analytics.py \
  tests/test_conversational_analytics_conversations.py \
  tests/test_conversational_analytics_turns.py \
  tests/test_ai_proxy_dashboard_designer.py tests/test_rbac.py # 101 passed
python -m pytest -q                                            # 1957 passed, 12 failed, 4 skipped
```

The 12 backend failures are pre-existing and unrelated: `test_billing.py` (2, VPN/data-plane provisioning), `test_business_insight_phase1.py` (3, snapshot staleness), `test_percent_change_summary.py` (4, percent-change stats), `test_visualization_engine.py` / `test_ai_dashboard_pipeline.py` / `test_ask_pipeline.py` (3, chart-type heuristics) -- none touch conversational analytics or dashboard design.

```
cd web-ui
npx vitest run \
  components/tablescope/conversation/chat-artifact-confirmation-card.test.tsx \
  components/tablescope/conversation/conversation-turn.test.tsx \
  app/ai/turn-bubbles.test.tsx \
  app/ai/page.test.tsx \
  components/tablescope/project/project-chats-screen.test.tsx \
  components/tablescope/project/workspace/workspace-assistant-panel.test.tsx  # 29 passed
npx tsc --noEmit -p tsconfig.json                                              # clean, no errors
npx vitest run                                                                 # 625 tests: 615 passed, 10 failed
```

The 10 frontend failures are pre-existing and unrelated (`IntelligenceCard`/`ChartSuggestionDialog` missing a `QueryClientProvider` in that one test file), matching the same failures confirmed unrelated on `UX-design-03` in the prior chat-artifact-surfaces fix.

New backend tests added to `test_conversational_analytics.py`: dashboard creation generates an inline preview without writing anything; the not-supported path explains itself with no proposal; accepting a proposal applies the design directly (asserting the constructed `DashboardDesignApplyRequest`); the `asset_id`-supplied path still just records it (old behavior preserved); a follow-up while a proposal is pending regenerates the whole design (asserting the second `review_dashboard_design` call's prompt contains both the original request and the new instruction, and the resulting widgets are the union of both); dashboard creation from chat requires Editor access (a viewer-role project member is rejected before `review_dashboard_design` is ever called).

New frontend tests added to `chat-artifact-confirmation-card.test.tsx`: the widget list and business questions render, Create applies the dashboard directly with no modal, and the partial-support caveat renders when appropriate.

## Merge

```
git fetch origin feat/chat-inline-dashboard-designer
git checkout UX-design-03
git merge --no-ff origin/feat/chat-inline-dashboard-designer
git push origin UX-design-03
```

No migration, no backend restart beyond a standard deploy.

## Deploy

Standard platform-api + web-ui build/deploy. No environment variable or config changes.

## Post-deploy verification

1. On at least two of the five chat surfaces (`/ai` page, project Chats page, docked Workspace Assistant panel, Project Overview "Ask TableScope," Overview screen "Ask Anything"), type "create an IT Incident dashboard" (or any domain the connected data supports). Confirm a proposal card appears inline with a list of proposed charts and a **Create** button -- no modal opens.
2. While that proposal is still pending, type a follow-up like "also add a chart for backlog by priority." Confirm the same card updates to a regenerated chart list reflecting both the original request and the new instruction.
3. Click **Create**. Confirm the card shows "Created" with a working link, and the dashboard exists under Project Dashboards with the previewed charts.
4. Ask for a dashboard on data the project doesn't have (e.g. a domain with no matching columns). Confirm an explanatory assistant message appears with no proposal card and nothing is created.
5. As a project member with only Viewer/tenant-viewer access, attempt to create a dashboard from chat. Confirm it is rejected and no dashboard is proposed or created.
6. Ask for "a chart that shows X" (single chart, not a dashboard). Confirm the existing single-chart preview-and-save flow is unaffected.
