# Business Insights / AI Context / Assignment / Pinning / Upload — validated & enhanced plan

Supersedes `Business_Insights_AI_Context_Data_Source_Assignment_Pinning_and_File_Upload_Fixes.pages`.
Read this document instead of the original. Where a section is not mentioned
here, the original stands.

**Branch:** `devin/business-insights-context-and-ux-fixes`
**Base:** `origin/devin/r-echarts-e2e-validation` (verified deployed lineage)

Four of the five fixes are real and correctly scoped. The corrections below
matter because **three of the five prescribe changing code that is already
correct**, which would send Devin either doing nothing or inventing a change
while the actual defect survives.

---

## 0. Validation findings

Every claim was checked against the repository at the base SHA.

### 0.1 Fix 1 — no transcript hydration exists; the stated fix has nothing to remove

The plan's implementation list says to "remove Business Insights transcript
hydration from persistent browser storage, cached route state, URL state,
global persisted state, or historical conversation fetches."

**None of those exist.** `web-ui/app/business-insight/page.tsx`:

```tsx
const [chatTurns, setChatTurns] = useState<ConversationTurn[]>([]);
const [chatConversationId, setChatConversationId] = useState<number | null>(null);
```

The only `useQuery` on the page is `homePins`. `getConversation` is called
**solely inside `pollConversation`**, which only runs from `handleAsk`. There
is no `localStorage`, no `sessionStorage`, no `useSearchParams`, no
`listConversations` call, and no mount-time fetch.

On a hard refresh the transcript is **already empty**. Requirement 4 of the
plan is already satisfied by the current code.

**Instruction: reproduce before changing anything.** If the reported retention
is real, it comes from a mechanism not in this file — most plausibly a
soft-navigation path that does not remount the segment. Have Devin record
which navigation gesture reproduces it (hard reload vs. client-side nav away
and back) and attach that to the PR before touching the transcript code.
Deleting "hydration" that does not exist is how a bug report gets closed
without the bug being fixed.

### 0.2 Fix 1 — the real defect nearby: there is no canonical Business Insights conversation

The plan's premise is that a turn is saved "to the AI Assistant under the
tenant/user-authorized **Business Insights conversation**" (singular). That
thread does not exist.

`handleAsk` creates a **brand-new conversation on every page mount**:

```tsx
if (chatConversationId == null) {
  const created = await createConversation({ initial_message: message });
  ...
}
```

and the backend titles it from the message body
(`platform-api/app/routes/conversational_analytics.py`):

```python
title = req.title or "New conversation"
if req.initial_message:
    title = req.initial_message[:80] + ("…" if len(req.initial_message) > 80 else "")
```

Because `chatConversationId` resets on every mount, **each visit that asks a
question creates another `AnalyticsConversation` row** with
`project_id = NULL`, titled with the question text. The AI Assistant lists all
of the user's conversations, so they all appear there. There is no grouping,
no surface tag, and nothing named "Business Insights".

Both surfaces are the **same store** — `AnalyticsConversation` via
`/api/conversational-analytics/conversations`. The AI Assistant is not a second
system; it is a list over the same rows.

So "keep the page ephemeral but preserve the canonical thread" is not two
things today — it is one row that the page happens to hold an id for. Building
the canonical thread the plan assumes already exists is **new work**, and it is
the prerequisite for the plan's own acceptance criterion *"Open AI Assistant
and confirm the turn exists under Business Insights."*

### 0.3 Fix 1 — the idempotency primitive already exists and is simply unused

The plan requires "Prevent duplicate message writes if a page submission
retries." The mechanism is already built:

```python
# platform-api/app/models/analytics_conversation.py
client_request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
...
UniqueConstraint("conversation_id", "client_request_id",
                 name="uq_analytics_turn_client_request_id")
```

`CreateConversationRequest` and `SubmitTurnRequest` both accept
`client_request_id`. The Business Insights page sends neither. This is a
one-line-per-call-site fix, not a new subsystem — see §1.1.

### 0.4 Fix 3 — root cause confirmed, and it is one missing argument

`platform-api/app/services/conversational_analytics.py:746-751`:

```python
project_id = conversation.project_id
if project_id is None:
    turn.status = "error"
    turn.error_code = "no_project"
    turn.assistant_message = "This conversation is not attached to a project."
    return
```

The Business Insights page never sends one:

```tsx
const created = await createConversation({ initial_message: message });
//                                        ^ no project_id
```

The AI Assistant page **does** (`createConversation({ project_id: projectId, ... })`),
which is exactly why the plan reports "the same request works after manually
selecting the IT project."

**A related path already exists and should not be confused with this one.**
`POST /api/ai/route-prompt` (`ai_proxy.py:829`) resolves a project for the Home
hero prompt — but it does **not parse the prompt at all**. It uses the caller's
`project_id` if given, else picks the most recently updated authorized project:

```python
target_id = await session.scalar(
    select(Project.id).where(...).order_by(Project.updated_at.desc()).limit(1)
)
```

That is a crude fallback, not a resolver. Do not extend it into the resolver
the plan describes — it has different callers and different semantics. Build
the resolver as its own service and let both call it.

### 0.5 Fix 2 — the list already has `overflow-y-auto`; the height chain is what is broken

The plan says "Make the list vertically scrollable within the available
workspace height." It already is, in
`web-ui/components/tablescope/data-source-builder/available-sources.tsx`:

```tsx
<div className="min-h-0 flex-1 space-y-2 overflow-y-auto px-0.5 py-1">
```

Adding overflow classes here will change nothing. The defect is one level up.

`flex-1 min-h-0 overflow-y-auto` only scrolls when an ancestor has a **bounded**
height. Compare the two columns in `workspace.tsx`:

```tsx
<div className="grid min-h-0 flex-1 grid-cols-1 gap-6 overflow-hidden py-4 lg:grid-cols-2">
  <div className="min-h-0 overflow-hidden border-line-tertiary lg:border-r lg:pr-6">
    <AvailableSources />        {/* wrapped in an extra div */}
  </div>
  <ProjectsColumn ... />        {/* IS the grid item directly */}
</div>
```

Both components have the **identical** root class — I checked, and my first
hypothesis that they differed was wrong:

```tsx
<div className="flex min-h-0 flex-col">   // available-sources.tsx:52
<div className="flex min-h-0 flex-col">   // projects-column.tsx:41
```

The difference is the **wrapper**. `ProjectsColumn` is the grid item itself, so
grid `align-items: stretch` gives it the row height and its inner
`flex-1 min-h-0` list scrolls correctly. `AvailableSources` sits inside an extra
`div`; that wrapper stretches, but `AvailableSources`'s own root is
`flex flex-col` with **no `h-full`**, so it sizes to its content instead of to
the wrapper. The content then overflows and the wrapper's `overflow-hidden`
**clips** it — producing exactly the reported symptom: about seven rows
visible, no scrollbar, the rest unreachable.

**The minimal correct fix is one class.** See §1.2. Search and the New badge
are genuinely new work and the plan's requirements for them are sound.

### 0.6 Fix 4 — the unique constraint blocks the plan's own acceptance criterion

The plan requires: *"An insight may be pinned in both places"* and *"Allow the
same insight to be both pinned to Home and pinned in Insights."*

`platform-api/app/models/home_pin.py`:

```python
__table_args__ = (
    UniqueConstraint(
        "tenant_id",
        "user_id",
        "pin_key",
        name="uix_home_pins_tenant_user_key",
    ),
)
```

There is **no destination column in the key**. If Devin follows the plan's
"normalized pin table with `destination = home | insights_panel`" suggestion by
adding a `destination` column to `home_pins`, the existing constraint makes the
second pin of the same insight fail with an integrity error. The acceptance
criterion cannot pass without altering this constraint to include
`destination`.

Also note `frozen_payload` already exists on the model and is written by
`insight_chart_selection.py`. The plan's requirement that a Home pin "continue
to use the latest authorized insight data rather than becoming a dead
screenshot" needs Devin to first establish **whether `frozen_payload` is
currently authoritative for rendering** — if it is, that is the "dead
screenshot" behavior the plan wants changed, and changing it affects existing
Home pins.

### 0.7 Fix 5 — the dropzone is already correct; the missing piece is a document-level guard

The plan's event-handling checklist implies the dropzone mishandles the drop.
It does not — `ai-upload-dropzone.tsx`:

```tsx
onDragOver={(e) => {
  e.preventDefault();
  ...
}}
onDragLeave={() => setDragActive(false)}
onDrop={(e) => {
  e.preventDefault();
  ...
  void handleFiles(e.dataTransfer.files);
}}
```

`preventDefault()` on both, and `dataTransfer.files` read correctly. A drop
**on the dropzone** already works.

The browser navigates/downloads when the file lands **anywhere else on the
page**, which is the default behavior for a document with no drop handler. I
searched the entire `web-ui` tree: **there is no window- or document-level
drag/drop guard anywhere.** The plan does state this requirement ("The entire
page must prevent the browser's default file-open behavior when a file is
dropped outside the active dropzone") but files it under general event
handling, where it reads as a detail rather than as the actual fix.

**This is the whole bug.** See §1.3.

---

## 1. Corrections, with before/after code

### 1.1 Fix 1 — send the idempotency key that already exists

**Before** (`web-ui/app/business-insight/page.tsx`):

```tsx
if (chatConversationId == null) {
  const created = await createConversation({
    initial_message: message,
  });
  const polled = await pollConversation(created.id);
  setChatConversationId(created.id);
  setChatTurns(polled.turns);
} else {
  const res = await submitTurn(chatConversationId, { message });
  ...
}
```

**After:**

```tsx
// A stable id per submission so a React remount, a retry, or dev strict-mode
// double-invoke cannot write the same turn twice. The uniqueness constraint
// uq_analytics_turn_client_request_id already enforces this server-side; the
// page simply never supplied the key.
const requestId = crypto.randomUUID();

if (chatConversationId == null) {
  const created = await createConversation({
    initial_message: message,
    client_request_id: requestId,
  });
  const polled = await pollConversation(created.id);
  setChatConversationId(created.id);
  setChatTurns(polled.turns);
} else {
  const res = await submitTurn(chatConversationId, {
    message,
    client_request_id: requestId,
  });
  ...
}
```

Verified: `client_request_id` is accepted on **both** paths, on both sides —
`CreateConversationRequest` / `SubmitTurnRequest` in
`web-ui/lib/api/conversational-analytics.ts`, and the matching Pydantic models
in `platform-api/app/routes/conversational_analytics.py`
(`client_request_id: str | None = Field(default=None, max_length=64)`). No
contract change is needed; only the two call sites above.

### 1.2 Fix 2 — restore the height chain

**Before** (`web-ui/components/tablescope/data-source-builder/available-sources.tsx:52`):

```tsx
return (
  <div className="flex min-h-0 flex-col">
```

**After:**

```tsx
return (
  // h-full is what makes the inner `flex-1 overflow-y-auto` list scrollable:
  // this component is wrapped in a grid item (unlike ProjectsColumn, which IS
  // the grid item), so without it the root sizes to content, overflows, and is
  // clipped by the wrapper's overflow-hidden -- the list never scrolls.
  <div className="flex h-full min-h-0 flex-col">
```

Equivalent alternative, if you prefer to fix it at the call site rather than in
the component: give the wrapper in `workspace.tsx` `flex flex-col` so its child
stretches. **Do one or the other, not both**, and state which in the PR.

Verify with 85 sources that the *last* row is reachable by scroll — not merely
that a scrollbar appears.

### 1.3 Fix 5 — add the document-level guard that does not exist

**Before:** nothing. No window/document drag or drop listener anywhere in
`web-ui`.

**After** — a small hook, mounted once high in the tree (app shell or layout),
not per-dropzone:

```tsx
"use client";
import { useEffect } from "react";

/**
 * Stop the browser opening/downloading a file dropped outside a real dropzone.
 *
 * With no document-level handler, dropping a file anywhere on the page is a
 * navigation -- the browser replaces the app with the file. Dropzones that
 * call preventDefault() themselves are unaffected: their handler runs first
 * and this only catches what reaches the document.
 */
export function useBlockStrayFileDrops(): void {
  useEffect(() => {
    const isFileDrag = (e: DragEvent) =>
      Array.from(e.dataTransfer?.types ?? []).includes("Files");

    // dragover must also be prevented, or the drop event never fires and the
    // browser navigates anyway.
    const onDragOver = (e: DragEvent) => {
      if (isFileDrag(e)) e.preventDefault();
    };
    const onDrop = (e: DragEvent) => {
      if (isFileDrag(e)) e.preventDefault();
    };

    document.addEventListener("dragover", onDragOver);
    document.addEventListener("drop", onDrop);
    return () => {
      document.removeEventListener("dragover", onDragOver);
      document.removeEventListener("drop", onDrop);
    };
  }, []);
}
```

Two details that make this correct rather than merely present:

- **Guard on `dataTransfer.types` containing `"Files"`.** Preventing every
  `dragover` breaks unrelated drag interactions — the plan explicitly warns
  about this ("while avoiding interference with unrelated drag interactions"),
  and the repo has drag-and-drop elsewhere (dashboards, scope builder).
- **`dragover` must be prevented too.** Preventing only `drop` is the common
  half-fix: without a prevented `dragover` the browser never delivers a
  cancellable `drop` to the document, and it navigates regardless.

The existing dropzone needs **no change** — its own `preventDefault()` runs on
the bubble path before the document handler sees the event.

### 1.4 Fix 3 — where the resolver plugs in

The minimum viable correction is one argument (`project_id`), but the plan
rightly wants inference. Keep them separate:

1. **Unblock first:** when the resolver returns a confident single project,
   pass it as `project_id` to `createConversation`. That alone removes the
   "not attached to a project" error.
2. **Do not route this through `route-prompt`** (§0.4) — different caller,
   different contract. New service, called by both.
3. The resolver must filter candidates by authorization **before** scoring, not
   after, so an unauthorized project can never influence ranking or appear in a
   clarification prompt. The plan requires this outcome; making it a
   pre-filter rather than a post-filter is what guarantees it.

---

## 2. Corrected effort picture

| Fix | Plan's framing | Reality |
|---|---|---|
| 1 — ephemeral transcript | remove hydration | **nothing to remove**; reproduce first. Real work is the canonical thread (§0.2) + idempotency key (§1.1) |
| 2 — source list | add scrolling | **already has `overflow-y-auto`**; one class fixes it (§1.2). Search + New badge are real new work |
| 3 — project context | new resolver | correct, and root cause is one missing argument (§0.4) |
| 4 — pin separation | add destination | correct, **but the unique constraint must change too** or the acceptance criterion cannot pass (§0.6) |
| 5 — drag/drop | fix dropzone handlers | **dropzone is already correct**; the missing piece is a document-level guard (§0.7, §1.3) |

## 3. Sequencing

Do §1.2, §1.3, and the one-argument part of §1.4 first — three small, verifiable
changes that resolve the visible symptoms of fixes 2, 5 and 3. Then the genuinely
new subsystems: the context resolver, the pin destination migration, and search
plus the New badge.

Do not start fix 1 until the retention is reproduced (§0.1).

## 4. What to keep from the original plan unchanged

These are correct and should not be diluted:

- Tenant/project/user authorization enforced **server-side**, never trusting a
  client-supplied project id.
- Never reveal an unauthorized project name during context clarification.
- The New badge computed from an **immutable** `created_at`/`loaded_at`, never
  a mutable `updated_at`, with a rolling 24h UTC window and no badge on null.
- Panel pins are **not** frozen snapshots; they refresh and show a change state
  only on material change.
- Do not deduplicate insights by generated title or summary.
- Do not send the AI prompt until required uploads finish.
- Structured, privacy-safe observability that never logs file or prompt contents.
