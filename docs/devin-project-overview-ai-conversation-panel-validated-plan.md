# TableScope Devin-Ready Plan: Project Overview AI Assistant Conversations (Validated)

## Validation summary — read this before the source plan

Checked against `origin/devin/r-echarts-e2e-validation` (HEAD `a1969ff`).
The overall shape of this plan is sound, but it rests on two premises that
don't match the current codebase — one makes the work easier than the
plan implies, one makes a section of the plan currently unbuildable as
written. Both are corrected below.

### Correction 1 — "preserving the unified AI-Assisted Upload" does not exist to preserve

The plan's objective says to "preserve the unified AI-Assisted Upload
behavior for `Upload file`," and Section "Existing regions" implies this
already works. **It does not.** Verified in
`web-ui/components/tablescope/project/overview-screen.tsx`
(`QuickActionsCard`, lines 567-632):

```tsx
{
  label: "Upload document",
  icon: IconFileText,
  onClick: () => router.push(`/projects/${projectId}/documents`),
},
```

This is a bare navigation to the Documents page — there is no unified,
classifying AI-Assisted Upload anywhere in the codebase today (confirmed
via `git log --all -S 'preferredAssetFamily'` and `-S 'asset_family'`
across full history: zero hits). This is the exact same finding as the
companion plan `devin/project-nav-unified-ai-upload-datasource-update`
(validated separately), which specifies building that unified intake as
new work.

**This plan has a hard dependency on that one.** "Upload file" opening the
unified AI-Assisted Upload (Section "Quick actions" → "Upload file") is
not implementable until the unified intake exists. Sequence accordingly:
land `devin/project-nav-unified-ai-upload-datasource-update`'s Sections
1–5 first (or at minimum, its capability endpoint + intake entry point),
then wire this plan's "Upload file" quick action to it. If this plan ships
first, "Upload file" should keep today's behavior (navigate to Documents)
rather than pointing at a component that doesn't exist yet — do not block
the Quick Actions layout change (one-column) on the upload dependency;
those are independent.

Confirmed accurate and unaffected by this correction: Quick Actions is
genuinely a two-column grid today (`grid grid-cols-2 gap-2`, same file,
line 609) — the plan's "convert to one vertical column" requirement is
real and independent of the upload dependency above.

### Correction 2 — no conversation-sharing model exists; "existing sharing policy" is not a thing to reuse

The plan's "Conversation privacy" section repeatedly refers to "the
existing sharing policy" and "explicitly shared and authorized" threads as
if reusing established infrastructure. Checked
`platform-api/app/models/analytics_conversation.py` in full: the
`AnalyticsConversation` model has `tenant_id`, `user_id` (creator only),
`project_id`, `surface`, `title`, `status` — **no `is_shared`,
visibility, or ACL field of any kind.** Confirmed further in
`platform-api/app/routes/conversational_analytics.py`'s `list_conversations`
(line 251): it filters strictly `tenant_id == context.tenant_id AND
user_id == context.user_id` — every conversation is implicitly private to
its creator today; there is no sharing mechanism to authorize against.

**This changes real scope.** Building a full thread-sharing system (who
can share, with whom, at what grain) is a meaningfully sized feature in
its own right and isn't scoped anywhere in this plan's sprints/phases.
Recommendation: ship this panel showing **only the current user's own
project conversations** (matching what the data model actually supports
today), and treat "explicitly shared and authorized" as explicitly
out-of-scope-for-now rather than quietly building a sharing model as a
side effect of a UI panel. Every place the source plan says "current
user's private conversations... and project conversations explicitly
marked shared and authorized," read it as "current user's own project
conversations" until/unless sharing is separately requested. This does
not weaken privacy — if anything it's the safer default, since it removes
an entire cross-user exposure surface (the plan's own stated top
concern — "Never show another user's private prompt or result merely
because both users can access the project" — is trivially satisfied when
there is no sharing to misconfigure).

The plan's third visibility condition ("user is authorized by an existing,
documented administrative review permission") — no such per-conversation
admin-review permission exists either; drop it for the same reason.

### Correction 3 (clarifying, not contradicting) — "temporary transcript" means on-page React state, not a separate storage tier

Worth making explicit so Devin doesn't over-correct: Project Overview's
"Ask Anything" already persists through the **exact same**
`createConversation`/`submitTurn` API and `AnalyticsConversation` table
that AI Assistant reads — confirmed in `overview-screen.tsx:113-150`:

```tsx
const created = await createConversation({
  project_id: Number(projectId),
  title: PROJECT_INSIGHTS_TITLE,
  surface: PROJECT_INSIGHTS_SURFACE,  // "project_insights"
  initial_message: message,
});
```

What's "temporary" is only the on-page `useState` transcript
(`chatTurns`, `chatConversationId`), which resets on refresh because
nothing rehydrates it from a stored ID — the underlying conversation row
is permanent from the moment it's created. The source plan's Section 7
already gets this right ("the saved question/result remains visible in
the AI Assistant Conversations panel" after refresh clears the page
transcript) — this note just removes the risk of reading "temporary" too
literally and excluding real Ask Anything history from the panel's query.

### Correction 4 — the surface filter has a concrete, precise answer

The plan's eligibility rule ("conversation scope/type is project or
Project Insights/Overview for that project") and its exclusion rule
("Business Insights conversations without this project scope") are both
underspecified in the source text. Verified exact `surface` values used
across the app:

| Creator | `surface` value |
|---|---|
| `web-ui/app/business-insight/page.tsx` | `"business_insights"` |
| `web-ui/components/tablescope/project-insight/project-insight-screen.tsx` | `"project_insights"` |
| Project Overview "Ask Anything" (`overview-screen.tsx`) | `"project_insights"` |
| `web-ui/app/ai/page.tsx` (AI Assistant, new conversation) | none passed → DB default `"ai_assistant"` |

Business Insight conversations *do* get a `project_id` set when the
question resolves to a specific project (confirmed:
`resolve_business_insight_project` in
`platform-api/app/services/conversational_analytics.py`), so filtering on
`project_id` alone is not sufficient to satisfy the plan's own exclusion
rule — a Business Insight conversation that happened to resolve to this
project would otherwise leak in. The precise, implementable filter is:

```python
AnalyticsConversation.project_id == project_id,
AnalyticsConversation.surface.in_(("project_insights", "ai_assistant")),
```

Use this exact condition in Section 2/3 of the source plan rather than the
prose description.

### Implementation shortcuts the source plan doesn't mention

1. **The list endpoint mostly already exists.** `GET /api/conversational-
   analytics/conversations?project_id=X` (`conversational_analytics.py:251`)
   already filters `tenant_id + user_id + project_id` and orders by
   `updated_at desc`. It's missing: a `limit` parameter, the surface
   filter from Correction 4, question/result preview fields, and
   completed-turn-only filtering. **Extend this endpoint** (add
   `limit`, apply the surface filter, add preview projection) rather than
   building an unrelated new route — Section 3's proposed
   `GET /api/projects/{projectId}/ai-conversations/recent` contract is a
   reasonable *response shape* to adopt, but implement it as parameters on
   the existing endpoint (or a thin wrapper that calls the same query
   builder) so there's one source of truth for "this user's project
   conversations," not two.
2. **`last_successful_turn_id` already exists on the model**
   (`analytics_conversation.py:47-49`, with a `last_successful_turn`
   relationship). This is exactly the field needed to get "the latest
   completed result" per conversation in one query via `selectinload`,
   without scanning turns or loading full message bodies — directly
   satisfies the plan's own performance requirements ("avoid loading
   entire message bodies," "avoid one query per conversation").
3. **Deep-linking already works.** `web-ui/app/ai/page.tsx` already reads
   both `?conversation=` and `?projectId=` query params on mount
   (confirmed: `searchParams.get("conversation")`,
   `searchParams.get("projectId")`) and hydrates the exact conversation.
   `overview-screen.tsx`'s own `openInAssistant()` already navigates to
   `/ai?conversation=${chatConversationId}&projectId=${projectId}` — reuse
   this exact pattern for each panel row's link target; there is no new
   URL scheme to invent. Turn-level deep-linking (`turnId`) is not
   currently read by `ai/page.tsx` — either add that (scroll-to-turn) or
   drop turn-level precision from the acceptance bar; don't claim it works
   today.

### Confirmed accurate, no correction needed

- `Project activity` panel exists exactly as described: rendered by
  `ProjectActivityCard` in `overview-screen.tsx` (heading "Project
  activity," line 523), backed by `GET /api/projects/{project_id}/activity`.
  **Important, and correctly anticipated by the source plan's own
  caution**: this endpoint's docstring states it "Powers the Audit Log
  (Intelligence) screen" — it is shared, not Overview-exclusive. Do not
  remove or modify the backend endpoint; only stop calling
  `useProjectActivity` from `overview-screen.tsx`, and grep the Audit Log
  screen component first to confirm it still imports the hook
  independently before deleting anything from Overview.
- Quick Actions' current order — Add data source, Create table, Upload
  document, New dashboard — already matches the required order; only the
  grid-to-column layout and the upload wiring (per Correction 1) need to
  change, not the ordering.

---

## Everything below is the original plan, preserved as validated

The objective's items 2–4 and 6, all Product decisions except the
sub-points corrected above, Scope (in/out), Phase 0 discovery list,
Sections 1 and 5–16 (panel construction, deep-link behavior, connecting
new questions, Quick actions functional requirements other than Upload
file's target, lower-panel layout, resource-nav preservation, loading/
empty/error states, caching/freshness, security/privacy minus the sharing
model, telemetry, full test matrix, implementation sequence, feature
flag/deployment/rollback, PR deliverables, manual acceptance checklist,
and definition of done) are accurate and should be implemented as
written, with these adjustments:

- Section "Conversation privacy" → apply Correction 2: current-user-only,
  drop the shared/admin-review branches until sharing is separately
  requested.
- Section 2 "Conversation scope" → apply Correction 4's exact filter.
- Section 3 "Add or reuse a recent-conversations contract" → apply
  shortcut 1 (extend the existing endpoint) and shortcut 2
  (`last_successful_turn_id`).
- Section 6 "Deep-link behavior" → apply shortcut 3 (reuse the existing
  `/ai?conversation=&projectId=` pattern; scope turn-level linking
  explicitly in or out based on whether `ai/page.tsx` gets a `turnId`
  reader added).
- Section 8 "Quick actions: one vertical column" → "Upload file" opens the
  unified AI-Assisted Upload **once `devin/project-nav-unified-ai-upload-
  datasource-update` lands**; until then, keep current Documents-page
  navigation behavior for that one action so this plan isn't blocked on
  the other.
- Any test or acceptance-checklist item asserting cross-user shared-thread
  visibility (e.g. "explicitly shared project thread visibility" in the
  Component/Integration test lists) — drop per Correction 2, or convert to
  "confirm no shared-thread UI is exposed" if a negative test is still
  useful.

## Branch / PR

Branch: `devin/project-overview-ai-conversation-panel`, based on
`origin/devin/r-echarts-e2e-validation` (HEAD `a1969ff` at validation
time) — same base as the sibling upload/nav plan, not stacked on it, per
this session's branching convention. The two plans have a real sequencing
dependency (documented in Correction 1) that should be resolved by
coordinating merge order, not by one branch depending on the other's
unmerged commits. This doc is the only change on the branch; Devin
implements per the source plan plus the corrections above.
