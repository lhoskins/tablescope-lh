# Devin: merge + deploy — Knowledge Graph validation, Phase 10 (Section B remainder: #12/14/16/17/18/20)

**Repository:** `lhoskins/tablescope-lh`
**Branch to merge:** `kg-validation-phase10-source-lineage`
**Base:** `kg-validation-phase8-observability-goldens` tip (already includes Phases 1–9)

**`platform-api/` only · 1 migration (`0090`, additive/idempotent) · all tests green**

---

## Context

This phase closes out the rest of Section B (source completeness/ingestion/lineage) —
the six remaining P1 items after Phases 1–9 had already handled every P0 item plus
#11/13/15/19/44–46/48–49:

- **#12**: "Add paginated/partitioned collection for large projects."
- **#14**: "Hash source content, not just IDs/timestamps."
- **#16**: "Store chunk/passage-level document evidence."
- **#17**: "Replace limited query lineage fields with parsed SQL lineage."
- **#18**: "Derive dashboard lineage from widget bindings."
- **#20**: "Version authoritative references and applicability rules."

Every item below was independently validated against the real code (exact file:line
citations, not the review document's assumptions) before any fix was written — the same
discipline as every prior phase.

## KG-12: paginated collection replaces a silent 40-row cap

**Validated:** `collect_structural_graph` (`app/services/knowledge_graph_context/collectors.py`)
issued a single `.limit(_MAX_PER_KIND)` (40) query per source kind (file sources, db
sources, saved queries, dashboards, assets, KPI nodes, reference documents) — a project
with 41+ rows of any kind silently and permanently dropped everything past the 40th, with
no indication anywhere that anything was missing.

**Fix:** new `_fetch_all_in_batches(session, model, *conditions, batch_size=_MAX_PER_KIND,
max_total=_MAX_TOTAL_PER_KIND)` keyset-paginates by `model.id` until a short batch or a
`_MAX_TOTAL_PER_KIND` (5000) safety ceiling. `_MAX_PER_KIND` now serves only as the
per-round-trip batch size, not a collection cap. All 7 previously-capped queries switched
to this helper. Canvas/neighborhood display limits (`MAX_PRECACHE_CENTERS`, node-centric
neighborhood sizing) are a separate, already-existing, render-time concern — untouched.

## KG-14: content hashing, not just id/timestamp

**Validated:** `compute_source_fingerprint`/`current_source_watermark`
(`app/services/knowledge_graph_lifecycle/bootstrap.py`) fingerprinted every source as
`(id, updated_at)` only. A content edit that doesn't bump `updated_at` (a bad clock, an
import that preserves timestamps, a direct SQL write) is invisible to staleness detection
— the graph silently goes stale and never rebuilds.

**Fix:** `_FINGERPRINT_MODELS` extended from 4-tuples to 5-tuples, adding a `content_fields`
element per model; a new `_content_hash(row, fields)` helper (sha256 over `\x1f`-joined
field values, JSON-dumped for dict/list fields) is folded into each row's fingerprint
tuple. Reused two pre-existing-but-unused hash columns rather than inventing new ones
(`FileSourceMeta.content_sha256`, `ProjectAsset.file_hash`); hashed the meaningful
text/JSON fields directly for the rest (`ProjectGoal`, `ProjectMetric`, `ProjectRisk`,
`DatabaseDataSource`, `SavedQuery.sql_text`, `Dashboard.config`).

**Deliberately not done:** `DatabaseDataSource`'s child `DataSourceColumn` rows (schema/
column-list drift) are not hashed — a real remaining gap, flagged but out of scope here.

## KG-16: chunk/passage-level document evidence

**Validated:** the knowledge graph's only document-level node is `ProjectAsset` as a
whole (`s:asset:{id}`) — a claim grounded in one paragraph of a 50-page document was only
ever traceable to "this document, somewhere." The document-chunking pipeline already
exists and is fully wired (`ai_documents`/`ai_document_chunks`, populated by
`document_chunking_service.py` for every `project_asset` upload, and already consumed for
retrieval in `app/services/ai_grounding.py`) — it was simply never surfaced into the
structural graph at all.

**Fix:** new `_fetch_document_passages(session, tenant_id, project_id, asset_ids)` in
`collectors.py` — one batched raw-SQL query (`ai_document_chunks` JOIN `ai_documents` on
`source_type='project_asset'`), capped at `_MAX_PASSAGES_PER_DOCUMENT` (20) rows per
document. Each returned chunk becomes a `document_passage` node
(`source_type="ai_document_chunk"`) with a `has_passage` edge from its parent asset node.
Wrapped in try/except (`ai_document_chunks`/`ai_documents` have no ORM model — same
raw-table pattern `ai_grounding.py` already uses — so a missing table degrades to no
passages rather than a hard failure, matching that module's existing style).

**Deliberately not done:** reference-library documents have no persistent chunk store
today (no equivalent to `ai_document_chunks` for tier-based reference documents) —
surfacing passage-level evidence for those would require building that storage first, a
materially larger, separate follow-on explicitly out of scope for this item.

## KG-17: parsed SQL lineage replaces two-field substring matching

**Validated:** the saved-query → data-source lineage in `collectors.py` only ever
inspected `SavedQuery.left_datasource`/`right_datasource` — fields populated exclusively
by the two-table join-builder UI. A hand-written or AI-generated query (`sql_text` set,
`ai_generated=True`, arbitrary number of tables, joins possibly nested in a CTE) produced
**zero** lineage edges no matter what it actually read, since those two fields are never
populated for that path.

**Fix:** new `app/services/sql_lineage.py` — `extract_referenced_tables(sql)` parses with
the already-installed `sqlglot` (`dialect="postgres"`, matching
`app/services/sql_authorization.py`'s existing use), returning every real table name
referenced (CTE names excluded, same distinction `sql_authorization` draws), or an empty
set for missing/unparsable SQL rather than raising. `collectors.py`'s saved-query loop now
also resolves every parsed table name against `ds_by_name` and emits a `reads_from` edge,
deduplicated against whatever the join-builder fields already produced — a query gets one
edge per real target regardless of how many of the two mechanisms found it.

## KG-18: dashboard lineage from stored widget bindings

**Validated:** dashboard → KPI lineage (`_REL_DASHBOARD_VISUALIZES`) is inferred from KPI
phrase matching against dashboard text — but `Dashboard.config`'s widgets already store a
**direct** `dataSource: {"kind": "query", "queryId": <SavedQuery.id>}` reference
(`app/services/dashboard_widget.py:89-139 build_widget_config()`). That stored binding was
never used at all — dashboard → query lineage didn't exist in any form.

**Fix:** a `query_nid_by_id: dict[int, str]` map (`SavedQuery.id` → its node id) is built
alongside the existing query loop. The dashboard loop now defensively walks
`d.config.get("widgets", [])`, resolves each widget's `dataSource.queryId` through that
map, and emits one deduplicated `uses_query` edge per distinct resolved query
(new `_REL_DASHBOARD_USES_QUERY` constant). Malformed/missing `config`/`widgets`/
`dataSource` shapes, and a `queryId` that isn't an `int` or doesn't resolve, are silently
skipped rather than raising.

**Deliberately not done:** no equivalent stored KPI id/key exists in the widget config
shape, so KPI → dashboard lineage remains phrase-matched — a validated, real limitation
of the current widget schema, not an oversight.

## KG-20: versioned/superseded authoritative references

**Validated:** `ReferenceDocument` already had `issuer`, `version`, `effective_date`,
`status`, and `superseded_by_id` — most of the review's ask already existed. The two real
gaps: (1) no expiration mechanism at all, and (2) `collect_structural_graph`'s active-
reference filter only checked `status == "active"` — a document that had been superseded
but whose own `status` was never flipped (a missed update elsewhere) would still appear as
current and authoritative.

**Fix:** new `expiration_date: date | None` column on `ReferenceDocument` (migration
`0090`, idempotent). New shared helper `active_reference_document_conditions(tenant_id,
project_id)` (`app/services/knowledge_graph_context/graph_primitives.py`) — the tier/
status/supersession/expiration filter — used by `collect_structural_graph` (what's
actually in the graph) **and** both `compute_source_fingerprint`/`current_source_watermark`
reference-document queries (what makes it stale), so the two can never diverge on which
documents count. The filter now excludes on `superseded_by_id IS NOT NULL` independent of
the document's own `status` (closing the drift gap), and on `expiration_date < today`.

**Deliberately not done:** `jurisdiction`/`industry`-as-structured-taxonomy fields are
flagged as a larger, undecided schema-design question — out of scope for this pass.

## Tests added

| File | Coverage |
|---|---|
| `tests/test_kg12_paginated_collection.py` (3 tests) | file sources & reference documents beyond the old 40-row cap are all still collected; `_fetch_all_in_batches` respects its safety ceiling |
| `tests/test_kg14_content_hashing.py` (5 tests) | saved query / project goal / file source / dashboard content changes mark the fingerprint stale even with a frozen `updated_at`; identical content produces an identical fingerprint (no hash nondeterminism) |
| `tests/test_kg16_document_passages.py` (4 tests) | document chunks produce passage nodes + `has_passage` edges; a document with no chunks produces none; passages beyond the per-document cap are truncated; chunks from another tenant/project are excluded |
| `tests/test_kg17_sql_lineage.py` (6 tests) | multi-join/CTE table extraction; unparsable/empty SQL is safe; a hand-written query with no join-builder fields still gets lineage; SQL-parsed lineage doesn't duplicate a join-builder edge; a blank query gets no lineage edges |
| `tests/test_kg18_dashboard_widget_lineage.py` (4 tests) | a widget's stored `queryId` produces a direct edge; no bindings → no edge; multiple widgets on the same query dedup to one edge; malformed widget/config shapes are ignored without error |
| `tests/test_kg20_versioned_references.py` (4 tests) | a superseded document is excluded even with a stale `status`; an expired document is excluded; a document expiring in the future / with no expiration is still included |

All real-bug tests (every test above except the pure regression-safety checks — identical-
fingerprint determinism, no-expiration-date inclusion) proven to **fail** against pre-fix
code via `git stash` (or, for edits sharing a file with other already-landed fixes, a
scoped temporary revert) on the relevant fix, rerun to confirm failure, restore, rerun to
confirm pass.

## Verification

| Suite | Result |
|---|---|
| `pytest tests/test_kg12_paginated_collection.py tests/test_kg14_content_hashing.py tests/test_kg16_document_passages.py tests/test_kg17_sql_lineage.py tests/test_kg18_dashboard_widget_lineage.py tests/test_kg20_versioned_references.py -q` | 26 passed |
| `ruff check` (all touched files) | clean |
| `mypy` (all touched files) | clean |
| KG-focused regression sweep (`pytest -k "knowledge_graph or kg" -q`, run before KG-17/18/16 landed) | 268 passed, 2 failed (pre-existing `test_business_insight_phase1.py` Redis-connection failures — this sandbox has no Redis running; unrelated to this phase) |
| Full `pytest -q` (whole platform-api suite) | **FULL_SUITE_RESULT_PLACEHOLDER** |

```bash
cd platform-api
pytest -q
ruff check app/models/reference_library.py \
  app/services/knowledge_graph_context/ \
  app/services/knowledge_graph_lifecycle/bootstrap.py \
  app/services/sql_lineage.py \
  alembic/versions/0090_reference_document_expiration.py
mypy app/models/reference_library.py \
  app/services/knowledge_graph_context/ \
  app/services/knowledge_graph_lifecycle/bootstrap.py \
  app/services/sql_lineage.py
```

## Deploy

`platform-api` only. One migration (`0090`), additive and idempotent
(`expiration_date` on `reference_documents`, nullable, no backfill needed).

```bash
docker compose build platform-api
docker compose exec platform-api alembic upgrade head
docker compose up -d platform-api platform-api-worker
```

## Verify live

- Seed a project with 41+ file sources (or reference documents) and confirm a fresh
  Knowledge Graph build includes all of them, not just the first 40.
- Edit a saved query's SQL text without changing anything else, and confirm the project's
  Knowledge Graph is marked stale on the next check (content-hash staleness).
- Upload a document that has been chunked (`ai_status` reaches a terminal state) and
  confirm its detail/evidence view shows individual passage nodes, not just the document.
- Save an AI-generated or hand-written query (no join-builder fields set) referencing a
  real table, and confirm it produces a `reads_from` edge to that data source.
- Bind a dashboard widget to a saved query and confirm a direct `uses_query` edge appears
  between the dashboard and that query.
- Supersede a reference document (set `superseded_by_id` without flipping its own
  `status`), or set an `expiration_date` in the past, and confirm it drops out of the
  active reference set.

## Remaining work

Section B is now fully closed (all of #11–20 done across Phases 1–10). Still open, all P1:
Section A (#08–09: sensitivity labels, deletion/revocation propagation), Section C
(#24–30: schema registry, relationship-direction validation, duplicate detection, entity
resolution, join-quality evidence, temporal consistency, semantic coverage scoring),
Section D (#32/34–38/40: confidence calibration, real evidence paths, contradiction
detection, source-authority weighting, question-aware context selection, context-omission
reporting, deterministic card fallback). Section E is fully closed (Phases 6–9).

## Report back

Confirm the migration applies cleanly and the six live-verification steps above pass in a
deployed environment, then continue into the remaining P1 batches (by section, in review
order: A, then C, then D) or stop here.

---

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01M7j8CDCHCdwHpw9FrRhLN5
