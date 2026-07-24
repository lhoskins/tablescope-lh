# Devin plan: tenant 2FA enforcement, Business-Insight page height fix, Project-Insight parity + governance

Repository: `lhoskins/tablescope-lh`
Base: the current integrated/deployed lineage (`devin/r-echarts-integration` or its
merged successor — confirm it has the R provenance badge + ECharts before
starting). Feature branch: `devin/tenant-2fa-insight-parity`.

Three independent items — may ship as one PR or three. Each is **additive**; do
not remove or rewrite existing working behavior. Land the branch into the deployed
lineage and redeploy so the changes actually show (don't strand it).

---

## 1) Tenant-wide 2FA enforcement (toggle in Tenant settings)

MFA already exists but is **role-based**, not tenant-controlled: `platform-api/app/auth/mfa_policy.py`
has `role_requires_mfa(role)` / `mfa_required_for_request(role, aal)` — today only
`tenant_admin`/`root_admin` must complete SMS MFA; Members are optional. There is
**no tenant flag** on the `Tenant` model. Add a tenant-level enforcement toggle.

**Enforcement semantics (exact):**
- **OFF (default):** unchanged from today — **admin/privileged accounts still
  require 2FA** (the existing role-based policy stays in force); Members remain
  optional. Turning the toggle off must never weaken admin 2FA.
- **ON:** the **entire organization** must log in with 2FA — every member of the
  tenant, regardless of role, requires an MFA-satisfied session. Admins remain
  required (superset of the OFF behavior).

Do:

- **Model + migration:** add `enforce_2fa` (boolean, default `false`,
  `server_default=false`) to `platform-api/app/models/tenant.py`. New Alembic
  revision **`0068`** (head is `0067`); additive column, reversible downgrade. Do
  not edit existing migrations.
- **Policy wiring:** extend `mfa_policy.mfa_required_for_request(...)` (and its
  callers/middleware in `app/main.py` / `app/auth/`) so that when the caller's
  tenant has `enforce_2fa = true`, **every** member (not just admins) must have a
  MFA-satisfied session (`aal2`) to reach tenant data/APIs. When the flag is off,
  behavior is exactly today's role-based policy. Keep the existing SMS phone-factor
  flow (migrations 0039/0040, `mfa_phone_factor`) as the enrollment path.
- **API:** an ADMIN-gated endpoint to read/update `enforce_2fa` for a tenant
  (extend the existing tenant admin route; audit the change).
- **UI:** add a **2FA enforcement toggle** to the tenant settings page
  `web-ui/app/admin/tenants/[id]/page.tsx` (a switch with a clear label/help:
  "Require two-factor authentication for all members"). Reflect current state;
  optimistic update + invalidate; ADMIN-only.
- **Enrollment UX:** when enforcement turns on, members without MFA must be routed
  to the existing SMS-MFA enrollment on next access rather than being locked out
  with no path — reuse the current MFA-required challenge flow.
- **Tests:** flag on → a Member request without `aal2` is challenged/blocked and a
  Member with `aal2` passes; flag off → current role-based behavior unchanged;
  toggle endpoint is ADMIN-only and audited; tenant isolation holds.

## 2) Business-Insight page height / scrolling

Symptom (from the page): the insight card list is **cut off** and you cannot
scroll to the last card when all panels are expanded; there should be **one**
scrollbar reaching the end.

Verified structure: the single intended scroll container is the app-shell
`<main className="flex-1 overflow-y-auto">`
(`web-ui/components/tablescope/app-shell.tsx:66`), inside
`<div className="flex min-h-0 flex-1 overflow-hidden">` (line 65). The
Business-Insight page (`web-ui/app/business-insight/page.tsx`, content wrapper
`space-y-10 py-6` ~line 188) renders the feed
(`web-ui/components/tablescope/home/intelligence-feed.tsx`).

Do:

- **Find and remove the clip.** Ensure exactly one scroll owner (the app-shell
  `main`). Look for a nested `overflow-*`/`max-h-*`/fixed-`h-*` on the
  business-insight page wrapper, the feed, or a card/panel container that caps
  height or introduces a second scrollbar, and remove/relax it so the content
  grows to its natural height.
- **Bottom reachability.** Add adequate bottom padding to the scroll content so
  the **last** card (with its panels expanded) is fully visible above the viewport
  edge — no final card clipped under the fold.
- **One scrollbar.** Confirm no inner scroll region competes with `main`; the page
  scrolls as a single column.
- **Test with all panels expanded:** expand every insight's Explain/Analysis
  details on a long list; confirm a single scrollbar, smooth scroll to the very
  last card, nothing cut off, at narrow and wide viewports. Re-check Home and other
  pages that share the app-shell to confirm no regression.

## 3) Project Insights = Business Insights (governance model + full card parity)

Two parts: give Project Insights the **same Analytical-Methods governance/execution
model** as Business Insights, and make Project-Insight cards **match** the
Business-Insight cards including all buttons/functions.

### 3a. Governance + method execution (so R/provenance exists on project cards)

Business Insights run the Analytical Method Engine during generation
(`home_intelligence._attach_method_envelopes` → `analyze()`; envelope carries
`executionEngine`, method, warnings). Project Insights currently do **not** run
`analyze()` for their cards — but `project_insight_service.py` already imports and
uses `ai_governance_service.evaluate_method` (line ~154), so the governance model
is partially present.

Do:
- Wire the Analytical Method Engine into Project-Insight card generation the same
  way Business Insights do it: run the governed method over each project insight's
  executed result set (reuse the `_attach_method_envelopes` pattern / the shared
  `analyze()` path), gated by `ai_governance_service.evaluate_method` (same
  governance model), so each project card carries an `analyticalMethod` envelope
  with real `executionEngine` (R-first with Python fallback) and provenance.
- Persist the envelope with the project-insight snapshot so it survives refresh
  (same as business insights).
- Keep it fail-closed per card (an engine problem must never drop a project card).

### 3b. Card parity (same buttons/functions)

Business card `IntelligenceCard` (`web-ui/components/tablescope/home/intelligence-card.tsx`)
has the full row: **Explain, Chart suggestion, R Analytics badge, Action, Agree,
Disagree, Add to dashboard**. Project card `InsightCardItem`
(`project-insight-screen.tsx`) already has **Explain, Agree, Disagree, Action**
(it uses `insight-feedback-dialog`/`-status` and `CreateActionFromInsightDialog`,
and already carries `card.analyticalMethod`), but is **missing Chart suggestion,
the R Analytics badge, and Add to dashboard** (verified: 0 matches for those in the
project screen).

Do:
- **Extract the shared card action row** (and the R Analytics badge, Chart
  suggestion control, and Add-to-Dashboard action) from `IntelligenceCard` into a
  reusable component/hook, and use it in `InsightCardItem` — so both card types
  render the **identical** button set and behavior (Explain, Chart suggestion,
  R Analytics badge when `analyticalMethod.executionEngine === "r"`, Action, Agree,
  Disagree, Add to dashboard). Prefer extraction over duplication so they cannot
  drift again.
- **Add to dashboard** on project cards should reuse the existing
  `save-insight-to-dashboard-modal` (defaulting to the project's dashboards).
- **Chart suggestion** reuses the same data-shape suggestion path as business
  insights (see the chart-intelligence plan) — the same six best charts.
- Keep the project-insight grouping (risk/trend/opportunity) and any
  project-specific context; only the action row + badge reach parity.
- Preserve existing project feedback/governance/acknowledge behavior.

### Tests (item 3)
- A project insight backed by a governed R method carries
  `analyticalMethod.executionEngine === "r"` and shows the R Analytics badge;
  Python/fallback shows no badge.
- Project card renders Explain, Chart suggestion, R Analytics badge, Action, Agree,
  Disagree, Add to dashboard — same as a business card (shared component test).
- Add-to-dashboard from a project card persists a widget to a project dashboard.
- Governance: a method disabled for the tenant is not used on project cards
  (same `ai_governance_service` gate).
- Existing project-insight feedback/acknowledge/stale behavior intact.

---

## Verification & landing

- platform-api `pytest`/`ruff`/`mypy`; web-ui `typecheck`/`test --run`/`build`.
- Browser: (1) toggle 2FA on a tenant → a Member is required to enroll/complete
  MFA; off → unchanged. (2) Business-Insight page: all panels expanded, one
  scrollbar, last card fully reachable. (3) Project-Insight cards match
  Business-Insight cards (buttons + R badge) and run governed methods.
- **Merge into the deployed lineage and redeploy** (rebuild web-ui) so the changes
  show; do not leave on an unmerged branch.

## Report
Changed files; the new `0068` migration + the `enforce_2fa` policy wiring; the
scroll-container fix (which nested clip/height cap was removed); the extracted
shared card component and the project governance/execution wiring; tests run; and
before/after screenshots for all three items.
