# Phase 5/6 LLM Framework end-to-end test plan

Goal: Prove the new Migrations and Conversions control plane is wired correctly in the live deployment, and that the UI exposes the two new tabs with the correct gated behavior.

Known runtime constraint: the AI server peer (`10.200.2.26:8000`) is still on the previous image and does not expose `POST /internal/vector-store/reindex` (returns `404`). A full re-index success therefore cannot be completed from the app host in this session. The plan tests the control plane through the failure boundary and explicitly records this dependency.

## Setup (performed before recording)

- EC2 app host is on `devin/llm-framework-huggingface-offline-deployment` at migration `0073`.
- `.env` has `LLM_EMBEDDING_MIGRATION_ENABLED=true`, `LLM_FP16_CONVERSION_ENABLED=true`, `LLM_FP16_CONVERTER_COMMAND=`.
- A short-lived root-admin JWT is minted inside the `platform-api` container for UI/API access.
- A test GGUF artifact is inserted into `llm_model_artifacts` with `format='gguf'` and `status='verified'` so the re-index endpoint has a valid artifact to reference.

## Test 1: LLM Framework page shows Phase 5/6 flags and tabs

1. Inject the root-admin JWT into `localStorage` (`tablescope.token` and `tablescope.user_meta`) and navigate to `https://app.tablescope.cloud/admin/settings/llm-framework`.
2. **Pass criteria**: the page loads with the heading "LLM Framework" and four tabs: "Inventory", "Catalog", "Migrations", "Conversions".
3. **Pass criteria**: the Status section shows `embedding_migration_enabled: true`, `fp16_conversion_enabled: true`, and `embedding_recall_threshold: 0.95`.

## Test 2: Phase 5 re-index endpoint queues a migration and worker fails at the AI boundary

1. API: `POST /api/llm-framework/artifacts/{test_artifact_id}/reindex` with body `{"tenant_id": 18, "embedding_model": "nomic-embed-text", "embedding_dim": 768}`.
2. **Pass criteria**: HTTP `202` with `migration_id`, `status: "pending"`, and a `job_id`.
3. Verify `GET /api/llm-framework/embedding-migrations` returns the new row.
4. Wait up to 30 seconds and re-query; **pass criteria**: the migration row has `status` `failed` and `detail` containing the AI server failure (e.g., `404`, `Not Found`, or `AI server re-index failed`).
5. UI: click the "Migrations" tab; **pass criteria**: the migration appears in the table with `failed` status and the form shows the fields Artifact ID, Tenant ID, Embedding model, Embedding dim, and a "Start re-index" button.

## Test 3: Phase 6 conversion endpoint queues a conversion and worker fails because no converter command is configured

1. API: `POST /api/llm-framework/catalog/convert` with body `{"repo_url": "https://huggingface.co/org/example-fp16", "quantization": "Q4_K_M"}`.
2. **Pass criteria**: HTTP `202` with `source_artifact_id`, `conversion_id`, `status: "pending"`, and a `job_id`.
3. Verify `GET /api/llm-framework/model-conversions` returns the new row.
4. Wait up to 30 seconds; **pass criteria**: the conversion row has `status` `failed` and `detail` exactly containing "No FP16 converter command configured".
5. UI: click the "Conversions" tab; **pass criteria**: the conversion appears in the table with `failed` status and the form shows Repo URL and Quantization fields with a "Convert" button.

## Test 4: Tenant admin cannot access the LLM Framework

1. Mint a tenant-admin JWT and attempt `GET /api/llm-framework/status`.
2. **Pass criteria**: HTTP `403` with detail containing the authorization failure.
3. Inject the tenant-admin JWT into the browser and navigate to `/admin/settings/llm-framework`.
4. **Pass criteria**: the page shows an error state such as "Unable to load LLM Framework status" and the LLM Framework nav is absent from the sidebar.

## Cleanup

- Delete the test GGUF artifact, migration, and conversion rows from the database.
- Revoke temporary SSH ingress to the EC2 security group.
