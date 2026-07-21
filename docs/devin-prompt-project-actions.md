# Devin prompt: Project Actions from Insight cards (validated + enhanced)

> This is an enhanced version of the original Project Actions prompt. Every
> file reference and integration point below was verified against
> `feature/sprint-08-knowledge-graph-lifecycle` (HEAD `359367f`). The
> **VALIDATED CODEBASE FACTS** and **CRITICAL CORRECTIONS** sections encode
> what was confirmed so you don't re-derive it — and two places where the
> original plan's assumptions were wrong.

---

Repository: `lhoskins/tablescope-lh`
Base branch: latest integrated branch containing
`feature/sprint-08-knowledge-graph-lifecycle` (NOT `main`).

## VALIDATED CODEBASE FACTS (confirmed — build on these)

- **All 19 referenced files exist** on the base branch. The two insight-card
  components to hook are confirmed:
  - Business Insight: `IntelligenceCard` (exported) in
    `web-ui/components/tablescope/home/intelligence-card.tsx:191`
  - Project Insight: `InsightCardItem` in
    `web-ui/components/tablescope/project-insight/project-insight-screen.tsx:894`
    (rendered at line 873).
- **Next Alembic revision is `0061`.** `0059` (`business_insight_results`) and
  `0060` (`project_insight_staleness`) are taken. Do not reuse them.
- **RBAC pattern** (`platform-api/app/auth/rbac.py`): `Role` StrEnum with
  hierarchy `VIEWER=0 < EDITOR=1 < ADMIN`. Reads use
  `require_role(Role.VIEWER)`; mutations use `require_role(Role.EDITOR)`.
  Project scoping uses the route-local `_require_project_access(project_id,
  session, context)` helper (see `routes/project_insight.py:44`). Mirror this
  exactly — do not invent a new access helper.
- **Frozen-snapshot precedent already exists**: `ProjectInsightAcknowledgement`
  (`platform-api/app/models/project_insight_acknowledgement.py`) is keyed by
  `UniqueConstraint(project_id, insight_id)` and stores a snapshot of
  `title`/`summary`/`category`/`severity` "so the Reviewed list stays
  meaningful even after the AI report is regenerated with different items."
  **Model `source_insight_snapshot` on this precedent** — it is the proven
  pattern for exactly this problem, and its existence is the direct evidence
  for CRITICAL CORRECTION #1.
- **Staleness hooks that exist**:
  - `project_insight_service.mark_project_insight_stale(session, tenant_id, project_id=None)`
    — marks `project_intelligence_snapshots.is_stale=True` (migration 0060).
  - `business_insight_cache.ANALYSIS_VERSION` (currently `4`) — the shared
    Business Insight cache (`business_insight_results`) is gated by
    (active KG version) + (this version int) + TTL, NOT by a per-project
    stale flag. See CRITICAL CORRECTION #2.
- **Project AI context cache** (`services/project_ai_context.py`):
  module-level `ProjectAIContextCache` (`_context_cache`), an **in-process
  dict** keyed by `(tenant_id, project_id, context_version)`, with
  `.invalidate(tenant_id, project_id)`. `context_version` is sourced from
  `ProjectBusinessContext.version`. See CRITICAL CORRECTION #3.
- **`countKey` is a closed union** in `web-ui/components/tablescope/nav.ts`:
  `"projects" | "queries" | "documents"`. Adding an actions badge requires
  extending this union AND adding a count source in `lib/ui/use-project-data.ts`.

## CRITICAL CORRECTION #1 — Business Insight insight IDs are NOT content-stable

The original plan hinges action↔insight linkage on `source_insight_id` being a
"stable insight ID/fingerprint". **This is false for Business Insight (Home)
cards.** `home_intelligence.py:3284` assigns `insight_id = uuid.uuid4().hex`,
regenerated on every analysis run; the shared-cache payload freezes it only
until the cache regenerates (KG-version change, TTL, or `ANALYSIS_VERSION`
bump). Project Insight cards prefer a server-generated `insightId` but the
acknowledgement model's own comment confirms IDs/items change across
regeneration. Consequence:

- `source_insight_snapshot` (frozen JSON) is the correct design for
  **traceability** — it never needs to match a live card. Keep it. ✔
- But **duplicate detection, the "actions already exist for this insight →
  show count" control, the list `source insight` filter, and re-linking a
  pinned Home card to its actions after a refresh all break** if they compare
  raw `source_insight_id`, because that id is not stable across regenerations.

**Required change:** at action-creation time, also compute and store a
**content-derived `source_insight_fingerprint`** = a stable hash of
`(project_id, normalized source_insight_type, normalized source_insight_title,
sorted source table/evidence keys)`. Use THIS for dedup/count/filter; keep the
raw `source_insight_id` only inside the frozen snapshot for provenance. Treat
the count/dedup feature as best-effort (a fingerprint collision or a
substantially reworded insight may miss) and never block creating another
authorized action — the original plan point 8's "multiple intentional actions
allowed" stance is correct.

## CRITICAL CORRECTION #2 — Home/Business Intelligence DOES use `build_project_ai_context`

The original plan (LLM context, point 5) hedges: "Confirm whether
Business/Home Intelligence uses the same package; if it does not, add …".
**Confirmed: it does.** `home_intelligence.py` imports and calls
`build_project_ai_context` at lines 2565 and 2767 (inside
`run_ai_intelligence`), in addition to its own `gather_project_context`.
Consumers of `build_project_ai_context`: `project_insight_service`,
`conversational_analytics`, `home_intelligence`, `repository_scanner`,
and `project_ai_context` itself.

**Consequences:**
- Adding the `actions` block to `build_project_ai_context` is a SINGLE
  integration point that automatically flows to Project Insight,
  conversational analytics, AND Home/Business Intelligence. Do not build a
  second representation.
- **But Home Intelligence fans out across every accessible project**, so the
  actions block is multiplied per-project in one Home run. The token budget
  (plan point 8) must be strict and is more important than the plan implies:
  hard-cap included actions per project (suggest ≤8, critical/high/blocked/
  overdue/recently-updated first), cap subtasks per action (suggest ≤5
  required, blocked first), truncate descriptions, and emit "N more omitted"
  counts rather than growing the block.

## CRITICAL CORRECTION #3 — cache/staleness is cross-process; plan under-specifies

Two distinct caches must be handled, and neither is invalidated by a naive
in-process call:

1. **`ProjectAIContextCache` is in-process only.** The FastAPI web workers and
   the separate arq worker each hold their own module-level dict. Calling
   `_context_cache.invalidate()` in the web process on an action mutation does
   NOT clear the arq worker's copy (and Home/Project-Insight rebuilds run in
   the worker). **Do not rely on in-process invalidation for correctness.**
   Preferred: make the actions block bypass this cache, OR fold an
   action-state component into the cache key so a stale entry is naturally
   missed. The cache is keyed by `context_version` today (from
   `ProjectBusinessContext.version`); actions are not part of that version, so
   an unchanged-context project would serve a stale actions block. Simplest
   robust option: **do not cache the actions sub-block** — load it fresh inside
   `build_project_ai_context` (it is a small bounded query) even when the rest
   of the context is cache-hit.

2. **The shared Business Insight cache (`business_insight_results`) has no
   per-project stale flag.** It is gated by active-KG-version +
   `ANALYSIS_VERSION` + TTL. `mark_project_insight_stale` does NOT touch it.
   So "mark Business Insight snapshots stale" is not literally possible for the
   shared cache. Choose ONE and state it in your PR:
   - (a) Accept that action changes surface in Business Insight only on the
     next natural refresh (TTL/KG-version/version-bump) — simplest, acceptable
     because Business Insight is a briefing, not a live view; OR
   - (b) Extend the `business_insight_cache` freshness check to include an
     action-state fingerprint per project so an action mutation invalidates
     that project's cached cards. Only do this if product wants immediate
     reflection.
   For **Project Insight**, `mark_project_insight_stale(session, tenant_id,
   project_id)` IS the correct hook and works today — call it on every
   action/subtask mutation (best-effort, outside the mutation's critical path,
   never a synchronous LLM call).

## CRITICAL CORRECTION #4 — do not fabricate registered-risk linkage

The plan's optional `linked registered risk ID` field: confirmed there is **no
existing reliable mapping** from an AI-detected Insight card to a registered
`ProjectRisk` row (they are separate concepts; `ProjectRisk` is
user/context-authored, insight cards are AI-detected). `source_insight_id`
links to the CARD, not a registered risk. **Omit `linked registered risk ID`
in v1** unless a mapping is explicitly designed and approved — populating it by
guesswork is exactly the fabricated linkage the plan's own LLM-guidance
(point 4) forbids. Keep the LLM guidance that the model must distinguish
registered risks from insight cards and must not invent a linkage.

---

## The rest of the original plan is validated as-is

Everything below is confirmed correct against the codebase and should be
implemented as the original prompt specifies. Key points restated for Devin:

**Domain model** — `ProjectAction` + `ProjectActionSubtask`, tenant- and
project-scoped, soft-delete (`archived_at`), server-authoritative
`percent_complete`. Add `source_insight_fingerprint` (Correction #1) alongside
the specified `source_insight_*` fields. Migration `0061` (never edit an
applied migration).

**Progress rollup** — backend authoritative; rounded average of active required
subtasks' `percent_complete`; cancelled excluded; status/percent consistency
(`not_started`→0, `completed`→100); recalc in the same transaction; block
parent completion while required subtasks incomplete (return 409/422 naming
the blockers); auto-complete parent when all active required subtasks hit 100%;
reopen on subtask reopen; guard concurrent updates.

**API** — project-scoped REST under `/api/projects/{project_id}/actions[...]`,
following `routes/project_insight.py` conventions. Every query/mutation
constrains `tenant_id` AND `project_id` from the auth context, never from
client IDs. Reads `require_role(Role.VIEWER)` + `_require_project_access`;
mutations `require_role(Role.EDITOR)` + `_require_project_access`. Validate
assigned owners are active project members. Never trust client-supplied
creator/updater/tenant/percentage/completion fields. Idempotent create
(note: no idempotency-key infra exists in the repo — implement minimally, e.g.
a client-generated request UUID with a unique constraint, plus UI submit
disable). Structured inline validation errors. Immutable `AuditEvent`s for all
transitions (the `audit_event` model exists; reuse it).

**Insight-card `+ Action` UX** — one shared `CreateActionFromInsightDialog`
wired into `IntelligenceCard` (Business Insight), `InsightCardItem` (Project
Insight risks/trends/opportunities), project suggested cards, and
authorized pinned Home cards (`home-pins-grid.tsx`) where the frozen card
identifies a valid, accessible project. Hide the control for loading cards,
cards without a valid project, inaccessible projects, and users lacking
`EDITOR`. Prefill title from recommended-action/callout else insight title;
description from summary+recommended action (editable); project non-editable;
`source_insight_*` + snapshot + fingerprint captured automatically. Initial
subtask area with `+ Add subtask`. Duplicate-submit prevention. Success →
`View action` deep link.

**Sidebar/routing** — add `NavKey` `"project-actions"` in `lib/ui/types.ts`;
add the `Project Actions` item in `projectNavGroups` immediately after
`Project Insights` (`nav.ts`), route `/projects/{projectId}/actions`; Next.js
page + screen using `ProjectShell activeNav="project-actions"`. A count badge
requires extending the `countKey` union (`"projects" | "queries" |
"documents"`) AND a count source in `use-project-data.ts` — only add it if you
wire both cleanly; otherwise omit rather than misuse an unrelated key.

**Workspace + detail/subtask UI, LLM context block, and tests** — implement per
the original prompt, with the Correction #1–#4 changes applied:
`build_project_ai_context` gains a bounded `actions` block (loaded fresh, not
cached — Correction #3); it flows to Project Insight, conversational analytics,
and Home/Business Intelligence automatically (Correction #2); action text is
delimited/sanitized as untrusted user context; LLM guidance states actions are
mitigation evidence not proof of resolution; omit `linked registered risk id`
(Correction #4). On mutation: call `mark_project_insight_stale` for Project
Insight (best-effort, non-blocking, no in-transaction LLM call); decide and
document the Business Insight shared-cache behavior (Correction #3, option a or
b); never rewrite frozen insight snapshots or remove existing risk cards.

## Definition of done (unchanged, plus)

Run targeted platform-api tests, web-ui component tests, tsc, lint, migration
up/down. Browser-verify Business Insight, Project Insight, pinned Home Insight,
Project Actions list, action detail, subtask creation, progress rollup, sidebar
nav. Screenshots: card with `+ Action`; create dialog with subtasks; workspace;
detail at partial and 100%. In the final response, report: changed files +
migration revision; API routes + auth decisions; the exact parent progress
formula; **the `source_insight_fingerprint` derivation (Correction #1)**;
**every `build_project_ai_context` consumer confirmed to receive the actions
block (Correction #2)**; **the chosen Business Insight cache behavior and why
the AI-context sub-block is or isn't cached (Correction #3)**; tests + browser
checks; limitations/follow-ups. Keep the PR focused on Project Actions — no
notifications, email, calendar sync, LLM-auto-generated tasks, or retraining.

## One dependency note for whoever runs this

The base branch's project sidebar currently has **no Documents or Dashboards
entries** (removed by a "sidebar cleanup" commit; restore is pending on
`claude/validate-enhance-logic-r2fyy1`, commit `6061fce`). When you add
`Project Actions` after `Project Insights`, do not also delete or reorder other
entries — and if the Documents/Dashboards restore has merged by then, keep it.
Coordinate so the two sidebar changes don't conflict.
