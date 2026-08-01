# TableScope Devin-Ready Plan: Restore Tenant-Wide 2FA Enforcement (Validated)

## Validation summary

The attached plan's technical diagnosis was checked line-by-line against
`origin/devin/r-echarts-e2e-validation` (current deployed lineage, HEAD
`a1969ff`). **It is unusually accurate.** Every specific code claim in the
"Confirmed code facts" section checks out exactly as described. This is a
validated, lightly-corrected, and file/line-grounded version of that plan —
the objective, required-behavior table, and almost all implementation
guidance are preserved unchanged. Corrections below are additions and
precision, not reversals.

### Confirmed exactly as claimed

- `Tenant.enforce_2fa` exists (`platform-api/app/models/tenant.py:43`).
- `membership.py` fetches the tenant row on every protected request and
  computes `tenant_enforce_2fa` (`membership.py:78-80`).
- **The core bug is real and verified**: `membership.py:81-89` gates the
  *entire* MFA check — role policy AND tenant policy — behind
  `get_settings().mfa_enforcement_enabled`:
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
  When `mfa_enforcement_enabled` is `False` (the default), this `and` chain
  short-circuits and `mfa_required_for_request` is **never called**,
  regardless of `tenant.enforce_2fa`. `mfa_policy.mfa_required_for_request`
  itself (`mfa_policy.py:48-63`) does NOT reference the master switch at
  all — the switch is entirely membership.py's/mfa.py's responsibility to
  apply, and both currently apply it to the tenant policy when they should
  only apply it to the role policy.
- `routes/mfa.py:117-124` (`/api/mfa/status`) has the identical bug:
  `tenant_requires = settings.mfa_enforcement_enabled and bool(tenant.enforce_2fa ...)`.
- `mfa_enforcement_enabled` defaults `False` in `config.py:264`.
- `docker-compose.yml:100`: `MFA_ENFORCEMENT_ENABLED: ${MFA_ENFORCEMENT_ENABLED:-false}`.
- `.env.example` and `platform-api/.env.example` both exist and contain
  **zero** references to `MFA` (confirmed via grep — the plan's claim that
  "the root and platform API environment templates do not declare the
  variable" is exactly right).
- `platform-api/tests/test_mfa.py:47-54` has an `autouse=True` fixture that
  force-sets `MFA_ENFORCEMENT_ENABLED=true` for every test in the file —
  confirmed verbatim, this is exactly why the suite doesn't catch the
  production-default failure mode.
- `platform-api/tests/test_settings.py`'s `test_current_2fa_toggle_and_audit`
  (line 134) only asserts the toggle's returned value flips
  (`assert r.json()["enabled"] is not initial`) — it never makes a
  subsequent protected request as a different, regular tenant member to
  confirm enforcement actually happened. Confirmed exactly as claimed.
- `web-ui/components/auth/mfa-gate.tsx`: confirmed one-time check via a
  `checked` ref (`useRef(false)`) gating the effect — its own comment
  states "enforcement also exists on the backend, so this is purely a UX
  redirect." Matches the plan's framing precisely.
- `DELETE /api/mfa/phone` (`routes/mfa.py:288-299`) checks only
  `settings.mfa_enforcement_enabled and role_requires_mfa(role)` — it never
  reads `tenant.enforce_2fa`. A non-privileged member of a tenant with
  `enforce_2fa=true` can delete their own MFA factor with no check at all.
  Confirmed exactly as claimed.
- `_is_mfa_exempt` (`membership.py:29-38`) uses `path.startswith(prefix)`
  over `("/api/auth/me", "/api/users/me", "/api/mfa", "/api/auth/logout")`
  — confirmed real prefix-collision risk (e.g. a future `/api/users/metrics`
  route would incorrectly become MFA-exempt).
- `security-settings-panel.tsx`: confirmed two real bugs beyond what the
  plan lists —
  1. `const enforce2fa = twoFaQuery.data?.enabled ?? false;` — while
     `twoFaQuery` is loading (`data` is `undefined`), this silently
     evaluates to `false`, so the switch renders **"Off" during the
     loading state**, exactly the bug the plan calls out.
  2. `toggle2fa`'s `onSuccess` only calls `queryClient.setQueryData(...)`
     for two cache keys (`["settings","security","2fa"]` and
     `["settings","tenant"]`) — it never invalidates
     `/api/mfa/status`. A member who already has the settings page's MFA
     status cached would not see it refresh after an admin flips the
     tenant policy in the same session.
  3. Confirmed literal copy: `"...required to complete SMS MFA at their
     next sign-in."` — factually wrong per the required-behavior table
     (an existing AAL1 session is blocked on its *next protected request*,
     not "next sign-in"). Confirmed exactly as claimed.
  4. The plan's "if the server rejects enablement... restore the prior
     value" concern does not actually apply here: the switch's checked
     state is derived purely from `twoFaQuery.data` (no optimistic local
     state is set before the mutation resolves), so there is nothing to
     "restore" on error — the switch already reflects the last-confirmed
     server value. Drop this specific sub-requirement; it describes a bug
     pattern (optimistic-update-then-rollback) that isn't present in this
     component.
- `require_role(Role.ADMIN)` gates both `set_current_enforce_2fa` and
  `set_enforce_2fa` (`routes/tenants.py:649,680`) — confirmed **no AAL2
  check and no Twilio-readiness check** before accepting `enabled: true`.
  This is a real, currently-exploitable footgun: with the master-switch
  fix applied (below), an admin without a verified phone (or with Twilio
  misconfigured) could flip `enforce_2fa=true` and lock out the entire
  tenant — including themselves — on the very next request.

### One concrete implementation shortcut found (reduces the plan's scope)

`platform-api/app/services/twilio_verify_service.py:29-34` already exposes
`settings.twilio_verify_configured` (a `bool` property) and raises
`TwilioConfigError` when Twilio Verify isn't configured. **Devin does not
need to build a new readiness probe** — `_set_enforce_2fa` in
`routes/tenants.py` just needs to check `get_settings().twilio_verify_configured`
before accepting `payload.enabled is True` and return `503` if it's `False`.

### No conflicting in-flight work

Confirmed no other branch is currently touching this: `git branch -a | grep
-i "2fa\|mfa"` shows only `devin/chart-suggestion-shape-cache-sidebar-2fa`
and `devin/tenant-2fa-insight-parity`, both already named in the plan as
historical/do-not-deploy-from branches. No correction needed to that
guidance.

---

## Everything below is the original plan, preserved as validated

The objective, repository/branch instructions, required-behavior table,
8-section implementation plan, files-expected-to-change list, validation
commands, production deployment/smoke-test steps, acceptance criteria,
rollback plan, and Devin completion-report checklist from the source
document are **all confirmed accurate and should be followed as written**,
with the two amendments below folded in.

### Amendment 1 — narrow the master-switch fix precisely

Section "2. Make the tenant database policy authoritative" already
specifies the correct target state:

```python
requires_mfa = tenant_requires_mfa or role_requires_effective_mfa
blocked = requires_mfa and not session_has_mfa(aal)
```

Concretely, this means in `membership.py`:

```diff
-    if (
-        get_settings().mfa_enforcement_enabled
-        and not _is_mfa_exempt(request.url.path)
-        and mfa_required_for_request(
-            user.role, context.aal, tenant_enforce_2fa=tenant_enforce_2fa
-        )
-    ):
+    role_requires_effective = (
+        get_settings().mfa_enforcement_enabled and role_requires_mfa(user.role)
+    )
+    if (
+        not _is_mfa_exempt(request.url.path)
+        and not session_has_mfa(context.aal)
+        and (tenant_enforce_2fa or role_requires_effective)
+    ):
         raise MfaRequiredError
```

and in `routes/mfa.py`:

```diff
-    role_requires = settings.mfa_enforcement_enabled and role_requires_mfa(role)
+    role_requires = settings.mfa_enforcement_enabled and role_requires_mfa(role)
     ...
-    tenant_requires = (
-        settings.mfa_enforcement_enabled
-        and bool(tenant.enforce_2fa if tenant else False)
-    )
+    tenant_requires = bool(tenant.enforce_2fa if tenant else False)
```

(`role_requires` line is unchanged — the master switch correctly continues
to gate *only* the role-based policy, per the plan's own stated intent
that `MFA_ENFORCEMENT_ENABLED` controls privileged-role platform policy,
not tenant policy.)

And `DELETE /api/mfa/phone` (`routes/mfa.py:288-299`):

```diff
     settings = get_settings()
     user = await session.get(User, context.user_id)
     role = (user.role if user else context.role) or "viewer"
-    if settings.mfa_enforcement_enabled and role_requires_mfa(role):
+    tenant = await session.get(Tenant, context.tenant_id)
+    tenant_requires = bool(tenant.enforce_2fa if tenant else False)
+    if tenant_requires or (settings.mfa_enforcement_enabled and role_requires_mfa(role)):
         raise HTTPException(
             status_code=400,
-            detail="SMS verification is required for your role and can't be removed.",
+            detail="SMS verification is required by tenant or role policy and can't be removed.",
         )
```

### Amendment 2 — reuse `twilio_verify_configured`, don't build a new probe

In section "4. Prevent unsafe enablement and fail closed on configuration
drift," replace "verify Twilio Verify configuration is complete" with a
concrete call site:

```diff
 async def _set_enforce_2fa(
     session: AsyncSession,
     context: RequestContext,
     tenant_id: int,
     payload: Enforce2faSettingsUpdate,
 ) -> Enforce2faSettingsResponse:
     tenant = await session.get(Tenant, tenant_id)
     if tenant is None:
         raise HTTPException(status_code=404, detail="Tenant not found")
+    if payload.enabled and not get_settings().twilio_verify_configured:
+        raise HTTPException(
+            status_code=503,
+            detail="Two-factor authentication cannot be enabled: the SMS "
+                   "provider is not configured for this deployment.",
+        )
+    if payload.enabled and context.aal != "aal2":
+        raise HTTPException(
+            status_code=409,
+            detail="Verify your own phone (step-up authentication) before "
+                   "requiring 2FA for the rest of the tenant.",
+        )
     old_value = tenant.enforce_2fa
     ...
```

This is also where "production readiness check: if any tenant has
`enforce_2fa=true` while the MFA provider is not configured" (the
degraded-health-state requirement) becomes moot for *new* enablement — the
pre-check above prevents that state from being created going forward. The
health check still has value for tenants that already have
`enforce_2fa=true` today from before this fix ships (Twilio was never
configured, or later becomes misconfigured) — keep that part of the plan
as written, scoped to catching pre-existing/drifted state rather than
duplicating the enable-time check.

### Amendment 3 — settings-panel fixes, precise diff

Section "5. Make the Settings UI reflect confirmed server state" —
concrete diff against the actual component:

```diff
-  const enforce2fa = twoFaQuery.data?.enabled ?? false;
+  const enforce2fa = twoFaQuery.data?.enabled ?? undefined;
```

and render `Off`/switch only when `enforce2fa !== undefined` (or keep a
loading skeleton until then) — do not fall back to `false` as the loading
placeholder.

```diff
     onSuccess: (data) => {
       queryClient.setQueryData(["settings", "security", "2fa"], data);
       queryClient.setQueryData<{ enforce_2fa: boolean } | undefined>(
         ["settings", "tenant"],
         (old) => (old ? { ...old, enforce_2fa: data.enabled } : old),
       );
+      queryClient.invalidateQueries({ queryKey: ["mfa", "status"] });
       push(...)
```

(Confirm the exact query key `web-ui/lib/mfa.ts`'s `useMfaStatus`/
`getMfaStatus` caller uses — invalidate that key, not a guessed one.)

Copy fix:

```diff
-      "All members of this tenant will be required to complete SMS MFA at their next sign-in."
+      "All members of this tenant — including anyone already signed in — will be required to complete SMS MFA on their next action."
```

Drop the "restore prior value on error" requirement (Amendment above
explains why — no optimistic update exists to roll back).

### Everything else

Sections 3 ("Align membership enforcement and MFA status"), 6 ("Add a
global client response handler"), 7 ("Correct the test architecture"), 8
("Add observability and audit evidence"), the files-expected-to-change
list, validation commands, production deployment/smoke-test steps,
acceptance criteria, rollback plan, and Devin completion-report checklist
are unchanged from the source document — implement exactly as specified
there. In particular, the 12-item backend test matrix and 7-item frontend
test matrix in section 7 correctly target the real bugs found above (e.g.
test #2 "`/api/mfa/status` -> `tenantRequiresMfa=true`... regardless of
`MFA_ENFORCEMENT_ENABLED=false`" is precisely what Amendment 1 fixes).

## Branch / PR

Branch: `devin/restore-tenant-2fa-enforcement`, based on
`origin/devin/r-echarts-e2e-validation` (HEAD `a1969ff` at validation
time — rebase onto the current head before opening the PR, per the
source plan's own instruction). This doc is the only change on the
branch; Devin implements per the source plan plus the three amendments
above.
