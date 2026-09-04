# Devin: merge + deploy — Knowledge Graph validation, Phase 4 (items #19, #21–23, #47: activation validation + KPI matching)

**Repository:** `lhoskins/tablescope-lh`
**Branch to merge:** `kg-validation-phase4-activation-kpi`
**Base:** `UX-design-03` (already includes Phases 1–3)

**`platform-api/` only · no migration · all tests green**

---

## Context

Fourth installment of the 50-item Knowledge Graph validation review. This batch closes
out the rest of Phase 1's P0 items: **#19** (KPI measurement semantic binding) and
**#21–23 + #47** (activation validation), all validated against the real code first.

## 19. Replace substring KPI measurement detection with semantic/structural binding

**Validated:** true, and reproduced a concrete false-positive: `_phrase_in` matched a KPI
phrase as a raw substring of a fully punctuation-stripped, space-collapsed haystack. A KPI
named **"Rate"** (exactly at the 4-character minimum) was falsely classified as "measured"
by *any* query whose text merely contained a word like "**corp**orate", "ac**curat**e", or
"mod**erat**e" — the phrase "rate" appears as a raw substring fragment inside each.

**Fix:** added `_norm_words` (collapses punctuation/whitespace runs to a single space
instead of deleting them, preserving word boundaries) and use it specifically for KPI
phrase/haystack normalization; `_norm` itself is untouched since other callers rely on its
no-space form for exact-match graph keys. `_phrase_in` now pads both the phrase and the
haystack with boundary spaces before the substring check, so a phrase only matches on
whole-word/whole-phrase boundaries.

**Deliberately not done:** true semantic (embeddings-based) matching — that's a much
larger feature (needs a vector index and a similarity threshold policy) than what a
false-positive substring bug calls for; this fix directly closes the concrete failure mode
the review demonstrates ("similarly named KPIs do not cross-link") without over-building.

**Tests:** `tests/test_kg19_kpi_phrase_matching.py` (4 tests) — the exact "Rate" vs.
"Corporate" false positive (proven to reproduce pre-fix), a multi-word true positive still
matching, and two direct unit tests of `_phrase_in`'s new word-boundary semantics.

## 21, 22, 23 & 47. Activation validation

**Validated:** all four point at the same root cause. `rebuild_execution.py`'s
pre-activation validator and `knowledge_graph_health.py`'s post-activation health check
were two independently hand-rolled, materially different implementations of "is this graph
structurally sound" — a pattern this review effort has now found several times (see the
`security-ts-iso-003` project-access consolidation from Phase 1). The pre-activation one
was the weaker of the two: a missing project hub, dangling edge references, and a high
orphan ratio were only warnings there, never blocking, so a candidate could be activated
and then immediately fail its own first health check (item #47's exact concern). Both also
read `version.disconnected_component_count` as though it had already been computed —
**it was always its default, `0`**, since nothing in the codebase ever actually computed it
from a candidate's own graph (item #22's confirmed bug).

**Fix:** new shared `app/services/knowledge_graph_lifecycle/structural_integrity.py`:
`evaluate_structural_integrity(nodes, edges)` —
- **KG-22:** computes real connected components via union-find over the candidate's own
  nodes/edges, reporting genuinely separate multi-node clusters beyond the main graph
  (isolated singleton nodes are tracked separately as orphans, not inflating the count).
- **KG-23:** a dangling edge reference is now a blocking error, not a warning.
- **KG-21:** an orphan ratio over 50% is now blocking — but only once there are enough
  nodes (≥4) for that ratio to mean anything; a brand-new project with just its hub node
  isn't penalized for not having content yet. No per-project-type threshold tiers exist
  (that needs a project-type taxonomy this codebase doesn't have) — a single conservative
  default until one is introduced.
- **KG-47:** wired into *both* `rebuild_execution.py::_validate_payload` (the activation
  gate) and `knowledge_graph_health.py::_structural_checks` (the post-activation report),
  so the two can no longer silently disagree, and a candidate is now held to the same
  strictness it would immediately face from its first health check.

**Also discovered while testing:** `merge_graph_sources` (existing code) already
unconditionally drops any edge whose endpoint isn't in the merged node set, and
`collect_structural_graph` always contributes exactly one project hub node — so in the
*current* pipeline, a dangling edge or missing hub can't actually reach validation through
a normal full rebuild. The new blocking checks are still real, valuable defense-in-depth
(a payload assembled another way — e.g. a future bug in the incremental-patch path, item
#43's territory — could still produce one) and are verified directly at the
`evaluate_structural_integrity` unit level; the orphan-ratio blocking behavior is
additionally proven end-to-end through a real full rebuild, since that one *is* reachable
depending on actual project content.

**Tests:** `tests/test_kg21_activation_validation.py` (7 tests) — dangling-edge blocking,
missing-hub blocking, high-orphan-ratio blocking (with enough coverage to judge),
high-orphan-ratio staying a warning for a tiny new project, real (not stale-zero)
disconnected-component computation, isolated singletons correctly excluded from that
count, and a full end-to-end rebuild proving a materially under-connected candidate never
gets activated (the last healthy version — none, in this fixture — stays in place, the
build is marked failed).

## Tests added

| File | Coverage |
|---|---|
| `tests/test_kg19_kpi_phrase_matching.py` (4 tests, new file) | word-boundary KPI matching, false-positive fix, true-positive preservation |
| `tests/test_kg21_activation_validation.py` (7 tests, new file) | blocking structural errors, non-blocking coverage-aware warnings, real component computation, end-to-end activation rejection |

## Verification

| Suite | Result |
|---|---|
| `pytest tests/test_knowledge_graph*.py tests/test_kg*.py -q` | 196 passed |
| `ruff check` (touched files) | clean |
| `mypy` (touched files) | clean |
| Full `pytest -q` (whole platform-api suite) | **1733 passed, 4 skipped, 10 failed** — 0 new; the same 10 pre-existing/unrelated failures confirmed on every prior batch |

```bash
cd platform-api
pytest -q
ruff check app/services/knowledge_graph_context/graph_primitives.py \
  app/services/knowledge_graph_lifecycle/structural_integrity.py \
  app/services/knowledge_graph_lifecycle/rebuild_execution.py \
  app/services/knowledge_graph_health.py
mypy app/services/knowledge_graph_context/graph_primitives.py \
  app/services/knowledge_graph_lifecycle/structural_integrity.py \
  app/services/knowledge_graph_lifecycle/rebuild_execution.py \
  app/services/knowledge_graph_health.py
```

## Deploy

`platform-api` only, no migration, no `web-ui`/`ai-server` change.

```bash
docker compose build platform-api
docker compose up -d platform-api platform-api-worker
```

## Verify live

- On a project with a KPI whose name is a short common word (e.g. contained inside other
  words like "corporate"/"accurate"), trigger a rebuild and confirm it's no longer
  misclassified as "measured" by unrelated queries.
- On a project with substantial, genuinely disconnected content (several risk/opportunity
  nodes with no relationships to anything), trigger a rebuild and confirm the build fails
  validation rather than silently activating an under-connected graph.
- Confirm a subsequent health check (`POST .../knowledge-graph/health-check`) reports the
  same `disconnected_components` count that the active version's own build recorded.

## Remaining work

Still open: item #20 (P1, reference-document versioning/applicability, deferred to Phase
2 per the review's own order); Section C's remaining items #24–30 (schema registry,
relationship direction validation, duplicate detection, entity resolution, join-quality
evidence, temporal consistency, semantic coverage scoring); Section D (AI grounding,
#31–40); Section E (lifecycle/reliability, #41–46, #48–50).

## Report back

Confirmation the stricter validation behaves correctly live (doesn't reject legitimate
small/new projects, does reject genuinely broken candidates), and whether to continue with
Section D (AI grounding — items #31–33/#39, still P0 and in the Phase 1 priority order) or
Section C's remaining P1 items next.

---

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01M7j8CDCHCdwHpw9FrRhLN5
