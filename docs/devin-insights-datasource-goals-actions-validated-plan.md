# Insights / Data Source Lifecycle / Goal Setting / Project Actions / Card Export — validated & enhanced plan

Supersedes `TableScope_Devin_Implementation_Plan_Insights_DataSource_Goals_Actions.md`.
Read this document instead of the original. Where a section is not mentioned
here, the original stands — its phases, test lists, and deployment/rollback
sections are sound and are not repeated below.

**Branch:** `devin/insights-datasource-goals-actions-fixes`
**Base:** `origin/devin/r-echarts-e2e-validation` (verified deployed lineage)

Nine items. Six of them have a precise, traceable root cause already sitting
in the code — in three cases the fix is a few lines, not a subsystem. Two
(governed data-source deletion, PNG export) are genuinely new work with
nothing to reuse or contradict. One (item 1, ephemeral transcripts) is a
plan whose Business Insights half was already validated in a prior document
(§0.0) — Project Insights is new territory and is covered here in full.

---

## 0.0 Overlap with a prior validated plan — read this first

Item 1's Business Insights half is the same defect already investigated in
`docs/devin-business-insights-ux-fixes-validated-plan.md` (branch
`devin/business-insights-context-and-ux-fixes`). That document found:

- **No transcript hydration exists** on the Business Insights page — a
  refresh already yields an empty transcript. Reproduce before "removing"
  anything.
- **There is no canonical "Business Insights conversation."** Every ask
  creates a new `AnalyticsConversation` row (`project_id = NULL`, titled from
  the question text). Building the canonical thread this plan assumes exists
  is the real work.
- `client_request_id` already exists on both `CreateConversationRequest` and
  `SubmitTurnRequest`, with a DB uniqueness constraint
  (`uq_analytics_turn_client_request_id`) — it is simply never sent from
  either insight page.

**This plan's item 1 extends the same defect to Project Insights and asks for
explicit `surface` typing (`business_insights` / `project_insights` /
`ai_assistant`), which the prior document did not cover.** §1.1 below
validates the Project Insights half and gives the `surface` column design.
If both branches are being worked in parallel, land the Business Insights
half once, in one place — do not fix the same root cause twice on two
branches.

---

## 0. Validation findings

Every claim was checked against the repository at the base SHA.

### 0.1 Item 1 — Project Insights has the same conversation-per-visit defect, confirmed independently

`project-insight-screen.tsx` renders its ask surface through
`HomeAiSuggestions` → `InsightsPanel` (`web-ui/components/tablescope/home/ai-suggestions.tsx`),
which shares the same `AnalyticsConversation` model and the same
`createConversation`/`submitTurn` client functions as Business Insights — there
is only **one** conversation store, not a separate "Project Insights"
mechanism. So the fix in §1.1 (the `surface` column) serves both pages from
one migration and one set of call-site changes; it is not two pieces of work.

### 0.2 Item 3 — root cause traced to one specific line; a purpose-built fix already exists unused

`platform-api/app/routes/upload.py:86-89`:

```python
elif lower_name.endswith((".xlsx", ".xlsm", ".xls")):
    content = sanitize_xlsx_content(content)
    # sanitize_xlsx_content returns CSV bytes
    clean_name = clean_name.rsplit(".", 1)[0] + ".csv"
```

`sanitize_xlsx_content` converts the workbook to CSV **bytes** for the Teiid
import pipeline (correct — Teiid's importer only parses CSV/TXT/Excel), but
this line also rewrites the **filename** to `.csv`. Three lines later the true
original extension is captured and never used for naming:

```python
original_format = (
    file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else None
)
```

`original_format` (`"xlsx"`) is stored on `FileSourceMeta.source_format`
(lines 213, 220) — for metadata/display purposes only. It is **not**
consulted by either of the two places that actually name the source:

```python
# line 165-167: what the servlet-facing datasource name uses
base_name = filename.rsplit(".", 1)[0].replace(" ", "_")
extension = filename.rsplit(".", 1)[-1].upper() if "." in filename else ""
datasource_name = f"{base_name}_{extension}" if extension else base_name
```

```python
# line 196: the persisted view_name
view_name = compute_view_name(filename)
```

Both read `filename`, which by this point is the **post-rewrite** `.csv` name
— hence `SalesJournal2025.xlsx` → `SalesJournal2025_CSV`.

**A function that does exactly what's needed already exists, unused for this
path:**

```python
# platform-api/app/services/file_sources.py:439
def display_source(
    physical_name: str, source_format: str | None
) -> tuple[str, str]:
    """Return ``(display_file_name, source_type)`` honoring the original upload.

    JSON/XML uploads are flattened to CSV, so the physical file on disk is
    ``foo.csv``. When ``source_format`` is recorded (e.g. ``"json"``) we present
    the original extension instead (``foo.json`` + type ``json``); otherwise we
    fall back to the on-disk extension.
    """
```

This is precisely the JSON/XML case the plan's own distinction
("original file format" vs. "ingestion/intermediate format") already solved
once. XLS/XLSX just never got routed through it. See §1.2 for the fix — it is
a two-call-site change, not a new naming service.

### 0.3 Item 4 — goal (success-criterion) deletion already ships end to end; the gap is narrower than the plan assumes

`delete_goal` exists in the service, the route, and the frontend, fully wired:

```python
# platform-api/app/services/project_context.py:424
async def delete_goal(self, project_id: int, goal_id: int) -> None:
    await self._require_project(project_id, write=True)
    goal = await self.get_goal(project_id, goal_id)
    previous = goal.to_redacted_dict()
    goal.active = False
    goal.version += 1
    await self.session.flush()
    invalidate_project_ai_context(self.context.tenant_id, project_id)
    await self._mark_knowledge_graph_stale(project_id, "Project context updated")
    await self._audit(..., event_type="project_context.goal_archived", ...)
```

```tsx
// web-ui/components/tablescope/project/business-context-screen.tsx:151-152,315
const goalDelete = useMutation({ mutationFn: deleteGoal.bind(null, projectId), ... });
...
onDelete={(id) => goalDelete.mutate(id)}
```

with a working confirmation dialog (`"Delete goal?"`, confirm/cancel). **Two
real gaps remain, both narrower than "enable deletion":**

1. **Child measures/risks are not cascaded.** `delete_goal` sets only
   `goal.active = False`. It never touches `ProjectMetric` or `ProjectRisk`
   rows reachable through `project_goal_metric_links` /
   `project_goal_risk_links`. The plan requires soft-deleting child
   measures/risks that belong **exclusively** to the criterion — that logic
   does not exist yet.
2. **The confirmation dialog shows no counts.** Current message is the
   generic `"This will archive the goal. It can be restored later."` The
   plan's required content — measure count, risk count, linked data matches —
   is not rendered.

Fix these two gaps (§2.1); do not rebuild deletion from scratch.

### 0.4 Item 5 — "delete" already means "archive"; there is no second, physical-delete operation

```python
# platform-api/app/routes/project_actions.py:1097
@router.delete("/{project_id}/actions/{action_id}")
async def archive_action(
    ...
) -> dict[str, Any]:
    """Soft-archive an action and its subtasks."""
    ...
    action.archived_at = now
```

The `DELETE` HTTP verb is already bound to an **archive** operation, named
`archive_action`. `ProjectAction.archived_at` is used pervasively throughout
the file to filter active vs. archived (`archived_at.is_(None)` appears at
lines 220, 235, 246, 452, 469, 711, 757, 771, and more).

**There is no endpoint that performs the plan's third state — a real,
permanent delete of an already-archived action.** The plan's lifecycle
(`active -> archived -> deleted`) needs a **new** endpoint; it is not a matter
of adding an "is it archived?" guard to the existing one, because the
existing `DELETE` route is already spoken for. See §1.3 for the naming
consequence this creates.

### 0.5 Item 6 — the reported symptom is reproduced exactly, in a fully manual dialog with no AI call at all

`web-ui/components/tablescope/project-actions/create-action-from-insight-dialog.tsx:124-134`:

```tsx
useEffect(() => {
  if (!open || !insight) return;
  const recommended = trimText(insight.recommendedAction);
  const cardTitle = trimText(insight.title);
  const cardSummary = trimText(insight.summary);

  setTitle(recommended || cardTitle || "");
  setDescription(
    recommended
      ? `${cardTitle}\n\nSummary: ${cardSummary}\n\nRecommended action: ${recommended}`
      : `${cardTitle}\n\nSummary: ${cardSummary}`,
  );
  ...
  setSubtasks([]);
```

This is the exact bug: `title` is set to the full `recommended` string
(`card.callout?.text`, which can be a full sentence of guidance) whenever one
exists, and `subtasks` is unconditionally `[]`. **There is no AI generation
call anywhere in this component** — it is a manual form pre-filled from raw
card fields. The plan's "structured AI action draft" (title/description/
subtasks/success-criteria from a schema-constrained model call) is entirely
new work; nothing here to reuse, and nothing that contradicts the plan.

### 0.6 Item 7 — this is feedback on work delivered earlier in this engagement, not a legacy bug

The exact strings the plan reports trace to code added during the deep
analysis work already merged into this lineage:

```python
# platform-api/app/services/home_intelligence.py:2902
"title": f"Claim: “{check.claim.text}”",
```

```python
# platform-api/app/services/card_diagnostics.py:500
"Investigate before acting" if family == RISK else "Monitor for confirmation"
```

```tsx
// web-ui/components/tablescope/home/insight-analysis-strip.tsx:64
{diagnostics.length} diagnostic steps
```

The "Claim" step is `claim_verification`'s narrative-checking feature
(verifies a card's own asserted cause against the data — see
`docs/DEVIN-MERGE-README.md` §3H if present on this lineage); "Investigate
before acting · low confidence" is `propose_actions`'s honest fallback when
diagnostics found no segment, driver, or change point to target. Both are
**correct, intentional behavior of the analysis engine** — the plan is
reporting that the **card-level summary surfaces it as repetitive noise**,
which is a presentation problem, not an engine problem. §1.4 keeps the
engine output untouched and changes only what the compact card strip shows.

### 0.7 Item 8 — the shared component already exists, is tested, and works correctly where it is wired; one render path never wires it

`InsightCardActionsDisclosure` (`web-ui/components/tablescope/insights/insight-card-actions-disclosure.tsx`)
already implements every requirement in the plan's §8: default collapsed,
`"More Actions"` label with `IconChevronDown`/`IconChevronUp`, click toggles,
`aria-expanded`, `aria-controls`, a component test file
(`insight-card-actions-disclosure.test.tsx`). It is **one shared component**,
not two route-specific copies — the plan's stated risk (a stranded branch, a
route-specific duplicate) does not describe the current state of the code.

**The actual defect is precise and small.** `IntelligenceCard` accepts
`actionsDisclosure?: "always-visible" | "collapsible"`. Exactly one caller
sets it:

```tsx
// web-ui/components/tablescope/home/intelligence-feed.tsx:73
actionsDisclosure = "collapsible",
```

`intelligence-feed.tsx` backs **Business Insight** (`app/business-insight/page.tsx`
imports `IntelligenceFeed`). **Project Insight** (`project-insight-screen.tsx`)
renders cards through a different path — `HomeAiSuggestions` →
`InsightsPanel` → `IntelligenceCard` — which passes:

```tsx
// web-ui/components/tablescope/home/ai-suggestions.tsx:537-543
<IntelligenceCard
  key={card.id}
  card={card}
  pinned={isPinned}
  hideActions
  onPin={onPin}
/>
```

`hideActions` suppresses the **entire** action row — Explain, Chart
suggestion, R badge, Action, Agree/Disagree, Add to dashboard — not just
"More Actions". Project Insight cards have none of this today, not a
collapsed version of it. `onSaveToDashboard`, `onFeedbackSave`,
`onFeedbackRemove`, `onCreateAction`, and `governance` are also never passed
here, so **item 6's Action button does not exist on Project Insight cards at
all** — the two bugs share one root cause. See §1.5.

### 0.8 Item 9 — confirmed: no export infrastructure exists anywhere

Searched the full `web-ui` tree for `html2canvas`, `toPng`/`dom-to-image`, and
any canvas `getDataURL`/`toDataURL` export helper: none. The plan's premise
(build PNG export from scratch, handle both ECharts canvas and Recharts SVG)
is accurate; there is nothing partial to find or contradict here.

### 0.9 Item 2 — confirmed as new work, with one fact worth reusing

No data-source deletion endpoint exists. What does exist:
`DELETE /data-source-assignments/{assignment_id}` (`data_source_assignments.py:228`)
removes a **project assignment** — the link between a source and a project —
not the source itself; do not confuse the two in the PR's root-cause section.
`FileSourceMeta.owner_id` already exists and is part of the table's uniqueness
constraint (`uq_file_source_view` on `tenant_id, owner_id, view_name`), so the
plan's "owner_id if not already authoritative" migration note is unnecessary
— it is already authoritative. The deletion saga, preflight endpoint, and VDB
orchestration in the plan's §2 are correctly scoped as new work.

### 0.10 Migration numbering — same collision risk flagged on two sibling branches already

Migration head on `origin/devin/r-echarts-e2e-validation` is `0069`, so this
branch's next revision is **`0070`** — the same number
`docs/devin-llm-framework-validated-plan.md` and
`docs/devin-business-context-validated-plan.md` both flagged for their own
branches. **A third branch is now competing for the same slot.** Confirm
which of the three has merged before generating this branch's migration, and
renumber to whatever `alembic heads` reports at that time — do not assume
`0070` is still free.

---

## 1. Corrections, with before/after code

### 1.1 Item 1 — the `surface` column and idempotency, for both insight pages

**Migration** (additive; number per §0.10):

```python
def upgrade() -> None:
    op.add_column(
        "analytics_conversations",
        sa.Column("surface", sa.String(32), nullable=False,
                   server_default="ai_assistant"),
    )
    # Existing rows are the AI Assistant's own history by definition -- they
    # were never created through an insight page's ask box.
```

**Before** (`web-ui/app/business-insight/page.tsx`):

```tsx
const created = await createConversation({ initial_message: message });
```

**After:**

```tsx
const created = await createConversation({
  initial_message: message,
  surface: "business_insights",
  client_request_id: crypto.randomUUID(),
});
```

Project Insight's equivalent call site (inside `InsightsPanel`'s ask box, or
wherever `project-insight-screen.tsx` submits a question) takes
`surface: "project_insights"` the same way. Both then need a **canonical
lookup** rather than always creating: check for an existing conversation with
`(user_id, surface, project_id)` before calling `createConversation`, and
`submitTurn` onto it if one exists — this is what makes the AI Assistant show
one growing "Business Insights" thread instead of a new row per visit (§0.1's
root cause).

### 1.2 Item 3 — thread the original format through both naming call sites

**Before** (`platform-api/app/routes/upload.py:165-167,196`):

```python
base_name = filename.rsplit(".", 1)[0].replace(" ", "_")
extension = filename.rsplit(".", 1)[-1].upper() if "." in filename else ""
datasource_name = f"{base_name}_{extension}" if extension else base_name
...
view_name = compute_view_name(filename)
```

**After:**

```python
from app.services.file_sources import display_source  # already imported nearby

display_name, _source_type = display_source(filename, original_format)
base_name = display_name.rsplit(".", 1)[0].replace(" ", "_")
extension = display_name.rsplit(".", 1)[-1].upper() if "." in display_name else ""
datasource_name = f"{base_name}_{extension}" if extension else base_name
...
view_name = compute_view_name(display_name)
```

`display_source` already does the right thing for JSON/XML by design; XLS/XLSX
just needs to flow through the same call. Verify `compute_view_name`'s
downstream consumers (Teiid VDB object naming, `_display_name_and_source_type`
callers in `file_analysis.py`) don't assume the CSV extension somewhere else —
grep for other `compute_view_name(filename)` call sites before merging, since
`file_analysis.py:266` has its own.

### 1.3 Item 5 — a genuinely new endpoint, not a guard on the existing one

Because `DELETE /{project_id}/actions/{action_id}` already means "archive"
(§0.4), the plan's "Direct deletion of an active action returns 409" cannot be
implemented by modifying that route — it already only archives, never
deletes, so it can't violate the rule the plan wants enforced. Add a distinct
route instead:

```python
@router.delete("/{project_id}/actions/{action_id}/permanent")
async def delete_action_permanently(
    project_id: int,
    action_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict[str, Any]:
    """Permanently remove an already-archived action. Requires prior archival."""
    await _require_project_access(project_id, session, context)
    action = await _get_action(session, context, project_id, action_id)
    if action.archived_at is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Archive the action before deletion",
        )
    # tombstone / soft-delete per current retention policy, not a hard DELETE FROM,
    # to satisfy "Preserve audit events and source-insight linkage in historical
    # audit records" -- mirror whatever pattern project_risks/project_goals use
    # for soft-delete rather than inventing a third convention.
    ...
```

Do not rename or repurpose the existing `archive_action` — it is called from
the frontend today (`Archive` button on active actions) and renaming its route
breaks that without warning.

### 1.4 Item 7 — change the card-level summary, not the diagnostic engine

The engine's output (`diagnostics`, `proposedActions`, the "Claim" step, the
"Investigate before acting" fallback) stays exactly as-is; it backs Full
Analysis and must not be weakened, per the plan's own §7A. What changes is
`insight-analysis-strip.tsx` — the compact strip shown directly on the card.

**Before** (`web-ui/components/tablescope/home/insight-analysis-strip.tsx`):
renders the lead diagnostic's title/finding (which can be the "Claim: ..."
step) plus the top action (which can be "Investigate before acting"), on
every card, unconditionally.

**After:** prefer a **non-claim, non-investigate** diagnostic step and a
**non-investigate** action for the strip when better ones exist further down
the list — reordering for *display* only, not for `Full Analysis`'s ordering,
which the engine still controls:

```tsx
const displayStep =
  diagnostics.find((d) => !d.title.startsWith("Claim:")) ?? diagnostics[0];
const displayAction =
  actions.find((a) => a.kind !== "investigate") ?? actions[0];
```

This directly serves item 7B too: when `displayAction.kind === "investigate"`
because nothing better was found anywhere in the list, that is the honest
state to show — label it with the plan's `Investigate` taxonomy entry rather
than hiding it, and stop showing `Caution` for it (the labeling fix in item 7B
is independent of this reordering and should use `action.kind` directly,
which `card_diagnostics.py` already emits as one of
`mitigate/capture/investigate/monitor` — map those to the plan's five-label
taxonomy rather than building a second classifier next to the one that
already produces a structured kind).

### 1.5 Item 8 — wire the existing component into the one path missing it

**Before** (`web-ui/components/tablescope/home/ai-suggestions.tsx:537-543`):

```tsx
<IntelligenceCard
  key={card.id}
  card={card}
  pinned={isPinned}
  hideActions
  onPin={onPin}
/>
```

**After:**

```tsx
<IntelligenceCard
  key={card.id}
  card={card}
  pinned={isPinned}
  actionsDisclosure="collapsible"
  onPin={onPin}
  onSaveToDashboard={onSaveToDashboard}
  onCreateAction={onCreateAction ? () => onCreateAction(card) : undefined}
  onFeedbackSave={onFeedbackSave ? (payload) => onFeedbackSave(card, payload) : undefined}
  onFeedbackRemove={onFeedbackRemove ? () => onFeedbackRemove(card) : undefined}
  governance={governanceById?.[card.insightId || card.id]}
/>
```

`InsightsPanel`'s own props (`onPin`, `pinnedByFingerprint`) do not currently
include `onSaveToDashboard`, `onCreateAction`, `onFeedbackSave`,
`onFeedbackRemove`, or `governanceById` — those need to be threaded in from
`project-insight-screen.tsx` the same way `app/business-insight/page.tsx`
already threads them into `IntelligenceFeed`. This is a prerequisite for
item 6's Action button existing on Project Insight cards at all, not an
independent piece of work — sequence it first (§2 below).

---

## 2. Sequencing

Do the small, verified fixes first — each is a handful of lines with a known
exact location:

1. **§1.5 (item 8 + unblocks item 6 on Project Insight)** — wiring only, no
   new component.
2. **§1.2 (item 3)** — two call sites, reusing `display_source`.
3. **§1.4 (item 7)** — display-only reordering plus the taxonomy mapping from
   `action.kind`, no new classifier.
4. **§0.3's two gaps (item 4)** — cascade child measures/risks, add counts to
   the confirmation dialog. Deletion itself already ships.

Then the larger new subsystems, per the original plan's Sprint A–D ordering,
which remains sound: temporary transcripts + `surface` (§1.1), governed
data-source deletion (item 2, confirmed net-new), the permanent-delete
endpoint for actions (§1.3), the AI action draft (item 6, confirmed net-new),
and PNG export (item 9, confirmed net-new).

Do not start item 1 without first checking whether
`devin/business-insights-context-and-ux-fixes` (§0.0) has already landed the
Business Insights half — implementing the same `client_request_id` /
canonical-thread fix twice on two branches is wasted work and a likely merge
conflict.

## 3. What to keep from the original plan unchanged

- The nine-item scope, the security/audit requirements, the deployment order,
  and the rollback section are all sound.
- The dependency-preflight design for item 2 (categorized blockers, deep
  links, re-check inside the deletion operation) is correct and detailed
  enough to build from directly.
- The AI action draft's schema constraints (reject unknown enums, limit
  subtask count, sanitize markdown, never auto-create) — unchanged.
- Item 7A's requirement that `Full Analysis`/`Explain`/audit records keep the
  full diagnostic detail — reinforced by §1.4, not weakened by it.
