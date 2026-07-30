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

### 1.2 §9.1 Capabilities — `embedding` is NOT routable like the others

Resolved, and it changes the design. Embeddings **are** served by Ollama, so they
look routable — but they are not:

```python
# ai-server/tablescope-ai-api/app/core/config.py
embedding_model: str = "nomic-embed-text"

# ai-server/tablescope-ai-api/app/services/llm_client.py
await client.post(f"{settings.ollama_url}/api/embeddings",
                  json={"model": settings.embedding_model, "prompt": text})

# ai-server/tablescope-ai-api/app/services/vector_store.py
EMBEDDING_DIM = 768  # nomic-embed-text dimension
client.create_collection(..., vectors_config=VectorParams(size=EMBEDDING_DIM, ...))
```

**The vector dimension is hard-coded and baked into every Qdrant collection at
creation time.** Swapping the embedding model changes the dimension (or, worse,
keeps 768 while changing the vector *space*), and every stored vector in every
per-tenant collection becomes meaningless. A same-dimension swap is the dangerous
case: Qdrant keeps accepting queries and retrieval quietly degrades to noise,
with no error to alert anyone.

So an embedding change is **not an atomic routing flip** — it is a re-index
migration:

1. create a new collection at the new dimension, alongside the old;
2. re-embed every document with the new model;
3. verify recall against a fixed query set on both collections;
4. cut over reads;
5. retain the old collection for rollback;
6. drop it only after a retention window.

**Phase 4 must exclude `embedding` from the routing profile.** Keep
`general_reasoning`, `sql_generation`, `insight_interpretation`,
`dashboard_planning`. Give embedding its own phase (§3.5) or leave it on the
environment variable. Offering an "Activate" button that silently corrupts
retrieval is worse than not offering it.

Add to the acceptance criteria: *the routing profile cannot assign a model to
`embedding`, and the API rejects an attempt with a message explaining why.*

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

### Open decisions — with defaults so work is not blocked

Devin should **proceed on the defaults below** and flag them in the PR
description. Each is reversible within its phase; none blocks Phase 1 or 2.

| Decision | Default to build against | Who can override |
|---|---|---|
| Network interpretation | **Private mTLS channel** (the plan's own primary recommendation). Build the offline bundle path as a documented, *unused* fallback. | Infrastructure/security |
| Deployment agent location | New service in `ai-server/docker-compose.yml`, same host as Ollama, only `/mnt/tablescope-ai/ollama` writable, no published port | Infrastructure |
| Embedding capability | **Excluded from routing** — see §1.2, it is a re-index migration, not a flip | Product, after §3.5 |
| Catalog scope | **Pre-quantized GGUF only** (§0.2) | Product — this one materially changes scope and the mockups |

Only the last needs a real answer before Phase 2 ships, because it decides
whether the approved catalog screen is buildable as drawn.

---

## 3. Delivery phases

### 3.1 Phase 1 — foundation, RBAC, read-only inventory

Every phase must be deployable with all later flags off. Phase 1 in the original
plan is sound but should absorb the corrections:

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

### 3.2 Phase 2 — Hugging Face catalog and Model Vault

Flags: `LLM_FRAMEWORK_ENABLED=true`, `LLM_FRAMEWORK_HF_CATALOG_ENABLED=true`,
deployment and routing still off.

1. `catalog_client.py` — server-side Hugging Face search, worker-only. Bounded
   timeouts, backoff, cancellation, rate-limit handling. **Egress allowlist with
   redirect validation**; never accept a download URL from the browser.
2. `approval_policy.py` — the configurable allowlist from §10.4. Default it to
   **GGUF formats only** (§0.2). The policy decides approval; the LLM never does.
3. License capture and `llm_license_approvals` rows. Ambiguous or missing license
   metadata ⇒ **Review required**, staging blocked.
4. `model_vault.py` — download to a per-job temp dir, per-artifact Redis lock plus
   the DB uniqueness constraint, traversal/symlink/quota defences, atomic move
   into `artifacts/`, quarantine on failure.
5. `scanner.py` + `manifest.py` — per-file SHA-256, malware scan, GGUF structural
   validation, strict-limit JSON parsing, canonical signed manifest.
6. `POST /artifacts/stage` returns `202` with a durable id; arq task registered in
   `WorkerSettings.functions`.
7. UI: catalog tab, detail panel, stage dialog, job progress that survives reload.

**Exit criteria.** A pre-quantized GGUF model can be searched, license-recorded,
staged, scanned, hashed and signed; a tampered file quarantines; a tenant admin
gets `403` from every endpoint; nothing has touched the AI server.

**The disk assertion from §1.3 belongs here**, at stage time — not at transfer
time, which is too late to fail gracefully.

### 3.3 Phase 3 — the deployment agent and transfer

Flag: `LLM_FRAMEWORK_DEPLOYMENT_ENABLED=true`. Models install **inactive**.

1. Deployment agent service on the AI host. mTLS, short-lived job authorization,
   writes only under `LLM_MODEL_INSTALL_PATH`, read-only root filesystem
   elsewhere. **Not a remote shell**: no arbitrary commands, no arbitrary paths.
2. **The agent holds the manifest-verification public key out of band** (§1.9).
   It must not accept a key delivered with the artifact.
3. `POST /targets/{id}/preflight` — the §13 attestation, plus the free-space
   inequality on *both* sides (§1.3) and the reserved rollback slot (§1.1).
4. Chunked transfer with resume; the agent **recalculates every hash** and
   verifies the manifest signature before anything is installed.
5. `OllamaAdapter.install()` — write the GGUF, generate the Modelfile from
   validated fields only, `ollama create`. **`ollama pull` fails closed.**
6. Signed receipt returned and verified by platform-api; `llm_installations` row.

**Exit criteria.** A staged artifact installs on the AI server, appears in
Installed as inactive, and **live traffic is provably unchanged** — same model
answering, same routing version. Network tests from §25 pass: the AI server
cannot resolve Hugging Face, the browser cannot reach the agent.

### 3.4 Phase 4 — routing, canary, activation, rollback

Flag: `LLM_FRAMEWORK_DYNAMIC_ROUTING_ENABLED=true`, **last**.

1. `llm_routing_profiles` with optimistic concurrency; `PUT /routing` requires
   `expected_version` and returns `409` on stale writes.
2. Capabilities: `general_reasoning`, `sql_generation`, `insight_interpretation`,
   `dashboard_planning`. **`embedding` is rejected** (§1.2).
3. Two-person approval for replacing an active production model; approval binds
   to artifact + target + capabilities + options and invalidates on any change.
4. Canary suite on synthetic data only. **Drop "no network egress attempt"** —
   that is a network test, not a canary (§1.6).
5. Activation per §16.3, with platform-level draining (Ollama has no drain API,
   §1.1): stop routing new requests to the old model, let outstanding ones finish
   or time out, then switch.
6. `stabilizing` state (§1.5) + automatic rollback inside the window.
7. Routing version in signed AI requests; Redis cache invalidated on activation;
   the environment-variable model remains the fallback during rollout.

**Exit criteria.** The §26 manual validation runs end to end on one non-critical
capability, including a deliberate canary failure that leaves the current model
active, and a rollback that restores it.

### 3.5 Phase 5 (conditional) — embedding model changes

Only if product wants embedding models managed here. This is a **re-index
migration**, not an activation (§1.2): dual collections, re-embed, recall
comparison against a fixed query set, cut over, retain, then drop. `EMBEDDING_DIM`
must become a per-collection property rather than a module constant before any of
this is possible.

### 3.6 Phase 6 (conditional) — FP16 → GGUF conversion

Only if the catalog must offer non-GGUF repositories (§0.2). Pinned converter
version, sandboxed with no network, and **a second manifest generated after
conversion** — the post-conversion bytes are what reach the runtime, and nothing
has hashed them yet. Do not fold this into Phase 2; it has its own threat model.

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

---

## 5. Phase 1 review (commit `39d69a5`)

Phase 1 is in good shape and picked up the validation findings:

| Finding | Status |
|---|---|
| §0.1 nav in Platform Administration, `isPlatformAdmin` | ✅ correct — the tenant-admin trap avoided |
| §0.4 `require_platform_admin` bypassing tenant membership | ✅ built, and documents why |
| §0.5 migration `0070`, `down_revision = "0069"` | ✅ correct chain |
| §0.3 dedicated `llm_audit_events` | ✅ one of 8 tables created |
| §0.2 GGUF-only default | ✅ `LLM_MODEL_CATALOG_GGUF_ONLY=true` |
| §1.4 `GET /capabilities`, `POST /quarantine-release` | ✅ both present |
| §1.7 flags in the compose env anchor | ✅ worker inherits them |

Two things to fix before Phase 4. Neither blocks Phase 2 or 3.

### 5.1 `embed` is offered as a routable capability — remove it

```python
# platform-api/app/services/llm_framework.py
CAPABILITIES = ["generate", "chat", "embed", "summarize", "classify", "code"]
```

`embed` must not be routable (§1.2). `EMBEDDING_DIM = 768` is a module constant
baked into every per-tenant Qdrant collection at creation; swapping the embedding
model invalidates every stored vector, and the same-dimension case is the
dangerous one — Qdrant keeps answering and retrieval quietly degrades to noise
with nothing raising an error.

Also note `llm_routing_profiles.capability` is an unconstrained `String(64)` with
no `CheckConstraint` or enum, so nothing at the database level stops it either.

Do:
1. Remove `"embed"` from `CAPABILITIES`, or return it flagged
   `{"routable": false, "reason": "..."}` so the UI can explain the absence.
2. Add a `CheckConstraint` on `capability` to the routable set — cheap now, and
   it makes the invariant survive a future caller that forgets.
3. Reject an `embed` assignment at the API with the reason, per §1.2's
   acceptance criterion.

### 5.2 Any service API key currently gets full platform admin

```python
async def require_platform_admin(...):
    if context.is_service:
        return context      # ← unconditional
```

Reasonable for worker-driven jobs, but §8 states the service identity must be
**"No"** for *Approve production replacement*. If Phase 4's approve endpoint
reuses this guard, a service key satisfies it — and two-person approval collapses
to whoever holds the key, which is exactly the control the plan exists to
enforce.

Do: keep `require_platform_admin` for read and worker paths, and add a separate
`require_human_platform_admin` (no service bypass) for **approve, activate,
rollback and delete**. Add a test asserting a service identity receives `403`
from the approve endpoint.

### 5.3 Capability vocabulary diverges from the plan

Phase 1 ships `generate / chat / embed / summarize / classify / code`; the plan
(§9.1) specifies `general_reasoning / sql_generation / insight_interpretation /
dashboard_planning`. The plan's names map to how TableScope actually routes work,
which is what a routing profile has to address. Reconcile now, while nothing
depends on the strings — after Phase 4 this becomes a data migration.
