# Devin-ready plan: proactive AI grounding pipeline (evidence manifest, hybrid retrieval, confidence)

**Verified base:** `origin/devin/r-echarts-e2e-validation` @ `5a24de88` — re-verify at implementation time.
**Companion document:** `docs/devin-ai-infra-sizing-plan.md` (production infrastructure sizing/cost) — deliberately separate, per the decision recorded below, since it needs a different approval path (budget) and is not a blocker to this document's work.

This plan is the formal write-up following a 25-question review of the original grounding recommendation. All 25 answers were accepted as given; this document also independently verifies (not just accepts) every factual claim in that recommendation against the actual code, and corrects two that don't hold up.

---

## 0. Validation notes — corrections to the source recommendation

Before specifying the fix, two things in the original recommendation needed checking and turned out to be wrong, plus one important architectural clarification:

1. **"81 governed KPIs" is inaccurate — the real count is 94.** Verified by parsing all 7 industry-pack JSON files directly (`platform-api/app/seed_data/ai_catalogs/*.json`): `tablescope_core` 14, `supply_chain` 9, `manufacturing` 9, `finance` 10, `healthcare` 10, `government` 9, `information_technology` 33 — total 94. "Seven industry packs" is correct.
2. **"Sends at most 15 matching KPIs" — no such cap exists anywhere in the code.** The actual filtering logic (`_col_match_score()` in `platform-api/app/services/upload_ai_profiler_service.py`, and `get_tags_and_kpis_for_ai_prompt()` in `reference_catalog_service.py`) scores KPIs/tags by matching required/example fields against available columns (keep ≥3, else fall back to the full list) — there is no `[:15]`-style truncation anywhere near KPI code. This changes the fix in §3 below: there's no cap to raise or make relevance-ranked, because there isn't a hardcoded cap today. What the existing filter lacks is a proper *rank-and-limit* step after relevance filtering, not a bigger limit.
3. **The Knowledge Graph context used by `_forward_prose_answer` is not query-aware.** `collect_knowledge_graph_ai_context()` (`platform-api/app/services/knowledge_graph_ai_context.py`) loads the project's stored graph, buckets nodes by type, and ranks by node **confidence** only (`_ranked()`, capped at `max_items=20`) — it does not take the user's question as an input at all. Two different users asking two completely different questions about the same project get the identical top-20-by-confidence slice. This is the single most important architectural fact this plan needs to fix — the original recommendation's instinct ("retrieval should be proactive, not fallback-only") is correct, but even once it's called proactively, it still won't be relevant to the specific question unless a query-aware ranking step is added. That's new work, not just a call-site change.

Everything else in the original recommendation checked out: the shared `execute_turn`/`_ask_and_run_core` backbone across all three surfaces (confirmed, PR #157/#158), the fallback-only design of `_forward_prose_answer` (confirmed and now partially fixed), the "extract → summarize → index" Reference Library pipeline (confirmed verbatim in `reference_library_processing.py`'s docstring), and the Knowledge Graph/Reference-Library/Company-Library/industry-KPI capability inventory in the original table.

---

## 1. Current retrieval architecture (traced, this is what exists to build on)

- **Vector search**: `ai-server/tablescope-ai-api/app/services/vector_store.py` wraps Qdrant directly. One collection per tenant (`tablescope_tenant_{tenant_id}`), plus a shared, tier/visibility-filtered `tablescope_reference_library` collection for Reference Library documents (filters enforced server-side: `owner_user_id`, `visibility`, `project_id`). Embedding model is `nomic-embed-text` via Ollama (768-dim), **not** OpenAI/sentence-transformers — meaning embedding generation also runs on the same GPU server as inference (relevant to the infra companion document, §5 there).
- **Document text is already fully embedded, not just summarized into the KG.** Reference Library documents go through extract → `summarize_reference_document()` (AI grounding summary stored on the row) → `index_reference_document()` (full extracted text chunked and embedded into the shared Qdrant collection). The Knowledge Graph only carries structural/summary nodes (`reference_document`/`document` types with a summary field capped at 400 chars) — **full passage text lives in Qdrant, not the KG.** This confirms the original recommendation's design principle ("KG organizes relationships and lineage; it should not substitute for retrieving actual supporting passages") already matches how the data is physically separated — the fix is to actually query both, not to change where anything is stored.
- **Two independent, inconsistent chunking implementations exist** — a real, previously-unnoticed defect this plan should fix while it's in this code: `platform-api/app/services/document_chunking_service.py` (`CHUNK_SIZE=3200` chars / `CHUNK_OVERLAP=500`, sentence/newline-boundary aware, used by the platform-api document pipeline) vs. `ai-server/tablescope-ai-api/app/routers/ai_indexing.py`'s own inline chunker (`chunk_size=512`, separate overlap variable, not shared code). Two documents indexed through different paths get chunked at meaningfully different granularity, which will produce inconsistent retrieval quality once hybrid retrieval depends on chunk boundaries being predictable.
- **Lexical/full-text search does not exist today**, despite two functions whose docstrings say "Full-text search across..." (`search_tags()`/`search_kpis()` in `reference_catalog_service.py`) — the actual implementation is plain Python substring matching over an in-memory list, not Postgres FTS or BM25. Postgres `tsvector`/`ts_rank`/`to_tsquery` has zero hits anywhere in `platform-api/app/`. Per the accepted answer to Q7, build this on Postgres FTS rather than a new search engine — but note it's genuinely new infrastructure, not an extension of an existing pattern as originally assumed.
- **Governed KPI matching already does real relevance filtering** (`_col_match_score()`), just not a proactive-retrieval-aware rank+limit step — see §3.

---

## 2. Proactive hybrid retrieval — architecture

### 2.1 Insertion point (per accepted Q2)

Insert as a new stage inside the existing shared path — `platform-api/app/services/conversational_analytics/__init__.py`'s `execute_turn()` / `_run_analytical_turn()`, and `platform-api/app/routes/ai_proxy_ask_and_run.py`'s `_ask_and_run_core()` — **not** a new parallel endpoint. Both already converge on `_ask_and_run_core`, so one new retrieval stage there reaches all three conversational surfaces (AI Assistant, Business Insight, Project Insight) and the Home/Business Insight card-generation planner, consistent with the shared-backbone finding from the prior plan (PR #157).

New function, e.g. `gather_grounding_evidence(question, *, tenant_id, project_id, source_columns=None) -> GroundingEvidence`, called **before** SQL generation (not gated on its failure), running in parallel with SQL generation where feasible (`asyncio.gather`) so proactive retrieval doesn't add latency on the critical path when SQL generation succeeds quickly.

### 2.2 Retrieval components (per accepted Q6/Q7/Q8)

1. **Vector similarity** — query both the tenant's own Qdrant collection and the shared `tablescope_reference_library` collection (already tier/visibility-filtered) using the question's embedding. Reuses existing `vector_store.py` infrastructure — no new vector infra needed.
2. **Lexical/BM25 via Postgres full-text search** — new. Add a `tsvector` column (generated, indexed with GIN) to the documents/chunks table(s) that back Qdrant indexing, and a `ts_rank`-scored query path. This is genuinely new work per §1's correction, sized accordingly (not a quick reuse).
3. **KG traversal, made query-aware** — extend `collect_knowledge_graph_ai_context()` (or add a new function alongside it that reuses its node-loading/adjacency-building, per §0 item 3) to score nodes against the actual question (e.g., embed the question, score against node title/summary text, or reuse the vector-similarity infrastructure from #1 against a lightweight KG-node-text index) instead of confidence-only ranking. This is the one piece of net-new relevance logic the original recommendation implicitly assumed already existed and doesn't.
4. **Governed KPI matching** — reuse `_col_match_score()`/`get_tags_and_kpis_for_ai_prompt()` as-is for the filtering step (it already works), and add a rank+limit step on top (e.g., top 10-15 by match score) so results are bounded and ordered, addressing the real gap identified in §0 item 2 (there's no cap today, which the original recommendation assumed was a "too small" existing cap — the actual gap is "no ranking/bounding at all," a different fix).
5. **Structured queries / analytical methods** — already reached via the existing SQL-generation path; no change needed here, this retrieval stage runs alongside it, not instead of it.

### 2.3 Reranking (per accepted Q8)

Heuristic reranker first, not a learned cross-encoder: score = weighted combination of (a) raw retrieval score (vector cosine / ts_rank / KG relevance score from 2.2.3), (b) document tier (company > project > industry, matching the existing Reference Library tier concept), (c) recency, (d) KG node confidence where applicable. Reserve context-window budget by evidence class (e.g., cap SQL result rows separately from document passages separately from KG facts) so a large SQL result can't crowd out document evidence, per the original recommendation's requirement.

### 2.4 Fallback ordering (per accepted Q13)

1. Proactive hybrid retrieval (2.1-2.3) — primary path, attempted for every question.
2. `_forward_prose_answer()` (`ai_proxy_ask_and_run.py:752`) — kept as a secondary fallback for anything the proactive stage's SQL-adjacent framing missed; already fixed (PR #157/#158) to trigger on both `generation_error` and `execution_error`, and should also be reachable from the CLARIFICATION dead-end per that same plan.
3. Explicit "insufficient evidence" response — new. Only reached if both of the above produce nothing usable. Must be honest and specific (e.g., "I couldn't find company documents, project references, or data that answers this" rather than a generic error), matching the release-gate requirement that answers degrade explicitly rather than quietly return ungrounded prose.

---

## 3. Model distinction requirement

Per the original recommendation, every synthesized answer must distinguish: observed data, company-defined policy/metric, project-specific context, industry guidance, and AI inference. Implement this as a structured response contract from the LLM (not free-text parsing after the fact) — extend the existing prompt/schema pattern already used for chart-patch classification (`ai-server/tablescope-ai-api/app/routers/ai_conversation.py`'s closed-vocabulary JSON response contract is the precedent to follow) so the model tags each claim/sentence with its evidence class as part of the generation call, rather than trying to classify free text after generation (which is unreliable and adds a second LLM call).

---

## 4. Grounding manifest — extend existing evidence/confidence services, don't build parallel ones (per accepted Q11/Q12)

### 4.1 `EvidenceFingerprint` (`platform-api/app/services/insight_evidence_fingerprint/`)

Current shape confirmed: `fingerprint_version, plan_fingerprint, result_fingerprint, semantic_fingerprint, series_fingerprint` — 100% SQL/data-shape based today, with the one exception that `build_plan_fingerprint()` already hashes `source_documents` (document *names* only, no content/passages/scores). Add:

- A new builder, `build_grounding_fingerprint(evidence: GroundingEvidence) -> str`, hashing: KG version id, KG node ids used, document chunk ids used (not full text — ids, matching the existing name-only precedent), governed KPI ids referenced, retrieval-method mix used. This becomes a 5th field on `EvidenceFingerprint`.
- Extend `build_plan_fingerprint()`'s `source_documents` input to carry chunk-level granularity where available, not just document names, since that's now retrievable.

### 4.2 `evaluate_confidence()` (`platform-api/app/services/insight_confidence/`)

Current shape confirmed: 9 weighted factors summing to 1.0, with document/reference evidence touched only by `corroboration` (weight 0.05, boolean presence of `source_context["referenceDocuments"]`/`uses_reference` — no quality/relevance signal) and `lineage_completeness` (weight 0.10, table/column name presence only). Per the accepted decision (add new factors to the existing evaluator, don't build a parallel gate):

- Upgrade `corroboration` from boolean presence to a real score based on the grounding evidence's retrieval quality (top retrieval score, number of distinct evidence classes present, chunk-level match strength) — same factor code, better-computed value.
- Add two new factors: `grounding_coverage` (does the retrieved evidence actually cover the claims made in the narrative — this is the "narrative consistency" check from the original recommendation) and `source_freshness` (age of the KG version / document index used relative to now, distinct from the existing `recency` factor which checks `executedAt`, a query-execution timestamp, not evidence freshness).
- Rebalance weights so `execution_grounding`'s current dominance (0.20) doesn't let a well-executed-but-ungrounded SQL query still reach "High" purely on data-shape factors — this directly implements the release-gate requirement "High confidence should require valid evidence... not merely that its SQL returned rows." Exact new weights are a tuning decision to validate against the eval set in §6, not something to fix in this document without data.
- `_basis_from_factors`/`_gap_text` (`scoring_helpers.py`) already generate human-readable confidence-reason text — extend their per-factor-code message tables to cover the two new factor codes, following the existing pattern exactly (no new mechanism needed).

### 4.3 Persistence — no migration required for the manifest itself

Confirmed both storage tables (`HomePin.frozen_payload`, `BusinessInsightResult.payload`) store cards as JSONB, not typed columns — new manifest fields (grounding fingerprint, evidence class tags, retrieval scores) can be added to the card dict/schema with **no migration**. `BusinessInsightResult` already has row-level `kg_version_id`/`source_fingerprint` for staleness tracking — the new per-card grounding fingerprint is a finer-grained addition alongside, not a replacement.

Frontend `InsightCard` type (`web-ui/lib/api/home-intelligence/insight-card.ts`) already has adjacent stub fields — `referenceDocuments?: string[]`, `kpiReferences?: string[]`, `evidenceFingerprint?`, `confidenceEvaluation?` — these need to become richer structured objects (e.g. `referenceDocuments: {id, title, chunkIds, retrievalScore}[]` instead of `string[]`) rather than adding new top-level fields for the same concepts.

---

## 5. UI — extend the existing card toolbar/detail view, don't build a new panel (per accepted Q14/Q15/Q16)

Add a "Sources" section to the existing card detail / "Full analysis" view, reached from `insight-card-action-toolbar.tsx` (the same toolbar Export SQL was just added to in the previous plan) — not a new standalone panel. Visible to all users by default; collapse raw retrieval scores/timestamps behind a "show technical details" toggle for non-admins. Render: documents considered + which passages were actually used, KG version + node titles used, tables/SQL used (already surfaced via the existing Export SQL feature — link/reuse, don't duplicate), governed KPI references, industry references, and the confidence-reason text already generated by `_basis_from_factors`/`_gap_text` (§4.2). Cards without a manifest (generated before this ships) render with the Sources section simply absent — no backfill, no fabricated retroactive manifest (per accepted Q16).

---

## 6. Evaluation and release gates

### 6.1 Labeled eval set (per accepted Q17)

Build from `scripts/demo_company/documents.py`'s existing synthetic corpus — confirmed to generate **119 distinct documents** per demo company (16 policies + 61 procedures + 7 executive reviews + 35 business-ops narratives), each with deterministic titles/department tags. Construct ~30-50 question → expected-source-document(s) pairs spanning policy questions, procedure questions, executive-review questions, and cross-department questions, covering all three conversational surfaces.

### 6.2 Test infrastructure to extend (per accepted Q20)

- `platform-api/tests/test_ai_ask_and_run.py` (655 lines, 23 tests) — already has source-matching tests (`test_ask_and_run_clarification_surfaces_matched_sources`, `test_ask_and_run_auto_selects_top_source`, `test_ask_and_run_passes_preferred_sources_to_generator`) as the direct hook to extend for "does this answer cite the reference library" assertions.
- `platform-api/tests/test_conversational_analytics.py` (546 lines, 15 tests) — already has `test_grounded_data_question_rejects_parroted_rewrites`, a grounding-adjacent precedent; extend with the new eval-set questions.

### 6.3 Release gates (from the original recommendation, each mapped to how it gets enforced)

| Gate | Enforcement |
|---|---|
| ≥90% retrieval of expected authoritative sources | Automated, run against the §6.1 eval set in CI |
| ≥95% citation validity | Automated — assert every cited document/KPI/KG-node id in a manifest actually exists and was actually retrieved (not hallucinated post-hoc) |
| Zero cross-tenant/cross-project retrieval | Automated tests (per accepted Q18) — extend the existing per-tenant Qdrant collection isolation tests; one-time manual security review before first production rollout as a supplement |
| Every answer exposes considered vs. used resources | Enforced by construction — §5's Sources panel renders directly from the manifest, not a separate audit |
| Equivalent grounding across all 3 surfaces for the same question | Automated equivalence test (per accepted Q20) extending §6.2's suites, since all 3 surfaces share `_ask_and_run_core` |
| Document/KG/KPI updates invalidate the right caches | Extend existing KG-version/staleness invalidation (`BusinessInsightResult.kg_version_id`/`source_fingerprint`) to also cover the new per-card grounding fingerprint |
| P95 latency targets met under concurrency | Provisional target (per accepted Q19): P95 first-token <3s, complete answer <15s for standard questions — load-test against the infra sizing in the companion document, revise once real numbers exist |
| Background card generation doesn't starve interactive questions | Verify against the existing `home_intelligence_max_concurrent_ai_calls_per_project=1` semaphore and arq `max_jobs=1` — confirm the new retrieval stage's added GPU load (embedding calls, per §1) doesn't regress this bound; may need its own concurrency accounting, flagged for the infra document |
| Explicit "insufficient evidence" degradation | §2.4 step 3 |

Synthetic demo-company data is sufficient for the initial gate; recommend a follow-up spot-check against 1-2 real pilot tenants before general availability (per accepted Q21).

---

## 7. Rollout (per accepted Q1, Q4, Q5, Q10)

1. **Project Insight first** — bounded scope, known document set via project-level Reference Library, easiest to validate against the §6.1 eval set.
2. **Business Insight** second.
3. **AI Assistant** third — broadest surface, ships once the shared retrieval stage is proven on the first two.

Independent, non-blocking: industry-reference reprocessing (the 44 failed/incomplete documents from the original recommendation's import) — flagged as its own parallel workstream, not a prerequisite; the retrieval pipeline should report honest coverage against whatever corpus exists rather than wait for it to be complete. Document-processing throughput/ingestion-capacity work is similarly out of scope unless ingestion is currently actively failing (worth a quick check, not assumed). This plan has no dependency on the LDAP/SSO, Data Source Builder, or conversation-consolidation work from prior plans — safe to build in parallel.

---

## 8. Test plan

1. Unit tests for the new `gather_grounding_evidence()` retrieval stage — mock each of the 4 retrieval components, assert correct merging/reranking/context-budget allocation.
2. Unit tests for the extended `build_grounding_fingerprint()` and the 2 new/1 upgraded confidence factors, following the existing test patterns for `insight_evidence_fingerprint`/`insight_confidence`.
3. Regression tests confirming existing SQL-only flows are unaffected in shape (grounding evidence is additive, not a replacement for the SQL path).
4. The full §6.1 eval set, run in CI, gating merge on the §6.3 thresholds once they're calibrated against a first real run (don't hardcode 90%/95% into CI before establishing what the current pipeline actually scores as a baseline).
5. Cross-tenant isolation tests extending the existing per-tenant Qdrant collection test coverage.
6. Manual, end-to-end, on all three surfaces once Project Insight's phase ships: ask the same question through Business Insight and AI Assistant once each is live, confirm equivalent grounding (release gate 5).
