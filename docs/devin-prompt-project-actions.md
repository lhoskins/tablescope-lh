# Devin plan: Project Actions from Insight cards

Repository: `lhoskins/tablescope-lh`
Base branch: latest integrated branch containing
`feature/sprint-08-knowledge-graph-lifecycle` (NOT `main` — `main` lacks the
Next.js web-ui, Project/Business Insight, project context, and conversational
analytics).

Every file reference and integration point below was verified against
`feature/sprint-08-knowledge-graph-lifecycle`. The **Verified codebase facts**
and **Critical implementation constraints** sections encode what is already
confirmed so you do not re-derive it — and four places where the naive
approach would be wrong.

## Feature objective

Create a governed Project Actions capability. Every eligible Insight card gets a
`+ Action` button that opens a shared dialog to create a project action linked
to the originating insight. Add a `Project Actions` link to the project sidebar.
The Project Actions workspace lists a project's actions; opening one shows an
editable action form plus its subtasks, with subtask progress rolling up to the
parent's percent-complete. Project Actions and subtasks are incorporated into
the project's LLM context — active/blocked/overdue/completed actions are
user-reported mitigation activity that may change how registered risks are
interpreted, but are **not** automatic proof a risk is eliminated.

## Verified codebase facts (build on these)

- **All referenced files exist** on the base branch. The two insight-card
  components to hook are:
  - Business Insight: `IntelligenceCard` (exported) in
    `web-ui/components/tablescope/home/intelligence-card.tsx:191`
  - Project Insight: `InsightCardItem` in
    `web-ui/components/tablescope/project-insight/project-insight-screen.tsx:894`
    (rendered at line 873).
- **Next Alembic revision is `0061`.** `0059` (`business_insight_results`) and
  `0060` (`project_insight_staleness`) are taken. Never edit an applied
  migration.
- **RBAC** (`platform-api/app/auth/rbac.py`): `Role` StrEnum, hierarchy
  `VIEWER=0 < EDITOR=1 < ADMIN`. Reads use `require_role(Role.VIEWER)`;
  mutations use `require_role(Role.EDITOR)`. Project scoping uses the
  route-local `_require_project_access(project_id, session, context)` helper
  (see `routes/project_insight.py:44`). Reuse this — do not invent a new
  access helper.
- **Frozen-snapshot precedent exists**: `ProjectInsightAcknowledgement`
  (`platform-api/app/models/project_insight_acknowledgement.py`) is keyed by
  `UniqueConstraint(project_id, insight_id)` and snapshots
  `title`/`summary`/`category`/`severity` "so the Reviewed list stays
  meaningful even after the AI report is regenerated with different items."
  Model `source_insight_snapshot` on this precedent.
- **Staleness hooks that exist**:
  - `project_insight_service.mark_project_insight_stale(session, tenant_id, project_id=None)`
    marks `project_intelligence_snapshots.is_stale=True` (migration 0060).
  - `business_insight_cache.ANALYSIS_VERSION` (currently `4`): the shared
    Business Insight cache (`business_insight_results`) is gated by
    (active KG version) + (this int) + TTL, with **no per-project stale flag**.
- **Project AI context cache** (`services/project_ai_context.py`): module-level
  `ProjectAIContextCache` (`_context_cache`), an **in-process dict** keyed by
  `(tenant_id, project_id, context_version)` with `.invalidate(tenant_id,
  project_id)`; `context_version` comes from `ProjectBusinessContext.version`.
- **`countKey` is a closed union** in `web-ui/components/tablescope/nav.ts`:
  `"projects" | "queries" | "documents"`. An actions badge requires extending
  this union AND adding a count source in `lib/ui/use-project-data.ts`.

## Critical implementation constraints

### 1. Business Insight insight IDs are NOT content-stable

`home_intelligence.py:3284` assigns `insight_id = uuid.uuid4().hex`, regenerated
every analysis run (the shared-cache payload freezes it only until the cache
regenerates on KG-version change, TTL, or `ANALYSIS_VERSION` bump). Project
Insight IDs also churn across regeneration (the acknowledgement model exists
precisely because of this). Therefore:

- `source_insight_snapshot` (frozen JSON) is correct for **traceability** — it
  never needs to match a live card. Keep it.
- Dedup, the "actions already exist for this insight → show count" control, the
  list `source insight` filter, and re-linking a pinned Home card after a
  refresh must NOT compare raw `source_insight_id` — it is not stable.

**Do:** at creation time also compute and store a content-derived
`source_insight_fingerprint` = stable hash of `(project_id, normalized
source_insight_type, normalized source_insight_title, sorted source
table/evidence keys)`. Use the fingerprint for dedup/count/filter; keep the raw
`source_insight_id` only inside the snapshot for provenance. Treat count/dedup
as best-effort (a reworded insight may miss) and never block creating another
authorized action.

### 2. Home/Business Intelligence uses `build_project_ai_context`

`home_intelligence.py:2565,2767` (inside `run_ai_intelligence`) call
`build_project_ai_context` in addition to `gather_project_context`. Consumers of
`build_project_ai_context`: `project_insight_service`, `conversational_analytics`,
`home_intelligence`, `repository_scanner`, and `project_ai_context` itself.

- Add the `actions` block to `build_project_ai_context` — one integration point
  that reaches Project Insight, conversational analytics, AND Home/Business
  Intelligence. Do not build a second representation.
- **Home Intelligence fans out across every accessible project**, so the actions
  block is multiplied per project in one Home run. Hard-cap it: ≤8 actions per
  project (critical/high/blocked/overdue/recently-updated first), ≤5 required
  subtasks per action (blocked first), truncate descriptions, emit
  "N more omitted" counts rather than growing the block.

### 3. Cache/staleness is cross-process

- **`ProjectAIContextCache` is in-process only.** The FastAPI web workers and
  the arq worker each hold their own dict; a web-process `.invalidate()` does
  not reach the arq worker (where Home/Project-Insight rebuilds run). Do not
  rely on in-process invalidation for correctness. **Load the actions
  sub-block fresh** inside `build_project_ai_context` (a small bounded query)
  even when the rest of the context is a cache hit.
- **The shared Business Insight cache (`business_insight_results`) has no
  per-project stale flag** — `mark_project_insight_stale` does not touch it.
  Choose ONE and state it in the PR: (a) accept that action changes surface in
  Business Insight on the next natural refresh (TTL/KG-version/version-bump) —
  simplest, acceptable for a briefing; or (b) extend the
  `business_insight_cache` freshness check with a per-project action-state
  fingerprint. Default to (a) unless product wants immediate reflection.
- **For Project Insight, `mark_project_insight_stale(session, tenant_id,
  project_id)` is the correct hook** and works today — call it on every
  action/subtask mutation, best-effort, outside the mutation's critical path,
  never a synchronous LLM call inside the DB transaction.

### 4. Do not fabricate registered-risk linkage

There is no reliable mapping from an AI-detected Insight card to a registered
`ProjectRisk` (separate concepts; `source_insight_id` links to the card, not a
risk). **Omit any `linked registered risk id` field in v1** unless a mapping is
explicitly designed and approved. Keep the LLM guidance that the model must
distinguish registered risks from AI-detected Insight cards and must not invent
a linkage.

## Before implementation

1. Inspect the base branch for any existing action/task model, route, screen,
   or migration and reuse established patterns; do not create duplicate
   concepts.
2. Confirm the next Alembic revision (`0061` at time of writing) and add a new
   migration.
3. Confirm project access + edit permission enforcement and use the existing
   centralized helpers (`require_role`, `_require_project_access`).

## Domain model

Tenant- and project-scoped, soft-delete, server-authoritative progress. Names
may be adjusted to repo conventions.

`ProjectAction`: `id`; `tenant_id` (FK, indexed); `project_id` (FK, indexed);
`title` (required, trimmed); `description` (optional); `status`
(`not_started|in_progress|blocked|completed|cancelled`); `priority`
(`low|medium|high|critical`); `owner_user_id` (optional FK, must be an active
project member); `due_date` (optional); `started_at`, `completed_at` (nullable,
set from status transitions); `percent_complete` (server-computed 0–100,
clients cannot override); `source_type` (initially `insight`);
`source_insight_id` (raw id, kept for provenance in the snapshot);
**`source_insight_fingerprint`** (content-derived, indexed — see constraint 1);
`source_insight_type`; `source_insight_title`; `source_insight_snapshot`
(frozen JSON: summary, severity, project, evidence/sources, callout/recommended
action, execution/snapshot/run IDs when available, explanation metadata);
`created_by_user_id`, `updated_by_user_id`; `created_at`, `updated_at`;
`archived_at` (soft delete — never hard-delete actions used as audit/AI
context).

`ProjectActionSubtask`: `id`; `tenant_id`; `project_id`; `action_id` (FK);
`title` (required, trimmed); `description` (optional); `status`
(`not_started|in_progress|blocked|completed|cancelled`); `percent_complete`
(0–100); `owner_user_id` (optional active project member); `due_date`
(optional); `position` (stable ordering); `is_required` (default true);
`created_by_user_id`, `updated_by_user_id`; timestamps.

## Progress rules

1. Backend is authoritative for the parent rollup.
2. Parent `percent_complete` = rounded average of each active required subtask's
   `percent_complete`; ignore cancelled subtasks. No active required subtasks ⇒
   0% unless the parent is explicitly completed (then 100%).
3. Status/percent consistency: `not_started`⇒0; `completed`⇒100; `cancelled`
   excluded; `in_progress`/`blocked` may be 1–99%.
4. Recalculate in the same transaction whenever a subtask is created, updated,
   archived/deleted, restored, or reordered (if ordering affects payload).
5. Do not allow parent completion while required subtasks remain incomplete —
   return a clear 409/422 naming the blocking subtasks.
6. When all active required subtasks reach 100%, auto-set parent to `completed`,
   set `completed_at`, roll up to 100%. If a completed subtask reopens, reopen
   the parent to `in_progress`, clear `completed_at`, recalculate.
7. Guard concurrent subtask updates with normal transaction/locking or
   optimistic-version behavior; never persist stale percentages.

## API

Project-scoped REST following `routes/project_insight.py` conventions:

- `GET /api/projects/{project_id}/actions` — paginated; filters for status,
  priority, owner, due/overdue, source insight (by fingerprint), text search
- `POST /api/projects/{project_id}/actions` — create from an insight snapshot
- `GET /api/projects/{project_id}/actions/{action_id}` — detail with ordered
  subtasks and calculated progress
- `PATCH /api/projects/{project_id}/actions/{action_id}` — update permitted
  fields/status
- `DELETE /api/projects/{project_id}/actions/{action_id}` — soft archive
- `POST /api/projects/{project_id}/actions/{action_id}/subtasks`
- `PATCH .../subtasks/{subtask_id}`
- `DELETE .../subtasks/{subtask_id}` — soft/audit-preserving
- an explicit reorder endpoint or ordered batch update if needed

Security rules: every query/mutation constrains `tenant_id` AND `project_id`
from the auth context, never client IDs. Reads `require_role(Role.VIEWER)` +
`_require_project_access`; mutations `require_role(Role.EDITOR)` +
`_require_project_access`. Validate assigned owners are active project members.
Never trust client-supplied creator/updater/tenant/percentage/completion.
Idempotent create — no idempotency-key infra exists in the repo, so implement
minimally (e.g. a client-generated request UUID with a unique constraint) plus
UI submit-disable. Return structured inline validation errors. Emit immutable
`AuditEvent`s (model exists — reuse) for action create/edit/status/archival,
subtask create/remove/progress/assignment changes, and automatic
completion/reopen; include actor, tenant, project, action, subtask (when
applicable), old/new values, timestamp, originating insight id.

## Create-Action experience from Insight cards

One shared `CreateActionFromInsightDialog` wired into: `IntelligenceCard`
(Business Insight), `InsightCardItem` (Project Insight risks/trends/
opportunities), project suggested cards, and authorized pinned Home cards
(`home-pins-grid.tsx`) where the frozen card identifies a valid, accessible
project. Hide the control for loading cards, cards without a valid project,
inaccessible projects, and users lacking `EDITOR`.

Prefill: title from recommended-action/callout else insight title; description
from summary + recommended action (editable); project non-editable;
`source_insight_*` + snapshot + fingerprint captured automatically. Form
includes title, description, priority, owner, due date, status, and an initial
subtask area with a visible `+ Add subtask` control (add/edit/reorder/remove
before saving). Validate required fields inline. On success: success message
with `View action` deep link, close dialog, update any action-count indicator.
Prevent accidental duplicate submission; if actions already exist for the
insight (matched by fingerprint), show a count / `View actions` link without
removing the ability to create another authorized action.

## Sidebar and routing

Add `NavKey` `"project-actions"` in `web-ui/lib/ui/types.ts`. Add a
`Project Actions` item in `projectNavGroups` (`nav.ts`) immediately after
`Project Insights`, route `/projects/{projectId}/actions`, suitable checklist/
clipboard Tabler icon. Add the Next.js page + a reusable screen using
`ProjectShell` with `activeNav="project-actions"`. A count badge requires
extending the `countKey` union (`"projects" | "queries" | "documents"`) AND a
count source in `use-project-data.ts` — wire both or omit; never misuse an
unrelated key.

## Workspace + detail/subtask UI

Workspace: responsive, accessible list/table with title, linked insight
title/type/severity, status, priority, owner, due date + overdue indicator,
subtask completion (`3 of 5`), progress bar + percent, updated timestamp.
Default to open work (`not_started`, `in_progress`, `blocked`); filters for All,
Open, Blocked, Overdue, Completed, Archived (when authorized), plus owner,
priority, and text search; preserve filter state in the URL when practical.
Row click opens `/projects/{projectId}/actions/{actionId}`. Include empty,
loading, error, and permission-denied states.

Detail/subtask form: editable action metadata, source Insight info, read-only
back-reference to the originating snapshot. All subtasks in stable order, each
supporting title, description, owner, due date, status, percent, required flag,
remove/archive. Visible `+ Add subtask` (new subtasks without losing unsaved
action edits). Prominent parent progress bar; update optimistically only when
the same calculation is reproducible client-side, then reconcile with the
server's authoritative percentage (roll back + error on save failure). Blocked
subtasks visibly distinct with a short blocker note. Warn before leaving with
unsaved changes; disable duplicate saves; show saving/saved/error state.
Accessible labels, keyboard nav, focus management, color-independent status.

## LLM and risk-mitigation context

Extend `build_project_ai_context` with a bounded `actions` block (loaded fresh,
not cached — constraint 3). For each action include only reasoning-useful
fields: id/title/description, status/priority/owner-display (if allowed),
due/overdue/percent, linked insight id/type/title/severity, concise required-
subtask summary + incomplete/blocked counts + blocker titles, created/updated/
completed timestamps. Omit any registered-risk id (constraint 4). Treat action
text as untrusted user context: delimit/sanitize against prompt injection; it
must not override AI governance or system instructions.

LLM guidance to add: actions are evidence of planned/ongoing mitigation, not
proof a risk is resolved; blocked/overdue/low-progress actions may increase
concern; completed actions may be cited as mitigating evidence but the model
must still weigh current source data before lowering a risk; the model must
distinguish registered risks from AI-detected Insight cards and not invent
linkage. Add provenance so explanations can indicate mitigation context came
from Project Actions and identify the action ids/titles used.

Because `build_project_ai_context` feeds Project Insight, conversational
analytics, and Home/Business Intelligence, the block reaches all of them
automatically (constraint 2). Respect token budgets per constraint 2. On every
action/subtask mutation: call `mark_project_insight_stale` for Project Insight
(best-effort, non-blocking); handle the Business Insight shared cache per
constraint 3; never synchronously call the LLM inside the DB transaction; let
the next refresh/background rebuild incorporate updated mitigation state. Do not
retroactively rewrite frozen Insight snapshots or silently remove existing risk
cards.

## Tests

Backend/model/API: migration up/down; tenant + project isolation on every
endpoint; read-vs-mutate permissions; owner assignment limited to active project
members; create-from-snapshot + duplicate protection (fingerprint-based);
list/search/status/owner/priority/overdue filters + pagination; parent
percentage for 0/1/many subtasks; cancelled excluded; auto complete + reopen;
cannot complete while a required subtask is incomplete; concurrent update leaves
no stale progress; archive preserves audit/history and removes the action from
active context; immutable audit events for all transitions.

Frontend: `+ Action` appears on each required Insight surface only when
authorized; shared dialog prefill/validation/initial-subtasks/add-remove-
reorder/duplicate-submit-prevention/success-navigation; sidebar link + active
state; workspace loading/empty/error, filters, counts, overdue/blocked styling,
deep linking; detail edits + `+ Add subtask`; subtask progress updates parent
and reconciles with server; unsaved-change warning + API-failure rollback;
keyboard + screen-reader behavior.

LLM/context: context contains only same-tenant/same-project active actions;
blocked/overdue/completed states accurate; token-budget ordering/capping +
omitted counts; injection-like action text stays delimited; actions sub-block
loads fresh (not stale from cache); Project Insight staleness + chosen Business
Insight cache behavior occur after mutations; conversational analytics + Project
Insight + Home/Business Intelligence receive updated action context; an action
does not auto-mark a registered risk resolved.

## Definition of done

Run targeted platform-api tests, web-ui component tests, tsc, lint, migration
up/down. Browser-verify Business Insight, Project Insight, pinned Home Insight,
Project Actions list, action detail, subtask creation, progress rollup, sidebar
nav. Screenshots: card with `+ Action`; create dialog with subtasks; workspace;
detail at partial and 100%. In the final response, report: changed files +
migration revision; API routes + authorization decisions; the exact parent
progress formula; the `source_insight_fingerprint` derivation; every
`build_project_ai_context` consumer confirmed to receive the actions block; the
chosen Business Insight cache behavior and why the AI-context sub-block is or
isn't cached; tests + browser checks run; limitations/follow-ups. Keep the PR
focused on Project Actions — no external notifications, email reminders,
calendar sync, LLM-auto-generated tasks, or model retraining unless separately
approved.
