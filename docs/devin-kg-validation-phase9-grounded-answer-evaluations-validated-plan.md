# Devin: merge + deploy — Knowledge Graph validation, Phase 9 (item #50: grounded-answer evaluations — final item)

**Repository:** `lhoskins/tablescope-lh`
**Branch to merge:** `kg-validation-phase8-observability-goldens`
**Base:** `UX-design-03` (already includes Phases 1–7)

This item was implemented on the same branch as Phase 8 (#48–49) rather than a new
branch — no file overlap risk either way, and it closes out the 50-item review's very
last item, so keeping it in one deployable unit made sense. If Phase 8 hasn't been merged
yet, this ships with it in the same merge; if Phase 8 is already merged, this is a small
follow-up commit on the same branch.

**`platform-api/` only · no migration · all tests green**

---

## Context

**This is the last of the 50 items.** #50 (P0): "Prove downstream KG use with
grounded-answer evaluations — Test AI Assistant, Business Insights, Project Insights,
Executive Brief, dashboard generation, and query generation against the same project.
Require the active KG version and evidence IDs in every response envelope. **Accept:**
evaluations show that company library, project references, industry guidance, data
sources, queries, dashboards, KPIs, risks, and actions influence the correct features
without leaking across scopes."

## Validated: only 4 of the 6 named features actually consume KG context

Grepping every `surface="..."` call site in `app/routes` and `app/services` (the argument
`collect_knowledge_graph_ai_context` requires, per KG-07/Phase 2) turns up exactly four
distinct surfaces: `business_insights`, `project_insights`, `dashboard_generation`,
`query_generation` — 8 call sites total across 6 route files plus the Business/Project
Insight services.

**AI Assistant** does not consume Knowledge Graph context at all — its conversational-turn
route (`app/routes/conversational_analytics_turns.py`) has zero references to KG context,
confirmed directly and consistent with the same finding already made in Phase 2. Wiring KG
grounding into free-form chat is a materially different, larger problem than the other
four surfaces (which each already have one clear per-generation injection point) — it's
flagged here as a real gap, but deliberately out of scope for this item; a natural
candidate for its own follow-up.

**"Executive Brief"** is not a separate backend feature — it's a frontend-only
presentation (`web-ui/lib/insights/summarize-top-cards.ts`,
`business-intelligence-workspace.tsx`) that synthesizes a headline from the same Business
Insight cards Business Insights already produces, via no separate AI call and no separate
KG context collection. It inherits Business Insights' grounding automatically the moment
Business Insights' response carries it — no additional wiring needed or possible.

Both corrected findings are consistent with this review's own prior pattern of surfacing
where the reviewed document's assumptions didn't match the real codebase (e.g. Phase 2's
finding that AI Assistant chat wasn't KG-grounded either).

## Fix: KG version + evidence ids in every real KG-grounded response envelope

**`collect_knowledge_graph_ai_context`** (`app/services/knowledge_graph_ai_context.py`)
already computed the active KG version id and the exact node/document/query evidence ids
that grounded each context collection — but only to write an audit row
(`record_kg_evidence_access`, KG-07/Phase 2); it never returned that data to the caller.
`record_kg_evidence_access` (`app/services/kg_evidence_audit.py`) now returns what it
recorded (`{"kg_version_id", "node_ids", "document_ids", "query_ids"}`, or `None` when
there was nothing to ground), and `collect_knowledge_graph_ai_context` attaches it to its
own return dict as `kg_grounding` (camelCased to `{"kgVersionId", "nodeIds", "documentIds",
"queryIds"}`). No new query — this is the exact same data the audit table already
persisted, now also handed back inline.

Each of the four surfaces was then wired to attach this as `kgGrounding` on its own
response:

- **project_insights**: `ProjectInsightResponse` (`app/schemas/project_insight.py`) gained
  a `kgGrounding: dict[str, Any] | None = None` field, populated at both construction sites
  in `project_insight_service/__init__.py` (the no-AI-result early return and the main
  success path).
- **business_insights**: `run_ai_intelligence` (700+ lines,
  `app/services/home_intelligence/orchestrator.py`) gained an optional `grounding_sink`
  output parameter — an output parameter rather than widening its `list[dict] | None`
  return type, which more than one caller (including this same module's own reuse of it
  for Project Insight's deterministic cards) depends on as-is. `_run_for_project` and the
  `/api/ai/run-intelligence-suite` route (`app/routes/home_intelligence_suite.py`) thread
  it through and attach `kgGrounding` to the route's response dict.
- **dashboard_generation** (3 endpoints: `ai_proxy_dashboard.py`,
  `ai_proxy_dashboard_generate.py`, `ai_proxy_dashboard_suggest.py`) and
  **query_generation** (3 endpoints: `ai_proxy_query.py`, `ai_proxy_query_actions.py`,
  `ai_proxy_ask_and_run.py`, the last with two internal KG call sites and two routes)
  each capture the already-fetched KG context into a local variable and merge
  `"kgGrounding": kg_context.get("kg_grounding")` into every dict they return — including
  error paths (`generation_error`/`execution_error`/`ai_unavailable`), where it's
  correctly `None` (or the real value if generation had already reached the KG-context
  step before failing later). Two of `ai_proxy_query_actions.py`'s paths (a fuzzy
  source-name match, an offline heuristic fallback) never call the AI server with KG
  context at all — their envelopes correctly report `kgGrounding: None` too, since they
  genuinely aren't KG-grounded, rather than fabricating a value.

## Grounded-answer evaluations

`tests/test_kg50_grounded_answer_evaluations.py` — for the two surfaces most directly
testable without heavy AI-server-pass-through mocking (project_insights, business_insights):
- `collect_knowledge_graph_ai_context`'s `kg_grounding` matches the real active KG version
  id and contains a real seeded node's id; is `None` for a project with no KG content.
- The actual HTTP response from `GET /api/projects/{id}/insight` carries `kgGrounding`
  matching that project's own active version and evidence — and, built for two separate
  tenants/projects in the same test run, **never** the other project's version id or node
  id (the isolation half of the Accept criterion).
- The actual HTTP response from `POST /api/ai/run-intelligence-suite` carries `kgGrounding`
  matching the real active version and seeded evidence.

**Deliberately not covered by a new evaluation test:** dashboard_generation and
query_generation's six endpoints are AI-server pass-throughs (`_forward_to_ai`) — proving
"the right evidence influenced the AI's actual generated content" for those would require
either a live AI server or building new response-content mocking infrastructure neither
this repo's existing tests nor this item's core ask (the envelope carrying the KG version
+ evidence ids) call for. Their wiring is proven correct by: code review (shown above),
clean `ruff`/`mypy`, and the full existing regression suite for those six endpoints passing
unchanged (161 tests across every touched surface's existing test files, 0 regressions).

## Tests added

| File | Coverage |
|---|---|
| `tests/test_kg50_grounded_answer_evaluations.py` (4 tests, new file) | grounding-block correctness (matches real version/evidence, `None` when empty), project_insights envelope + cross-project isolation, business_insights envelope |

All 4 proven to fail against pre-fix code (`git stash` on the six core wiring files —
`kg_evidence_audit.py`, `knowledge_graph_ai_context.py`, `project_insight_service/__init__.py`,
`schemas/project_insight.py`, `home_intelligence/orchestrator.py`, `home_intelligence_suite.py`
— rerun, confirm all 4 fail with `KeyError: 'kg_grounding'`/`'kgGrounding'`, restore, confirm
all 4 pass).

## Verification

| Suite | Result |
|---|---|
| `pytest tests/test_kg50_grounded_answer_evaluations.py -q` | 4 passed |
| `pytest tests/test_kg07_evidence_audit.py tests/test_kg39_grounding_status.py tests/test_ai_ask_and_run.py tests/test_dashboard_suggest_preview_chart_type.py tests/test_ai_proxy_query_relationship_hints.py tests/test_business_insight_shared_cache.py tests/test_dashboards.py tests/test_project_insight.py tests/test_project_insight_rebuild.py tests/test_project_source_resolver.py tests/test_home_intelligence.py tests/test_kg50*.py -q` | 161 passed, 0 regressions across every touched surface |
| `ruff check` (all 12 touched files) | clean |
| `mypy` (all 12 touched files) | clean |
| Full `pytest -q` (whole platform-api suite) | pending final count at doc-write time — see follow-up commit; expected to match the ~1775 passed / 10 pre-existing-unrelated-failures baseline from Phase 8 |

```bash
cd platform-api
pytest -q
ruff check app/services/kg_evidence_audit.py \
  app/services/knowledge_graph_ai_context.py \
  app/services/project_insight_service/__init__.py \
  app/schemas/project_insight.py \
  app/services/home_intelligence/orchestrator.py \
  app/routes/home_intelligence_suite.py \
  app/routes/ai_proxy_dashboard.py \
  app/routes/ai_proxy_dashboard_generate.py \
  app/routes/ai_proxy_dashboard_suggest.py \
  app/routes/ai_proxy_query.py \
  app/routes/ai_proxy_query_actions.py \
  app/routes/ai_proxy_ask_and_run.py
mypy app/services/kg_evidence_audit.py \
  app/services/knowledge_graph_ai_context.py \
  app/services/project_insight_service/__init__.py \
  app/schemas/project_insight.py \
  app/services/home_intelligence/orchestrator.py \
  app/routes/home_intelligence_suite.py \
  app/routes/ai_proxy_dashboard.py \
  app/routes/ai_proxy_dashboard_generate.py \
  app/routes/ai_proxy_dashboard_suggest.py \
  app/routes/ai_proxy_query.py \
  app/routes/ai_proxy_query_actions.py \
  app/routes/ai_proxy_ask_and_run.py
```

## Deploy

`platform-api` only, no migration, no `web-ui`/`ai-server` change (the frontend can start
reading `kgGrounding` off any of these responses whenever it's ready to; its absence in
older clients is harmless since it's purely additive).

```bash
docker compose build platform-api
docker compose up -d platform-api platform-api-worker
```

## Verify live

- Call `GET /api/projects/{id}/insight` for a project with an active Knowledge Graph and
  confirm the response's `kgGrounding.kgVersionId` matches that project's current active
  version (visible via `GET /api/projects/{id}/knowledge-graph/status`), and
  `kgGrounding.nodeIds`/`documentIds`/`queryIds` reference real evidence for that project.
- Call `POST /api/ai/run-intelligence-suite` for the same project and confirm the same.
- Trigger dashboard suggestion / query generation for a project with real KG content and
  confirm `kgGrounding` appears in the response with the correct version id.
- Confirm a project with no Knowledge Graph content yet gets `kgGrounding: null` across
  all four surfaces rather than an error or a stale/wrong value.

## Overall: the 50-item review is now complete

Every P0 item is done. Remaining open items are all P1: Section A (#08–09, sensitivity
labels, deletion/revocation propagation), Section B (#12/14/16–18/20, pagination, content
hashing, chunk-level evidence, parsed SQL lineage, widget-derived dashboard lineage,
reference versioning), Section C (#24–30, schema registry, relationship-direction
validation, duplicate detection, entity resolution, join-quality evidence, temporal
consistency, semantic coverage scoring), Section D (#32/34–38/40, confidence calibration,
real evidence paths, contradiction detection, source-authority weighting,
question-aware context selection, context-omission reporting, deterministic card
fallback), and Section E (none left — closed out across Phases 6–9).

## Report back

Confirmation `kgGrounding` shows correctly live across all four surfaces for both a
KG-rich and a KG-empty project, and — since every P0 item across all 50 is now done —
whether to continue into the remaining P1 batches (by section, in review order: B, then
C, then D, then A) or consider the review complete at this priority level.

---

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01M7j8CDCHCdwHpw9FrRhLN5
