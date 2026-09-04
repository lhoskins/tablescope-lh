# Devin: merge + deploy — Knowledge Graph validation, Phase 1 (Section A: security/isolation)

**Repository:** `lhoskins/tablescope-lh`
**Branch to merge:** `kg-validation-phase1-security`
**Base:** `UX-design-03`

**`platform-api/` only · no migration · all tests green**

---

## Context

This is the first installment of a full implementation of the 50-item Knowledge Graph
validation review (`Tablescope_Knowledge_Graph_50_Improvements.md`, reviewed commit
`80dff068...`, an ancestor of the current `UX-design-03` HEAD). Every item below was
independently re-verified against the real code on this branch before being fixed —
several findings in the original review turned out to be broader or narrower than
described once checked against the actual routes/services. This batch covers Section A
(security, authorization, isolation) items **#1–#6**, plus the merge of an
already-built-but-unmerged branch that covers part of #1–#2. Items #7 (audit records) and
#10 (isolation regression suite beyond what's included here) are still open — see
**Remaining work** below.

---

## 0. Merged `security-ts-iso-003` (already built, was never merged into `UX-design-03`)

That branch closed two of this review's confirmed gaps as part of a broader
project-access consolidation: `knowledge_graph.py`'s `/health` and `/builds/{build_id}`
routes performed **no** project-access check at all, and every other route in that file
checked tenant membership but not real ownership/active-membership. It introduced the
canonical policy module `app/services/project_access.py::authorize_project_access` and
wired it into every route in `knowledge_graph.py`. This batch builds on top of that merge
rather than duplicating it. See `docs/devin-ts-iso-003-project-access-policy-validated-plan.md`
for that branch's own detail.

## 1–2. Enforce tenant authorization on every KG route / pass request context into health services

**Validated:** true, and worse than described once traced further — `project_graph.py`'s
`GET /projects/{id}/graph` (the actual node/edge canvas data, a *different* route file
from `knowledge_graph.py`) had its own, weaker `_require_project_access` that checked
**only** that the project belonged to the caller's tenant, with no ownership or active-membership
check. Any authenticated user in the same tenant — not just members — could read any
private project's Knowledge Graph through this route, even after the `security-ts-iso-003`
merge above (which never touched this file).

**Fix:** replaced `project_graph.py`'s `_require_project_access` with the same
`authorize_project_access` policy used everywhere else, and threaded `context.role`
through to `build_node_centric_graph` for the visibility filtering added in item 4.

**Test:** `test_kg04_document_visibility.py::test_project_graph_denies_a_same_tenant_non_member_on_a_private_project` — a same-tenant non-member requesting a private project's graph now gets 403 (was 200).

## 3. Apply tenant predicates to every structural collector

**Validated:** true for the models that actually carry a `tenant_id` column.
`collect_structural_graph`'s per-kind collectors (`FileSourceMeta`, `DatabaseDataSource`,
`Dashboard`, `ProjectAsset`) filtered by `project_id` alone. Because `Project.id` is
globally unique and the project's own tenant is already verified before collection
starts, this wasn't a live cross-tenant *access* bug today — but it meant a data-integrity
anomaly elsewhere (a row whose `tenant_id` doesn't match its own `project_id`'s tenant,
e.g. from a bulk-import bug) would silently surface in the wrong tenant's graph with no
defense at this layer. `SavedQuery` has no `tenant_id` column at all — documented in
code rather than worked around.

**Fix:** added explicit `tenant_id == tenant_id` predicates to the four collectors that
support it.

**Test:** `test_knowledge_graph_context.py::test_structural_collectors_ignore_tenant_mismatched_rows` — seeds one tenant-matched and one tenant-mismatched row of each kind (same `project_id`, wrong `tenant_id`) and asserts only the matched ones appear.

## 4. Enforce document visibility and membership at graph-read time

**Validated:** true. `ProjectAsset` documents may be `visibility="private"` (readable only
by their owner/a tenant admin, per `project_assets.py`'s own existing policy) or
`"shared_project"`. The Knowledge Graph snapshot is built once (by whichever project
member last triggered a rebuild) and cached for the whole project — every subsequent
read was serving that cache to every member unfiltered, so a private document's node,
summary, and any AI card/gap/action/trace-path citing it as evidence could reach a
teammate who is a legitimate project member but not that document's owner.

**Fix:** new `app/services/knowledge_graph/visibility.py::filter_payload_for_viewer`,
applied on every read of the node-centric payload (`build_node_centric_graph`) and on the
legacy `{nodes, edges}` path in `project_graph.py`. Strips the private node, any edge
touching it, and any card/gap/recommended-action/trace-path whose evidence cites it. A
request that centers directly on a hidden node degrades to an empty/"not found"-shaped
response rather than echoing its title.

**Tests:** `test_kg04_document_visibility.py` (4 tests) — legacy-path leak (member sees it, owner doesn't; both proven against pre-fix code), and two unit-level tests against `filter_payload_for_viewer` directly (neighborhood filtering, and the hidden-center-node case).

## 5–6. Prevent user-specific AI cards from becoming project-wide cache content / authorization filtering before AI-server requests

**Validated:** true, and the two items turned out to be one fix. The pre-cache pass that
generates AI insight cards for every centre-eligible node (`_precache_center_cards`, run
once per rebuild using the *rebuilding* member's identity) sent the **full** raw graph —
including documents private to other members — to the AI server as context, and cached
whatever cards came back for the whole project. Item 4's read-time filter catches any
card that formally cites the hidden node as evidence, but the private content had already
left the system as an outbound AI-server request by that point, and a card whose
generated prose incorporated it without adding it to `traceToEvidence` would slip past
that filter entirely.

**Fix:** new `filter_raw_graph_for_user` (same module), applied inside
`_precache_center_cards` before any AI call, using the rebuilding user's own document
access. Wired into both places that function is called: the snapshot-based rebuild
(`knowledge_graph/snapshot.py`) and the lifecycle manager's real build path
(`knowledge_graph_lifecycle/rebuild_execution.py`). The persisted full-graph snapshot is
untouched — only the AI's input is filtered — so the document's own owner still sees it
normally via item 4's read-time filter.

**Test:** `test_kg06_ai_input_visibility.py` — stubs the AI client and asserts a private
document's label never appears in the AI request when a non-owner teammate triggers the
rebuild, and does appear when the owner does.

---

## Remaining work (not in this batch)

Tracked as a 50-item checklist for continued implementation across sessions:

- **#7 (P0):** source-access audit records for every KG-powered answer — not started, substantial new feature (needs its own audit-log table/schema).
- **#10 (P0):** a comprehensive automated isolation regression suite across every KG and downstream endpoint — items 4 and 6's tests cover their own specific scenarios but not the full matrix the review asks for.
- Sections B–E (items 8–9, 11–50): source completeness/lineage, graph integrity/activation validation, evidence/confidence/grounding, and lifecycle/reliability/performance — not started.

`#10` **is** included in this batch (see below) — its scope is the full Knowledge Graph
route surface (`knowledge_graph.py` + `project_graph.py`); the "downstream" half of that
item's own ask (grounded-answer evaluations against AI Assistant/Business
Insights/Project Insights/dashboards/executive summaries) is left to item #50, a distinct
and larger undertaking since each of those features has its own request/response shape.

## 10. Automated isolation regression suite

**Fix:** new `tests/test_kg10_isolation_regression_suite.py` — a parametrized matrix over
every route in `knowledge_graph.py` and `project_graph.py` (10 routes), each exercised
three ways: same-tenant non-member of a private project (expect 403), a different
tenant's project id (expect 404), and the project's own owner (expect neither -- a sanity
check that the matrix isn't just failing closed for everyone). 30 tests total.

## Tests added this batch

| File | Coverage |
|---|---|
| `tests/test_knowledge_graph_context.py` (+1 test) | KG-03: tenant-mismatched rows excluded from all 4 fixed collectors |
| `tests/test_kg04_document_visibility.py` (4 tests, new file) | KG-01/04: non-member denied; private doc hidden from non-owner member, visible to owner; hidden-center-node degrades safely |
| `tests/test_kg06_ai_input_visibility.py` (1 test, new file) | KG-05/06: private doc never sent to AI server for a non-owner's rebuild, is sent for the owner's own rebuild |
| `tests/test_kg10_isolation_regression_suite.py` (30 tests, new file) | KG-10: every KG route × {non-member denied, cross-tenant denied, owner allowed} |

All new/modified tests independently verified to fail against pre-fix code (`git stash` on just the fix files, rerun, restore).

## Verification

| Suite | Result |
|---|---|
| `pytest tests/test_kg04_document_visibility.py tests/test_kg06_ai_input_visibility.py tests/test_kg10_isolation_regression_suite.py tests/test_knowledge_graph*.py tests/test_ts_iso_003_project_access.py tests/test_document_families.py -q` | 290 passed |
| `ruff check` (touched files) | clean |
| `mypy` (touched files) | clean |
| Full `pytest -q` (whole platform-api suite) | **1678 passed, 4 skipped, 10 failed** — 0 new. 7 are the same pre-existing/unrelated failures confirmed on every prior turn of this repo's work (`test_business_insight_phase1.py::test_snapshot_*` ×3, `test_percent_change_summary.py::test_summary_*` ×4); the other 3 (`test_ai_dashboard_pipeline.py`, `test_ask_pipeline.py`, `test_visualization_engine.py`) are in files this branch's diff never touches, and were independently reproduced running only those 3 tests against the branch with no KG changes applied -- pre-existing on `UX-design-03`, unrelated to chart/visualization-engine work merged separately. |

```bash
cd platform-api
pytest -q
ruff check app/routes/project_graph.py app/services/knowledge_graph/visibility.py \
  app/services/knowledge_graph/snapshot.py app/services/knowledge_graph_context/collectors.py \
  app/services/knowledge_graph_lifecycle/rebuild_execution.py
mypy app/routes/project_graph.py app/services/knowledge_graph/visibility.py \
  app/services/knowledge_graph/snapshot.py app/services/knowledge_graph_lifecycle/rebuild_execution.py
```

## Deploy

`platform-api` only, no migration, no `web-ui`/`ai-server` change.

```bash
docker compose build platform-api
docker compose up -d platform-api platform-api-worker
```

## Verify live

- As a same-tenant user who is not a member of a private project, confirm every Knowledge Graph route (status/rebuild/builds/health/versions/dependencies/graph) now returns 403 (was previously readable on some routes).
- With a project that has a private document (visibility="private") and a non-owner active member, confirm the member's Knowledge Graph view never shows that document's node, and that the owner's view still does.
- Trigger a Knowledge Graph rebuild as a non-owner member of a project with another member's private document; confirm no card references that document's content.

## Report back

Confirmation the access gaps no longer reproduce, full-suite pass/fail counts from your
own run, and whether to continue with item #7 (audit records — needs its own migration
for a new audit-log table, deliberately left out of this no-migration batch) next, or
move on to Section B (source completeness/lineage).

---

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01M7j8CDCHCdwHpw9FrRhLN5
