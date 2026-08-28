# TableScope Devin-Ready Plan: Tenant & Project Isolation Security Fixes (Increment 1)

Repository: `lhoskins/tablescope-lh`
**Branch to merge:** `claude/project-workspace-unified-tabs`
**Base:** `release/deploy-2026-08-07`
**Merge test:** clean, no conflicts (verified via throwaway-branch `git merge --no-commit --no-ff` against `origin/release/deploy-2026-08-07`, current HEAD `5eae64d0`)

This is the first shipped increment against the "Tablescope Tenant and
Project Isolation Security Assessment" (125 audit questions, 22 numbered
findings, `TS-ISO-001` .. `TS-ISO-022`). It covers both Critical findings and
six High/Medium findings, each with a real code fix and new tests — not a
restatement of the assessment. Everything else in the assessment is
explicitly out of scope here; see §4.

---

## 1. Merge rules — read first

1. **Do not rewrite, refactor, rename, or reformat the delivered files.**
   Merge as-is; resolve conflicts (if the base has moved further) by
   preserving the delivered code and adapting the surrounding code.
2. Suspected bug in this delta → **report it in the PR description**, don't
   silently change it.
3. This branch also carries an earlier, already-deployed commit
   (`08d9b52b`, Google Drive Spreadsheet connector Increment 0) ahead of
   `release/deploy-2026-08-07` — that commit is unrelated to this security
   work and should merge along with it; no action needed beyond a normal
   merge.

```bash
git fetch origin
git checkout -b devin/tenant-project-isolation-fixes origin/release/deploy-2026-08-07
git merge origin/claude/project-workspace-unified-tabs
```

---

## 2. What shipped (commit `e189ec9e`)

| Finding | Severity | Fix |
|---|---|---|
| **TS-ISO-001** | Critical | `platform-api/app/routes/ai_proxy_permissions.py` — `/api/ai/permissions` was an unauthenticated `GET` any caller could hit with an arbitrary `(tenant_id, user_id, project_id)` triple to enumerate project membership and pull datasource/query/dashboard context. Changed to a signed `POST`; `verify_internal_ai_request()` (new `app/services/internal_ai_auth.py`) checks HMAC signature, timestamp freshness (120s window), and replay (Redis `SET NX EX`, fails open only if Redis itself is unreachable) before any authorization check runs. Any authorization failure returns a constant `403 "Forbidden"` — the response body never distinguishes "wrong project" from "not a member" from "bad signature". |
| **TS-ISO-002** | Critical | `platform-api/app/services/sql_authorization.py` (new) + `app/routes/query.py` + `app/routes/query_sql_helpers.py` — ad hoc SQL reaching Teiid (the caller's original SQL *and* every LLM repair-loop rewrite) was never checked against the caller's project-scoped table allowlist, and had no statement-type restriction. `authorize_sql(sql, allowed_tables)` parses with `sqlglot` (`dialect="postgres"`), rejects multi-statement payloads, rejects any root or nested node that isn't `SELECT`/`UNION`/`EXCEPT`/`INTERSECT` (catches `INSERT`/`UPDATE`/`DELETE`/`DROP`/`CREATE`/`ALTER`/`CALL`/etc. anywhere in the tree, including hidden inside a CTE or a UNION branch), then checks every table reference against the allowlist (case-insensitive, excluding CTE-defined aliases). Wired into `_execute_sql_with_repair`'s inner `_execute` callback so it runs on the initial SQL and on every repair rewrite, not just the first attempt. The non-SQL `tableName` path in `query_datasource` gets the equivalent allowlist check directly. |
| **TS-ISO-006** | High | `platform-api/app/services/chat_attachment_adapter.py` + `app/services/conversational_analytics/__init__.py` — chat attachment context building trusted `attachment_ids` against `tenant_id` alone, so any authenticated user in a tenant could reference another user's or another conversation's uploaded attachment by guessing its id. `build_attachment_context` now also filters on `conversation_id` and `uploaded_by`; any requested id that doesn't match all three raises `AttachmentAuthorizationError`, handled as a hard turn failure (`status="error"`, `error_code="attachment_unauthorized"`) rather than silently proceeding with a partial/wrong attachment set. |
| **TS-ISO-007** | High | `ai-server/tablescope-ai-api/app/core/security.py` + `platform-api/app/main.py` — `verify_signature` silently no-opped when `AI_SIGNING_SECRET` was unset, so a misconfigured deployment would accept any unsigned internal request. Now raises `403` at request time when the secret is empty, and `platform-api`'s `create_app()` refuses to start in `production` if `TABLESCOPE_AI_SIGNING_SECRET` is unset — fails closed at both layers. |
| **TS-ISO-008** | High | `platform-api/app/models/user_vdb.py` + `app/models/shared_vdb.py` + 8 write sites (`tenant_onboarding_service.py`, `project_sharing.py`, `tenant_data_planes_crud.py`, `tenants_crud.py`, `tenants_users.py`) — `UserVDB`/`SharedVDB.encrypted_password` was written and read as plaintext despite the field name. New writes now go through the existing Fernet helper (`app/services/crypto.py::encrypt_secret`); `get_decrypted_password()` dual-reads — tries Fernet decrypt, falls back to the raw value on failure — so rows not yet migrated keep working. Paired with `platform-api/scripts/backfill_vdb_password_encryption.py` (new, idempotent, dry-run by default) to re-encrypt existing plaintext rows post-deploy. |
| **TS-ISO-009** | Medium | `platform-api/app/routes/conversational_analytics_conversations.py` — its local `_check_project_access` was the one project-membership query in the codebase missing an `is_active` filter, letting a removed member keep read access to conversation history. Added the filter. |
| **TS-ISO-015** | Medium | `platform-api/app/routes/auth.py` — password login without a `tenant_slug` used `session.scalar(query)`, silently picking an arbitrary account when the same email exists in more than one tenant (email is unique per-tenant, not globally). Now rejects with `400` and asks the caller to specify `tenant_slug` when more than one candidate matches. |
| **TS-ISO-018** | Medium | `platform-api/app/observability.py` + `app/config.py` + `app/main.py` — `/metrics` was unauthenticated and labeled requests by raw `request.url.path`, leaking resource IDs into label values and creating unbounded label cardinality. Now labels by the matched route *template* (`request.scope["route"].path`, e.g. `/api/projects/{id}`) and, when `METRICS_ACCESS_TOKEN` is configured, requires a matching `X-Metrics-Token` header (returns `404`, not `401/403`, on mismatch so the endpoint's existence isn't confirmed to a prober). Also added a startup guard: `production` now refuses to boot with `CORS_ALLOW_ORIGINS` unset or left as `*`. |

**Adjacent correction folded in:** while refactoring the shared
project-access check (`app/routes/ai_proxy_shared.py::_check_project_access`
→ `_authorize_project_access`) to fix TS-ISO-001/002, found that private
projects previously allowed *only* the owner, silently ignoring explicit
`ProjectMember` rows — contradicting the assessment's own stated access
policy ("Read private project: allow if explicitly assigned"). Corrected as
part of the same refactor since both fixes depend on this function.

### Test status

- **platform-api**: `1600 passed`, 3 failed, 4 skipped (810.84s). The 3
  failures (`test_business_insight_phase1.py::test_snapshot_fresh_when_no_kg_build_postdates_it`,
  `test_snapshot_stale_after_kg_rebuild`, `test_snapshot_null_without_run`)
  are `redis.exceptions.ConnectionError` — no local Redis in the CI/sandbox
  container this was run in, **pre-existing and unrelated to this change**
  (reproducible on `release/deploy-2026-08-07` before this branch's commits).
  The 4 skipped are `tests/e2e/test_vpn_smb_repository.py` (live E2E, needs
  `VPN_SMB_E2E_API_URL`) — also pre-existing.
- **ai-server**: `156 passed`, 0 failed.
- New tests added this increment: `test_ai_proxy_permissions.py` (9),
  `test_sql_authorization.py` (23), `test_query_datasource_authorization.py`
  (4), 2 new tests in `test_query_sql_repair.py`, `test_chat_attachment_authorization.py`
  (7), `test_conversational_analytics_membership_check.py` (2),
  `test_vdb_password_encryption.py` (5), `test_login_tenant_ambiguity.py`
  (3), `test_cors_and_metrics_hardening.py` (7), `test_startup_signing_secret_required.py`
  (3); ai-server: `test_signature_verification.py` (4), `test_context_builder_permissions_call.py` (2).

---

## 3. Deploy steps

1. Merge per §1.
2. **New required production environment variables** — `platform-api`'s
   `create_app()` now raises `RuntimeError` at startup if either is missing
   when `ENVIRONMENT=production`:
   - `TABLESCOPE_AI_SIGNING_SECRET` — non-empty, shared secret between
     `platform-api` and `ai-server`. If this isn't already set in the
     production environment, generate one (e.g. `openssl rand -hex 32`) and
     set it identically on both services *before* deploying this branch —
     ai-server signs `/api/ai/permissions` requests with it, platform-api
     verifies with it, and it's already used for the pre-existing
     ai-server→platform-api HMAC pattern this reuses.
   - `CORS_ALLOW_ORIGINS` — explicit comma-separated origin list. Must not
     be unset or `*` in production.
3. **Optional**: `METRICS_ACCESS_TOKEN` — if set, `/metrics` requires header
   `X-Metrics-Token` to match. Leave unset to keep `/metrics` open (dev
   default / no behavior change if not adopted immediately).
4. **New pip dependency**: `sqlglot==30.17.0`, added to
   `platform-api/requirements.txt`. Confirm it installs cleanly in the
   deploy image (pure-Python, no native extensions expected).
5. **Post-deploy, run once**:
   ```bash
   cd platform-api
   python -m scripts.backfill_vdb_password_encryption          # dry run, prints affected row count
   python -m scripts.backfill_vdb_password_encryption --apply  # re-encrypts legacy plaintext rows
   ```
   Idempotent — safe to re-run; it only touches rows that fail Fernet
   decryption (i.e., are still plaintext).
6. No new Alembic migration in this increment — the VDB password fields are
   unchanged in shape (`encrypted_password` was already the column name),
   only what's stored in them changes.

---

## 4. Explicitly out of scope for this increment — remaining assessment findings

These are real findings from the assessment, not yet fixed. Recommend
sequencing as their own reviewed PRs (per the assessment's own PR2-PR5
structure) rather than folding into this branch:

- **TS-ISO-003** (systemic): `_authorize_project_access` (this increment's
  refactor target) is the *strongest* of at least 6 divergent project-access
  implementations found across the codebase — most other route families
  (dashboards, datasources, uploads, KG endpoints, etc., roughly 15 route
  modules) still run their own ad hoc ownership/membership checks with
  varying correctness. Needs a single shared `ProjectAccessPolicy`
  abstraction rolled out uniformly. **Includes a specific cross-tenant bug
  found during this validation pass but not fixed here**: the
  knowledge-graph health/builds endpoints do not scope by project access at
  all — flag this explicitly to whoever picks up TS-ISO-003, it's a
  concrete instance of the systemic gap, not a hypothetical one.
- **TS-ISO-004**: PostgreSQL row-level security — defense-in-depth so a bug
  in application-layer checks can't leak cross-tenant rows.
- **TS-ISO-005**: vector-store (Qdrant) query scoping rework.
- **TS-ISO-010**: file-proxy endpoint hardening.
- **TS-ISO-011**: cross-store deletion completeness (Qdrant + object storage
  + Postgres must all agree when a project/tenant is deleted).
- **TS-ISO-012**: data-plane fallback removal (a fallback path that can
  silently cross tenant boundaries under failure).
- **TS-ISO-013**: session/refresh token hardening.
- **TS-ISO-014**: service-identity scoping (internal service credentials
  currently broader than the calls they need to make).
- **TS-ISO-016**: asset-metadata visibility parity across surfaces.
- **TS-ISO-017**: background-job re-verification (a job enqueued while
  authorized, but whose authorization should be re-checked at execution
  time if it runs much later).
- **TS-ISO-019/020**: Terraform/infra hardening.
- **TS-ISO-021**: audit logging/alerting for authorization failures.
- **TS-ISO-022**: comprehensive DAST/pen-test gate as a final program
  milestone.

Full detail on each of these lives in the original assessment and Devin
implementation-plan documents the user supplied; this file does not restate
them — it only records what changed in code and what's confirmed still
open.
