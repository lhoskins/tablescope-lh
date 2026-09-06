# TS-ISO-013: Session Token Hardening — Standalone Implementation Plan

**Status:** Open — partial renewal protection exists; implementation required

**Severity:** Medium

**Owner:** Platform / Identity / Security / Web

**Target branch:** `UX-design-03`

**Plan branch:** `codex/ts-iso-013-session-token-hardening`

**Depends on:** Existing tenant-scoped authentication and SMS MFA enforcement
**Related findings:** TS-ISO-001 (tenant context), TS-ISO-011 (session deletion/revocation), TS-ISO-015 (tenant login ambiguity)

## 1. Objective

Make a TableScope login a server-managed, revocable session with an immutable identity and absolute start time across login, token exchange, automatic renewal, explicit refresh, and MFA upgrade. Repeated refresh must never extend the absolute session lifetime or carry stale MFA assurance.

The implementation must support tenant-wide and session-specific revocation, rotate refresh credentials with reuse detection, minimize browser token exposure, and preserve the current user experience of active-session renewal without permitting indefinite or untracked sessions.

## 2. Current-state finding

The current code has an absolute-lifetime concept, but it is not consistently enforced across token-minting paths:

| Area | Current behavior | Security gap |
|---|---|---|
| Access tokens | First-party HS256 JWT contains tenant, user, role, permissions, optional `aal`, and optional `ses` | No required session ID or server-side session record exists |
| Automatic renewal | `renew_access_token()` preserves `ses` and checks the configured absolute TTL | It is stateless and preserves `aal` without checking whether MFA is still valid or revoked |
| Explicit refresh | `/api/auth/refresh` creates a new token with only the previous `aal` extra claim | It drops `ses`, resetting the absolute-session anchor on the next renewal family |
| MFA upgrade | `/api/mfa/phone/verify` creates a new `aal2` token | It does not preserve the original session ID/start and can establish a new token family inside the same login |
| Initial issuance | Login/exchange tokens do not set `ses` until automatic renewal occurs | Different refresh paths infer or reset the family boundary inconsistently |
| MFA assurance | A factor-level `verified_until` exists and login/exchange derive `aal` from it | Renewal carries `aal2` without re-reading the authoritative expiration/removal state |
| Revocation | Sign-out clears browser/Supabase state; TableScope access tokens remain stateless until expiry | No immediate per-session, user, tenant, or compromise revocation |
| Browser storage | First-party bearer token is stored in `localStorage` and replaced from `X-Session-Token` | A browser script compromise can read and exfiltrate the token; background tabs can race token replacement |
| Refresh credential | `/auth/refresh` requires the current bearer token and returns another bearer token | There is no rotating refresh-token family, reuse detection, or durable refresh state |

### Root cause

Token renewal was added to solve unexpected hourly logout, while session creation, MFA elevation, explicit refresh, and logout remained independent minting paths. The token carries enough information to authenticate but there is no authoritative server-side session lifecycle tying those paths together.

## 3. Scope and non-goals

This plan covers first-party TableScope sessions created from Supabase, SSO/SAML, LDAP, and supported direct/exchange flows. It covers web access/refresh tokens, MFA assurance, revocation, browser handling, and logout.

It does not replace Supabase or enterprise identity providers. It does not treat connector OAuth refresh tokens as user sessions. Service-to-service API keys and TS-ISO-010 workload identities require separate lifecycle controls and must not be represented as user sessions.

## 4. Session invariants

1. Every user access token contains a cryptographically random immutable session ID (`sid`).
2. Every token in a session family preserves the same server-recorded `created_at`/absolute expiry; client claims cannot move it.
3. Access tokens are accepted only while their server-side session is active and generation-matched.
4. Explicit refresh, automatic renewal, MFA upgrade, role/permission refresh, and tenant navigation never create a new session implicitly.
5. `aal2` is accepted only while the session's authoritative MFA assertion is active and policy still permits it.
6. Removing a factor, changing MFA policy, disabling a user, deleting a tenant, password reset, suspected compromise, or administrator revocation invalidates applicable sessions promptly.
7. Refresh credentials rotate once; reuse of a consumed credential revokes the entire family.
8. Access and refresh tokens are tenant-bound and cannot be adopted by another tenant tab/session.
9. Session and refresh secrets are never stored in plaintext, logs, URLs, analytics, or client metadata.
10. Absolute expiry cannot be extended by activity, clock skew, retry, concurrent refresh, MFA verification, or migration fallback.

## 5. Target design

### 5.1 Server-side session model

Add an Alembic migration and models for `auth_sessions` and `auth_refresh_tokens`.

Recommended `auth_sessions` fields:

```text
id UUID PRIMARY KEY                         # sid
tenant_id BIGINT NOT NULL
user_id BIGINT NOT NULL
external_subject VARCHAR NOT NULL
provider_type VARCHAR NOT NULL
status ENUM(active, revoked, expired, compromised)
created_at TIMESTAMPTZ NOT NULL             # immutable absolute start
absolute_expires_at TIMESTAMPTZ NOT NULL    # immutable
idle_expires_at TIMESTAMPTZ NOT NULL
last_seen_at TIMESTAMPTZ NOT NULL
generation INTEGER NOT NULL DEFAULT 1
role_version / membership_version
mfa_level VARCHAR NOT NULL DEFAULT 'aal1'
mfa_verified_at TIMESTAMPTZ
mfa_expires_at TIMESTAMPTZ
revoked_at TIMESTAMPTZ
revocation_reason VARCHAR
created_ip_hash / last_ip_hash
created_user_agent_hash / last_user_agent_hash
```

Recommended `auth_refresh_tokens` fields:

```text
id UUID PRIMARY KEY                         # refresh jti
session_id UUID NOT NULL
token_hash BYTEA/VARCHAR NOT NULL UNIQUE
generation INTEGER NOT NULL
issued_at / expires_at TIMESTAMPTZ
consumed_at TIMESTAMPTZ
replaced_by_id UUID
revoked_at TIMESTAMPTZ
```

Store only a keyed hash of refresh-token secret material. Session evidence should contain coarse or keyed-hash device/network metadata, not raw IP addresses or full user-agent strings unless an approved audit policy requires them.

Add indexes for active session lookup by `sid`, tenant/user revocation, absolute expiry, idle expiry, and refresh hash. Keep session audit/evidence compatible with TS-ISO-011 so tenant deletion can revoke first and retain only policy-approved evidence.

### 5.2 Token claims

Access tokens should contain only validated, short-lived authorization claims:

```text
sid       immutable session UUID
jti       unique access-token UUID
sub       external subject
tenant_id / org_id / user_id
role / permissions
aal       current assurance level
auth_time original primary-auth time
mfa_time  most recent verified MFA assertion, when present
sg        session generation
iat / nbf / exp / iss / aud
```

Retain `ses` temporarily for compatibility, but set it from the server session's immutable `created_at` on every issuance. The server record is authoritative. Remove client-controlled or inherited claim dictionaries from minting APIs; build claims from a typed session/user snapshot and an explicit allowed field list.

Use asymmetric signing with a versioned `kid` and JWKS where operationally feasible. At minimum, rotate the current signing key through managed secrets with overlapping verification keys and prohibit the checked-in/default `change-me-please` value at production startup.

### 5.3 Login and exchange

After Supabase/SSO/LDAP credential verification and tenant membership checks:

1. Create one `AuthSession` with a random `sid`, immutable absolute expiry, idle expiry, provider, and current role/membership version.
2. Derive MFA state from an actual current assertion. A remembered factor enrollment alone must not silently become a new `aal2` session unless policy explicitly defines and audits a trusted MFA window.
3. Issue a short-lived access token and one refresh credential for the session.
4. Set the refresh token as `HttpOnly`, `Secure`, `SameSite=Lax` or stricter, narrow `Path=/api/auth`, and host-only cookie.
5. Return the access token initially for compatibility, then migrate it from `localStorage` to in-memory storage. Prefer a backend-for-frontend/HttpOnly session-cookie design if adopted consistently.

Do not create multiple server sessions due to page reload, harmless exchange retry, or concurrent login callback. Use a bounded idempotency/correlation key for the authentication transaction.

### 5.4 Explicit refresh and rotation

Change `/api/auth/refresh` to consume the refresh cookie, not to clone claims from the access token.

In one transaction:

1. Hash and lock the presented refresh token row.
2. Load and lock the associated session.
3. Verify session status, tenant/user status, absolute expiry, idle expiry, membership generation, refresh expiry, and token generation.
4. Recompute role and permissions from authoritative records.
5. Recompute MFA assurance from the session assertion, factor state, tenant policy, and `mfa_expires_at`.
6. Atomically mark the token consumed and insert its replacement.
7. Update bounded `last_seen_at`/idle expiry without changing `created_at` or `absolute_expires_at`.
8. Issue an access token with the same `sid`, `ses`, and session generation.

If an already-consumed refresh token is presented, mark the session `compromised`, revoke the family, expire the cookie, and require full authentication. Concurrent refreshes need a short grace/idempotency mechanism that does not permit two live descendants.

Return generic authentication errors and stable safe codes such as `SESSION_EXPIRED`, `SESSION_REVOKED`, `SESSION_COMPROMISED`, and `MFA_REQUIRED`.

### 5.5 Automatic renewal

Remove stateless access-token renewal from `AuthMiddleware` once cookie refresh is available. The middleware must never mint a new token using only the old JWT payload.

During a bounded migration period, automatic renewal may call the same server-side session service used by `/auth/refresh`, but it must:

- require `sid` and a valid active server session;
- preserve server `created_at`/absolute expiry;
- recompute user, membership, role, permission, and MFA state;
- cap the new access-token expiry at the session absolute expiry;
- fail closed on session-store uncertainty for protected data requests;
- never turn a legacy token without `sid` into a new long-lived session.

Legacy tokens should retain their original `iat` as a conservative cap and receive only a short migration window, after which reauthentication is required.

### 5.6 MFA assurance lifecycle

- Record MFA assurance on the session with `mfa_verified_at` and `mfa_expires_at`.
- `/api/mfa/phone/verify` upgrades the existing `sid`; it must not create a new absolute session.
- Refresh and request authorization downgrade expired `aal2` to `aal1` or return `MFA_REQUIRED` for protected roles/actions.
- Removing/deactivating the factor immediately increments session generation or clears MFA assurance for all affected sessions.
- A tenant `enforce_2fa` or privileged-role change is checked against current database policy, not only token claims.
- High-risk operations may require a shorter step-up window than ordinary session MFA; encode the assertion time and enforce the route policy server-side.
- Never extend `mfa_expires_at` through token refresh. Only a new successful challenge may extend it.

The current user-level `MfaPhoneFactor.verified_until` can support compatibility, but session assurance must be explicit so one verification cannot ambiguously elevate unrelated devices/sessions unless that is an approved policy.

### 5.7 Request-time validation and revocation

For each protected request:

- validate JWT signature, algorithm, `kid`, issuer, audience, `exp`, `nbf`, `iat`, `jti`, tenant, and required typed claims;
- load a compact session status/generation record from Redis, backed by Postgres;
- require the JWT `sid`, tenant/user, and `sg` to match the active session;
- enforce absolute/idle expiry and current tenant/user status;
- enforce current membership/role generation for sensitive operations;
- reject deleted/quarantined tenants and projects in coordination with TS-ISO-011.

Use a short Redis cache for active state plus an immediate invalidation channel. A Redis outage must not cause revoked or unknown sessions to be treated as valid; use a bounded Postgres fallback or fail closed according to route risk.

Revocation operations:

- current session logout;
- all sessions for current user;
- administrator revoke one user in one tenant;
- tenant-wide revoke;
- revoke on user disable/removal, password reset, factor removal, role/membership change, SSO/LDAP disable, tenant deletion, or compromise detection.

### 5.8 Browser and CSRF handling

- Move refresh credentials to a secure HttpOnly cookie.
- Keep short-lived access tokens in memory; remove `tablescope.token` from `localStorage` after migration.
- If cookies authenticate state-changing requests, add CSRF protection using same-site policy plus an origin check and synchronizer/double-submit token as appropriate.
- Use `credentials: 'include'` only for the API origin and never send credentials to connector/customer URLs.
- Coordinate refresh across browser tabs with `BroadcastChannel` and a single-flight lock; tenant ID and `sid` must match before adopting refreshed state.
- Clear memory, cookie, cached user metadata, service-worker data, and Supabase state on logout or terminal session error.
- Apply `Cache-Control: no-store` to token/refresh responses and avoid bearer tokens in response headers after migration.
- Keep access and refresh tokens out of URLs, logs, analytics, crash reports, and browser error telemetry.

## 6. Implementation work breakdown

### Phase A — Session persistence and issuance

1. Add `AuthSession` and hashed rotating refresh-token models/migration.
2. Add a session service for creation, typed claim issuance, validation, rotation, revocation, and expiry.
3. Update Supabase, SSO, LDAP, direct login, and token exchange to create exactly one session.
4. Set `sid`, `jti`, `ses`, `auth_time`, `sg`, and authoritative MFA timestamps on initial issuance.
5. Add production startup validation for signing secrets/keys and session configuration.

### Phase B — Refresh and MFA correctness

1. Replace `/auth/refresh` claim cloning with transactional refresh-cookie rotation.
2. Update MFA verification to elevate the existing server session and preserve its immutable start/expiry.
3. Recompute/downgrade MFA on refresh and protected requests.
4. Cap every access token's `exp` at `absolute_expires_at`.
5. Add consumed-token reuse detection and family compromise revocation.

### Phase C — Request validation and revocation

1. Update middleware/context to require session ID/generation for user tokens.
2. Add Redis/Postgres active-session lookup and immediate invalidation.
3. Add logout, all-device logout, session inventory, and admin revocation endpoints.
4. Wire revocation to user/tenant/factor/membership/password/identity lifecycle events.
5. Integrate tenant deletion quarantine/revocation with TS-ISO-011.

### Phase D — Web migration

1. Add credentialed refresh-cookie handling and single-flight tab coordination.
2. Move access token storage from `localStorage` to memory.
3. Add CSRF and strict origin validation for cookie-authenticated operations.
4. Replace `X-Session-Token` adoption with explicit refresh results.
5. Verify logout clears all first-party and Supabase session state.

### Phase E — Enforcement and cleanup

1. Support old no-`sid` tokens only for a short, fixed migration window bounded by original `iat`.
2. Enable strict server-session validation for all protected routes.
3. Remove stateless `renew_access_token`, response-header renewal, and legacy localStorage bearer persistence.
4. Add cleanup jobs for expired/revoked refresh rows and policy-compliant session evidence retention.
5. Exercise key rotation, compromise, revocation, failover, and rollback runbooks.

## 7. Expected file changes

| Area | Files |
|---|---|
| Models/migration | new `platform-api/app/models/auth_session.py`, model exports, new Alembic revision |
| JWT/session service | `platform-api/app/auth/jwt.py`, new `app/services/auth_session_service.py`, signing-key/JWKS support |
| Middleware/context | `platform-api/app/auth/middleware.py`, `context.py`, membership and MFA policy dependencies |
| Auth routes | `platform-api/app/routes/auth.py`, SSO/LDAP exchange routes, new session/logout routes |
| MFA | `platform-api/app/routes/mfa.py`, `mfa_phone_service.py`, factor-removal/revocation paths |
| Configuration | `platform-api/app/config.py`, environment templates, secret/key deployment validation |
| User/tenant lifecycle | user disable/removal, membership/role changes, password reset, tenant deletion orchestration |
| Web auth | `web-ui/lib/auth.ts`, `web-ui/lib/api-client.ts`, Supabase callbacks, login/logout/session coordination |
| Tests | JWT/session, refresh concurrency/reuse, MFA expiry, revocation, browser storage, CSRF, multi-tenant matrix |
| Operations | session/key rotation, compromise response, revocation, migration, monitoring, and rollback runbooks |

Exact paths and the Alembic revision must be confirmed against the repository head when implementation begins.

## 8. API behavior

Recommended endpoints:

```text
POST   /api/auth/refresh                 # rotating HttpOnly refresh cookie
POST   /api/auth/logout                  # revoke current sid and expire cookie
POST   /api/auth/logout-all              # revoke caller's tenant sessions
GET    /api/auth/sessions                # redacted current-user session inventory
DELETE /api/auth/sessions/{sid}          # revoke caller-owned session
POST   /api/admin/users/{id}/revoke-sessions
POST   /api/admin/tenants/{id}/revoke-sessions
```

Requirements:

- Login/exchange sets the refresh cookie and returns a short-lived access token plus redacted session metadata.
- Refresh never accepts tenant, user, role, `aal`, `ses`, expiry, or permissions from the request body.
- Logout is idempotent and attempts server revocation even if the browser access token is expired.
- Session inventory exposes device label, coarse last activity, creation, expiry, and current-session indicator without token material or raw IP/user-agent data.
- Administrative revocation requires current MFA/step-up and produces an immutable audit event.

## 9. Test plan

### Absolute lifetime and refresh tests

- Login, exchange, refresh, automatic renewal during migration, and MFA upgrade all preserve the same `sid`, `ses`, `created_at`, and `absolute_expires_at`.
- Repeated refresh immediately before expiry cannot move the absolute deadline.
- Access-token `exp` never exceeds session absolute expiry.
- Legacy tokens without `sid` cannot create a fresh full-lifetime session.
- Clock-skew boundaries, expired sessions, idle sessions, and malformed timestamps fail safely.

### Rotation and concurrency tests

- A refresh token is consumed exactly once and replaced atomically.
- Reuse of a consumed token revokes the family and forces full login.
- Two concurrent tabs produce one valid descendant without false compromise under the documented grace/idempotency rule.
- Database/Redis failures cannot result in two uncontrolled refresh descendants.
- Refresh tokens are stored only as keyed hashes and never appear in logs or responses outside the secure cookie.

### MFA tests

- `aal2` survives refresh only until the authoritative session/factor expiry.
- Expired MFA downgrades to `aal1`; protected admin routes return `MFA_REQUIRED`.
- MFA verification elevates the current session without changing its absolute start.
- Removing/deactivating a factor removes MFA assurance from every affected session promptly.
- Tenant `enforce_2fa`, role elevation, and shorter high-risk step-up policy are checked from current records.
- A copied token with stale `aal2` is rejected/downgraded after server-side assertion expiry.

### Revocation and isolation tests

- Logout immediately rejects the current access and refresh token.
- Logout-all and admin revocation affect the correct tenant/user only.
- Disabling a user, removing membership, password reset, SSO/LDAP disable, or tenant deletion revokes the correct sessions.
- A `sid` from Tenant A combined with Tenant B claims is rejected.
- Session caches cannot return another tenant's state and invalidation reaches all API replicas.
- Redis outage behavior matches the documented fail-closed/Postgres fallback policy.

### Browser tests

- Refresh cookie has `HttpOnly`, `Secure`, correct `SameSite`, narrow path, and host-only attributes.
- Refresh and cookie-authenticated state changes reject cross-site requests and invalid origins/CSRF tokens.
- Access/refresh tokens do not remain in `localStorage`, sessionStorage, URLs, logs, analytics, or service-worker caches.
- Multiple tabs coordinate refresh and cannot overwrite a different tenant/session.
- Logout clears TableScope and Supabase state and redirects to the correct tenant login.

## 10. Deployment sequence

1. Deploy session/refresh tables, signing-key support, cleanup jobs, and monitoring with current tokens still accepted.
2. Start creating server sessions and `sid` claims on every new login/exchange; issue secure refresh cookies to a canary cohort.
3. Change `/auth/refresh` and MFA upgrade to the server-session service; verify immutable lifetime and current MFA decisions.
4. Enable request-time session validation for canary tenants and exercise revocation across all API replicas.
5. Migrate the web client to memory access tokens, credentialed refresh, CSRF protection, and cross-tab coordination.
6. Shorten the access-token TTL to the approved value after refresh reliability is demonstrated.
7. Expire the fixed legacy-token migration window and require `sid` on all user tokens.
8. Remove stateless middleware renewal, `X-Session-Token`, and `localStorage` bearer persistence.
9. Rotate signing keys/secrets and run reuse-detection, compromise, absolute-expiry, MFA-expiry, and tenant-revocation drills.

Monitor active sessions, refresh success/failure, reuse detections, revocation propagation, MFA downgrades, clock skew, Redis/Postgres latency, and forced reauthentication rate throughout rollout.

## 11. Rollback

- Roll back client code only while the server supports the immediately previous cookie/session contract; retain server session records and absolute expiry.
- If refresh is degraded, require reauthentication rather than extending sessions from JWT claims alone.
- Do not restore `/auth/refresh` claim cloning, stale `aal` propagation, indefinite automatic renewal, or new `localStorage` refresh secrets.
- A rollback must never reset `created_at`, `absolute_expires_at`, or a revoked/compromised session.
- Keep verification keys for already-issued short-lived access tokens during a bounded signing-key rollback; never restore a compromised signing key.

## 12. Acceptance criteria

- [ ] Every new user token contains `sid`, `jti`, `ses`, `sg`, and bounded assurance timestamps derived from a server session.
- [ ] Login, exchange, explicit refresh, automatic migration renewal, and MFA upgrade preserve one immutable absolute-session boundary.
- [ ] Repeated refresh cannot extend absolute TTL or stale MFA assurance.
- [ ] Refresh credentials rotate atomically, are stored hashed, and family reuse causes revocation.
- [ ] Access tokens are rejected promptly after session, user, membership, tenant, or factor revocation.
- [ ] MFA policy and expiry are checked from current server state for protected requests.
- [ ] Refresh credentials are secure HttpOnly cookies and browser bearer tokens no longer persist in `localStorage` after migration.
- [ ] CSRF, origin, multi-tab, and tenant/session-adoption tests pass.
- [ ] No token, signing secret, raw IP, or sensitive session payload appears in logs or analytics.
- [ ] Key rotation, revocation propagation, compromise response, and dependency-failure runbooks are exercised.

TS-ISO-013 must remain open until repeated-refresh, MFA-expiry, refresh-reuse, immediate-revocation, multi-tab, and two-tenant production-like tests pass and the legacy stateless renewal paths have been removed.

## 13. Validation addendum

All nine current-state findings in Section 2 (JWT claim shape, `renew_access_token()`, `/api/auth/refresh`, `/api/mfa/phone/verify`, login/exchange claim issuance, `MfaPhoneFactor.verified_until`, stateless tokens with no revocation, `localStorage`/`X-Session-Token` handling, and the absence of a rotating refresh-token family) were independently re-verified line-by-line against `platform-api/app/auth/jwt.py`, `app/routes/auth.py`, `app/routes/mfa.py`, `app/services/mfa_phone_service.py`, `web-ui/lib/api-client.ts`, and confirmed **accurate** in every case. Two clarifications worth noting for implementers:

- `create_access_token`'s module docstring (`jwt.py:1-12`) does not mention the `aal`/`ses` claims it actually supports — worth a doc-comment fix alongside this work, not a blocker.
- `MfaPhoneFactor.verified_until`-derived `aal` (via `mfa_aal_for_user`) is wired into `/auth/login` and `/auth/exchange` only. It is not consulted by `/auth/refresh` or `renew_access_token`, which is the exact mechanism by which stale `aal2` survives renewal (Section 2's "MFA assurance" row) — `app/services/mfa_phone_service.py` (already in Section 7's file table) is the load-bearing file for closing that gap and should be called out explicitly in Section 5.6's task list, not just implied by "recompute/downgrade MFA on refresh."

Two files touch first-party token issuance/handling and are missing from Section 7's file table; add them:

- **`web-ui/lib/api/voice.ts`** — duplicates its own `TOKEN_KEY = "tablescope.token"` constant and reads the bearer token directly via raw `fetch()`, bypassing `api-client.ts`'s `request()`/`streamRequest()` helpers entirely. A renewed token returned via `X-Session-Token` on a `/api/ai/speech/transcribe` call is silently dropped, so a long voice-transcription session never slides its renewal window the way every other API call does. Any migration to memory-only token storage or cookie-based refresh (Section 5.8) must also update this file or it will keep reading a token that no longer exists in `localStorage`.
- **`platform-api/app/main.py`** — registers `SESSION_TOKEN_HEADER` ("X-Session-Token") in `CORSMiddleware(expose_headers=[...])`. Any change to the renewal-delivery mechanism (e.g. moving to a cookie per Section 5.8) requires updating this wiring too; it is the one place outside `middleware.py` that the current header-based renewal contract touches.

No claim in Section 2 was found to be inaccurate or overstated.
