# Enterprise Authentication Spike

**Branch:** `devin/tenant-ldap-sso-enterprise-auth`  
**Base:** `origin/devin/r-echarts-e2e-validation` @ `84684dd4`

## Current authentication flow

1. Tenant slug (`/{slug}` or `/{slug}/login`) is rendered by `TenantLogin` (`web-ui/components/auth/tenant-login.tsx`).
2. Browser collects email/password and calls `supabase.auth.signInWithPassword` (`web-ui/lib/auth.ts`).
3. On success, the Supabase access token is sent to `POST /api/auth/exchange` (`platform-api/app/routes/auth.py::exchange_token`).
4. `exchange_token` verifies the Supabase RS256 token (`app/auth/clerk.py::verify_external_token(provider="supabase")`).
5. It looks up the local `User` by a strict `User.external_id == external_user_id` match, scoped to `tenant_slug` if supplied.
6. If no `User` matches, it returns `403 "User does not belong to requested tenant"` (tenant-scoped) or `404 "No platform-api user linked to external id ..."`.
7. Once a `User` is found, `mfa_phone_service.mfa_aal_for_user(session, user.id)` is called. If the user has completed Twilio Verify phone verification within the configured window, the token is minted with `aal: "aal2"`; otherwise `aal` is omitted.
8. `create_access_token` (`app/auth/jwt.py`) mints a first-party HS256 token carrying `sub`, `tenant_id`, `user_id`, `role`, `permissions`, and `aal`.
9. `require_membership` (`app/auth/membership.py`) revalidates the user/tenant on every protected request and enforces tenant 2FA (`tenant.enforce_2fa`) and admin-tier MFA via `mfa_phone_service`.

## Key finding: identity-linking gap

`exchange_token` has no path for "this is the same person, authenticating with a new provider/identity". When a user first authenticates via Supabase SAML, Supabase will return a brand-new `sub` UUID that does not match the existing `User.external_id` for that email. The current strict lookup will fail closed. This is why the `user_auth_identities` table is required.

## MFA/assurance

MFA is derived entirely by `mfa_phone_service.mfa_aal_for_user()` keyed on the platform `User.id`. There is no Supabase-native MFA enrollment or per-identity MFA factor. Once an SSO/LDAP identity is linked to the correct `User.id`, the existing `aal2` check applies automatically.

## Existing patterns to reuse

- `tenants_security_policy.py`: `current`-before-`/{tenant_id}` route ordering, `aal2` step-up guard, `AuditEvent` logging.
- `network_file_connection.py` / migration `0079`: schema template for `ldap_connections` and Fernet column encryption via `crypto.py`.
- `repository_scanner.py`: durable, tenant-scoped, idempotent background-job pattern.
- `tenant_data_planes.py`: VPN/private-network reachability primitive.
- `TenantAuthBinding` / `SupabaseAuthService.link_local_user`: identity-binding precedent.

## Open questions for later phases

- LDAP sync engine needs a real AD/LDAP server or a disposable Samba/AD container for integration tests.
- SSO start/callback needs the exact Supabase SAML `signInWithSSO` / `auth.exchangeCodeForSession` flow and the server-side provider-creation boundary.
- Supabase provider management endpoint and metadata validation.

## Decision

Proceed with Phase 1 (models, migrations, identity linking, settings foundation) and Phase 2/4 endpoints as stubs that fail closed until the external IdP/LDAP integrations are validated.
