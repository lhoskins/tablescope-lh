# TS-ISO-020: AI and Infrastructure Secrets Hardening — Standalone Implementation Plan

**Status:** Open — partial encryption and fail-closed AI-secret checks exist; managed lifecycle and rotation are required

**Severity:** Medium

**Owner:** Platform / AI / Cloud Security / Identity / SRE

**Target branch:** `UX-design-03`

**Plan branch:** `codex/ts-iso-020-ai-infrastructure-secrets-hardening`

**Depends on:** TS-ISO-014 (service identity scoping), TS-ISO-019 (cloud network hardening)
**Related findings:** TS-ISO-010 (file-proxy hardening), TS-ISO-012 (data-plane fallback completion), TS-ISO-013 (session-token hardening), TS-ISO-017 (background-job reauthorization)

## 1. Objective

Replace shared, static, environment-delivered TableScope secrets with managed, purpose-specific, versioned credentials and encryption keys whose plaintext is never written to Terraform state, EC2 user data, cloud-init logs, source-controlled configuration, container metadata, or database rows.

Connector and tenant credentials must use authenticated envelope encryption with explicit key versions and tenant/record-bound encryption context. AI, worker, gateway, signing, JWT/session, webhook, model-vault, and infrastructure credentials must have separate trust domains, least-privilege IAM access, bounded lifetimes, independently testable rotation, immediate revocation, and auditable use.

## 2. Current-state finding

The repository encrypts many application credentials and now rejects a missing AI signing secret in production, but key provenance and lifecycle remain weak:

| Area | Current behavior | Remaining gap |
|---|---|---|
| Connector encryption key | `TABLESCOPE_SECRET_KEY` is optional; when absent, `crypto.py` derives Fernet from `JWT_SECRET_KEY` | JWT signing and database-secret encryption share a failure domain, and JWT rotation can make connector data unreadable |
| Key parsing | A non-Fernet passphrase is silently SHA-256-derived into a Fernet key | Production cannot prove that approved high-entropy key material or a managed key generated the ciphertext |
| Ciphertext format | Fernet ciphertext contains no TableScope purpose, tenant, record, or application key version | Rotation, scope verification, selective revocation, and cryptographic provenance are not explicit |
| Key cache | One `_fernet()` instance is cached process-wide | There is no current/next key refresh, managed-secret version awareness, or prompt revocation propagation |
| Legacy VDB passwords | `UserVDB` and `SharedVDB` return the stored value as plaintext after any decryption exception | Corruption, wrong key, and legacy plaintext are indistinguishable and can silently reach downstream authentication |
| Secret delivery | Compose passes JWT, service, Teiid, AWS, Supabase, Stripe, AI, Twilio, Google, model, SMTP, and connector secrets through environment variables | Broad shared environment blocks expose more secrets to more processes than each workload requires |
| Static AWS keys | `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` remain supported in the application container | Long-lived credentials can bypass instance/workload identity and are difficult to attribute or revoke safely |
| AI Terraform | `ai_signing_secret` is a sensitive Terraform variable interpolated into EC2 user data | Terraform sensitivity only redacts display; the value can enter state, EC2 user-data APIs, instance metadata, and cloud-init artifacts |
| AI host bootstrap | Cloud-init writes `AI_SIGNING_SECRET` to `ai-server/.env` and logs deployment output | A long-lived shared secret is materialized on disk and distributed through a bootstrap mechanism not designed for secret rotation |
| AI trust | Both request directions use the same HMAC secret and lack key ID/generation | Compromise affects both directions; callers cannot rotate independently or prove which version signed a request |
| Replay handling | Internal AI signature replay storage logs and fails open when Redis is unavailable | A captured valid request remains usable inside the timestamp window during dependency failure |
| Application bootstrap | Root user data generates JWT/Teiid/Postgres secrets directly into `.env` | Secrets are host-local, not centrally inventoried, versioned, backed up, rotated, or synchronously distributed |
| Model signing | LLM manifest signing uses a filesystem key path and fingerprint configuration | Private signing material may reside on the shared host rather than a hardware-backed/signing service boundary |
| Defaults | Example files contain `please-change-me`/`change-me-please`; configuration defaults include the JWT placeholder | Production startup does not comprehensively reject every placeholder, fallback, mixed environment, or missing version |
| Rotation evidence | No common secret metadata, usage telemetry, rotation workflow, or old-key revocation drill exists | Encryption and secret presence do not demonstrate lifecycle assurance |

### Root cause

Secrets were initially injected as ordinary deployment settings and one symmetric helper was reused for multiple credential types. Encryption-at-rest fixes protected new database writes, but retained development fallbacks and plaintext compatibility to avoid lockout. AI infrastructure similarly used Terraform/cloud-init because the host needed a shared value at first boot. These compatibility paths became production-capable without a managed rotation contract.

## 3. Scope and non-goals

This plan covers:

- application, AI, model, connector, database, Teiid, workload, webhook, third-party, and cloud credential inventory;
- AWS Secrets Manager/KMS-backed runtime retrieval, envelope encryption, secret references, and workload IAM;
- purpose separation, version metadata, rotation, revocation, recovery, cache behavior, and audit;
- removal of JWT-derived encryption, plaintext dual-read, static AWS keys, user-data/state secrets, shared HMAC, and weak defaults;
- tests, migration, deployment, compromise response, and release evidence.

This plan does not store customer content in Secrets Manager, use one KMS key as a universal authorization boundary, or treat encryption as a substitute for tenant/project authorization. TS-ISO-014 owns workload capabilities, TS-ISO-019 owns private endpoints and egress, and TS-ISO-022 owns the blocking assurance gate.

## 4. Security invariants

1. Every production secret has a named purpose, owner, environment, consumer set, version, rotation period, and revocation procedure.
2. JWT/session signing, connector encryption, AI authentication, model signing, webhooks, third parties, databases, Teiid, and tenant gateways never share master key material.
3. Plaintext secrets never enter Git, Terraform variables/state/plan output, EC2 user data, AMIs, container images, logs, traces, metrics, URLs, or database fields.
4. Workloads retrieve only their required secret versions through their own least-privilege identity and private endpoint.
5. Connector ciphertext is authenticated and bound to purpose, environment, tenant, record type/ID, and key version.
6. Missing, corrupt, legacy-unclassified, wrong-context, disabled, expired, or revoked ciphertext fails closed and is quarantined.
7. New encryption always uses the current active version; decryption accepts only an explicit bounded version set during rotation.
8. Rotation is online, observable, resumable, and ends with verified old-version revocation.
9. Secret caches have bounded TTL, respond to revocation, and never persist plaintext to disk or crash artifacts.
10. Secret access and rotation events are auditable without recording values, ciphertext, signatures, or sensitive customer identifiers.
11. Backup/restore and disaster recovery preserve the approved key/secret version relationship without exporting master keys.
12. A failed secret provider, KMS, replay store, or policy lookup makes the protected operation unavailable rather than weaker.

## 5. Target design

### 5.1 Secret inventory and classification

Create a machine-readable registry containing:

```text
secret name and purpose
environment and data classification
authoritative provider/path or key ARN
producer and approved consumers
workload/tenant scope
credential/key type and algorithm
active and next version
maximum age / rotation owner
revocation and recovery runbook
logging/redaction identifiers
dependent services and restart/reload behavior
```

At minimum inventory JWT/session keys, connector/VDB/LDAP encryption, AI request identities, internal file proxy, service/workload credentials, PostgreSQL/Redis/Teiid, S3/data-plane roles, Supabase, Stripe, Twilio, Google/OAuth, SMTP, Hugging Face, metrics, webhooks, model-manifest signing, TLS/mTLS, Terraform/CI, and backup credentials.

Secret values are never included in the registry. CI compares declared runtime references to the registry and rejects unregistered secret-shaped environment variables or Terraform inputs.

### 5.2 AWS KMS and Secrets Manager hierarchy

Use distinct customer-managed KMS keys or clearly separated grants/aliases for:

- application envelope encryption;
- session/signing keys where KMS signing is used;
- AI/workload authentication and mTLS issuance;
- model/artifact manifest signing;
- audit/evidence encryption;
- tenant storage keys already defined by the isolated data plane.

Store operational secret material in Secrets Manager under environment- and purpose-specific paths. Resource policies, key policies, grants, secret tags, and VPC endpoint policies must require the expected account, environment, workload principal, and purpose. Application IAM can read only its named secrets and invoke only required KMS operations; AI, worker, gateway, CI, rotation Lambda, and administrators receive separate policies.

Use private Secrets Manager, KMS, STS, and logging endpoints from TS-ISO-019. Enable CloudTrail data events where supported and alert on denied, unusual, cross-environment, or administrative secret access.

### 5.3 Runtime secret delivery

Replace value-bearing environment variables with secret references and a typed `SecretProvider` interface. Production implementation resolves managed versions using workload identity. Local/test uses an explicit non-production provider that cannot activate when `ENVIRONMENT=production`.

Preferred delivery order:

1. direct SDK retrieval into process memory with bounded cache and refresh;
2. agent/sidecar materialization into root-owned `tmpfs` files with strict permissions and atomic version swaps;
3. orchestrator-native secret references where metadata and process boundaries meet the same controls.

Do not place values in Compose interpolation, `docker inspect`, command-line arguments, process titles, unit files, shell history, cloud-init, image layers, or persistent `.env` files. Workloads receive distinct references and cannot enumerate the secret namespace.

Remove static AWS access-key variables in production. SDKs use instance/task/workload roles with short-lived STS credentials, source identity/session tags, private endpoints, and bounded permissions.

### 5.4 Connector and database credential envelope encryption

Replace the global Fernet helper with versioned authenticated envelope encryption. Use KMS `GenerateDataKey` and an approved AEAD such as AES-256-GCM:

```text
format_version
algorithm
kms_key_arn / application_key_id
key_version
encrypted_data_key
nonce
ciphertext
authentication tag
encryption_context digest
created_at
```

Encryption context includes exact non-secret identifiers:

```text
environment
purpose (connector_oauth, vdb_password, ldap_bind, ...)
tenant_id
record_type
record_id
credential_generation
```

The decryptor reconstructs and validates the expected context from the loaded canonical record; it never trusts context supplied beside the ciphertext. Copying ciphertext across tenants, record types, or records must fail cryptographically.

Use separate logical purposes and, where risk warrants, separate KMS keys for connector OAuth tokens, VDB passwords, LDAP bind credentials, and sensitive provider configuration. Store only ciphertext envelopes in Postgres. Never log the envelope or return it through schemas.

### 5.5 Legacy migration and fail-closed reads

Inventory each existing credential into one of: valid explicit-key Fernet, JWT-derived Fernet, confirmed legacy plaintext, corrupt/unreadable, or absent. Classification must use controlled migration metadata and validation—not ordinary request-time trial-and-return behavior.

Migration procedure:

1. freeze/record the exact old key sources under restricted migration access;
2. read one tenant/batch through an offline migration role;
3. prove the source format and expected credential record;
4. encrypt into the new envelope/current version;
5. test the credential through its approved connector without exposing it;
6. atomically replace the row and write non-secret migration evidence;
7. quarantine failures for credential re-entry by an authorized tenant administrator.

After migration, delete `get_decrypted_password()` plaintext fallback and JWT-key derivation. A normal application decrypt exception returns a safe `CREDENTIAL_UNAVAILABLE` state and never sends stored ciphertext/plaintext guesses downstream.

### 5.6 AI and internal workload secrets

Replace the single bidirectional AI HMAC secret with TS-ISO-014 workload identity, preferably private mTLS plus short-lived audience/capability tokens. If HMAC remains during migration:

- use separate platform-to-AI and AI-to-platform keys;
- include key ID, identity, audience, method/path/body digest, request ID/nonce, timestamp, and capability;
- store keys in Secrets Manager, retrieve by workload identity, and keep plaintext only in memory;
- accept current and next versions for a bounded overlap;
- fail closed when replay storage or key policy is unavailable for protected operations;
- revoke and evict the old version after both directions prove current use.

Terraform passes only secret ARNs/names and workload role configuration. EC2 user data contains no `AI_SIGNING_SECRET`; it installs no persistent secret file. The AI service refreshes managed versions without rebuilding the instance where safe.

Model-manifest signing should use an asymmetric KMS signing key or hardware-backed signer. Build/deployment workloads request signatures; runtime verifies with published public keys and versioned key IDs. The private signing key is never mounted into the shared model directory.

### 5.7 JWT, webhooks, third parties, and databases

- Implement TS-ISO-013's versioned asymmetric JWT/session signing or an equivalent managed rotation design; encryption keys remain separate.
- Store Stripe, Supabase, Twilio, Google, SMTP, Hugging Face, metrics, webhook, database, Redis, and Teiid secrets in purpose-specific managed entries.
- Give API, worker, AI, gateway, and one-time migration processes only the entries they need.
- Rotate database/Teiid users with current/next credential overlap, connection-pool eviction, health verification, and old-login disablement.
- Provider OAuth refresh-token updates write a new encrypted envelope/generation atomically; stale jobs cannot overwrite a newer credential.
- Webhook verification keys and service credentials carry provider/purpose versions and cannot be reused as internal API keys.

### 5.8 Rotation state machine

Implement a common managed workflow:

```text
planned -> generated -> staged -> dual-read/dual-verify -> writers-current
-> re-encrypt/reconnect -> verified -> old-disabled -> old-revoked -> complete
```

Every phase is idempotent, approved for high-risk secrets, and recorded through TS-ISO-021. Rotation tracks consumer acknowledgements and last-seen version without recording values. It blocks old-key revocation until required rows/services are migrated, but it never extends overlap silently.

Emergency compromise rotation skips scheduled grace where possible: disable mint/write, revoke the compromised version, invalidate caches/tokens/connections, quarantine affected jobs, issue the replacement, and require reauthentication/re-entry where recovery cannot prove confidentiality.

### 5.9 Redaction and memory handling

Centralize secret redaction across structlog, standard logging, exception handlers, Sentry, HTTP clients, task results, Terraform/CI output, and support bundles. Redact known field names plus provider token/key patterns, Authorization/cookie headers, signed URLs, connection strings, ciphertext envelopes, and query parameters.

Prevent debug endpoints and serializers from dumping settings or process environments. Disable core dumps for secret-bearing processes, restrict `/proc`/container inspection, use non-root processes, zero mutable buffers where practical, and bound plaintext lifetime. Error messages identify only secret reference/purpose and safe version ID.

## 6. Implementation work breakdown

### Phase A — Inventory, providers, and production guardrails

1. Generate the complete secret/key/credential registry and owner/consumer matrix.
2. Add production startup validation that rejects placeholder/default keys, JWT-derived encryption, local provider, static AWS keys, missing versions, and purpose reuse.
3. Create KMS keys/grants, Secrets Manager hierarchy, private endpoints, workload IAM, CloudTrail, and access alerts.
4. Implement typed `SecretProvider`, bounded cache, version metadata, refresh/invalidation, and centralized redaction.
5. Remove values from Terraform inputs/user data and pass only managed references.

### Phase B — Application envelope encryption

1. Add versioned credential envelope fields/model metadata and KMS AEAD service.
2. Bind encryption context to environment, purpose, tenant, record, and credential generation.
3. Update connector, VDB, LDAP, repository, OAuth, and provider write/read paths.
4. Build the explicit legacy classifier/backfill and credential re-entry workflow.
5. Remove JWT fallback, passphrase derivation, plaintext dual-read, and unversioned Fernet writes after verified migration.

### Phase C — AI, model, and workload identity

1. Replace Terraform/cloud-init AI secret material with workload identity and managed references.
2. Split directional HMAC keys during migration, add key IDs/versions, and make replay protection fail closed.
3. Move to private mTLS/short-lived workload tokens under TS-ISO-014.
4. Move model-manifest private signing to KMS/asymmetric signing and publish versioned verification keys.
5. Remove filesystem signing keys and shared persistent AI `.env` secret files.

### Phase D — Operational credentials and rotation

1. Migrate JWT/session, webhook, Supabase, Stripe, Twilio, Google, SMTP, Hugging Face, metrics, database, Redis, and Teiid credentials.
2. Add current/next rotation adapters and pool/cache reload for each consumer.
3. Integrate stale-generation rejection with TS-ISO-017 jobs and tenant gateway/data-plane credentials.
4. Add rotation scheduler, owner attestation, expiry alerts, emergency revocation, and recovery runbooks.
5. Rotate each production secret family once and revoke the old version.

### Phase E — Enforcement and assurance

1. Add secret, IaC/state, image-layer, history, log, and runtime environment scans.
2. Add IAM simulation and endpoint-policy tests for allowed and denied consumers.
3. Add TS-ISO-021 access/rotation/denial events without secret material.
4. Make TS-ISO-022 block releases on unmanaged secrets, placeholder keys, failed scans, missing rotation evidence, or excessive IAM.
5. Conduct compromise, provider outage, cache revocation, backup/restore, and rollback drills.

## 7. Expected file changes

| Area | Expected files |
|---|---|
| Secret abstraction | `platform-api/app/services/crypto.py`, new secret provider/envelope/key-version/rotation services |
| Configuration | `platform-api/app/config.py`, environment examples, production startup validation, removal of value-bearing Compose variables |
| Credential models | connector, VDB/shared VDB, LDAP, repository, OAuth/provider models and a new Alembic revision |
| Consumers | SaaS/Google/QuickBooks, repository, Teiid/VDB, enterprise auth, billing, SMS/email, metrics, webhook clients |
| AI authentication | platform internal AI auth/signers, AI-server security/signing code, workload token/mTLS clients |
| AI infrastructure | `terraform/ai-server/*`, instance IAM/endpoints, immutable image/bootstrap, `ai-server/docker-compose.yml` |
| Model signing | LLM manifest/vault/deployment services, KMS signer and public-key verification registry |
| Cloud/IAM | Terraform KMS, Secrets Manager, policies/grants/endpoints, CloudTrail and alert resources |
| Jobs/audit | TS-ISO-017 generation-aware rotation jobs; TS-ISO-021 security events |
| Tests/CI/docs | encryption-context, migration, IAM, secret scans, rotation/revocation, outage, recovery, deployment and runbooks |

Exact paths, Alembic revision, AWS account layout, secret inventory, and current deployed key sources must be confirmed before implementation.

## 8. Test plan

### Cryptography and isolation

- Encrypt/decrypt each credential purpose under its exact tenant/record/generation context.
- Copy ciphertext across tenant, record, purpose, environment, or generation and verify authenticated decryption fails.
- Missing, unknown, corrupt, revoked, expired, and unsupported algorithms/versions fail closed.
- New writes always use current version; bounded prior versions are decrypt-only during rotation.
- JWT rotation cannot affect connector/VDB/LDAP decryptability.
- No ordinary read path treats a decrypt exception as plaintext.

### Provider, IAM, and delivery

- API, worker, AI, gateway, CI, migration, and rotation identities can access only their registered secrets/keys/actions.
- IAM simulation and live negative tests deny cross-environment, cross-purpose, cross-tenant, listing, administration, and wrong-endpoint access.
- Secret values are absent from Terraform state/plan, user data, EC2 console output, images, layers, Compose inspection, process arguments, logs, traces, Sentry, metrics, and support bundles.
- Static AWS credentials are rejected in production and workload STS sessions carry expected identity/tags.
- Provider/VPC endpoint failure produces a safe unavailable response and no fallback key.

### Migration and rotation

- Classify and migrate valid explicit-key, JWT-derived, and confirmed plaintext legacy rows; quarantine ambiguous/corrupt rows.
- Resume interrupted batches without double encryption or tenant crossover.
- Exercise planned current/next rotation for every secret family and verify consumer acknowledgements/pool eviction.
- Revoke the old version and prove no service, row, job, connection, backup restore, or canary uses it.
- Emergency compromise rotation invalidates caches/tokens/jobs promptly and never restores compromised material.

### AI and model signing

- Wrong direction, key ID, generation, audience, capability, path/body, timestamp, replay, and revoked AI requests fail closed.
- Replay-store outage denies protected mutations.
- AI restarts without secrets in user data or persistent `.env` and retrieves only its managed versions privately.
- Model manifests verify against the expected asymmetric key/version; tampered artifacts or wrong environment keys fail.
- Model signing workload can sign but cannot export private key material.

## 9. Deployment sequence

1. Record deployed secret references, consumers, ciphertext formats/counts, key fingerprints/versions, Terraform state exposure, IAM, caches, and recovery dependencies without exporting values.
2. Deploy KMS/Secrets hierarchy, workload IAM, private endpoints, audit/alerts, typed provider, version metadata, and redaction while existing readers remain unchanged.
3. Move non-database operational secrets to managed references one purpose/workload at a time; verify refresh and remove each value-bearing environment/user-data path.
4. Deploy envelope encryption and dual-read only for explicitly classified old formats. Migrate canary tenants, validate connectors, then expand in bounded batches.
5. Make new writes use the envelope exclusively; quarantine remaining ambiguous credentials and remove plaintext/JWT-derived request-time fallback.
6. Split/version AI directional keys, remove user-data `.env` delivery, then migrate to TS-ISO-014 private mTLS/short-lived tokens.
7. Move model signing to KMS/asymmetric keys and migrate JWT, webhook, database, Redis, Teiid, and remaining third-party credentials.
8. Rotate every family through current/next, verify consumers and migrated ciphertext, disable/revoke old versions, and retain safe evidence.
9. Enable TS-ISO-022 blocking secret/IAM/rotation gates and run compromise, outage, backup/restore, and rollback drills.

Never remove an old decrypt version before inventory and migration evidence prove the required rows were converted. Never preserve availability by falling back to JWT-derived, plaintext, environment, or user-data secret material.

## 10. Rollback

- Roll back application code only while the previous managed, uncompromised decrypt/verify version remains explicitly enabled and audited.
- Retain envelope/version metadata and migrated ciphertext; do not rewrite it to unversioned Fernet or plaintext.
- If a new secret version fails, stop new writes, return to the last approved managed version, evict caches/connections, and investigate. Do not restore secrets to user data or `.env`.
- A revoked or compromised version remains revoked through rollback.
- If KMS/Secrets Manager is unavailable, fail the protected operation and recover private connectivity/provider health; do not derive a local fallback.
- Restore from backups only with approved KMS grants and version mapping; verify old revoked credentials cannot become active.

## 11. Acceptance criteria

- [ ] Every production secret/key is registered with purpose, owner, consumers, environment, version, rotation, revocation, and recovery policy.
- [ ] No production connector encryption key is derived from JWT or an arbitrary passphrase.
- [ ] Connector/VDB/LDAP/provider ciphertext uses authenticated tenant/record/purpose/generation-bound envelopes with explicit versions.
- [ ] Plaintext dual-read is removed; ambiguous/corrupt legacy rows are quarantined rather than guessed.
- [ ] Secret values are absent from Terraform state/inputs, EC2 user data, cloud-init, AMIs/images, persistent `.env`, Compose inspection, logs, and telemetry.
- [ ] API, worker, AI, gateway, CI, and rotation identities have distinct least-privilege KMS/Secrets access through private endpoints.
- [ ] Static AWS keys and placeholder/default production secrets are rejected.
- [ ] AI authentication has separate direction/identity/audience/capability/version and fail-closed replay protection, then transitions to TS-ISO-014 workload identity.
- [ ] Model private signing material is non-exportable and runtime verification uses versioned public keys.
- [ ] Every secret family completes a current/next rotation drill and the old version is demonstrably revoked.
- [ ] Secret scans, IAM simulation/live negatives, cross-tenant crypto tests, provider-outage, compromise, backup/restore, and rollback tests pass.
- [ ] TS-ISO-021 records correlated secret lifecycle/access decisions without secret or customer-content leakage.

TS-ISO-020 must remain open until JWT-derived and plaintext fallbacks are removed, AI/user-data/environment secret delivery is replaced, purpose-separated managed keys are deployed, and rotation plus old-key revocation is proven for every production secret family.

## 12. Validation addendum

All thirteen current-state findings in Section 2 were independently re-verified line-by-line against `platform-api/app/services/crypto.py`, `app/models/{user_vdb,shared_vdb}.py`, `docker-compose.yml`, `ai-server/docker-compose.yml`, `terraform/ai-server/{variables,main}.tf`, `terraform/ai-server/user-data-ai.sh.tpl`, `terraform/user-data.sh.tpl`, `platform-api/app/routes/ai_proxy_shared.py`, `app/services/internal_ai_auth.py`, `ai-server/tablescope-ai-api/app/core/security.py`, and the `.env.example` files, and confirmed **accurate**, with one clarification:

- **The "static AWS keys remain supported" finding (Section 2's "Static AWS keys" row) is true in effect but not by the mechanism it implies.** `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` are passed as env vars in `docker-compose.yml`, but they are **not** named fields in `platform-api/app/config.py` — the application never reads them directly. They work because `boto3.client("s3", ...)` (in `s3_storage.py`) is called without explicit credentials on the non-dedicated path, so boto3's own default credential chain picks them up from the process environment. The practical risk (long-lived static keys usable by the container) is identical either way, but Section 6/9's remediation should target the compose file and boto3 client construction, not `config.py` — there is no `config.py` field to remove for this one.

Four additional findings, confirmed with file:line evidence, should be added to Section 6/7:

- **`TABLESCOPE_SECRET_KEY` has no fail-closed production startup check, unlike `TABLESCOPE_AI_SIGNING_SECRET`.** `platform-api/app/main.py`'s `create_app()` already refuses to boot in production if the AI signing secret is unset — but has zero reference anywhere to `TABLESCOPE_SECRET_KEY`. Production can run indefinitely on the SHA-256-derived-from-JWT-secret Fernet key (Section 2's "Connector encryption key" and "Key parsing" rows) with no boot-time guard, the exact failure pattern the AI-signing-secret check exists to prevent. This is a small, isolated, high-value fix that doesn't require the full envelope-encryption redesign to land first.
- **The root/app-server instance's own secret-generation surface is missing from Section 7's file table entirely.** `terraform/user-data.sh.tpl` independently generates `JWT_SECRET_KEY`, `TEIID_API_KEY`, and `POSTGRES_PASSWORD` via `openssl rand` directly into `.env` on first boot (Section 2's "Application bootstrap" row cites this behavior, but Section 7 only lists `terraform/ai-server/*` — the parallel root-instance path needs its own line.
- **Neither cloud-init template restricts `.env` file permissions after writing secrets into it.** Both `terraform/ai-server/user-data-ai.sh.tpl` and `terraform/user-data.sh.tpl` `chown` the file to the application user but never `chmod` it — the `.env` files containing freshly-generated or interpolated secrets are left at the default umask (typically world/group-readable) on disk. Section 5.3/5.6's guidance to avoid "persistent `.env` files" already covers the end state; this is worth calling out explicitly as an interim hardening step for however long the transition takes.
- **Replay protection is asymmetric between the two AI HMAC directions, not just fail-open in one place as Section 2's "Replay handling" row states.** The ai-server→platform-api direction (`internal_ai_auth.py`) has a Redis-backed single-use replay check that fails open on Redis errors. The platform-api→ai-server direction (`ai-server/.../core/security.py`'s `verify_signature`, used by e.g. the `/vector-store/reindex` internal endpoint) has **no replay/nonce store at all** — only signature and a 300-second timestamp window. Section 5.6's "fail closed when replay storage or key policy is unavailable" requirement should be understood as needing a *new* replay store on the ai-server side, not just a fail-closed fix to the existing one on the platform-api side.
