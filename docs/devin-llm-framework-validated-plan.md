# LLM Framework — validated & enhanced implementation plan

Supersedes `Tablescope_Devin_Plan_LLM_Framework_Hugging_Face_Offline_Deployment.md`.
Read this document instead of the original. Where a section is not mentioned
here, the original stands.

**Branch:** `devin/llm-framework-huggingface-offline-deployment`
**Base:** `origin/devin/r-echarts-e2e-validation` (verified deployed lineage)

The submitted plan is architecturally sound — the isolation model, the
separation of artifact / installation / routing / activation, the two-person
approval, and the refusal to pretend a browser button crosses an air gap are all
correct and should be kept. What follows are the places where it does not match
this repository, plus the gaps that would have surfaced mid-build.

---

## 0. Validation findings

Every claim below was checked against the repository at the base SHA. Facts the
original plan asked Devin to "confirm before coding" are answered here.

### 0.1 Correction — the Settings workspace is real, but §4 puts the item in the wrong section

The plan's §4 paths all exist on the deployed lineage and are correct:

```
web-ui/app/admin/settings/layout.tsx                            ✅
web-ui/components/tablescope/settings/settings-workspace.tsx    ✅
web-ui/components/tablescope/settings/settings-nav.tsx          ✅
```

`useSettingsNavItems()` builds sections **Workspace / Knowledge / Security /
Integrations / Intelligence / Platform Administration**, and every item carries
its own `visible: () => boolean`. Two distinct gates already exist:

```ts
const isAdmin =
  user?.isSuperAdmin ||
  ["admin", "tenant_admin", "root_admin"].includes(user?.rawRole ?? "");
const isPlatformAdmin =
  user?.isSuperAdmin || user?.rawRole === "root_admin";
```

**Here is the trap.** §4 says to add LLM Framework to the **Intelligence**
section "near Analytical Methods and AI Governance". Both of those neighbours are
declared `visible: () => isAdmin` — and `isAdmin` **includes `tenant_admin`**.
Following the neighbouring pattern therefore shows LLM Framework to tenant
admins, which directly violates the plan's own §8 matrix ("See LLM Framework
navigation — Tenant admin: No") and acceptance criterion ("Tenant admins cannot
access its UI or APIs").

**Put LLM Framework in `Platform Administration` with
`visible: () => isPlatformAdmin`**, alongside Tenants and Users. That section
exists precisely for platform-scoped infrastructure, which is what §8 argues
model deployment is. The gate the plan asks for in §20
(`user.isSuperAdmin || user.rawRole === "root_admin"`) is already implemented as
`isPlatformAdmin` — reuse it rather than re-deriving it.

Route: `web-ui/app/admin/settings/llm-framework/page.tsx`, matching the existing
`/admin/settings/<slug>` convention (`analytical-methods`, `ai-governance`,
`platform/tenants` are all siblings under `app/admin/settings/`).

### 0.2 Blocking — the runtime is Ollama, and the mockups show a path that does not exist

The plan asks Devin to confirm the production runtime. It is **Ollama**, with
**Qdrant** for vectors, defined in a *separate* stack at `ai-server/docker-compose.yml`:

```yaml
tablescope-ai-api:  # FastAPI
  environment: [OLLAMA_URL=http://ollama:11434, QDRANT_URL=http://qdrant:6333]
ollama:
  image: ollama/ollama:latest
  runtime: nvidia
  volumes: [/mnt/tablescope-ai/ollama:/root/.ollama]
  environment: [OLLAMA_NUM_PARALLEL=4, OLLAMA_MAX_LOADED_MODELS=3, OLLAMA_KEEP_ALIVE=30m]
```

`ai-server/tablescope-ai-api/requirements.txt` contains **no** `transformers`,
`torch`, `vllm`, or `llama-cpp-python` — the API is a client of Ollama, not a
model host itself. So:

- The Phase 1 adapter is the **Ollama adapter**. Do not build vLLM/TGI adapters.
- **Ollama loads GGUF.** It does not load Hugging Face FP16 safetensors directly.

**This breaks the approved mockups.** Screen 1 stages
`Meta-Llama-3.1-8B-Instruct` at **16.2 GB, FP16, safetensors**. Screen 2 installs
the same model at **Q4_K_M, 8.2 GB**. A convert-and-quantize step happened
between those two screens that the plan never specifies, and it is not a small
one: it means running llama.cpp's conversion toolchain over downloaded weights.

**Recommendation — Phase 1 restricts the catalog to pre-quantized GGUF
repositories** (e.g. `*-GGUF` publishers). No conversion, no extra toolchain, no
new attack surface, and the artifact you verify is byte-identical to the artifact
you install — which is the whole point of the manifest. Update the mockup copy so
the staged artifact and the installed artifact are the same thing.

If FP16→GGUF conversion is genuinely required, it is **its own phase** with its
own threat model: pinned converter version, sandboxed execution, no network, and
a second manifest generated *after* conversion, because the post-conversion bytes
are what actually reach the runtime and nothing has hashed them yet.

### 0.3 Blocking — `AuditEvent` cannot store platform-scoped events

§17 says to use existing audit infrastructure "if it supports platform-scoped
events." It does not:

```python
# platform-api/app/models/audit_event.py
tenant_id: Mapped[int] = mapped_column(
    ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
)
```

`tenant_id` is **NOT NULL with a cascading FK**. An LLM deployment is not owned by
a tenant, and back-dooring one in would make platform audit rows vanish when that
tenant is deleted. **Create the dedicated `llm_audit_events` table.** Treat the
conditional in §17 as resolved.

### 0.4 Blocking — `require_role(Role.ROOT_ADMIN)` will not work for platform endpoints

`platform-api/app/auth/rbac.py` defines the ladder
(`viewer < member/editor < db_admin < admin < tenant_admin < root_admin`), but
`require_role` "verifies membership (active, tenant-scoped) first via
`require_membership`, which also pins the effective role from the DB."

A platform-scoped endpoint guarded with `require_role(Role.ROOT_ADMIN)` therefore
still demands a tenant context, and the role is read from *tenant membership* —
which is the wrong authority for a platform infrastructure change.

`User.is_super_admin` exists (`platform-api/app/models/user.py:42`) and is the
right signal. **Add a new dependency**, e.g. `require_platform_admin()`, that
authorises on `is_super_admin` (or a global `root_admin`) **without** requiring
tenant membership, and use it on every `/api/llm-framework/*` route. This does
not exist yet and is a prerequisite for §19.

### 0.5 Resolved — migration head

The plan says "do not guess the next migration number." The answer:

- 70 migrations, **exactly one head: `0069_project_actions_workspace.py`**
  (revision `0069`).
- Convention is zero-padded sequential. **The next revision is `0070`.**

Two cautions, both learned the hard way while validating this:

- **Confirm the head on the branch you actually base on.** The head differs
  between the deployed lineage and sibling feature branches. Re-run the check
  after checking out your base, not before.
- **Do not count heads by grepping `down_revision`.** Merge revisions declare it
  as a *tuple*, and a naive string-literal scan misses those and reports phantom
  extra heads. Use `alembic heads`.

### 0.6 Confirmed — everything else the plan assumes

| Plan assumption | Status |
|---|---|
| `platform-api/app/routes/ai_proxy.py` is the AI path | ✅ exists |
| arq worker, `app.tasks.workflows.WorkerSettings` | ✅ exists; `functions: ClassVar[list]` is where new tasks register |
| `TABLESCOPE_AI_ENABLED` / `_API_URL` / `_SIGNING_SECRET` | ✅ all three in `docker-compose.yml` |
| Signed app→AI requests | ✅ `ai_intelligence_client._sign_payload(...)` with timestamp |
| `/opt/tablescope` available to API **and** worker | ✅ both mount it — the vault path fits |
| Redis + durable DB state | ✅ |
| No `ai-server` service in root compose | ✅ correct — it is a **separate stack/host**, which supports the isolation story |

---

## 1. Corrections and enhancements to the plan

### 1.1 §9.2 Runtime adapters — make Ollama concrete

Keep the `LLMRuntimeAdapter` protocol. Implement **only** `OllamaAdapter` in
Phase 1, with these specifics:

- **Install** = write the GGUF into the model directory, then `ollama create
  <name> -f Modelfile` where the Modelfile is `FROM /models/<artifact>/model.gguf`
  plus pinned parameters. Generate the Modelfile from validated fields — never
  from free text in the model card.
- **`ollama pull` must be blocked outright.** It reaches the internet, which
  violates the core invariant. The adapter should fail closed if the runtime is
  configured in a way that permits it.
- **Rollback is cheap here and the config already supports it.**
  `OLLAMA_MAX_LOADED_MODELS=3` means the previous model can stay resident while
  the new one is validated — that is exactly the rollback retention §16.4 wants.
  Reserve one of the three slots for the rollback candidate and say so in the
  preflight capacity check.
- **Activation has no drain API.** Ollama does not expose "finish in-flight then
  swap." §16.3 step 3 ("drain or safely complete in-flight requests") must be
  implemented at the *platform* layer — stop routing new requests to the old
  model, wait for outstanding ones to complete or time out, then switch. Do not
  claim runtime-level draining.
- `OLLAMA_KEEP_ALIVE=30m` means an unloaded model may linger; health checks must
  assert the *active* model answers, not merely that Ollama is up.

### 1.2 §9.1 Capabilities — `embedding` needs an owner

The capability list includes `embedding`, and the AI server runs Qdrant. Before
implementing, confirm **what currently produces embeddings** — Ollama, the AI
API, or something else. If embeddings come from a different path, `embedding`
must not be in the Phase 1 routing profile, or activation will appear to succeed
while changing nothing.

### 1.3 §11 Model Vault — the disk math is missing

The plan sets `LLM_MODEL_VAULT_MAX_BYTES` but never states the transient
worst case. At peak a single deployment holds **three copies**:

1. the download temp directory,
2. the verified artifact in `artifacts/`,
3. the copy landed on the AI server.

Plus the retained rollback model on the AI server. For an 8B Q4 GGUF (~5 GB)
that is modest; for a 70B it is not. **Add an explicit preflight assertion** that
free space on *both* sides exceeds `artifact_size × 2 + reserve` (app server) and
`artifact_size + retained_rollback_size + reserve` (AI server). §13 lists free
disk as an input but never states the inequality — state it.

`/opt/tablescope` is already mounted into both `platform-api` and
`platform-api-worker`, so `LLM_MODEL_VAULT_PATH=/opt/tablescope/model-vault`
works with no compose change. Note that the **worker** is what downloads, so the
vault must be writable there — it is.

### 1.4 §19 API contract — add the two missing endpoints

```text
GET  /api/llm-framework/capabilities        # what routing profiles may assign
POST /api/llm-framework/artifacts/{id}/quarantine-release
```

The first is needed because the frontend cannot hard-code the capability list
without drifting from the backend. The second is the documented escape hatch for
§23's "quarantine artifact" row — as written, a quarantined artifact has no
lifecycle end other than deletion, and an operator who resolves a false positive
has no path forward.

### 1.5 §15 State machine — one missing terminal state

The status list has no state for "activated, stabilization window still running."
`active` is reached at step 7 of §16.3, but automatic rollback may still fire
during the window. Add:

```text
stabilizing        # active, but inside the auto-rollback window
```

Without it, a deployment that auto-rolls-back looks like it went
`active → rolling_back` with no record that it was never *confirmed* active, and
the audit trail cannot distinguish "ran fine for a week then was replaced" from
"failed its stabilization window."

### 1.6 §16.2 Canary suite — one check cannot work as written

> "No network egress attempt."

A canary cannot prove a negative from inside the runtime. What it *can* do is
assert the AI server's egress is blocked at the network layer — which is §25's
network test, run from infrastructure, not a canary prompt. **Move this item out
of the canary suite** into the network-isolation test set, and keep it as a
deployment *precondition* rather than a per-model check.

### 1.7 §21 Feature flags — add the compose wiring step

The four flags are correct. Note that **`docker-compose.yml` only forwards
variables it explicitly names** — a flag set in `.env` alone is silently ignored,
which looks exactly like the feature not working. Every flag must be added to the
`&platform_api_env` anchor, which the worker inherits via `*platform_api_env`.

### 1.8 §8 Permissions — the matrix is right, the enforcement point is not

Keep the matrix. But "Until granular permissions exist, require `root_admin` or
`isSuperAdmin` at the API and UI layers" needs §0.4's new dependency to exist
first. Sequence it as the first backend task in Phase 1, with its own tests, so
every later endpoint inherits a guard that is already proven.

### 1.9 Threat-model gap: the manifest signing key

§11 says to sign the manifest "with a deployment-signing key that is separate
from the user-facing AI request signing secret" — correct. But the plan never
says **where the AI-server side gets the public key**, and that is the crux: if
the agent fetches the verification key from the app server at deploy time, an
attacker who controls the app server controls both the manifest and the key that
validates it, and the signature proves nothing.

**Require the agent to hold the trusted public key out of band** — baked into its
configuration/image at provisioning time, rotated by a deliberate infrastructure
action, never delivered alongside the artifact. Add this to §14's configuration
block and to the documented rotation procedure in §31.

---

## 2. Devin handoff — answers already established

These were listed in §33 as things Devin must determine. They are settled:

| Question | Answer |
|---|---|
| Base branch | `origin/devin/r-echarts-e2e-validation` |
| Migration head | `0069_project_actions_workspace`; next revision **`0070`** |
| Production AI runtime | **Ollama** (`ollama/ollama:latest`, nvidia runtime) + Qdrant |
| Model storage | `/mnt/tablescope-ai/ollama` on the AI host |
| Model-loading mechanism | Ollama Modelfile import (`ollama create`); `pull` is prohibited |
| Selected adapter | `OllamaAdapter`, GGUF only, Phase 1 |
| AI stack location | separate `ai-server/docker-compose.yml`, not the root compose |
| Vault path | `/opt/tablescope/model-vault` (already mounted, API + worker) |
| Audit table | new `llm_audit_events`; existing `audit_events` is tenant-scoped NOT NULL |
| Settings shell | exists; add to **Platform Administration**, gate `isPlatformAdmin` (§0.1) |
| Frontend route | `web-ui/app/admin/settings/llm-framework/page.tsx` |
| Platform auth guard | does **not** exist — build `require_platform_admin()` first (§0.4) |

Still genuinely open, and requiring a human decision:

1. **Network interpretation** — private mTLS channel vs absolute air gap. The
   plan handles both; infrastructure has to say which.
2. **Where the deployment agent runs** — a new service in
   `ai-server/docker-compose.yml`, on the same host as Ollama, with only
   `/mnt/tablescope-ai/ollama` writable.
3. **Embedding capability owner** (§1.2).
4. **GGUF-only vs conversion pipeline** (§0.2) — this changes scope materially,
   and it is the one that decides whether the approved mockups are buildable
   as drawn.

---

## 3. Revised phase 1

Phase 1 in the original plan is sound but should absorb the corrections:

1. `require_platform_admin()` dependency + tests (§0.4) — **first**, everything
   else depends on it.
2. Migration `0070`: `llm_model_artifacts`, `llm_artifact_files`,
   `llm_runtime_targets`, `llm_installations`, `llm_routing_profiles`,
   `llm_deployments`, `llm_deployment_attempts`, `llm_audit_events`. Additive
   only.
3. Feature flags in `config.py` **and** the compose env anchor (§1.7).
4. Read-only inventory: targets, installations, active routing, provenance.
5. Frontend: nav item in **Platform Administration** (`isPlatformAdmin`) plus
   `web-ui/app/admin/settings/llm-framework/page.tsx` (§0.1).
6. No Hugging Face calls, no downloads, no activation.

Acceptance for Phase 1: a super admin sees the module with real runtime-target
inventory read from the database; a tenant admin gets `403` from every endpoint
and no navigation entry; `alembic upgrade head` is clean from `0069`.

---

## 4. What to keep unchanged

To be explicit, because these are the parts most likely to be "simplified" and
they are all correct:

- Hugging Face is reachable **only** from the app-server worker.
- The artifact is frozen to an **immutable commit SHA** before approval.
- `trust_remote_code` stays off; no repository code is executed, ever.
- Verification failure **quarantines**; it never degrades to a warning.
- Installing an additional model does not touch routing.
- The requester cannot approve their own production replacement.
- Canaries use synthetic data only.
- Redis is never the sole record of a deployment.
- The agent is not a remote shell and takes no arbitrary paths or commands.
- Rollback retention is mandatory before a replace.
