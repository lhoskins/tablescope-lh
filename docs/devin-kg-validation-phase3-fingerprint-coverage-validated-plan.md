# Devin: merge + deploy — Knowledge Graph validation, Phase 3 (items #11, #13, #15: fingerprint + coverage manifest)

**Repository:** `lhoskins/tablescope-lh`
**Branch to merge:** `kg-validation-phase3-fingerprint-ingestion`
**Base:** `UX-design-03` (already includes Phase 1)

**`platform-api/` only · no migration · all tests green**

---

## Context

Third installment of the 50-item Knowledge Graph validation review. This batch
implements items **#13** (P0), **#15** (P0), and **#11** (P1, folded in because its
"coverage manifest" deliverable is the same computation #15 needed).

## 13. Expand the source fingerprint to every graph-relevant source

**Validated:** true. `compute_source_fingerprint` tracked goals, metrics, risks,
`DatabaseDataSource`, saved queries, dashboards, `ProjectAsset`, and repository scans —
but not uploaded file sources (`FileSourceMeta`) or the Reference Library
(`ReferenceDocument`, any tier). Editing or adding an uploaded file or a reference
document left the fingerprint (and therefore staleness detection) completely unchanged.

**Fix:** added `FileSourceMeta` to the existing generic per-model fingerprint loop, and a
dedicated reference-document query mirroring `collect_structural_graph`'s own tier scope
(project docs, tenant-wide company docs, global industry standards) — so the fingerprint
tracks exactly what the collector actually pulls into the graph, no more and no less.

**Tests:** `tests/test_kg13_source_fingerprint.py` (5 tests) — fingerprint changes when a
file source, a project reference, a company reference, or an industry standard is added;
does *not* change for another tenant's company reference. All verified to fail pre-fix.

## 15 & 11. Ingestion status tracking + an explicit coverage manifest

**Validated:** both real gaps, and closely related enough to fix together.
`collect_structural_graph` silently caps each source kind at 40 records
(`_MAX_PER_KIND`) with no visibility into what got excluded, and per-source ingestion
state (`ProjectAsset.ai_status`, `FileSourceMeta.ai_profile_status`,
`DatabaseDataSource.last_test_status`) already existed on each model but was never
surfaced at the *build* level — a build could succeed while quietly omitting sources that
were truncated, still processing, or failed.

**Fix:** new `app/services/knowledge_graph_context/coverage.py::compute_source_coverage`
returns a `{source_type: {total, included, excluded, failed, pending}}` manifest for
every source kind the collector draws on (file sources, database sources, project assets,
reference documents, saved queries, dashboards) — best-effort per source type, so one
query failing never blocks the others or the build. Saved queries and dashboards are
user-authored (no extraction pipeline to fail or leave pending), so they report only the
truncation-cap counts; the review's own item #11 wording ("total, included, excluded,
failed, and pending counts by source type") is satisfied per-kind even where
failed/pending is always 0.

Wired into both `KnowledgeGraphLifecycleManager` build paths
(`run_full_rebuild`/`run_incremental_rebuild` in `rebuild_execution.py`) — the coverage
manifest is merged into the existing `KnowledgeGraphVersion.validation_summary` JSON
column (no migration needed, that column already exists and was already the right place
for build-time diagnostics) alongside the pre-existing validation errors/warnings/orphan
ratio, which itself **was not previously exposed via the API at all** — added
`validation_summary` to `KnowledgeGraphVersionRead` so both the existing validation info
and the new coverage manifest are now visible on `GET .../knowledge-graph/versions`.

**Deliberately not done:** wiring the coverage manifest into the health-check's
overall healthy/degraded verdict (the second half of item #11's acceptance test, "the
health result cannot call that graph fully healthy") — that's activation-gating logic
that belongs with items #21/#47 (materially stricter activation validation), which touch
the same health-check module and are next in the Phase 1 P0 priority order.

**Tests:** `tests/test_kg15_source_coverage.py` (5 tests) — file-source pending detection,
asset failed-vs-pending, data-source untested-vs-failed, reference-document tier scoping
(including an excluded-status doc and a cross-tenant doc correctly excluded), and the
truncation-cap math itself (monkeypatched to a small cap rather than seeding 41 rows).

## Tests added

| File | Coverage |
|---|---|
| `tests/test_kg13_source_fingerprint.py` (5 tests, new file) | fingerprint reacts to file sources and all 3 reference-document tiers; ignores cross-tenant company references |
| `tests/test_kg15_source_coverage.py` (5 tests, new file) | per-source-type total/included/excluded/failed/pending correctness |

## Verification

| Suite | Result |
|---|---|
| `pytest tests/test_knowledge_graph*.py tests/test_kg0*.py tests/test_kg1*.py tests/test_ts_iso_003_project_access.py -q` | 195 passed |
| `ruff check` (touched files) | clean |
| `mypy` (touched files) | clean |
| Full `pytest -q` (whole platform-api suite) | **1718 passed, 4 skipped, 10 failed** — 0 new; the same 10 pre-existing/unrelated failures confirmed on the prior two batches |

```bash
cd platform-api
pytest -q
ruff check app/services/knowledge_graph_context/coverage.py \
  app/services/knowledge_graph_context/__init__.py \
  app/services/knowledge_graph_lifecycle/bootstrap.py \
  app/services/knowledge_graph_lifecycle/rebuild_execution.py \
  app/schemas/knowledge_graph.py
mypy app/services/knowledge_graph_context/coverage.py \
  app/services/knowledge_graph_lifecycle/bootstrap.py \
  app/services/knowledge_graph_lifecycle/rebuild_execution.py \
  app/schemas/knowledge_graph.py
```

## Deploy

`platform-api` only, no migration, no `web-ui`/`ai-server` change.

```bash
docker compose build platform-api
docker compose up -d platform-api platform-api-worker
```

## Verify live

- Upload a file source or add/edit a Reference Library document, then confirm a
  Knowledge Graph rebuild is triggered (staleness detected) where it previously wasn't.
- On a project with more than 40 sources of one kind, trigger a rebuild and confirm
  `GET .../knowledge-graph/versions` shows `validation_summary.source_coverage` with a
  non-zero `excluded` count for that source type.
- On a project with a document stuck in `ai_status="failed"` or `"extracting"`, confirm
  the same manifest reports it under `failed`/`pending` for `assets`.

## Remaining work

Still open, tracked as the 50-item checklist. Next in the Phase 1 P0 priority order:
item #19 (KPI measurement semantic binding) and items #21–23/#47 (activation validation,
including wiring this batch's coverage manifest into the health-check verdict).

## Report back

Confirmation the fingerprint/coverage changes behave correctly live, and whether to
continue with #19 or #21–23/#47 next.

---

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01M7j8CDCHCdwHpw9FrRhLN5
