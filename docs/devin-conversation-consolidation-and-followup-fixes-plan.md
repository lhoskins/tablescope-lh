# Devin-ready plan: conversation consolidation, AI/library validation, and PR #156 follow-up bugs

**Verified base:** `origin/devin/r-echarts-e2e-validation` @ `702253b4` (the merge of PR #156) — re-verify at implementation time.

This plan supersedes/extends nothing from PR #155/#156 — those items are done. This is new investigation, each item traced against the current code, not guessed.

---

## Item 1 — Business Insight and Project Insight questions spawn a new "Business Insights" conversation every time instead of consolidating into one thread

### Finding: the fix already exists, unmerged

**`PR #146` — "feat(conversations): canonical Business and Project Insight threads" — is open, unmerged, and is exactly the fix for this.** From its own description: *"one conversation per (tenant, user, surface) for Business Insights and one per (tenant, user, project) for Project Insights. New questions append to the existing thread instead of spawning duplicates."* This is precisely the bug you're describing — multiple "Business Insights"-titled conversations piling up instead of one durable thread per surface.

What it adds, verified via its file list:
- `canonical_key` + `merged_into_conversation_id` columns on `AnalyticsConversation`, unique on `(tenant_id, user_id, canonical_key)`.
- `app/services/canonical_conversations.py` — atomic get-or-create of the canonical thread, idempotent turn submission, merge-alias resolution.
- New `POST /api/conversational-analytics/canonical-turns` endpoint.
- Routes `business_insights`/`project_insights` surfaces through the canonical append path; `ai_assistant` "New chat" conversations correctly stay independent (this is deliberate — you don't want every AI Assistant chat forced into one thread, only the two auto-titled insight surfaces).
- A one-time consolidation script (`scripts/consolidate_insight_conversations.py`) to merge your *existing* duplicate "Business Insights" conversations into one canonical thread, rather than leaving the old duplicates orphaned.
- Migration `9ef39057749a_canonical_insight_conversations`.

### Do not merge it as-is — it needs a rebase, not a click-merge

PR #146 is based on commit `6cca9ea1`, from **before** roughly 10 subsequent PRs landed on `devin/r-echarts-e2e-validation`, including the routes-layer file-split (Phase 4) and services-layer file-split (Phase 2) work done earlier in this project. GitHub reports `mergeable_state: clean` (no textual conflicts), but that only means git can auto-merge the diff — it does not mean the result is logically correct. Specifically:

- PR #146 modifies `platform-api/app/routes/conversational_analytics_conversations.py` and `conversational_analytics_turns.py` — confirmed these still exist at the same paths on the current tip, so a rebase is mechanically straightforward, but both files may have picked up unrelated changes since `6cca9ea1` that need to be reconciled by hand, not just auto-merged.
- The turn-execution bug fixed in Item 3 below (`platform-api/app/services/conversational_analytics/__init__.py`) is in a file PR #146 does **not** touch — so merging PR #146 first vs. fixing Item 3 first is safe in either order, they don't conflict with each other.

**Plan**: check out `devin/canonical-insight-conversations`, rebase onto the current `devin/r-echarts-e2e-validation` tip (not merge — rebase, so you can resolve any drift file-by-file), re-run the full test suite (`pytest -q`, `npm test -- --run`, `npm run build`) since the PR's own "1229 passed" was against its stale base and needs to be re-proven against current code, then merge. Also re-verify `alembic heads` resolves to a single head before assigning the migration a final position — the current tip already has two migration files that don't share a simple numeric sequence (`0083_enterprise_auth.py` and `91455ab780b4_insight_feedback_review.py`), so confirm they're already merged to one head via a merge-revision file before adding a third.

### Verification

1. Run the consolidation script in `--dry-run` mode against a copy of production data first, review what it would merge, before running it for real.
2. Manual: ask a question in Business Insight, refresh, ask another — confirm both land in the same conversation/thread instead of creating a second "Business Insights" entry. Repeat for Project Insight. Confirm AI Assistant's "New chat" still creates independent conversations (that's correct, expected behavior, not a regression).

---

## Item 3 — Validate AI Assistant, Business Insight, and Project Insight can converse using the Company/Reference Library

### Finding: the capability exists in the code; two confirmed bugs are the reason it doesn't work reliably

All three surfaces share one code path — confirmed by tracing the call graph, not assumed: `execute_turn()` (`platform-api/app/services/conversational_analytics/__init__.py:146`) → `_run_analytical_turn()` → `_ask_and_run_core()` (imported from `app.routes.ai_proxy`, which re-exports from `ai_proxy_ask_and_run.py`). This is the same core function whether the question originates from AI Assistant, Business Insight, or Project Insight — there is no separate implementation per surface, so a bug found in one surface affects all three identically.

**Bug A — the document/Knowledge-Graph fallback only fires on one specific failure mode.** `_forward_prose_answer()` (`ai_proxy_ask_and_run.py:752-783`) is real, working code — its docstring: *"Free-text answer from the AI server's documents + knowledge-graph path... Grounds the answer in the project's Knowledge Graph when one exists."* The Knowledge Graph is built from Reference Library / Company Library documents (confirmed via `governing_documents`/`reference_guidance` node types in `knowledge_graph_ai_context.py`, and `knowledge_graph_context.py`'s own docstring: *"the authoritative reference library (project + company + industry)"*). So the underlying capability you're expecting is genuinely built.

The bug is in when it gets called. `conversational_analytics/__init__.py:290`:
```python
if run.get("status") == "generation_error":
    prose = await _forward_prose_answer(...)
    ...
if run.get("status") != "success":
    turn.status = "error"
    ...
    return
```
This fallback fires **only** when SQL generation itself fails (`generation_error`). A question like "Tell me about the cybersecurity framework" gets the model to *attempt* SQL (it's always instructed to try), which then fails when actually **executed** against the database — landing in `status == "execution_error"` instead (confirmed real and reachable: set at `ai_proxy_ask_and_run.py:586` and `:924`). That status falls straight into the generic `if run.get("status") != "success"` branch and returns a hard error, one `if` away from the exact fallback that would have answered it correctly from the Knowledge Graph.

The identical gap exists in the direct `POST /actions/ask-and-run` route (`ai_proxy_ask_and_run.py:786`, the "Ask AI" modal elsewhere in the app) — same function, same bug, confirmed by the same code.

**Bug B — capability/meta questions dead-end before ever trying to answer.** The turn classifier (`ai-server/tablescope-ai-api/app/routers/ai_conversation.py`) sorts every message into exactly 5 buckets: `new_analysis|query_change|chart_change|explain|clarification` (line 88, the literal prompt text). A question like "are you able to see the reference library?" doesn't fit any of the first four, so it lands in `clarification`. Platform-api's handling of that (`conversational_analytics/__init__.py:177-184`):
```python
if intent == ConversationalIntent.CLARIFICATION:
    turn.status = "error"
    turn.error_code = "needs_clarification"
    turn.assistant_message = (
        "I'm not sure what you'd like me to do. You can ask a new question, "
        "refine the current one, or ask for a different chart format."
    )
    return
```
This returns immediately with a hardcoded canned message — it never attempts `_ask_and_run_core`/the prose fallback at all. Neither the SQL path nor the Knowledge Graph path is ever tried for a question the classifier buckets this way.

### Fix

1. In `conversational_analytics/__init__.py` (`execute_turn`), extend the fallback trigger to cover `execution_error` in addition to `generation_error` — the intent (the model couldn't ground this in a SQL result, try the document/KG path instead) applies equally to both failure modes. Consider whether *any* non-success status should attempt the fallback before giving up, rather than enumerating specific status strings one at a time, since a third failure mode will hit the same gap again otherwise.
2. Apply the identical fix to `ai_proxy_ask_and_run.py`'s `ai_ask_and_run` route (`POST /actions/ask-and-run`), which has the same status-branching bug independently.
3. For the CLARIFICATION dead-end: before returning the canned message, attempt `_forward_prose_answer()` first — if the Knowledge Graph/document path produces a real answer, use it; only fall back to the canned "I'm not sure what you'd like me to do" message if that also comes back empty. This turns a capability/meta question like "can you see the reference library?" into an actual answer instead of a dead end, without needing to add a 6th classifier bucket (though that's a reasonable longer-term improvement — flagged as optional, not required for this fix).

### Verification

1. Regression tests for both fixed branches: a question that fails at SQL execution (not generation) should get a real prose answer when the project has Knowledge Graph content available, in both `execute_turn` and `ai_ask_and_run`. A capability/meta question that classifies as `clarification` should attempt the prose fallback before falling back to the canned message.
2. Manual, on all three surfaces (AI Assistant, Business Insight, Project Insight) for the same tenant/project with real Reference Library content: ask "Tell me about [a real reference-library document's topic]" and confirm a grounded answer, not an error. Ask "are you able to see the reference library?" and confirm a real answer instead of the canned clarification message.

---

## Item 4 — File URL: data source is created, but disappears/gets deleted when clicked

### Investigation result: thoroughly checked, root cause not conclusively found — here's what's ruled out and what to check next

This was investigated in depth against the Data Source Builder's own "Active Data Sources in this Session" list (`active-sources-table.tsx`) and its row-click target (`data-review-modal.tsx`), since that's the screen in your screenshot. Ruled out, with evidence:

- The row's `onClick` (`active-sources-table.tsx:79`) only does `setReviewItem(item)` — plain local React state, opens `DataReviewModal` as an overlay. It does not navigate, does not touch the Zustand store's `activeSourceId`, and does not call any removal action.
- For a freshly-created (not-yet-backend-persisted) source specifically, `DataReviewModal` makes **zero network calls** — it renders from already-cached local preview data and returns immediately. There's nothing in that path that could 404/error and trigger a cleanup.
- `removeSource`/`unmarkCreated` (the store's only two source-removal actions) are called from exactly two places — the row's separate "X" button and `table-select-modal.tsx` — never from the review modal or the click handler.
- No `useEffect` keyed on `activeSourceId` exists anywhere in the reviewed files that could run a side effect on click.
- The project's separate Data Sources screen (`data-sources-screen.tsx`, outside the builder wizard) has explicit, separately-gated Archive/Delete actions with their own confirmation dialogs (`archive-source.tsx`, `delete-source-dialog.tsx`) — clicking a row there opens a detail panel via `setSelectedKey`, not an automatic archive/delete. Also checked, also doesn't show an obvious auto-delete-on-click path, though this was a shallower pass than the builder's own flow.

**One real, adjacent bug found** (not confirmed to be the reported symptom, but worth fixing regardless): `syncExisting()` (the store function that reconciles the session's draft sources with the backend's `my-datasources` list on refetch) can't match a freshly-created source's `crypto.randomUUID()` id against that same source's later `existing-file-${id}` form once the backend picks it up — so instead of merging into one row, a **duplicate** entry gets added. This is the opposite symptom (a source appearing twice, not disappearing), but it's a real defect in the same reconciliation logic and should be fixed while this area is being worked on.

### What's needed before this can be fixed correctly

Code review alone couldn't reproduce this — the two most-likely destructive paths were checked and ruled out with evidence, not assumption. Before Devin spends more time here, please confirm:
1. **Exactly where the click happens** — still inside the Data Source Builder wizard (the "Active Data Sources in this Session" list, matching the screenshot), or after finishing the 2-step wizard, when viewing it from the project's regular Data Sources screen?
2. **What "disappears" looks like** — does the row vanish from the list immediately, does it show briefly then vanish, does a page/modal open and then close/error, or does it navigate somewhere and 404?
3. If possible, a browser console/network-tab capture at the moment it happens — a DELETE/archive request firing (even unintentionally) would immediately confirm or rule out a network-triggered cause versus a pure client-state bug, and would tell Devin exactly which endpoint to trace backward from instead of searching forward from the click.

### Recommended fix in the meantime (the confirmed bug, independent of the unconfirmed one)

Fix the `syncExisting()` id-reconciliation gap regardless: use a stable identifier (e.g. match on `view_name`/backing file identity rather than the ephemeral client-generated UUID) so a session-drafted source and its later backend-confirmed counterpart resolve to one row, not two. This is a real, evidenced defect worth fixing even though it isn't confirmed to be the reported symptom.

---

## Item 5 — Network File Browsing (from PR #156): extremely slow (up to 5 minutes for 3 records), and shows "This folder is empty" + "Request failed: 500" for a share known to contain `sample.csv`

Three distinct, precisely-traced bugs, all in the browse path — not the earlier button-visibility fix from PR #156, which was correct and unrelated to this.

### Bug A — the 500 itself: session-establishment errors are completely unhandled in the browse path

`platform-api/app/services/smb_gateway.py`'s `list_network_path()` (browse) calls `_register_session(connection, source_ip)` **before** its own `try:` block. Contrast with the file-*read* path (`_read_blocking`), where the identical call is the *first statement inside* `try:`. Any exception during SMB session setup — auth failure (`SMBAuthenticationError`, which doesn't inherit from either exception type the surrounding handlers catch, so it wouldn't be caught even if it were inside `try`), connection failure, protocol negotiation failure — propagates completely unhandled: past `list_network_path`, past the route's `except NetworkPathError` in `platform-api/app/routes/file_imports.py`, into FastAPI's bare default 500 handler, with no `detail` message and skipping the `finally`/session-cleanup entirely.

**Fix**: move `_register_session(...)` inside the `try:` block in the browse path's `_list()` function, matching the read path's structure. Add `SMBAuthenticationError` (and any other real connection/auth exception types from the SMB library) to what gets caught and converted into a proper `NetworkPathError` with a user-meaningful message (e.g. "Could not authenticate to the network share" rather than a bare 500), instead of only catching `SMBOSError`/`SMBResponseException`.

### Bug B — the "This folder is empty" + "Request failed: 500" combination

`network-repository-modal.tsx`: `entries` is initialized to `[]` and is only ever updated inside the success branch of the browse call; the error handler sets `error` but never touches `entries`. The empty-state message (`entries.length === 0 ? "This folder is empty." : ...`) is rendered independently of whether `error` is set, so a failed request leaves `entries` at its initial empty array while *also* showing the error — producing exactly the simultaneous "This folder is empty" + "Request failed: 500" your screenshot shows. This is a pure UI-state bug, unrelated to Bug A, though Bug A is very likely what's actually causing the request to fail in the first place.

**Fix**: don't render the "This folder is empty" message when `error` is set — show only the error state in that case. Straightforward, isolated change.

### Bug C — genuine multi-minute slowness (separate from, and worse than, whatever's causing the 500)

Three compounding causes, all confirmed in `smb_gateway.py`:

1. **A full extra SMB round-trip per file.** `list_network_path()` calls `entry.stat()` inside its `for entry in smbclient.scandir(target)` loop. The `smbclient` library's own documentation states `SMBDirEntry.stat()` "always requires an extra SMB call" beyond what `scandir()` already returned — `scandir`'s single directory-query call already includes size/timestamps/attributes, but that data is discarded and re-fetched one file at a time. This is the direct mechanism behind "3 records = 5 minutes": each additional file adds a full network round-trip over the VPN link, not a fixed cost.
2. **No SMB session reuse.** Every browse call does a full session negotiate+auth handshake (`_register_session`) and tears it down (`delete_session`) in `finally` — including when a user just clicks into a subfolder one level down. Each click pays the full connection-setup cost again.
3. **A blocking, uncached, unbounded call on every browse request.** `get_tenant_source_ip()` → `find_source_ip_for_cidr()` → `_list_local_ipv4()` runs `subprocess.run(["ip", "-4", "-json", "addr", "show"], timeout=5)` **synchronously inside the async request path, with no `asyncio.to_thread`** — blocking the entire event loop (not just this request — every concurrent request on the same worker) for up to 5 seconds. If the `ip` command isn't found, it falls back to `socket.gethostname()`/`getfqdn()` + `socket.getaddrinfo()` — blocking DNS calls **with no timeout at all**, which can hang far longer than 5 seconds if DNS resolution is slow, and this runs on *every single browse request*, not once per session.

**Fix, in priority order** (2 and 4 give the biggest win for the least risk; 1 and 3 are more involved):
1. Stop calling `entry.stat()` per file — use the attributes `scandir()`'s single call already returns (size, timestamps, file-vs-directory) instead of re-fetching them.
2. Wrap `_list_local_ipv4()`'s `subprocess.run` and DNS fallback in `asyncio.to_thread`, and add an explicit timeout to the DNS fallback path (it currently has none). This alone fixes the event-loop-blocking problem regardless of the SMB-specific fixes.
3. Cache the resolved tenant source IP (it doesn't change between requests in normal operation) instead of re-deriving it on every browse call — even with (2) fixed, doing this work on every request is wasteful.
4. Longer-term: reuse an SMB session across a browse "session" (e.g., cache the connection for the duration of a modal being open, tied to the connection id) rather than a fresh negotiate+auth handshake on every single request, including subfolder navigation within the same browse session.

### Verification

1. Backend test: mock an SMB auth failure during `list_network_path()`, assert it surfaces as a proper `NetworkPathError`/4xx with a real message, not an unhandled 500.
2. Backend test/benchmark: browse a directory with several files, assert no per-file network call beyond the single `scandir` (e.g. via a mock call-count assertion on the SMB client), and assert `_list_local_ipv4`'s subprocess/DNS calls don't block the event loop (can be tested by asserting they run inside `asyncio.to_thread` or via a wall-clock concurrency test).
3. Frontend test: mock a failed browse response, assert the modal shows only the error state, not "This folder is empty" simultaneously.
4. Manual, against the real VPN SMB share: browse the repository containing `sample.csv`, confirm it lists (not "empty"), confirm no 500, and time the round trip before/after the fix — this is the test that actually matters here, the others are regression coverage.

---

## Item 6 — "Show period statistics" toggle: reposition, add padding, restyle to match the Shared-project pill toggle

### Current state (traced)

`percent-change-summary-panel.tsx:225-230` renders the toggle using the generic `web-ui/components/ui/switch.tsx` `Switch` component, inline in a `flex flex-wrap items-center gap-3` row on the right side of the control bar, next to the search box and the page-size `<select>`. That `Switch` component is designed for a wider settings-panel layout (label + description + track + on/off text spread across a `flex items-start justify-between gap-4` row) — it doesn't fit well in a compact toolbar slot, which is almost certainly why it reads as "barely visible": it's not that the component is styled wrong in isolation, it's the wrong component for this placement.

The table's leftmost column header is literally titled **"Insight"** (`percent-change-summary-table.tsx:185`) — confirming "above the Insight column" means the top-left of the table/page, not the current top-right control-bar position.

The visual target, `web-ui/components/tablescope/project/share-toggle.tsx`, is a purpose-built compact pill: `<div className="flex items-center gap-2 rounded-md border border-line-secondary bg-bg-primary px-2.5 h-8">` containing a text label ("Shared"/"Private") and a small `h-4 w-7` switch track — this is a different, smaller component than the generic `Switch`, not a styling variant of it.

### Fix

1. Don't reuse `ShareToggle` directly (it's coupled to project-sharing mutation logic specific to that feature). Build a small local pill-toggle following its exact visual pattern instead — either a tiny reusable component (e.g. `PillToggle` taking `label`/`checked`/`onChange`) if you want to reuse this style elsewhere later, or just inline the same JSX structure with `label="Period Statistics"` — either is fine, pick based on whether you expect to need this look elsewhere.
2. Move it out of the right-side control-bar cluster entirely. Position it above the table, aligned with the left edge (above the "Insight" column), with its own margin/padding above and below so it has visual breathing room instead of being squeezed into a dense flex row — this satisfies both "moved to the left above the Insight column" and "some padding between top and bottom of the toggle."
3. Keep the existing `showStatistics` state, `SHOW_STATISTICS_STORAGE_KEY` localStorage persistence, and the `handleShowStatisticsChange` handler exactly as they are — this is a pure presentational relocation/restyle, no behavior change to the default-off toggle logic already delivered in PR #156.

### Verification

Manual: confirm the toggle now sits above the table's left edge (above "Insight"), has visible vertical spacing around it, matches the Shared-project pill's visual weight (border, height, compact track), and reads "Period Statistics" — and that toggling it still shows/hides the stat columns and persists across a page reload exactly as before.

---

## Summary: files touched per item

| Item | Primary files |
|---|---|
| 1 | Rebase/merge `devin/canonical-insight-conversations` (PR #146) — `analytics_conversation.py`, `conversational_analytics_conversations.py`, `conversational_analytics_turns.py`, new `canonical_conversations.py`, migration `9ef39057749a` |
| 3 | `platform-api/app/services/conversational_analytics/__init__.py`, `platform-api/app/routes/ai_proxy_ask_and_run.py` |
| 4 | `web-ui/lib/stores/data-source-builder-store.ts` (`syncExisting` id-reconciliation fix, confirmed); root cause of the disappearing-on-click symptom needs a repro before further code changes |
| 5 | `platform-api/app/services/smb_gateway.py`, `platform-api/app/services/tenant_network_source_ip.py`, `platform-api/app/routes/file_imports.py`, `web-ui/components/tablescope/data-source-builder/network-repository-modal.tsx` |
| 6 | `web-ui/components/tablescope/home/percent-change-summary-panel.tsx`, possibly a new small pill-toggle component |
