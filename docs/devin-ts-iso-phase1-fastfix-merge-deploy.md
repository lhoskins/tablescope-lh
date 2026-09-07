# Devin: merge + deploy — TS-ISO Phase 1 fast-fixes (real code, real deploy)

**Repository:** `lhoskins/tablescope-lh`
**Target branch:** `UX-design-03`
**Branch:** `security/ts-iso-phase1-fastfixes`

## This is different from every prior TS-ISO doc in this program — read this first

Every previous `docs/devin-ts-iso-*` document in this repository was about merging a **planning document** — a single Markdown file with zero runtime effect, explicitly "no deploy required." **This one is not that.** This branch contains real application code, nginx configuration, and CI configuration changes across `platform-api`, `ai-server`, and `nginx`. Merging it **does** require a deploy: platform-api and ai-server need to restart on the new code, and nginx needs a config reload.

This is Phase 1 of `docs/security/ts-iso-implementation-roadmap.md` — the five items in that roadmap's Phase 1 table, chosen specifically because each is a single-purpose, independently testable fix with **no** Terraform change, **no** AWS/KMS console work, **no** schema migration, and **no** cross-team coordination. See that roadmap doc for how this phase fits into the full 11-plan program and what comes next.

## What changed and why

| # | Plan | Change | Files |
|---|---|---|---|
| 1 | TS-ISO-020 | Added a fail-closed production startup check for `TABLESCOPE_SECRET_KEY`, mirroring the existing check for `TABLESCOPE_AI_SIGNING_SECRET`. An empty value silently falls back to a key derived from `JWT_SECRET_KEY` (see `config.py`'s own comment) -- fine for dev, must never happen unnoticed in production since this key encrypts data-source passwords at rest. | `platform-api/app/main.py` |
| 2 | TS-ISO-022 | Added `.github/dependabot.yml` covering every real package ecosystem in the repo (github-actions, npm, pip x3 directories, docker x7 directories). Explicitly excludes the `apache-maven-3.9.6/MyProject/` pom.xml files — that's a vendored copy of the Maven distribution itself, not first-party source under active dependency management; noted in a comment in the file for whoever revisits it. | `.github/dependabot.yml` |
| 3 | TS-ISO-011 | Wired the previously dead-code `delete_tenant_collection`/`delete_project_vectors` Qdrant functions into the real tenant/project deletion paths, and fixed their exception handling: a genuine "not found" (404) is a no-op, but any other failure now propagates as `VectorStoreError` instead of being silently swallowed as "already deleted." Added two new HMAC-signed ai-server routes (`/vector-store/delete-tenant-collection`, `/vector-store/delete-project-vectors`, same signing contract as the existing `/vector-store/reindex`) and a platform-api client for them, called best-effort (same pattern as the existing VDB-undeploy step) from `DELETE /tenants/{id}` and `DELETE /projects/{id}`. | `ai-server/.../services/vector_store.py`, `ai-server/.../routers/internal.py`, `platform-api/app/services/ai_intelligence_client/{endpoints,__init__}.py`, `platform-api/app/routes/{tenants_crud,projects_crud}.py`, `platform-api/app/schemas/tenant.py` |
| 4 | TS-ISO-017 | Migrated the first worker job (`run_knowledge_graph_health_check`) off a bare `SessionLocal()` onto the existing-but-previously-unadopted `tenant_session` helper (`app/database.py`), which binds Postgres RLS for the duration of the job -- exactly the "canary job" step the plan's own deployment sequence calls for. `tenant_id` is now threaded through the enqueue call and worker signature (it was previously only implicit via `project_id`). | `platform-api/app/tasks/workflows.py`, `platform-api/app/routes/knowledge_graph.py` |
| 5 | TS-ISO-010 | Closed the live XFF pre-auth-bypass on `/internal/file-proxy`: nginx now overwrites `X-Forwarded-For` with `$remote_addr` instead of appending to whatever the client sent, and the route's own `_client_ip()` no longer reads the header at all -- it uses only the real TCP peer address, since this route isn't proxied through nginx and has no legitimate reverse-proxy hop in front of it. | `nginx/conf.d/app.conf`, `platform-api/app/routes/internal_file_proxy.py` |

### On item 3's behavior change

`TenantDeleteResponse` gained a new field, `qdrant_collection_deleted: bool`. Any caller (UI, script) that deserializes this response with strict/extra-forbid parsing needs to tolerate the new field; nothing else in the response shape changed. `DELETE /projects/{id}`'s response is unchanged (still 204 No Content) -- the new Qdrant call happens before the delete, best-effort, and is not reported back to the caller.

### On item 4's behavior change

`enqueue_run_knowledge_graph_health_check` gained a new required positional parameter (`tenant_id`, before `project_id`) and the `run_knowledge_graph_health_check` arq task's signature changed the same way. This is registered in arq by function name, so no worker-registration config changes are needed -- but if anything outside this repo enqueues this job by name directly (rather than through the Python helper), it needs to pass `tenant_id` as the new first argument.

## Testing performed

All tests run against the actual changed code, not against mocks of the change itself.

| Suite | Command | Result |
|---|---|---|
| New: startup guard | `pytest platform-api/tests/test_main_startup_guards.py` | 3 passed -- production refuses to start with an empty `TABLESCOPE_SECRET_KEY`, starts normally with it set, and dev/test are unaffected. |
| New: Qdrant deletion (ai-server) | `pytest ai-server/tablescope-ai-api/tests/test_vector_store_deletion.py` | 6 passed -- real in-memory-Qdrant deletion, not-found-is-a-no-op, and real-error-propagates for both functions. |
| New: signed deletion routes (ai-server) | `pytest ai-server/tablescope-ai-api/tests/test_internal_vector_deletion_routes.py` | 4 passed -- valid signature deletes, forged signature is rejected with 403, for both new routes. |
| New: deletion client (platform-api) | `pytest platform-api/tests/test_ai_intelligence_client_deletion.py` | 6 passed -- AI-disabled returns `False`, success returns `True`, server error raises `AIUnavailableError`, for both functions. |
| New: TS-ISO-017 canary worker | `pytest platform-api/tests/test_kg_health_check_worker.py` | 2 passed -- the job still commits a real health-check row via `tenant_session`, and still reports (not raises) a failure the same way as before. |
| New: TS-ISO-010 XFF fix | `pytest platform-api/tests/test_internal_file_proxy_client_ip.py` | 4 passed -- reproduces the exact prior bypass (spoofed header matching a trusted CIDR, real peer outside it) and confirms it is now rejected; confirms a legitimate real-peer request is still accepted. |
| Full ai-server suite | `pytest ai-server/tablescope-ai-api` | **173 passed** (pre-existing warnings only, unrelated to this change) |
| Full platform-api suite | `pytest platform-api` | **1938 passed, 12 failed, 4 skipped.** All 12 failures were independently confirmed pre-existing on a clean `origin/UX-design-03` checkout (same 12, same test names, verified by stashing this branch's changes and re-running just those 12 node IDs against the unmodified baseline) -- unrelated to this change (visualization/percent-change/business-insight-snapshot/billing tests, none of which touch the files this phase modifies). Two tests *did* regress on the first full run (`test_cors_and_metrics_hardening.py::test_production_with_explicit_origins_starts`, `test_startup_signing_secret_required.py::test_production_with_secret_starts`) because they construct a "should start successfully" production settings scenario without a `TABLESCOPE_SECRET_KEY` -- both fixed by adding that env var to the two tests, then reconfirmed with a second full run showing exactly the same 12 pre-existing failures and nothing new. |

No regressions from this change in either full suite -- the 12 platform-api failures above are pre-existing repo state, not introduced here. No Java/Maven changes in this phase (TS-ISO-010's remaining workload-identity redesign, which does touch the Teiid connector, is Phase 4 of the roadmap, not this phase).

**Pre-existing platform-api failures (not part of this change, listed for the merge reviewer's awareness):** `test_ai_dashboard_pipeline.py::test_correct_widget_converts_oversized_pie`, `test_ask_pipeline.py::test_matrix_resolves_to_heatmap_not_a_narrowed_bar`, `test_billing.py::test_provision_isolated_data_plane`, `test_billing.py::test_provision_isolated_vpn_awaits_details`, `test_business_insight_phase1.py` (3 snapshot-staleness tests), `test_percent_change_summary.py` (4 tests), `test_visualization_engine.py::test_many_categories_is_horizontal_bar`. Worth a separate cleanup pass outside this security program.

## Merge

```bash
git fetch origin
git checkout -b merge-ts-iso-phase1 origin/UX-design-03
git merge origin/security/ts-iso-phase1-fastfixes
# resolve any conflict by re-reading the two sides -- see "Files touched" above
# push / open PR
```

## Deploy — this phase actually needs one

1. **Merge and build.** Both `platform-api` and `ai-server` images need to be rebuilt from the merged code (no new Python dependencies were added; no `Dockerfile`/`requirements.txt` changes).
2. **No database migration.** No Alembic revision was added -- `TenantDeleteResponse` is a Pydantic response schema, not a DB model change.
3. **Roll out ai-server first, then platform-api.** The new platform-api client (`ai_intelligence_client.delete_tenant_collection`/`delete_project_vectors`) calls the two new ai-server routes; if platform-api is deployed first and calls a route ai-server doesn't have yet, `_post` treats a 404 as an `AIUnavailableError` and the tenant/project deletion route logs a warning and continues (best-effort, does not block deletion) -- so this ordering is a nice-to-have for a clean rollout, not a hard requirement.
4. **Reload nginx** after deploying platform-api, to pick up the `X-Forwarded-For` config change (`nginx -s reload`, or the container's normal restart path -- no downtime expected, this is a single `proxy_set_header` line).
5. **No feature flag, no gradual rollout needed.** All five fixes are unconditional -- there is no environment variable or config toggle to flip after deploy. (TS-ISO-020's new startup check is the one item worth double-checking in advance: confirm `TABLESCOPE_SECRET_KEY` is actually set in the production environment *before* deploying, or the app will refuse to start. Every other production environment variable this pattern already covers -- `TABLESCOPE_AI_SIGNING_SECRET`, `CORS_ALLOW_ORIGINS` -- is presumably already set correctly, since the app is running today; confirm `TABLESCOPE_SECRET_KEY` the same way.)

## Verification after deploy

| Check | How |
|---|---|
| App starts | Both services come up; no `RuntimeError` in platform-api startup logs about `TABLESCOPE_SECRET_KEY`. |
| XFF fix live | `curl` (or equivalent) the public app with a forged `X-Forwarded-For` header and confirm nginx's outbound header to platform-api is the real connecting IP, not the forged one (inspect platform-api access/debug logs for the request, or temporarily log `_client_ip()`'s return value in a non-production environment first). |
| Qdrant deletion wired | Delete a test project or tenant with at least one indexed document; confirm (via ai-server/Qdrant logs, or a direct Qdrant collection check in a non-production environment) that the corresponding collection/points are gone, and that `TenantDeleteResponse.qdrant_collection_deleted` is `true` in the tenant-delete response body. |
| TS-ISO-017 canary healthy | Trigger a knowledge-graph health check (`POST .../health-check`) and confirm the job completes and a `KnowledgeGraphHealthCheck` row is written, same as before this change. |
| Dependabot active | Check the repository's Dependabot tab/PRs after the next scheduled run (weekly) for update PRs against the new ecosystems. |

## Report back

Confirm the merge is clean, both full test suites pass in CI, and the four post-deploy checks above look correct. If `TABLESCOPE_SECRET_KEY` is not already set in the production environment, **stop before deploying** and get it set first -- the new guard will otherwise take the app down on the next restart, which is the intended fail-closed behavior but should not be a surprise at deploy time.

Once this phase is confirmed stable in production, proceed to Phase 2 of `docs/security/ts-iso-implementation-roadmap.md` (TS-ISO-014 Service Identity Scoping, TS-ISO-013 Session-Token Hardening) -- both are larger efforts that sit on the authentication hot path and need their own dedicated implementation and Devin doc, not a fast-follow like this one.
