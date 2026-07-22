# Devin plan: Insight feedback review lifecycle, statuses, and card behavior

Repository: `lhoskins/tablescope-lh`

This plan completes the end-to-end Insight feedback workflow: Agree bypasses
review, Disagree enters a governed reviewer queue, the submitter sees live
status on the card, a reviewer can acknowledge / request information / receive a
response / disposition, and project members see only a safe governance badge —
all tenant-scoped, project-scoped, permission-gated, and audited.

> This is a **validated + corrected** version of an earlier draft. The earlier
> draft's branch recommendation was wrong and would have stranded the work
> without its prerequisites. Read section 0 before touching any branch.

---

## 0. Branch reality — READ FIRST (this is where the earlier draft was wrong)

The earlier draft said to base this work on
`devin/prompt-query-gen-width-invite-feedback` (PR #71) because it "contains the
Insight Review work plus the latest UI fixes." **That is false**, verified
against the actual trees:

- `devin/prompt-query-gen-width-invite-feedback` does **NOT** contain migration
  `91455ab780b4`, the `review_status` state machine, the `/review/queue`,
  `/review/{id}/claim|release|disposition` endpoints, or the reviewer page
  `web-ui/app/insight-feedback/review/page.tsx`.
- Instead it ships a **different, simpler, conflicting** implementation of the
  same feature: a single flat admin-list endpoint
  `GET /api/insight-feedback/review`
  (`platform-api/app/routes/insight_feedback.py`, `review_insight_feedback`) and
  a page at `web-ui/app/admin/insight-feedback/page.tsx`. No review columns, no
  claim/disposition, no state machine.
- The **governed review workflow this plan extends lives only on**
  `devin/prompt-3-thumbs-feedback-review` (PR #65). Confirmed present there:
  `platform-api/alembic/versions/91455ab780b4_insight_feedback_review.py`, the
  `review_status`/`reviewer_user_id`/`reviewer_comment`/`reviewed_at` model
  fields, the reviewer endpoints, `_PERMISSION_REVIEW = "insight_feedback.review"`,
  and `web-ui/app/insight-feedback/review/page.tsx`.
- The two branches are **divergent**: `devin/prompt-3-thumbs-feedback-review` is
  **not** an ancestor of `devin/prompt-query-gen-width-invite-feedback`. You
  cannot get the governed workflow by branching from query-gen.
- **Neither branch is merged into `feature/sprint-08-knowledge-graph-lifecycle`
  (the deployed lineage).** The deployed lineage has only the base per-user
  feedback (migration `0054_insight_feedback.py`, per-user routes) — no review
  at all. Both review efforts are stranded on unmerged branches.

### Two implementations collide — reconcile, don't stack

Because both branches define insight-feedback "review," a naive merge produces
two `GET .../review*` routes and two review pages backing the same feature. You
must land on **one** design. This plan standardizes on the **governed workflow
from `devin/prompt-3-thumbs-feedback-review`** (it is the richer, auditable
design this plan needs) and **retires the flat admin list** from query-gen.

### Base branch decision

1. **Base the new work on `devin/prompt-3-thumbs-feedback-review`** — it is the
   only branch containing the governed review scaffolding this plan extends.
   Suggested new branch: `devin/insight-review-status-card-workflow`.
2. First run `git fetch origin` and re-verify PR #65 / #71 states. If PR #65 has
   since merged into an integration branch that also carries the query-gen UI
   fixes, base on that merged integration branch instead — but only if
   `platform-api/alembic/versions/91455ab780b4_insight_feedback_review.py` and
   `web-ui/app/insight-feedback/review/page.tsx` are present in it. **Verify
   presence before coding; do not assume.**
3. If you must combine query-gen's UI fixes with prompt-3's review workflow,
   merge prompt-3 **into** your branch and then **delete the query-gen flat
   review path** (`review_insight_feedback` route + `web-ui/app/admin/insight-feedback/page.tsx`
   + its `getInsightFeedbackReview`-style client), replacing all callers with
   the governed queue. Do not leave both alive.
4. Do NOT start from `main` or from `claude/validate-enhance-logic-r2fyy1`
   (the latter is the KG-lifecycle validation line and does **not** contain
   migration `0060` or the review work).
5. Do not modify migration `91455ab780b4`. Add a **new** Alembic revision
   chained off the current head for the new columns/table in section 7.

### Migration-chain facts (verified)

- `91455ab780b4` has `down_revision = '0060'`
  (`0060_project_insight_staleness.py`).
- `0060` exists on `feature/sprint-08-knowledge-graph-lifecycle`,
  `devin/prompt-3-thumbs-feedback-review`, and
  `devin/prompt-query-gen-width-invite-feedback`, but **not** on
  `claude/validate-enhance-logic-r2fyy1` (which stops at `0059`). Confirm your
  chosen base includes `0060` before adding the next revision, or your new
  migration's `down_revision` will dangle.

---

## 1. What already exists on `devin/prompt-3-thumbs-feedback-review` (preserve)

Verified in that branch — do **not** rebuild these:

**Backend** (`platform-api/app/routes/insight_feedback.py`,
`platform-api/app/models/insight_feedback.py`):

- Per-user upsert: `GET /{insight_id}`, `POST /batch`, `PUT /{insight_id}`,
  `DELETE /{insight_id}` — all gated `require_role(Role.VIEWER)` and filtered to
  `user_id == context.user_id`. `PUT`/`DELETE` already reset
  `review_status = pending` and clear reviewer fields on edit/withdraw.
- Model fields from `91455ab780b4`: `review_status` (String(20), default
  `"pending"`, indexed), `reviewer_user_id` (FK users, `SET NULL`, indexed),
  `reviewer_comment` (Text), `reviewed_at` (DateTime tz). Plus the pre-existing
  `status` field (default `"active"`).
- Reviewer workflow: `GET /review/queue` (filterable by `review_status`,
  paginated), `GET /review/{feedback_id}`,
  `POST /review/{feedback_id}/claim`, `POST /review/{feedback_id}/release`,
  `POST /review/{feedback_id}/disposition`.
- Permission gate: `_PERMISSION_REVIEW = "insight_feedback.review"`,
  `_can_review_feedback = context.has_permission(...) or has_role(ADMIN)`.
  `context.has_permission` exists on `RequestContext`
  (`platform-api/app/auth/context.py:44`). Project access enforced via
  `_require_project_access_for_review` (admins bypass; others must be project
  members).
- Existing status constants: `pending`, `accepted`, `rejected`,
  `needs_more_information`; `_FINAL_REVIEW_STATUSES = {accepted, rejected,
  needs_more_information}`.

**Frontend**: `web-ui/app/insight-feedback/review/page.tsx` (reviewer queue),
`web-ui/lib/api/insight-feedback.ts`, `web-ui/lib/hooks/use-insight-feedback.ts`,
`web-ui/components/tablescope/home/insight-feedback-dialog.tsx`, thumbs controls
on the intelligence card.

### Precise gaps vs. this plan (the actual work)

Read carefully — these are the deltas, verified against prompt-3's code:

1. **No `not_required` state.** The `91455ab780b4` migration defaults
   `review_status` to `"pending"` for **all** feedback, including Agree. Agree
   feedback wrongly enters the reviewer queue. Add `not_required` and route
   Agree to it.
2. **No `in_review` state.** `claim_review_feedback` only sets
   `reviewer_user_id`; it leaves `review_status = pending`. There is no
   `in_review` value in the status set. Claim must transition
   `pending → in_review` and set `acknowledged_at`.
3. **`needs_more_information` is a dead end.** It sits in
   `_FINAL_REVIEW_STATUSES` and there is no submitter response path back. Make it
   non-terminal and add a user-response endpoint that returns it to `in_review`.
4. **No `acknowledged_at`, no `feedback_revision`, no immutable review-event
   table.** All net-new (section 7).
5. **No project-level governance** (`Under Review`/`Disputed`/`Validated`/
   `Superseded`) and no safe governance batch endpoint. Net-new (section 9).
6. **No status badge/dialog on cards.** Status is only visible in the reviewer
   page today. Add per-card personal status badge + detail dialog across all
   card surfaces (section 5/8).
7. **Reviewer UI labels are ambiguous** (`Claim`/`Accepted`/`Rejected`).
   Relabel (section 6).
8. **`disposition` gate is loose.** It allows dispositioning from any state and
   only requires a comment for the "final" set. Tighten to require `in_review`
   for final dispositions and enforce the transition rules in section 4.

---

## 2. Status model (canonical API values → labels)

Keep the record-lifecycle `status` field separate from `review_status`.

**Record `status`:** `active` (show on card) / `withdrawn` (kept for audit,
hidden as active). `withdrawn` is a new value for the existing `status` column —
no migration needed (String(20) already), just application logic.

**`review_status`** (extend the existing column's allowed set):

| API value | User-facing label | Meaning | Terminal |
|---|---|---|---|
| `not_required` | Feedback Saved | Agree recorded; no reviewer action. | Yes |
| `pending` | Pending Review | Disagree submitted, not yet acknowledged. | No |
| `in_review` | In Review | A reviewer acknowledged/claimed it. | No |
| `needs_more_information` | Response Needed | Reviewer asked the submitter for more. | No |
| `accepted` | Feedback Accepted | Reviewer agrees the disagreement is valid. | Yes |
| `rejected` | Insight Upheld | Reviewer determined the Insight still stands. | Yes |

Never render bare `Accepted`/`Rejected`: `accepted` = **Feedback Accepted**
(not "Insight accepted"); `rejected` = **Insight Upheld** (not "user rejected").
Keep API enum values separate from localized labels — return both a canonical
`review_status` and a `review_status_label` (or map on the client via a single
shared helper), never let each card derive its own vocabulary.

**Governance label (project-visible, no private data):**

| Label | Trigger |
|---|---|
| `Under Review` | ≥1 active disagreement in `pending`/`in_review`/`needs_more_information`. |
| `Disputed` | ≥1 active disagreement `accepted` and the Insight not yet superseded/regenerated. |
| `Validated` | The applicable disagreement was `rejected` (Insight Upheld) and no other active/accepted disagreement exists. |
| `Superseded` | A regenerated Insight replaces the disputed snapshot. |

Governance responses must never leak submitter identity, reason codes, comments,
or reviewer discussion.

---

## 3. State transitions

```
[*] --> not_required        : Agree saved
[*] --> pending             : Disagree submitted
pending --> in_review       : Reviewer acknowledges (claim)
in_review --> pending       : Reviewer releases
in_review --> needs_more_information : Reviewer requests information
needs_more_information --> in_review : User responds
in_review --> accepted      : Feedback valid (Feedback Accepted)
in_review --> rejected      : Insight upheld
pending --> withdrawn       : User withdraws
in_review --> withdrawn     : User withdraws / admin closes
not_required --> pending    : User changes Agree to Disagree
accepted --> pending        : User submits material revision
rejected --> pending        : User submits material revision
```

Transition rules (enforce server-side; reject illegal transitions with 409/422):

1. **Save Agree** → `status=active`, `review_status=not_required`; clear
   `reviewer_user_id`, `reviewer_comment`, `reviewed_at`, `acknowledged_at`;
   exclude from default queue.
2. **Save Disagree** → `status=active`, `review_status=pending`; store mandatory
   comment (existing 4,000-char rule), reason codes, frozen `card_snapshot`;
   clear stale reviewer/disposition fields on a new material revision.
3. **Claim/Acknowledge** → require `pending`; atomically set `in_review`,
   `reviewer_user_id = caller`, `acknowledged_at = now`; **409 if not pending**
   (already claimed/dispositioned). This replaces prompt-3's claim that left
   status at `pending`.
4. **Release** → claimant or admin only; `in_review → pending`; clear
   `reviewer_user_id`, `acknowledged_at`; keep audit trail.
5. **Needs More Information** → only from `in_review`; require reviewer comment;
   set `needs_more_information`; retain `reviewer_user_id`; **not terminal**.
6. **User Response** → submitter only; require `needs_more_information`; require
   non-whitespace response; append a review-event; set `in_review`; retain
   reviewer.
7. **Final Disposition** → only from `in_review`; claimant or admin only; require
   rationale; `accepted` (Feedback Accepted) or `rejected` (Insight Upheld); set
   `reviewed_at` and reviewer identity server-side.
8. **User Changes Feedback** → Agree→Disagree requeues (`pending`);
   Disagree→Agree sets `not_required`; a material edit to a
   pending/in-review/resolved disagreement creates a review-history revision and
   returns to `pending`; never silently overwrite already-reviewed evidence.
9. **Withdraw** → `status=withdrawn`; preserve history/audit; drop the active
   personal badge; recompute project governance.

---

## 4. Card behavior

**Placement.** Keep both thumbs in the card footer; render the personal badge
immediately after: `👍  👎  [Pending Review]`. Render the project governance
badge near the header severity badge: `High Risk  [Under Review]`. The badge
never replaces the selected thumb.

**Personal card states** (submitter's own view):

| Condition | Thumb | Personal badge |
|---|---|---|
| No active feedback | none selected | none |
| Agree saved | thumbs-up active | Feedback Saved |
| Disagree pending | thumbs-down active | Pending Review |
| Reviewer claimed | thumbs-down active | In Review |
| Info requested | thumbs-down active | Response Needed |
| Feedback accepted | thumbs-down active | Feedback Accepted |
| Insight upheld | thumbs-down active | Insight Upheld |

**Tones** (never color-only — include text + accessible name + tooltip):
Feedback Saved = success; Pending Review = warning; In Review = brand/blue;
Response Needed = high-attention/orange; Feedback Accepted = strong governance
tone (must not imply the Insight is valid); Insight Upheld = success;
Under Review = warning; Disputed = danger; Validated = success; Superseded =
neutral.

**Badge is a button.** Clicking opens `InsightFeedbackStatusDialog` (or a
right-side panel) showing: current status + plain-language explanation;
submission timestamp; the user's sentiment/reasons/comment; reviewer name after
acknowledgement (if disclosure allowed); `acknowledged_at`; reviewer question
for `needs_more_information`; a response form when action is required; final
disposition label + reviewer rationale + `reviewed_at`; linked corrective
Project Action when available; `Edit`/`Withdraw` when permitted; `View review
details` for reviewers. For `Response Needed`, make the badge prominent and
auto-focus the response field.

**Apply to every card surface** with one shared vocabulary (extract shared
helpers/components; do not fork the mapping per card):

- Business Insight cards — `web-ui/components/tablescope/home/intelligence-card.tsx`.
- Project Insight Risk/Trend/Opportunity cards — `InsightCardItem` in
  `web-ui/components/tablescope/project-insight/project-insight-screen.tsx`
  (~line 894).
- Project-scoped suggested Insight cards.
- Home-pinned Insight cards — `web-ui/components/tablescope/home/home-pins-grid.tsx`.

---

## 5. Reviewer workspace (`web-ui/app/insight-feedback/review/page.tsx`)

Use the same labels and state machine. **Default queue filter:** Disagree
feedback in `pending`/`in_review`/`needs_more_information`; exclude
Agree/`not_required` unless the reviewer picks All. Columns: project, Insight,
severity, sentiment, reason, submitted-by, age, assigned reviewer, review status.

Reviewer actions by status:

| Status | Actions |
|---|---|
| Pending Review | Acknowledge |
| In Review (mine) | Release, Request More Information, Feedback Accepted, Insight Upheld |
| In Review (other reviewer) | Read-only unless tenant admin |
| Response Needed | See response status; no final disposition until a response (or audited admin override) |
| Feedback Accepted / Insight Upheld | Read-only; reopen only via explicit audited admin action |

**Relabel** the existing reviewer UI: `Claim → Acknowledge`,
`Accepted → Feedback Accepted`, `Rejected → Insight Upheld`,
`Needs more information → Request More Information`. Reviewer rationale is
mandatory for every disposition and every information request.

---

## 6. Backend implementation

**New Alembic migration** (chained off the current head — see section 0 facts;
do not edit `91455ab780b4`). Add:

- `acknowledged_at` (DateTime tz, nullable).
- `feedback_revision` (Integer, nullable/default 1).
- An **immutable review-event table** (private): tenant_id, project_id,
  feedback_id, insight_id, event_type, from_review_status, to_review_status,
  actor_user_id, comment/response (nullable), feedback_revision, created_at.
  Do **not** put private submitter/reviewer comments into any generic audit log
  that ordinary project users can read.

**Model** (`platform-api/app/models/insight_feedback.py`): add the two columns
and the event model. Extend the allowed `review_status` set with `not_required`
and `in_review`.

**Routes** (`platform-api/app/routes/insight_feedback.py`):

1. Upsert (`PUT`/`POST batch`): Agree → `not_required`; Disagree → `pending`;
   create a revision + review-event on material edits (per rule 8).
2. Claim: implement the real `pending → in_review` transition + `acknowledged_at`
   (currently missing).
3. Release: `in_review → pending`, clear `acknowledged_at`.
4. Disposition: require source `in_review`; `accepted`/`rejected` terminal with
   mandatory rationale; move `needs_more_information` **out** of the final set
   and make it a distinct "request info" action from `in_review` (retain
   reviewer). Set reviewer identity + `reviewed_at` server-side; reject
   client-supplied reviewer identity/timestamps.
5. **New** user-response endpoint, submitter-only:
   `POST /api/insight-feedback/{insight_id}/review-response` — require
   `needs_more_information`, require non-whitespace body, append a review-event,
   transition to `in_review`, keep the assigned reviewer.
6. **New** safe governance batch endpoint returning only `insight_id`,
   governance status, and last status-change timestamp — no identity/reason/
   comment/reviewer data. This is what project cards call.
7. Return normalized display + workflow fields so clients don't derive
   conflicting states.
8. **Retire** the query-gen flat `GET /api/insight-feedback/review`
   (`review_insight_feedback`) if it is present in your base — the governed
   queue supersedes it (see section 0).

**Authorization** (reuse existing): `insight_feedback.review` permission + admin
mapping; tenant isolation; project access; submitter-only personal reads;
claimant-or-admin for disposition/release.

**Audit** immutable events for: Agree saved, Disagree submitted, edited/revised,
withdrawn, acknowledged, released, information requested, user responded,
Feedback Accepted, Insight Upheld, admin reopen.

---

## 7. Frontend implementation

Shared helpers/components (repo naming conventions):
`getInsightFeedbackDisplayState(feedback)`, `InsightFeedbackStatusBadge`,
`InsightGovernanceBadge`, `InsightFeedbackStatusDialog`. Extend
`web-ui/lib/api/insight-feedback.ts` and `web-ui/lib/hooks/use-insight-feedback.ts`
with the new endpoints.

**React Query.** After save / reviewer action / response / withdrawal:
optimistically update the known record in cache, then invalidate — the current
user's batch feedback query, the affected card query, reviewer queue/detail
queries, the governance-status batch query, and Home pins if a pinned card is
visible. Refresh Project/Business Insight data only when a disposition makes the
Insight stale (section 8). No card should show a stale status until a full page
reload.

**Privacy.** A user sees their own status/details; a reviewer sees
tenant/project-scoped review info; other members see only the governance badge;
never show a submitter's comment or identity on another user's card.

---

## 8. AI / Insight lifecycle

Disposition must not auto-retrain or rewrite the frozen Insight.

- Pending/In Review/Response Needed → Insight may show `Under Review`; do not
  treat the disagreement as validated evidence.
- Feedback Accepted → set governance `Disputed`; mark the appropriate Insight
  snapshot stale (reuse the existing staleness path used by project insights —
  e.g. `mark_project_insight_stale` for project cards / the business-insight
  cache invalidation for business cards; confirm the exact call in your base);
  include the governed reviewer result in future project AI context via
  `build_project_ai_context`; require regeneration before clearing `Disputed`.
- Insight Upheld → set `Validated` only when no other active/accepted
  disagreement exists for the same Insight; keep the disagreement + rationale for
  audit.
- Regenerated Insight → preserve the old review against the frozen
  insight_id/fingerprint; mark the old card `Superseded`; do not auto-copy the
  old disposition to a materially different Insight unless fingerprint rules
  justify it.

---

## 9. Tests

**Backend** (`platform-api/tests/test_insight_feedback.py` — extend):
Agree → `not_required` and absent from default queue; Disagree → `pending`;
claim `pending → in_review` + `acknowledged_at`; concurrent claim → one success
+ one 409; release → `pending` and cleared assignment; `needs_more_information`
non-terminal; user response → `in_review` retaining reviewer;
`accepted`/`rejected` require rationale and are terminal; client cannot forge
reviewer identity/status/timestamps; material edit creates a revision and
requeues; tenant/project isolation + reviewer-permission checks; governance
batch response carries no private data; multi-disagreement governance precedence.
(SQLite note: `server_default` booleans store as strings under SQLite in this
repo — set explicit values in fixtures rather than relying on defaults.)

**Frontend**: every card surface shows the same thumb + label; no feedback → no
badge; Agree → Feedback Saved; Disagree → Pending Review immediately;
acknowledge → In Review without reload; Response Needed opens question + response
field; user response updates status; Feedback Accepted / Insight Upheld render
unambiguous labels; badge keyboard-accessible with an accessible name; other
users cannot see private reasons/comments; governance badge follows precedence;
withdraw clears active personal state while preserving history.

**Regression**: feedback edit/remove still work; Business/Project/Home-pinned
cards still render; reviewer queue filters + pagination still work; the
4,000-char comment validation still holds; if you retired the query-gen flat
`/review` route, confirm nothing else called it.

---

## 10. Definition of done

- Exact transitions in section 3 enforced by the API; Agree bypasses review,
  Disagree enters the queue.
- A user reads their feedback status from every applicable card; a reviewer can
  acknowledge → request info → receive response → disposition.
- UI clearly distinguishes Feedback Accepted from Insight Upheld; governance
  badge never leaks private content.
- All transitions audited via the immutable review-event table.
- `pytest` + `ruff` (platform-api) and `tsc` + lint + component tests (web-ui)
  green; the new migration applies cleanly on top of the verified head.
- Browser-verified: Agree→Feedback Saved; Disagree→Pending Review;
  Acknowledge→In Review; Request Information→Response Needed→user response;
  Feedback Accepted; Insight Upheld; across Business, Project, and Home-pinned
  cards.
- Final report lists: the base branch actually used and how the two review
  implementations were reconciled (section 0); changed files; new migration
  revision id + `down_revision`; API changes; status-transition decisions;
  privacy behavior; tests run; screenshots.

## 11. Delivery sequence

1. Backend status-transition corrections + new migration + tests.
2. Review-event/user-response support.
3. Shared card status mapping + badge + status dialog.
4. Reviewer workspace relabel + action gating.
5. Safe project governance badge + batch endpoint.
6. AI staleness/context integration.
7. Full regression + browser verification.

Keep it in one focused PR if the review-event schema change is small; split the
governance aggregation + AI integration into a second PR if they grow large,
after the personal card-status workflow is complete and tested.
```
