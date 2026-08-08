# Devin-ready plan: AI server production infrastructure sizing

**Verified base:** `origin/devin/r-echarts-e2e-validation` @ `5a24de88` — re-verify at implementation time.
**Companion document:** `docs/devin-ai-grounding-pipeline-plan.md` (the retrieval/grounding software work). Deliberately separate per the accepted decision — this document needs your budget sign-off independently and is not a blocker to the grounding pipeline shipping on current infrastructure; the grounding work can be built and validated before any infra cutover happens.

This is a sizing and cost document, not a final procurement decision. It presents options with real current pricing; final sizing should come from load-testing the grounding pipeline (companion document) on current infrastructure first, per the accepted answer to Q16/22.

---

## 1. Current state — verified, not assumed

Every claim below was checked directly against the repo, not taken on faith from the original recommendation.

| Claim | Status | Evidence |
|---|---|---|
| AI server is `g6.xlarge` | **Confirmed** | `terraform/ai-server/variables.tf:16` (`default = "g6.xlarge"`), `terraform/ai-server/user-data-ai.sh.tpl` |
| Running `llama3.1:8b` | **Confirmed** | `ai-server/tablescope-ai-api/app/core/config.py:22`, `user-data-ai.sh.tpl:102` (`ollama pull llama3.1:8b`) |
| Home Intelligence previously flooded Ollama with concurrent requests, later bounded | **Confirmed** | `platform-api/app/config.py:165` (`home_intelligence_max_concurrent_ai_calls_per_project: int = 1`), enforced via `asyncio.Semaphore` in `home_intelligence/orchestrator.py:124-127,230` |
| AI worker limited to `max_jobs = 1` | **Confirmed** | `platform-api/app/tasks/workflows.py:1488`, `WorkerSettings.max_jobs`, with an explicit comment: *"The GPU AI server runs one model at a time; running more than one job concurrently just queues LLM requests and causes avoidable timeouts."* |
| AI timeouts raised to 900 seconds | **Confirmed, but the citation in the source material was wrong** — it's `platform-api/app/services/ai_intelligence_client/transport.py:18` (`httpx.Timeout(900.0, connect=10.0)`), not `config.py` (that file's only 900-adjacent setting is an unrelated MFA SMS window) |

**New finding, not in the original recommendation**: `nomic-embed-text` (the embedding model for all vector search, confirmed in §1 of the companion document) also runs via Ollama **on this same GPU instance**. Embedding generation and LLM inference currently compete for the same single GPU. This matters directly for sizing — the grounding pipeline's proactive retrieval (companion document) will increase embedding-call frequency (every question needs a query embedding, not just document indexing), adding load to an already-saturated single-GPU box. Any sizing decision needs to account for embedding load, not just inference load — it was undercounted in the original recommendation.

**Current instance specs** (`g6.xlarge`): 4 vCPU, 16 GiB system RAM, 1x NVIDIA L4 GPU (24 GB GPU memory). An internal estimate in `docs/ai-implementation-plan.md` puts current cost at ~$216/month — this is meaningfully below the ~$587.50/month a pure on-demand rate implies ($0.8048/hr × 730 hrs, verified via current AWS pricing search), which likely reflects a reserved/savings-plan rate or partial-month utilization assumption in that document rather than on-demand pricing. Worth reconciling which is actually being billed today before comparing against the options below, so the before/after cost comparison is apples-to-apples.

---

## 2. Why current sizing is insufficient for production (confirmed reasoning, not just repeating the recommendation)

- Single GPU, single concurrent job (`max_jobs=1`) — this was a deliberate, necessary mitigation for the *current* single-instance reality, not a design goal. It directly caps system throughput at whatever one 8B model on one L4 can serve, serialized.
- The grounding pipeline (companion document) adds retrieval-time embedding calls on the same GPU, increasing per-question GPU work even before considering a larger model.
- 16 GiB system RAM and 4 vCPUs is tight for concurrent retrieval (hybrid search merging, reranking) running alongside inference on the same box, even before considering document-processing background load.

---

## 3. Sizing options — costed, per accepted Q25 (present a range, don't pre-commit)

All prices are **on-demand, us-east-1**, verified via current search (not the original recommendation's numbers, which weren't sourced) — reserved instance / savings-plan pricing typically runs 30-50% below on-demand for 1-3 year commitments and should be evaluated once a target instance type is chosen, but isn't quoted here since it depends on commitment term decisions outside this document's scope.

| Option | Instance | Specs | On-demand cost | Notes |
|---|---|---|---|---|
| **Current (baseline)** | 1x `g6.xlarge` | 4 vCPU / 16 GiB / 1x L4 (24 GB) | ~$0.80/hr ≈ $587/mo | Confirmed insufficient per §2 |
| **Minimal upgrade** | 1x `g6e.xlarge` | 4 vCPU / 32 GiB / 1x L40S (48 GB) | Meaningfully more than current but roughly half of the 4xlarge option below | More GPU memory than current (headroom for a larger model or concurrent embedding+inference), but same vCPU/RAM class as today — **likely still insufficient** for the concurrent retrieval+synthesis+background-indexing workload the companion document's pipeline adds; listed for completeness of the range, not as a real recommendation |
| **Recommended starting point** | 2x `g6e.4xlarge` (replicas) | 16 vCPU / 128 GiB / 1x L40S (44.7 GB GPU mem) each | $3.0042/hr per replica ≈ $2,193/mo per replica, **≈ $4,386/mo for 2 replicas** | Matches the original recommendation's target spec; 2 replicas for the availability requirement (release gate: "at least two inference replicas across failure domains") |
| **Reduced-cost variant** | 1x `g6e.4xlarge` | Same as above, single replica | ≈ $2,193/mo | No redundancy — only consider if budget is the binding constraint and you're willing to accept single-instance risk during initial production rollout, upgrading to 2 replicas once usage/revenue justifies it |

**L40S vs. L4**: 48 GB GPU memory (44.7 GB usable, per AWS's own spec) vs. 24 GB on the current L4 — materially more headroom for a larger model (14B-32B, per the original recommendation) plus concurrent embedding load, without the two competing for the same constrained 24 GB.

---

## 4. Serving stack (per accepted Q18 — vLLM is a separate, sequenced migration)

Continue serving via Ollama on whatever instance is chosen for the initial production cutover — do not bundle a serving-stack migration with a hardware migration. Evaluate vLLM (continuous batching, queue metrics, tensor/pipeline/data-parallel scaling) as its own follow-on plan, sequenced **after** the grounding pipeline is proven functionally correct and the new hardware is stable in production. Bundling both changes at once makes it impossible to isolate which change caused a given regression if something goes wrong.

## 5. Model choice (per accepted Q23)

If moving to a 14B-32B model, budget for re-validating the **entire** existing prompt suite against it — SQL generation accuracy, chart-type selection, insight narrative quality, conversation-turn classification — not just the new retrieval-synthesis prompts this and the companion plan introduce. A model swap changes behavior system-wide. Select the model via grounded-answer evaluation against the companion document's §6.1 eval set, not reputation, per the original recommendation's own stated principle.

Keep the embedding model (`nomic-embed-text`) unchanged in this phase — don't change the LLM and the embedding model simultaneously; if evaluation later shows embedding quality is a retrieval bottleneck, that's a separate, isolated change to evaluate on its own.

## 6. Supporting infrastructure (from the original recommendation, largely unchanged, re-stated for completeness)

- Embeddings/reranking: keep as a separate service or worker pool so it doesn't contend with answer generation on the same request path — this is now a harder requirement than originally stated, given §1's finding that embedding and inference already share one GPU today.
- Retrieval: dedicated Qdrant capacity (already in use, per companion document §1) plus the new Postgres lexical/FTS capacity (companion document §2.2.2) — confirm current Qdrant instance sizing is adequate for the added proactive-retrieval query volume, since it will now be queried on every question instead of only on fallback.
- Metadata/lineage: PostgreSQL (already the system of record).
- Cache/queue: dedicated Redis with tenant/project/KG-version-aware keys.
- Document processing: separate CPU worker pool (8-16 vCPU / 64 GiB RAM) — only if current ingestion is confirmed to actually be capacity-constrained (per the companion document's accepted Q4/Q20, this is flagged as unconfirmed, not assumed).

---

## 7. Sequencing (per accepted Q16/22)

1. Build and validate the grounding pipeline (companion document) on **current** infrastructure first.
2. Load-test the validated pipeline against realistic concurrency (multiple tenants, multiple concurrent conversational turns) to get real latency/throughput numbers.
3. Use those numbers, not the estimates in this document, to make the final call between the sizing options in §3.
4. Cut over production traffic only after the new instance(s) pass the same release gates (companion document §6.3) that the pipeline was validated against on current hardware — a hardware change should not be allowed to silently regress grounding quality or latency.

## 8. Test plan

1. Load test: representative concurrent-tenant traffic against current `g6.xlarge`, establishing a real baseline (P95 latency, throughput ceiling, GPU utilization) before any hardware decision is finalized.
2. Repeat the same load test against a `g6e.4xlarge` staging instance once provisioned, before committing to the 2-replica production cutover.
3. Confirm `max_jobs`/concurrency-semaphore settings are re-tuned for the new hardware's actual capacity — the current `max_jobs=1`/`home_intelligence_max_concurrent_ai_calls_per_project=1` values were specifically calibrated for a single-GPU, single-model reality and should not be assumed to still be correct on different hardware without re-validating.
4. Confirm the companion document's release gates (retrieval accuracy, citation validity, latency) still pass on the new infrastructure, not just that the new instance boots and responds.
