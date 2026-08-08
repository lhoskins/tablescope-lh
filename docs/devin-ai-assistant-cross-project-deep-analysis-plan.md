# TableScope Devin-Ready Implementation Plan

## AI Assistant: Cross-Project Routing and Deep-Analysis Grounding

**Status:** Ready for implementation
**Recommended branch:** `devin/ai-assistant-cross-project-deep-analysis`
**Base branch:** `devin/mobile-responsive-voice-input`. Confirmed by direct comparison: this branch is 22 commits ahead of `devin/r-echarts-e2e-validation` with 0 commits behind and a clean common ancestor at `5a24de88` — it is a strict superset containing the just-implemented shared `AskAnythingComposer` (all three AI surfaces now render through one composer component), mobile-responsive fixes, and voice input. Branching from it means this work starts from the composer consolidation already in place instead of redoing it.
**Deployment method:** Pull request, automated validation, staging deployment, production deployment behind a feature flag.

---

## 0. The problem, confirmed against the running code

**Report:** Asking "Why is material cost increasing?" in AI Assistant with the "IT" project selected returns an analysis built entirely from `it_assets`/`it_incidents` — a materially wrong answer, not a wrong-but-defensible one. The user's own diagnosis is that Insight Cards' deeper analysis isn't reachable from the AI Ask pipeline, that requiring a project selection is the wrong model, and that the system should search across projects, run real queries/analytics to get there, and do it fast.

That diagnosis is correct on every point, and each part traces to a specific, narrow place in the code:

**0.1 — AI Assistant is hard-locked to one project, by design, today.** `web-ui/components/tablescope/project/ai-assistant-screen.tsx` renders the literal text "Cross-project disabled" (line 112) and a context-rail row `Cross-project: off` (line 213). `askProjectAi()` (`web-ui/lib/ui/use-project-data.ts:672`) takes a mandatory `projectId` and posts to `/api/ai/ask`. There is no code path today by which a question can be answered from more than one project's data in a single AI Assistant turn.

**0.2 — The ask pipeline is a single-shot NL→SQL→execute path, not the diagnostic engine.** `platform-api/app/routes/ai_proxy_ask_and_run.py::_generate_sql_for_question()` builds `allowed_tables` from exactly one query:
```python
ds_stmt = select(FileSourceMeta).where(
    FileSourceMeta.project_id == project_id,
    FileSourceMeta.tenant_id == context.tenant_id,
    FileSourceMeta.archived.is_(False),
)
```
then hands those table names, plus a single-project `_kg_context()` call (`ai_proxy_shared.py:193`, also takes one `project_id`), to one `ai.generate_sql()` LLM call, which produces one SQL statement that gets executed once. For "IT" selected, the LLM sees only IT's tables — it has no way to know Finance or Procurement even exist, so it does the only thing it can: forces a plausible-looking query out of incidents and assets. This is not a prompting bug; it is a structural scoping limit, and no amount of prompt tuning fixes it.

**0.3 — The deep, verified diagnostic pipeline already exists, was built this cycle, and Ask Anything never calls it.** `platform-api/app/services/home_intelligence/` (`orchestrator.py`, `diagnostic_orchestration.py::_run_diagnostic()`/`_card_diagnostic_insights()`, `method_driven_insights.py`, `cross_reference.py`, `claim_verification.py`) is the multi-query, method-driven, cross-referenced, causal-claim-verified engine that powers Insight Cards — the same engine this session's earlier work hardened (real R-anomaly markers, cross-references against other data sources, verified causal claims). It runs per project. Nothing in `ai_proxy_ask_and_run.py` calls into it. The user's instinct — "the Insight Cards results is not in the AI Ask pipeline" — is exactly the gap.

**0.4 — Every layer underneath already supports crossing project boundaries; only the application-level filters don't.** This is the important finding, because it means the fix is not "build cross-project federation" — that already exists — it's "stop artificially narrowing to one project, and add a fast routing step so the LLM isn't drowned in irrelevant tables":
- **Teiid/VDB:** `platform-api/app/models/user_vdb.py` — `UserVDB` is one row **per user per tenant** (`user_id` is `unique=True`), not per project. A user's Teiid connection already spans every project's views in the tenant; `allowed_tables` is an application-level allowlist passed to the LLM, not a database-level partition.
- **Vector store:** `ai-server/tablescope-ai-api/app/services/vector_store.py` — Qdrant collections are named `tablescope_tenant_{tenant_id}` (one per **tenant**, not per project); `project_id` is applied only as an optional `FieldCondition` payload filter at search time. Tenant-wide semantic search already works today; it's simply never called without the filter.
- **Precomputed insights:** `platform-api/app/models/business_insight_result.py` — `BusinessInsightResult` carries both `tenant_id` and `project_id` as plain columns on one table. Every insight card ever generated for a tenant is one `WHERE tenant_id = :t` query away, across all its projects.
- **A working precedent for "don't require a project pick" already ships:** `platform-api/app/routes/home_intelligence_suggestions.py` (`/home/query-suggestions`, `/home/dashboard-suggestions`) already treats `project_id` as *optional* — when it's omitted, the route iterates every project the caller can access and runs `work(project)` per project. AI Assistant is the odd one out, not the norm.

**0.5 — The performance constraint is real and already documented from this session's earlier AI-infra work, and it cuts against a naive fix.** The AI server is a single `g6.xlarge` (1× L4 GPU) serving both `llama3.1:8b` generation and `nomic-embed-text` embeddings through the same Ollama process, with `max_jobs: ClassVar[int] = 1` on the arq worker (`platform-api/app/tasks/workflows.py:1488`) and `home_intelligence_max_concurrent_ai_calls_per_project = 1` (`platform-api/app/config.py:165`) specifically because the GPU can't run concurrent AI calls today. A design that fans the full diagnostic pipeline out across every project on every question would make things much slower, not faster, and would collide directly with those existing limits. **The routing step has to be cheap** — an embedding lookup and a DB query, not an LLM call — so that the expensive, LLM-driven work only ever runs against the two or three projects that are actually likely to have the answer.

None of this requires new infrastructure. It requires: (1) a cheap, tenant-wide relevance-ranking step that runs before any project is committed to, (2) wiring that ranking into the existing `_ask_and_run_core` path instead of the mandatory single `project_id`, (3) an on-demand, time-bounded way to invoke the existing diagnostic engine from a chat turn instead of only from the background refresh job, and (4) a response shape that can carry more than one project's answer when more than one is genuinely relevant.

---

## 1. Objective

Make AI Assistant (and the same underlying `_ask_and_run_core` path used by Business Insights' and Project Insights' ask boxes, now that all three run through the shared `AskAnythingComposer`) answer questions without requiring the user to pick a project first, by:

1. Ranking which of the tenant's projects are actually relevant to the question, using the cheap, already-tenant-wide retrieval mechanisms that exist today (vector search, precomputed insights).
2. Reusing the existing verified diagnostic engine — not a new one — when a question calls for real analysis rather than a lookup, invoked on demand and time-bounded so it never blocks the chat response indefinitely.
3. Returning more than one attributed answer when more than one project is genuinely relevant, instead of forcing a single answer out of whichever project happened to be selected.
4. Keeping the whole thing fast by making the cheap ranking step the gate that decides how much expensive work happens, not an afterthought.

The existing project-scoped behavior is not being removed — a project selector remains available as an optional narrowing filter for the (still valid) case where a user wants to pin a question to one project. It stops being mandatory.

---

## 2. Non-negotiable requirements

- No project selection is required to ask a question in AI Assistant. The composer's existing "ask" affordance keeps working unchanged when a user does pick one (that becomes an explicit narrowing hint, not the only signal).
- Tenant, role, and data-plane authorization boundaries are unaffected — "cross-project" means across the projects the *asking user* already has access to within their own tenant, never across tenants and never into projects the user isn't a member of. `ProjectMember`-based access filtering (the same filter `_build_query_summary()` in `ai_proxy_ask.py` already applies) gates the candidate project set before ranking, not after.
- The routing step must be materially cheaper than a full diagnostic run — no new LLM call for ranking on the hot path; reuse the existing embedding infrastructure and precomputed insight rows.
- When a question needs real analysis (a "why is X changing" / driver / trend question, not a lookup), the system must run the same verified diagnostic engine Insight Cards use — not a shallower one-shot SQL guess dressed up to look like analysis.
- The system must be able to return multiple, clearly attributed answers when multiple projects are relevant, and a single answer (today's behavior, unchanged in shape) when only one is.
- If no project has a confident answer, say so honestly (or ask a narrowing question) rather than confidently answering from an irrelevant project — this is the literal failure mode in the reported bug, and it must become structurally impossible, not just less likely.
- Response latency for the common case (routing finds a strong single-project match, existing single-shot SQL path answers it) must not regress from today's single-project latency. Latency for the "no strong precomputed match, deep analysis needed" case is allowed to be higher, but must be bounded and must give the user visible progress rather than a silent long wait.

---

## 3. Architecture: a three-stage pipeline

### 3.1 Stage 1 — Fast, cheap project routing (replaces the mandatory `project_id`)

New service, e.g. `platform-api/app/services/ai_question_router.py`:

1. Resolve the caller's accessible projects the same way `_build_query_summary()` already does (owned + active-member projects), scoped to `context.tenant_id`.
2. Embed the question once (reuse the existing `nomic-embed-text` embedding call already used for indexing — do not add a second embedding model).
3. Run a **tenant-wide** Qdrant search (`ai-server/tablescope-ai-api/app/services/vector_store.py`, omitting the `project_id` payload filter — this is a filter removal, not new capability) against the tenant's collection, and separately query `BusinessInsightResult`/`HomePin` rows across the tenant (`WHERE tenant_id = :t`, no `project_id` filter) for a keyword/semantic match against existing card titles/summaries/KPI tags.
4. Combine both signals into a per-project relevance score. A project with no matching vectors and no matching precomputed insight scores near zero — this is what keeps "IT" out of contention for a material-cost question, deterministically, not by hoping the LLM declines to answer from the wrong table.
5. Keep the explicit project selection (when the user did pick one, or when a Business Insight / Project Insight ask box is scoped by its surface) as a hard override or a strong prior — never discard an explicit signal in favor of the inferred one.
6. Cap the candidate set (e.g., top 3 projects above a minimum relevance floor) before Stage 2 runs. This cap is the performance guardrail: it bounds how many times the expensive Stage 2 work can run per question, independent of how many projects the tenant has.

This stage does no LLM inference — it's an embedding call (already paid for on every indexed document today) plus two indexed DB queries. It should run in well under a second.

### 3.2 Stage 2 — Per-candidate-project answering, bounded and reusing existing engines

For each project surviving Stage 1's cap (run concurrently, bounded by the existing `home_intelligence_max_concurrent_ai_calls_per_project`-style semaphore so this doesn't multiply load past what the single-GPU AI server can take):

1. **Check for a reusable precomputed answer first.** If Stage 1 already surfaced a `BusinessInsightResult`/`HomePin` card whose evidence directly answers the question (high relevance score, same metric/entity), return it — with its existing evidence fingerprint and confidence evaluation (`insight_evidence_fingerprint`/`insight_confidence` packages, already built this session) — without running any new query. This is the fastest possible path and is literally "the Insight Cards results in the AI Ask pipeline" the user asked for.
2. **Classify the question's complexity** before deciding which engine to use. A simple lookup ("how many open incidents") stays on today's single-shot `_generate_sql_for_question()`/`_ask_and_run_core()` path — don't make simple questions slower. A driver/causal/trend question ("why is X increasing", "what's driving Y") routes to the diagnostic engine. Reuse the existing intent-classification precedent in `platform-api/app/services/conversational_analytics/intent_classification.py` as the pattern to extend (a small closed-vocabulary/regex-plus-LLM-fallback classifier), rather than inventing a new classification approach.
3. **Invoke the diagnostic engine on demand, time-bounded.** `home_intelligence/diagnostic_orchestration.py::_run_diagnostic()`/`_card_diagnostic_insights()` and `method_driven_insights.py` are today only reached from the background refresh job (`app/tasks/workflows.py`, arq, `max_jobs=1`). Add a synchronous entry point that runs the same diagnostic step(s) with a hard wall-clock budget (a few seconds, configurable) scoped to the one candidate project and the one question's shape. If the budget is exceeded, fall back to the single-shot SQL path for that project rather than blocking the chat turn — never let one project's slow analysis stall the whole response. If a question's own pattern makes it clear deep analysis is required but won't fit the budget, degrade to an interim "analyzing…" chat turn and complete it asynchronously via the existing conversation/turn machinery (the same mechanism Insight Cards already use for background work), rather than forcing a rushed, low-confidence answer.

### 3.3 Stage 3 — Aggregate and present

1. **One confident project** → respond exactly as today (same envelope shape; no frontend change needed for this case).
2. **Multiple confident projects** → return a small ordered list of attributed answers (e.g., `{ project: "Finance", answer: ..., envelope: ... }`, `{ project: "Procurement", ... }`), rendered in the composer with a per-answer project label, reusing the existing `ResponsePresenter`/`ResultChart`/`ResultTable` components per answer rather than building new rendering.
3. **No confident project** → say so plainly ("I didn't find cost data clearly tied to a specific project — did you mean Finance, or should I look tenant-wide?") instead of forcing an answer from the nearest-scoring irrelevant project. This is the one behavior change that directly closes the reported bug even before any deep-analysis work lands.

---

## 4. Implementation workstreams

### Phase 0 — Baseline and inventory

1. Confirm `devin/mobile-responsive-voice-input` is still the correct base and fetch its current SHA.
2. Re-verify this plan's file/line citations against that SHA (`ai-assistant-screen.tsx`, `ai_proxy_ask_and_run.py`, `ai_proxy_shared.py`, `home_intelligence/*`, `user_vdb.py`, `vector_store.py`, `business_insight_result.py`, `home_intelligence_suggestions.py`) — this plan verified them against `5a24de88`/the mobile-voice branch tip; re-check for drift if work starts later.
3. Confirm today's `/api/ai/ask` and `_ask_and_run_core` test coverage (`platform-api/tests/test_ai_ask_and_run.py`) as the regression baseline — no existing single-project behavior should change shape, only gain a "was this project chosen for me or by me" path.

### Phase 1 — Stage 1 routing service (no behavior change yet)

1. Build `ai_question_router.py`: accessible-project resolution, tenant-wide vector search call (filter removal on the existing search function), tenant-wide precomputed-insight lookup, combined scoring, capped candidate list.
2. Add tests: a tenant with projects across unrelated domains (mirroring the reported IT-vs-material-cost case) must rank the domain-relevant project(s) above the irrelevant one for a domain-specific question, and must respect `ProjectMember` access boundaries (a project the user can't access must never appear as a candidate, regardless of relevance score).
3. Ship behind a flag, called but not yet wired into the response — verify ranking quality and latency in isolation first.

### Phase 2 — Wire routing into `_ask_and_run_core`, single-answer case only

1. Make `project_id` optional on `/api/ai/ask`; when absent, call the Stage 1 router and take its top candidate as today's single `project_id` would have been. Explicit `project_id` (still supported) always wins.
2. Update `ai-assistant-screen.tsx` to stop requiring a project pick and remove/replace the "Cross-project disabled" copy (`web-ui/components/tablescope/project/ai-assistant-screen.tsx:112,213`) with the routed project's name, so the user can see which project answered.
3. Add the "no confident project" honest-decline response from Stage 3.3 — this alone fixes the reported bug's specific failure mode.
4. Regression-test that Business Insights' and Project Insights' ask boxes (already surface-scoped, not going through the new router) are unaffected — routing is additive to the AI-Assistant-without-a-picked-project case only in this phase.

**Exit criterion:** A material-cost question with no project selected reaches the correct project (or says it can't find one) instead of silently answering from an irrelevant one. Single-shot SQL answering, unchanged otherwise.

### Phase 3 — Precomputed-insight reuse (Stage 2, step 1)

1. Wire the tenant-wide `BusinessInsightResult`/`HomePin` match found in Stage 1 into an actual short-circuit answer path, carrying the existing evidence fingerprint/confidence evaluation through to the chat response.
2. Test: a question that closely matches an existing insight card returns that card's grounded answer without a new SQL generation call (verify via call-count assertions, not just correctness).

### Phase 4 — On-demand diagnostic engine invocation (Stage 2, steps 2-3)

1. Add the question-complexity classifier (extends the pattern in `conversational_analytics/intent_classification.py`).
2. Add the time-bounded synchronous entry point into `diagnostic_orchestration.py`'s existing functions, scoped to one project/one question shape.
3. Add the budget-exceeded fallback to single-shot SQL, and the interim-message-plus-async-completion path for cases that need it, reusing the existing conversation/turn infrastructure.
4. Load-test against the documented AI-server constraints (`max_jobs=1`, single GPU) to confirm the Stage 1 cap actually keeps this from regressing existing insight-refresh or dashboard-generation latency; tune the candidate-project cap and per-project time budget based on real numbers, not assumptions.

### Phase 5 — Multi-answer aggregation and presentation

1. Extend the response envelope to optionally carry multiple attributed answers (additive/backward-compatible — the single-answer shape is unchanged when there's one).
2. Update the shared `AskAnythingComposer` to render multiple attributed answers when present.
3. E2E test: a tenant with two projects that both have genuinely relevant data to one question gets both, clearly labeled.

### Phase 6 — Rollout

1. Ship Phase 1-2 (routing + honest decline) first behind a feature flag, since it's the highest-value, lowest-risk fix for the reported bug on its own.
2. Enable for an internal test tenant, verify against real multi-project data (including a deliberately-adversarial case shaped like the report: an IT-heavy project plus a Finance/Procurement project, asking a cost question).
3. Roll out Phases 3-5 incrementally behind the same flag once each phase's exit criteria pass, given each is independently useful.

---

## 5. Test requirements

- Router unit tests: relevance ranking correctness (including the IT-vs-cost adversarial case above), access-boundary enforcement, latency budget (assert the routing call makes no LLM request).
- `_ask_and_run_core` tests: explicit `project_id` still overrides routing; omitted `project_id` routes correctly; no-confident-project path returns the honest-decline response, not a forced answer.
- Diagnostic on-demand invocation tests: time budget is enforced and falls back correctly; concurrency respects the existing per-project AI-call semaphore.
- Multi-answer tests: envelope shape is backward compatible for the single-answer case; multi-answer case renders correctly attributed per project.
- Regression: existing `platform-api/tests/test_ai_ask_and_run.py` and `test_conversational_analytics.py` suites continue to pass unmodified for all previously-covered single-project cases.
- Load test: routing + capped Stage 2 fan-out under concurrent chat traffic does not exceed the AI server's documented single-GPU capacity; record actual p50/p95 latency for (a) precomputed-match, (b) single-shot SQL, (c) on-demand diagnostic cases.

---

## 6. Devin implementation instructions

1. Base branch is `devin/mobile-responsive-voice-input` (confirmed above) — fetch and confirm the SHA in the PR description before starting.
2. Reuse, don't reimplement: the existing embedding call used for indexing, the existing `ProjectMember` access-filtering pattern from `ai_proxy_ask.py::_build_query_summary()`, the existing `insight_evidence_fingerprint`/`insight_confidence` packages, the existing `conversational_analytics/intent_classification.py` pattern, and the existing `home_intelligence/diagnostic_orchestration.py` functions — this plan is about wiring existing engines together with a new cheap routing gate, not building parallel analysis logic.
3. Ship Phase 1-2 first and independently — it is the direct fix for the reported bug and has no dependency on the later phases.
4. Every phase must include before/after evidence against the exact reported scenario (a cost question with no project selected, in a tenant that has both IT-only and cost-relevant projects) in the PR description, not just passing unit tests.
5. Do not regress today's single-project, explicitly-scoped latency — the routing step must be measured and shown to be cheap, not assumed to be.
6. Do not deploy to production until Phase 6's staging verification against the adversarial multi-project case passes.
