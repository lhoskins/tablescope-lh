# Devin: merge + deploy — Knowledge Graph validation, Phase 5 (Section D: items #31, #33, #39)

**Repository:** `lhoskins/tablescope-lh`
**Branch to merge:** `kg-validation-phase5-grounding`
**Base:** `UX-design-03` (already includes Phases 1–4)

**`platform-api/` only · no migration · all tests green**

---

## Context

Fifth installment of the 50-item Knowledge Graph validation review. This batch covers
Section D's remaining P0 items: **#31** (confidence/evidence separation), **#33**
(evidence-required inference — validated, already largely correct), and **#39** (surface
degraded grounding). **#32** (confidence calibration) is deliberately not attempted this
batch — see below.

## 31. Separate compatibility, evidence strength, and confidence

**Validated:** true. `knowledge_graph_ai.py`'s AI-generated insight cards carried a single
opaque `confidence` number taken straight from the model's self-reported value, with no
independent signal for how much real evidence backs the claim.

**Fix:** added a deterministic `evidenceStrength` (0–1), computed **only** from the card's
own grounded evidence — never from the LLM — combining: how many evidence items converge
(more is stronger), whether any of them is real project data vs. Reference-Library
guidance only (project data is stronger), and the structural confidence already recorded
on the deterministic edges connecting that evidence to the center. The card's overall
`confidence` is now `min(modelConfidence, evidenceStrength)` — the raw model score is kept
as its own field (`modelConfidence`) but can no longer single-handedly make a
thinly-evidenced claim look authoritative. Added `reviewerConfidence: None` — schema-ready
for a future human-review workflow, deliberately left unpopulated rather than
fabricated, since no such workflow exists yet. Added `valid: true` for forward
compatibility (always true at this point, since ungrounded cards are already rejected
earlier in the pipeline — see #33).

## 32. Calibrate confidence instead of trusting raw model values

**Deliberately not attempted.** Real statistical calibration (comparing stated confidence
against actual outcome accuracy, reporting precision/recall by threshold) requires a
labeled dataset of confirmed-correct vs. confirmed-incorrect Knowledge Graph findings —
none exists in this codebase or environment, and fabricating one would produce a
calibration that's worse than none at all (false precision). Item #31's confidence/evidence
separation is the structural prerequisite a real calibration effort would need regardless;
this batch builds that foundation without pretending to calibrate against data that
doesn't exist. A future effort with real production outcome data (e.g. which cards users
acted on, dismissed, or flagged as wrong) could implement this properly.

## 33. Require evidence for every inferred node, edge, card, gap, risk, recommendation

**Validated:** already substantially correct for the one AI-inferred object type this
pipeline actually produces (insight cards) — `_resolve_evidence_keys`/`_map_card` already
reject any card whose evidence doesn't resolve to a real graph node (`if not evidence_keys:
return None`), and gaps/recommended actions in this pipeline are built entirely
deterministically from real graph structure (never LLM-fabricated), so they're
evidence-grounded by construction, not by a separate gate. No code change was needed here
— the review couldn't confirm this without reading the code, so tests were added to prove
it rather than leaving it as an unverified assumption.

**Tests:** existing `test_map_card_rejects_fabricated_evidence` already covered the
rejection gate; no new production code needed for this item specifically (see #31's tests
for the evidence-strength grounding).

## 39. Surface degraded KG grounding instead of failing open silently

**Validated:** true. `collect_knowledge_graph_ai_context` — the single choke point behind
Business Insights, Project Insights, and dashboard/query generation (see Phase 2's audit
log work) — returned the identical empty shape whether a project legitimately had no
Knowledge Graph content yet, or loading the graph outright failed. Every caller proceeded
identically either way, with the "fail-open by design" comment stating this as intentional.

**Fix:** the returned block now always carries `grounding_status`: `"ok"` for both a real
result and a legitimately-empty project, `"unavailable"` only when graph loading itself
failed — plus a distinct `logger.warning(...)` (not the previous ambiguous swallow) naming
which surface degraded. Wired into all 3 real call sites:
- `home_intelligence/orchestrator.py` (Business Insights) — logs distinctly.
- `project_insight_service` (Project Insights) — logs distinctly **and** sets a new
  `kgGroundingDegraded: bool` field on `ProjectInsightResponse` (that schema already has
  `graphStatus`/`graphBlockingReasons`/`graphDisclosure` for the KG's *lifecycle* state —
  this closes the one gap: whether *this specific report's* context collection succeeded).
- `ai_proxy_shared.py::_kg_context` (dashboard/query generation, 7 route call sites) —
  logs distinctly.

**Deliberately not done:** threading this into a user-facing UI surface for Business
Insights or dashboard/query generation — those don't have an equivalent typed response
field to extend without deeper restructuring, and doing so would require a `web-ui` change,
out of scope for this backend-only batch (consistent with every prior batch in this
review). Logging is the honest, correctly-scoped fix for those two; Project Insight gets
the real API-visible field since it already had the natural home for it.

## Tests added

| File | Coverage |
|---|---|
| `tests/test_knowledge_graph_ai.py` (+3 tests) | modelConfidence/evidenceStrength/reviewerConfidence present and independent; confidence capped by weak evidence even with a near-perfect model score; more converging evidence scores higher than a single item |
| `tests/test_kg39_grounding_status.py` (4 tests, new file) | `grounding_status: "ok"` for both empty-but-healthy and populated results; `"unavailable"` + a distinct log line on a real load failure; proof that the two failure/empty cases are otherwise byte-for-byte identical except for this one field |

All new/modified tests independently verified to fail against pre-fix code.

## Verification

| Suite | Result |
|---|---|
| `pytest tests/test_knowledge_graph*.py tests/test_kg*.py -q` | 192 passed |
| `pytest tests/test_project_insight.py tests/test_project_insight_rebuild.py tests/test_home_intelligence.py tests/test_business_insight_phase1.py tests/test_ai_ask_and_run.py tests/test_ai_proxy_permissions.py tests/test_ai_proxy_shared.py -q` | 134 passed, 3 failed (same pre-existing/unrelated Redis-connection failures as every prior batch) |
| `ruff check` (touched files) | clean |
| `mypy` (touched files) | clean |
| Full `pytest -q` (whole platform-api suite) | **1729 passed, 4 skipped, 10 failed** — 0 new; the same 10 pre-existing/unrelated failures confirmed on every prior batch |

```bash
cd platform-api
pytest -q
ruff check app/services/knowledge_graph_ai.py app/services/knowledge_graph_ai_context.py \
  app/services/home_intelligence/orchestrator.py app/services/project_insight_service/__init__.py \
  app/schemas/project_insight.py app/routes/ai_proxy_shared.py
mypy app/services/knowledge_graph_ai.py app/services/knowledge_graph_ai_context.py \
  app/services/home_intelligence/orchestrator.py app/services/project_insight_service/__init__.py \
  app/schemas/project_insight.py app/routes/ai_proxy_shared.py
```

## Deploy

`platform-api` only, no migration, no `web-ui`/`ai-server` change.

```bash
docker compose build platform-api
docker compose up -d platform-api platform-api-worker
```

## Verify live

- Generate a Knowledge Graph insight card and confirm the API response includes
  `modelConfidence`, `evidenceStrength`, and `reviewerConfidence` alongside `confidence`,
  and that `confidence <= min(modelConfidence, evidenceStrength)`.
- Temporarily break KG context loading (e.g. point at an invalid project id, or simulate a
  DB hiccup) and confirm platform-api logs a `"proceeding WITHOUT Knowledge Graph
  grounding"` warning naming the surface, and that a Project Insight report for that
  project comes back with `kgGroundingDegraded: true`.
- Confirm a project with a genuinely empty (not-yet-built) Knowledge Graph does **not**
  trigger that warning or flag — only real load failures should.

## Remaining work

Still open: Section C's remaining P1 items (#24–30); Section D's remaining P1 items
(#34–38, #40); Section E (lifecycle/reliability — #41–46, #48–50, several P0); item #20
(P1, deferred to Phase 2's own scope). #50 (downstream grounded-answer evaluations) is
best done last, once the rest of the pipeline is stable.

## Report back

Confirmation the confidence fields and degraded-grounding logging behave correctly live,
and whether to continue with Section E (lifecycle/reliability — #41–46, #48–49, several
still P0; #47 already done in Phase 4) or Section C P1 cleanup next. #50 (downstream
grounded-answer evaluations) is best done last, once the rest of the pipeline is stable.

---

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01M7j8CDCHCdwHpw9FrRhLN5
