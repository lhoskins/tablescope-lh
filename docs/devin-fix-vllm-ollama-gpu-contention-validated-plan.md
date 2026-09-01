# vLLM/Ollama GPU contention fix — merge & deploy plan

## 1. What this fixes

`ollama:11434` was going unreachable (connection refused / warm-timeout in
platform-api's VDB warm path) while `vllm` (Glimmer) stayed healthy. Root
cause traced to `ai-server/docker-compose.yml`, not a bad build or a stuck
process:

- `vllm` is started with `--gpu-memory-utilization 0.9` — vLLM pre-allocates
  that fraction of the shared GPU's memory for its own KV cache **at
  startup**, and holds the reservation continuously whether or not it's
  actively serving a request.
- `ollama` shares the same GPU (`runtime: nvidia` on both services; the
  `ollama` service's own comment says *"Allow Ollama to share the GPU with
  vLLM"*) with `OLLAMA_MAX_LOADED_MODELS=3` and `OLLAMA_KEEP_ALIVE=30m` — it
  expects to keep multiple models resident.
- With vLLM claiming ~90% up front, Ollama is left fighting over the
  remaining ~10%. If it can't fit its models in that headroom it can fail to
  load, hang, or crash — which reads externally as "unreachable on
  :11434," matching what was observed.
- Compounding it: the `ollama` service had **no `healthcheck:`** (unlike
  `qdrant`, which has one). `depends_on: condition: service_started` only
  confirms the container process started, never that Ollama is actually
  serving, so nothing here would auto-recover it if it wedged.

This is a config/resource-allocation issue, not something restarting Teiid
would touch or fix — Teiid is a separate JVM process with no GPU/Ollama
dependency. (See the sibling `fix-sql-repair-glued-keywords` branch, which
covers the actual Teiid-facing SQL-generation defect from the same incident
report; this branch is purely about the AI stack's GPU allocation.)

## 2. What changed

`ai-server/docker-compose.yml`, two changes, both scoped to this file:

1. `vllm` service: `--gpu-memory-utilization` `"0.9"` → `"0.75"`, leaving
   real headroom for Ollama's models on the shared GPU instead of vLLM
   claiming the GPU almost whole.
2. `ollama` service: added a `healthcheck:` block, same shape as the
   existing `qdrant` one — probes `localhost:11434` via `/dev/tcp`, so
   Docker's health state (and `restart: unless-stopped`) can actually detect
   and recover a wedged Ollama instead of the container just sitting there
   "started" but unresponsive.

No other services, code, or config touched.

```diff
   ollama:
     ...
     volumes:
       - /mnt/tablescope-ai/ollama:/root/.ollama
+    healthcheck:
+      test: ["CMD-SHELL", "bash -c \"echo > /dev/tcp/localhost/11434\""]
+      interval: 10s
+      timeout: 5s
+      retries: 5
+      start_period: 15s
     restart: unless-stopped
   ...
   vllm:
     ...
       - --max-model-len
       - "12288"
       - --gpu-memory-utilization
-      - "0.9"
+      - "0.75"
```

## 3. Verification performed

- `python3 -c "import yaml; yaml.safe_load(open('ai-server/docker-compose.yml'))"` —
  parses cleanly.
- Manual read-through of the resulting compose file against the `qdrant`
  healthcheck pattern already in use, for consistency.
- No code changes, so no test suite applies here. This is an infra
  config change — the real verification is on the live host (§5).

## 4. Deploy

This is `ai-server` only — platform-api is untouched, no atomic
cross-service coordination needed (unlike the sibling
`rename-ollama-url-to-llm-target-url` branch).

```bash
cd ai-server
docker compose up -d ollama vllm
```

`docker compose up -d` recreates only the services whose config actually
changed (`ollama`, `vllm`) — it will not touch `tablescope-ai-api`,
`ai-worker`, or `qdrant`. Recreating `vllm` means a brief reload of Glimmer
into GPU memory (expect it to be unavailable for generation for the
duration of that reload, typically under a minute for a W4A16-quantized
model); `ollama` recreation is fast since it's not GPU-loading a model at
container-start time.

**Yes, a reload is required** for this to take effect — `--gpu-memory-utilization`
is a vLLM startup flag, and Docker health-checks are read at container
creation, so both `ollama` and `vllm` need to be recreated (not just
restarted in place if that skips re-reading `docker-compose.yml` — use
`docker compose up -d`, not `docker compose restart`, to guarantee the new
config is picked up).

### Rollback

```bash
cd ai-server
git checkout HEAD~1 -- docker-compose.yml   # or revert this specific commit
docker compose up -d ollama vllm
```

## 5. Verify live

After `docker compose up -d ollama vllm`:

- `docker compose ps` — both `ollama` and `vllm` should show `healthy`
  (ollama now has a health state to check; previously it only ever showed
  "running").
- `curl http://localhost:11434/api/tags` from the ai-server host (or from
  inside `tablescope-ai-api`'s container: `curl http://ollama:11434/api/tags`) —
  should return a model list, not a connection error.
- `nvidia-smi` on the host — confirm vLLM's reserved memory dropped and
  Ollama's process now shows resident memory instead of failing to
  allocate.
- Re-run the original failing query ("What is the backup failure rate?")
  end-to-end once both this branch and `fix-sql-repair-glued-keywords` are
  deployed — RAG grounding (which needs Ollama's embeddings) and SQL
  generation (Glimmer/vLLM) should both complete without the earlier
  warm-timeout/"connection closed" errors.

## 6. Report back

Once deployed, please confirm:
- `docker compose ps` shows `ollama` as `healthy`.
- The backup-failure-rate query (or any query exercising RAG grounding)
  completes without an Ollama-unreachable error.
- If GPU memory is still tight at 0.75 for vLLM (e.g. vLLM itself fails to
  start, or throws an out-of-memory error), report the exact error — the
  ratio may need further tuning based on actual GPU capacity, which isn't
  visible from the repo alone.
