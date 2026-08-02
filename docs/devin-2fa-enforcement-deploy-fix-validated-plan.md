# Devin-ready plan: fix 2FA enforcement (deploy mismatch + master-switch config)

## Symptom

Tenant admin turns on "require 2FA for all members" (the `enforce_2fa`
tenant toggle) and nothing is enforced for anyone — not members, not admins.

## Root cause (confirmed by direct code comparison, not assumed)

This is **not a bug in the current `devin/r-echarts-e2e-validation` code** —
it's a live deployment running an older/wrong commit. Proof:

`platform-api/app/auth/membership.py` has two different versions across
branches in this repo:

- **`devin/r-echarts-e2e-validation` (current tip, `145dadd`) — correct:**
  ```python
  role_requires_effective = (
      get_settings().mfa_enforcement_enabled and role_requires_mfa(user.role)
  )
  if (
      not _is_mfa_exempt(request.url.path)
      and not session_has_mfa(context.aal)
      and (tenant_enforce_2fa or role_requires_effective)
  ):
      raise MfaRequiredError
  ```
  The tenant toggle (`tenant_enforce_2fa`) is authoritative on its own —
  it's OR'd in, so it works regardless of the master switch.

- **`devin/data-source-builder-url-unc-imports` (an older sibling branch,
  cut before the 2FA restore work landed) — buggy:**
  ```python
  if (
      get_settings().mfa_enforcement_enabled
      and not _is_mfa_exempt(request.url.path)
      and mfa_required_for_request(
          user.role, context.aal, tenant_enforce_2fa=tenant_enforce_2fa
      )
  ):
      raise MfaRequiredError
  ```
  Here `mfa_enforcement_enabled` is AND'ed across the **entire** check,
  including the tenant toggle. `mfa_enforcement_enabled` defaults to `False`
  (env `MFA_ENFORCEMENT_ENABLED`, unset in most environments — the config
  comment literally says "flip to true once MFA is fully provisioned"). On
  this version, with the switch off, turning on the tenant toggle does
  nothing, and admin-only enforcement doesn't fire either — exactly the
  reported symptom.

I ran the identical request (`tenant.enforce_2fa=True`, member role, `aal1`
token, `MFA_ENFORCEMENT_ENABLED` unset) against both branches' code directly:
200 OK on the buggy version, 403 `MFA_REQUIRED` on the fixed version. The fix
(`591db9a`, merged via PR #114) is already on `devin/r-echarts-e2e-validation`
and has three dedicated regression tests covering exactly this interaction
(`test_tenant_enforce_2fa_blocks_member_aal1_with_master_switch_off`,
`test_mfa_status_tenant_requires_ignores_master_switch_off`,
`test_remove_phone_blocked_when_tenant_enforces_2fa` in
`platform-api/tests/test_mfa.py`), all currently passing.

**No code change is needed for this.** The problem is entirely "what's
actually running in production."

## Steps

### 1. Confirm what's actually deployed

On the app server, in the live checkout directory (per the existing
`deploy_*.sh` scripts, this is `/home/ubuntu/tablescope`):

```bash
cd /home/ubuntu/tablescope
git rev-parse HEAD
git merge-base --is-ancestor 591db9a HEAD && echo "HAS the 2FA fix" || echo "MISSING the 2FA fix"
```

If that says "MISSING," confirm directly by checking which version of the
check is actually live:

```bash
git show HEAD:platform-api/app/auth/membership.py | grep -A3 "get_settings().mfa_enforcement_enabled"
```

If `mfa_enforcement_enabled` appears as its own top-level `and` clause
(not nested inside `role_requires_effective`), that's the buggy version.

### 2. Redeploy from a commit that has the fix

The fix has been on `devin/r-echarts-e2e-validation` since `591db9a` (PR
#114) — no need to wait on anything else to get this specific issue fixed.
Redeploy from that branch's current tip:

```bash
cd /home/ubuntu/tablescope
git fetch origin devin/r-echarts-e2e-validation
git checkout devin/r-echarts-e2e-validation
git reset --hard origin/devin/r-echarts-e2e-validation
git rev-parse --short HEAD
sudo docker compose build platform-api web-ui
sudo docker compose up -d platform-api platform-api-worker web-ui
sleep 8
sudo docker compose exec -T platform-api alembic upgrade head
sudo docker compose exec -T platform-api alembic current
```

(If PR #120 — `claude/consolidate-demo-refresh-and-slot-fix` — has merged by
the time this runs, deploy from `devin/r-echarts-e2e-validation` after that
merge instead; it includes this same 2FA fix plus the demo-refresh and
tenant-slot-TTL fixes from the same investigation, so one redeploy covers
all of it.)

### 3. Set the master switch — required for the "admin-only when toggle is
   off" half of the original ask

The tenant toggle now works independently of `MFA_ENFORCEMENT_ENABLED`
once step 2 lands. But the *other* half of what was asked for — "when the
toggle is off, it should go back to enforcing only for admin users" — is
gated by that same master switch on purpose (`role_requires_effective =
mfa_enforcement_enabled and role_requires_mfa(role)`), so admins are never
locked out before Twilio is provisioned. If `MFA_ENFORCEMENT_ENABLED` is
still unset in the live `.env`, admin-only fallback enforcement will stay
off even after this redeploy — only the tenant-wide toggle will work.

Check the live `.env` for the app server:
```bash
grep MFA_ENFORCEMENT_ENABLED /home/ubuntu/tablescope/.env
```
If it's missing or `false`, and Twilio Verify is already configured and
working (it should be — SMS OTP is a shipped feature), set:
```
MFA_ENFORCEMENT_ENABLED=true
```
then recreate `platform-api`/`platform-api-worker` so the new env value is
picked up:
```bash
sudo docker compose up -d platform-api platform-api-worker
```

### 4. Verify live, both states of the toggle

With a real (non-admin) member account and a real admin account:

- **Tenant toggle ON**: `PUT /api/tenants/current/2fa-enforcement {"enabled": true}` as
  an admin, then confirm a *member* hitting any non-exempt route
  (e.g. `GET /api/projects`) with an `aal1` session gets `403
  {"error": "MFA_REQUIRED"}`.
- **Tenant toggle OFF**: `PUT ... {"enabled": false}`, then confirm a member
  with `aal1` can access normally, but an *admin/owner/db_admin* with `aal1`
  still gets `403 MFA_REQUIRED` (this is the part that depends on step 3).
- In both cases, completing SMS verification (`POST /api/mfa/phone/verify`)
  should clear the block and let the same request through.

## What NOT to do

- Don't touch `platform-api/app/auth/membership.py`, `mfa_policy.py`, or
  `mfa_errors.py` — they're already correct on `devin/r-echarts-e2e-validation`.
  Rewriting them risks reintroducing a bug rather than fixing one.
- Don't merge or deploy from `devin/data-source-builder-url-unc-imports`
  directly — it's the branch confirmed to carry the buggy version of this
  file. It was already merged into `r-echarts-e2e-validation` via PR #116
  without touching `membership.py`, so `r-echarts-e2e-validation` itself is
  safe to deploy from; it's only that standalone branch that isn't.
