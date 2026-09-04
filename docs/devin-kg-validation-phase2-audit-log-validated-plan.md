# Devin: merge + deploy — Knowledge Graph validation, Phase 2 (Section A item #7: evidence audit log)

**Repository:** `lhoskins/tablescope-lh`
**Branch to merge:** `kg-validation-phase2-audit-log`
**Base:** `UX-design-03` (already includes the Phase 1 batch)

**`platform-api/` only · includes a migration (0087) · all tests green**

---

## Context

Second installment of the 50-item Knowledge Graph validation review. This batch
implements item **#7**: source-access audit records for every KG-powered answer.

## Validation notes (before implementing)

The review lists "AI Assistant, Business Insights, Project Insights, dashboards, and
executive summaries" as the surfaces to audit. Tracing the actual code found this
needed correcting:

- **AI Assistant chat** (`ai_ask.py` / `conversational_analytics`) does **not** currently
  consume any Knowledge Graph context at all — there is nothing to audit there yet. Wiring
  KG context into AI Assistant chat would be new functionality, out of scope for an
  audit-logging item.
- The real KG-powered surfaces all funnel through a **single existing choke point**:
  `knowledge_graph_ai_context.py::collect_knowledge_graph_ai_context`, called by
  `home_intelligence/orchestrator.py` (Business Insights), `project_insight_service`
  (Project Insights), and `ai_proxy_shared.py::_kg_context` (dashboard generation, query
  generation — 7 separate route call sites across `ai_proxy_dashboard.py`,
  `ai_proxy_dashboard_suggest.py`, `ai_proxy_dashboard_generate.py`, `ai_proxy_query.py`,
  `ai_proxy_query_actions.py`, `ai_proxy_ask_and_run.py` ×2).
- "Executive summaries" (`synthesise_cross_project`) don't call this function directly —
  they aggregate cards that were already generated (and already audited) per-project by
  Business Insights, so no separate instrumentation point was needed there.

Since every real consumer shares one function, instrumenting it once covers all of them
correctly, rather than duplicating audit logic five times.

## Implementation

**New table `knowledge_graph_evidence_access`** (migration `0087`, model
`app/models/knowledge_graph_evidence_access.py`): one row per KG context collection —
`tenant_id`, `project_id`, `user_id`, `surface`, `kg_version_id` (the project's active
`KnowledgeGraph.active_version_id` at collection time), and `node_ids` / `document_ids` /
`query_ids` (JSON arrays).

**New `app/services/kg_evidence_audit.py`**: `record_kg_evidence_access(...)` — the
best-effort write helper (an audit-write failure never breaks the feature it's auditing);
`evidence_ids_from_nodes(...)` — splits a node list into node/document/query ids by each
node's `source_type`.

**`collect_knowledge_graph_ai_context`** now takes a required `surface` argument
(`business_insights` | `project_insights` | `dashboard_generation` | `query_generation`).
Each bucketed item (risk/opportunity/gap/warning/kpi/document/process/entity) and each
lineage edge is tagged internally with the originating node id(s) as it's built; **after**
ranking/deduping/capping — not before — the function collects exactly the ids that
survived into the *returned* context (not the full candidate set merely considered),
writes the audit row, then strips the internal `_id`/`_ids` tags before returning, so the
AI-server-facing schema is unchanged.

All 9 call sites updated to pass their real `surface` label (`orchestrator.py`,
`project_insight_service/__init__.py`, and 7 routes via `ai_proxy_shared.py::_kg_context`,
which now requires `surface` explicitly rather than defaulting it).

## Tests added

| File | Coverage |
|---|---|
| `tests/test_kg07_evidence_audit.py` (4 tests, new file) | writes a row with the correct tenant/project/user/surface/kg_version/node/document/query ids; different surfaces recorded as separate rows; an empty/no-evidence context writes no row; the internal `_id`/`_ids` audit tags never leak into the AI-facing response schema |

Verified to fail against pre-fix code (temporarily removed the new model/service files,
reran — `ModuleNotFoundError` as expected) and pass post-fix.

## Verification

| Suite | Result |
|---|---|
| `pytest tests/test_kg07_evidence_audit.py tests/test_knowledge_graph_ai_context.py tests/test_knowledge_graph_ai.py tests/test_business_insight_phase1.py tests/test_ai_ask_and_run.py tests/test_ai_proxy_permissions.py tests/test_ai_proxy_query_relationship_hints.py tests/test_ai_proxy_shared.py tests/test_dashboard_suggest_preview_chart_type.py tests/test_home_intel_tenant_slots.py tests/test_home_intelligence.py tests/test_home_intelligence_insights_cache.py tests/test_project_insight.py tests/test_project_insight_rebuild.py -q` | 158 passed, 3 failed (all pre-existing/unrelated Redis-connection failures in `test_business_insight_phase1.py`, same as every prior turn) |
| `pytest tests/test_knowledge_graph*.py tests/test_kg0*.py -q` | 145 passed |
| `ruff check` (touched files) | clean |
| `mypy` (touched files) | clean |
| Full `pytest -q` (whole platform-api suite) | **1712 passed, 4 skipped, 10 failed** — 0 new; the exact same 10 pre-existing/unrelated failures confirmed on the prior (Phase 1) batch (`test_business_insight_phase1.py` ×3, `test_percent_change_summary.py` ×4, `test_ai_dashboard_pipeline.py`, `test_ask_pipeline.py`, `test_visualization_engine.py`) |

```bash
cd platform-api
pytest -q
ruff check app/models/knowledge_graph_evidence_access.py app/services/kg_evidence_audit.py \
  app/services/knowledge_graph_ai_context.py app/routes/ai_proxy_shared.py \
  app/routes/ai_proxy_dashboard.py app/routes/ai_proxy_dashboard_generate.py \
  app/routes/ai_proxy_dashboard_suggest.py app/routes/ai_proxy_query.py \
  app/routes/ai_proxy_query_actions.py app/routes/ai_proxy_ask_and_run.py \
  app/services/home_intelligence/orchestrator.py app/services/project_insight_service/__init__.py
mypy app/models/knowledge_graph_evidence_access.py app/services/kg_evidence_audit.py \
  app/services/knowledge_graph_ai_context.py
```

## Deploy

`platform-api` only, **includes migration 0087**, no `web-ui`/`ai-server` change.

```bash
cd platform-api
alembic upgrade head   # creates knowledge_graph_evidence_access
docker compose build platform-api
docker compose up -d platform-api platform-api-worker
```

## Verify live

- Trigger a Business Insights refresh, a Project Insights refresh, and a dashboard/query
  AI generation on the same project; confirm each writes a `knowledge_graph_evidence_access`
  row with the correct `surface` label and a non-empty `node_ids`.
- Confirm `kg_version_id` on a fresh row matches the project's currently active
  `KnowledgeGraphVersion`.
- Confirm a project with no Knowledge Graph data (empty context) writes no row.

## Remaining work

Still open, tracked as the 50-item checklist: Section A items #8–9 (P1, deferred to Phase
3 per the review's own recommended order); Sections B–E (items 11–50).

## Report back

Confirmation the audit rows are being written correctly for a real project, and whether
to continue with Section B (source completeness/lineage, items #11–20) next.

---

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01M7j8CDCHCdwHpw9FrRhLN5
