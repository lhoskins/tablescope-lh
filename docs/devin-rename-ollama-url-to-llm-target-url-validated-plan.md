# Devin: merge + deploy — rename the `ollama_url` wire field to `llm_target_url`

**Repository:** `lhoskins/tablescope-lh`
**Branch to merge:** `rename-ollama-url-to-llm-target-url`
**Base:** `release/deploy-2026-08-07`

**1 commit · 25 files across `platform-api/` AND `ai-server/` · no migration · pure identifier rename, no behavior change · all tests green**

---

## 1. Read this before merging: cross-service deploy ordering

This rename touches the JSON field platform-api sends to ai-server on every LLM call (`ollama_url` → `llm_target_url`). **`platform-api` and `ai-server` must be rebuilt and redeployed together, not staggered.** If they go out momentarily out of sync:

- New `platform-api` (sends `llm_target_url`) talking to old `ai-server` (only knows `ollama_url`): the field platform-api sends is simply unrecognized by the old Pydantic model, so it's dropped — ai-server falls back to its own default (`settings.ollama_url`, a real Ollama host) instead of the routed target (Glimmer via vLLM). **This silently reintroduces the exact "is it using Ollama?" problem this rename was meant to close** — not an error, just a silent wrong-backend fallback, for as long as the mismatch lasts.
- Old `platform-api` (still sends `ollama_url`) talking to new `ai-server` (only knows `llm_target_url`): same failure mode in reverse.

**This is normally a non-issue** — the standard deploy pattern already used throughout this repo's other Devin docs rebuilds and restarts every changed service in one `docker compose` invocation:

```bash
docker compose build platform-api ai-api   # confirm the ai-server service name in your compose file
docker compose up -d platform-api platform-api-worker ai-api
```

Just don't split this into two separate deploy steps with a gap between them, and don't merge only one side of this branch.

---

## 2. What this is — and isn't

**Is:** a pure identifier rename. platform-api's LLM Framework already resolves SQL generation/repair to Glimmer served over vLLM today (confirmed live in the incident this came out of: `SQL generated ... sources=[...]`). Every parameter, request field, and dataclass attribute carrying that resolved target URL was still named `ollama_url` — a holdover from before dynamic routing existed. That naming, not a routing bug, is what prompted "we agreed to use Glimmer, remove Ollama."

**Isn't:** a change to what backend actually serves anything. No routing logic changed. No config changed. No `runtime_type="ollama"` support was removed from the LLM Framework's admin/deployment system, and Ollama itself was **not** decommissioned.

**Deliberately left as genuinely-Ollama, not renamed:**
- ai-server's `settings.ollama_url` (`OLLAMA_URL` env var) — the fallback default when no per-request override arrives, and the fixed target `generate_embeddings()`/`check_health()` always use. Embedding models are explicitly excluded from the dynamic routing framework (`validate_routing_capability`'s own comment: swapping one would silently invalidate existing Qdrant vectors and needs a separate re-index migration) — so embeddings genuinely still require a working Ollama instance today. **If `ollama:11434` is down, embeddings/RAG grounding are broken right now, independent of this rename and of the SQL-generation fix in the sibling branch** (`fix-sql-repair-glued-keywords`) — that's real and separate; this branch doesn't touch it.
- platform-api's `settings.llm_ollama_url`, `llm_ollama_adapter.py`, and `LLMInstallation.ollama_model_name` (a persisted DB column from migration `0077` — renaming a column is a schema migration, out of scope for an identifier cleanup).

---

## 3. What changed (mechanical, file list)

**platform-api** (3 files): `ActiveRouting.ollama_url` → `llm_target_url` in `app/services/llm_framework.py`; the two call sites that build the outbound request payload, `app/routes/ai_proxy_shared.py` and `app/services/ai_intelligence_client/endpoints.py` (`payload["ollama_url"]` → `payload["llm_target_url"]`).

**ai-server** (22 files): the `ollama_url` field on `AIBaseRequest` (`app/models/schemas/common.py` — the base every routed request inherits), `DocumentProfileRequest`, and `AnalyzeFileRequest` → `llm_target_url`; the `ollama_url` parameter on `generate()`/`generate_sql()`/`repair_sql()` in `app/services/llm_client.py` → `llm_target_url` (its module docstring also updated — it opened with "Ollama LLM client," which was itself part of the confusion); all 17 routers' `ollama_url=req.ollama_url` → `llm_target_url=req.llm_target_url`; the test file exercising `llm_client.py` updated to match.

---

## 4. Verification

| Suite | Result |
|---|---|
| `ai-server` `pytest -q` (full suite) | **156 / 156 passed** |
| `ai-server` `ruff check app tests` | clean on every touched file (5 pre-existing unrelated `F401`s in `app/routers/ai.py`, untouched by this branch) |
| `ai-server` `mypy app` | clean on every touched file (10 pre-existing unrelated errors elsewhere, untouched by this branch) |
| `platform-api` targeted regression (every test file importing `llm_framework`/`ai_intelligence_client`/`ai_proxy_shared`, 14 files) | **245 / 245 passed** (3 skips of the pre-existing, unrelated Redis-connection failures in `test_business_insight_phase1.py` seen in every run this session) |
| `platform-api` `ruff`/`mypy` on touched files | clean |

```bash
cd ai-server/tablescope-ai-api && pytest -q && ruff check app tests && mypy app
cd ../../platform-api && pytest -q && ruff check app tests && mypy app
```

---

## 5. Deploy

No migration. See §1 for the one real requirement: deploy both services together.

```bash
docker compose build platform-api ai-api
docker compose up -d platform-api platform-api-worker ai-api
docker compose ps   # confirm both healthy before considering this done
```

### Rollback
Also atomic, same reasoning as §1:
```bash
git checkout <previous-sha> -- platform-api/app/routes/ai_proxy_shared.py platform-api/app/services/ai_intelligence_client/endpoints.py platform-api/app/services/llm_framework.py ai-server/
docker compose build platform-api ai-api
docker compose up -d platform-api platform-api-worker ai-api
```

---

## 6. Verify live

- Run any SQL-generation query end-to-end (e.g. the same "backup failure rate" query from the incident this came out of, ideally after the sibling `fix-sql-repair-glued-keywords` branch also lands) and confirm the ai-server log line still reads the routed model/target correctly — check the request actually reaching ai-server carries `llm_target_url`, not a `None`/fallback.
- Grep platform-api and ai-server logs for a moment right after deploy for any sign of the fallback-to-Ollama failure mode described in §1 (e.g. SQL-generation calls suddenly hitting `ollama:11434` instead of the vLLM target) — that would mean the two services deployed out of sync.
- Confirm embeddings/grounding status is unchanged from before this deploy (still whatever it was — this branch doesn't touch that path either way).

---

## 7. Report back

`pytest`/`ruff`/`mypy` totals in your own environment for both services; confirmation both services were deployed in the same step; and confirmation (via logs or a live query) that SQL-generation calls are still reaching the routed vLLM/Glimmer target post-deploy, not falling back to Ollama.
