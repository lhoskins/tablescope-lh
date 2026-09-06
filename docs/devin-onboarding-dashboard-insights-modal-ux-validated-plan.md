# Devin: merge + deploy — onboarding email verification, dashboard cleanup, insights persistence, reconnect-modal sizing

**Repository:** `lhoskins/tablescope-lh`
**Branch to merge:** `fix/onboarding-dashboard-insights-modal-ux`, based on `origin/UX-design-03` at `1416dcf8`
**Base:** `UX-design-03` (or wherever that branch has landed by the time this merges — confirm with `git log origin/UX-design-03..HEAD` that only this branch's commits are ahead)

Four independent fixes, each scoped to its own files. **One Alembic migration** (`0094_email_verification`, new table + 2 new columns on `users`). See §5 for the migration.

---

## 1. Merge rules — read first

1. **Do not rewrite, refactor, rename or reformat the delivered files.** Merge as-is; resolve conflicts by preserving the delivered code and adapting the surrounding code, per the standing convention in this repo's other `devin-*-validated-plan.md` docs.
2. Suspected bug → **report it in the PR description**, don't silently change it.
3. Run the new Alembic migration (§5) as part of deploy — this is not optional, item #1 does not work without it.

```bash
git fetch origin
git checkout -b merge-onboarding-dashboard-insights-modal-ux origin/UX-design-03
git merge origin/fix/onboarding-dashboard-insights-modal-ux
```

---

## 2. Item #1 — Two-step email verification before credentials/login info are sent

**Problem reported:** creating a tenant (or inviting a user into one) immediately emailed a "click here to set your password" link, with no check that the recipient actually owns that inbox. A typo'd address, or someone else's inbox, would receive live login/credential information.

**Fix:** a new email-ownership-verification gate sits in front of both credential-sending paths. Nothing changes about how a user ultimately signs in (still Supabase, still no local password store) — only the *order* changes:

1. **Step 1 (immediate, at tenant/user creation):** create the local `User` row unverified (`email_verified=False`). No Supabase identity is created yet. Send the existing (previously unused) `account_confirmation` email template with a link to `{app_base_url}/verify-email?token=<raw>`. The token is a `secrets.token_urlsafe(32)` value; only its SHA-256 hash is persisted (`email_verification_tokens.token_hash`), 24h TTL.
2. **Step 2 (`POST /api/auth/verify-email`, new route):** consumes the token, marks `user.email_verified=True`, then — only now — creates/links the Supabase identity (`create_or_invite_user`) and sends the real credential email (`workspace_ready_with_password_setup` for a tenant admin, `user_invitation` for an invited user).

Applied at **both** places the user asked for:
- **Tenant admin** (Stripe-webhook-driven onboarding): `platform-api/app/services/tenant_onboarding_service.py`. `_ensure_root_admin` now only creates the local user + membership (no Supabase call). New `_send_root_admin_verification_email` sends the confirmation email (idempotent — skipped if a token already exists for that user/purpose, so a replayed webhook doesn't spam it). New public method `complete_root_admin_verification(user, tenant)` is step 2, called by the verify-email route. `_send_lifecycle_emails` now branches: send the confirmation email if unverified, or run step 2 directly if a retry finds the user already verified (e.g. a webhook replay after verification succeeded but a later provisioning step failed).
- **Tenant-admin inviting a user**: `platform-api/app/routes/tenants_users.py`. `create_user` creates the local `User` directly (no Supabase call), does VDB/folder provisioning immediately (unaffected — doesn't need Supabase), then sends the confirmation email. New `complete_user_invitation(session, user, tenant)` is step 2, called by the verify-email route.

**New shared pieces:**
- `platform-api/app/models/email_verification_token.py` — `EmailVerificationToken` model (`tenant_id`, `user_id`, `token_hash`, `purpose` ∈ `{tenant_admin_invite, user_invite}`, `expires_at`, `consumed_at`).
- `platform-api/app/services/email_verification_service.py` — `create_verification_token` / `consume_verification_token`. `consume_verification_token` is idempotent: clicking an already-verified user's link a second time returns `already_verified=True` instead of erroring.
- `platform-api/app/routes/auth.py` — `POST /api/auth/verify-email` (unauthenticated, like `/forgot-password`). Dispatches to whichever completion handler matches the token's `purpose`.
- `web-ui/app/verify-email/page.tsx` — new public page; reads `?token=`, calls the route, shows "email confirmed, check your inbox for the next email" or an error with a link back to sign-in.
- `web-ui/lib/auth.ts` — new `verifyEmail(token)` helper.

**Schema/model changes:**
- `users` gains `email_verified: bool` (default `false`) and `email_verified_at: datetime | null`.
- `UserRead` (API response) now includes `email_verified` — the tenant users list can surface unverified invitees if the frontend is later extended to show it (not done in this change; out of scope).

**Side effect you should know about:** a new user's customer folder (`CustomerFolderService.ensure_user_folders`) is now created at step 1, before any Supabase identity exists, so it's keyed by the local numeric `user.id` instead of the eventual Supabase id — it is **not** renamed after verification. This matches the fallback (`user.external_id or str(user.id)`) already used identically in `tenants_crud.py`, `projects_crud.py`, `tenant_data_planes_crud.py` and the JWT `sub` claim for any user without an external identity, so it is not a new pattern, just a new caller of it. `tests/test_tenants.py::test_create_tenant_and_user` was updated to assert the folder by numeric id instead of `supa-<email>`.

**`web-ui/app/billing/success/page.tsx`:** the provisioning-progress checklist previously force-completed *every* step once overall `status === "provisioned"` — including "Setup email sent". That's no longer true (credential email now waits on the admin's own action), so that step is marked `independent` and only completes when `root_admin_status === "invite_sent"`. Added a "Confirmation email sent" step and reworded the "provisioned" copy to describe the two-step flow.

---

## 3. Item #2 — Remove the hard-coded "Best Improvement Opportunities" dashboard panel

**Problem reported:** every AI-generated dashboard showed a "Best Improvement Opportunities" panel in the bottom-right corner; not wanted, remove it.

- `platform-api/app/routes/ai_proxy_dashboard_designer.py`: `_operational_widgets()` no longer returns the `improvement-opportunities` entry — only `operational-brief`. The chart placement that used to sit next to it (`_apply_operational_layout`, grid cell index 2) is widened from `gridW: 3` to `gridW: 6` so no empty gap is left.
- `web-ui/components/dashboard/DashboardViewer.tsx`: removed the `improvements` lookup, its render block, and its drag-persist branch; `OperationalNarrativeWidget.type` narrowed to `"operational_brief"` only.
- `web-ui/lib/dashboard/operationalLayout.ts`: `generatedPlacement`'s matching chart-index widened `w: 3 → 6` to match the backend. The lower-level `operationalLayout()` helper's reserved-slot computation for the removed panel was deliberately **left in place as dead code** (always filtered out by the caller) — touching it would have required rewriting `operationalLayout.test.ts`'s own protective assertion for no behavioral gain.
- `platform-api/tests/test_ai_dashboard_designer.py`: updated to assert exactly one operational widget.
- Old, already-saved dashboards that still have a persisted `improvement_opportunities` entry in their DB `config` JSON are unaffected — `operationalNarratives()` does an unchecked cast on that JSON, so a stale entry simply won't match the `type === "operational_brief"` lookup and is silently ignored (no crash, no migration needed for existing rows).

---

## 4. Item #3 — Business/Project Insight keep analyzing across navigation

**Problem reported:** clicking Analyze/Refresh on Business Insight or Project Insight, then navigating away and back, lost the in-progress state — no way to tell a background run was still going.

**What was already correct (not touched):**
- Business Insight already uses Redis-backed run tracking (`home_intel_queue.py`) with SSE streaming.
- Project Insight's *executive-summary* suite (`suite="project_insight"`) already used the `ProjectIntelligenceSnapshot.is_stale` pattern correctly.

**What was actually broken:** Project Insight's *risk/trend/opportunity cards* suite (`suite="insights"`, served by `POST /api/ai/home/insights`) had no persistence at all — `refresh=true` awaited the AI run synchronously in the request; navigating away aborted the visible progress with no way to recover it, and reloading showed nothing indicating a run was still happening (or already finished with new data).

**Fix — extend the same `is_stale` pattern to the `insights` suite:**
- `platform-api/app/tasks/workflows.py`: new arq task pair `enqueue_rebuild_project_insights_cards` / `rebuild_project_insights_cards`, registered in `WorkerSettings.functions`. Mirrors `rebuild_project_insight`'s retry-on-`AIUnavailableError` behavior, but is a plain one-shot job per (tenant, user, project) rather than a debounced multi-user sweep, since it's triggered by one user's manual click. On any AI failure (retryable exhausted, or terminal) it still clears `is_stale` so the UI doesn't spin forever, while keeping the last-good payload intact.
- `platform-api/app/routes/home_intelligence_suggestions.py`: `POST /api/ai/home/insights?refresh=true` now marks the snapshot `is_stale=True` and enqueues the background job, returning immediately with `stale: true` — it no longer awaits `_run_for_project` in the request. Without `refresh`, the existing snapshot's `stale` flag is returned as-is. First-ever visit with no snapshot yet still runs synchronously once (bootstrap), matching `project_insight`'s own first-visit behavior.
- `web-ui/lib/api/home-intelligence/project-result.ts`: `ProjectResult` gains `stale?: boolean`.
- `web-ui/components/tablescope/project-insight/project-insight-screen.tsx`: `insightsQuery` now polls every 5s while the current project's snapshot reports `stale: true`; the page's `running` indicator ORs in that stale flag, so revisiting the page mid-run still shows the in-progress state instead of stale-looking data with no explanation.

**Tests:**
- `tests/test_home_intelligence_insights_cache.py`: the two tests that asserted the old synchronous-refresh behavior were rewritten to assert the new enqueue-and-poll behavior (`test_home_insights_refresh_enqueues_background_job_and_marks_stale`, `test_home_insights_worker_clears_stale_on_ai_failure`).
- `tests/test_project_insight_rebuild.py`: 4 new worker-level tests for `rebuild_project_insights_cards` (missing-project skip, retry-on-retryable-`AIUnavailableError` leaves `is_stale` untouched, terminal-error clears `is_stale` while preserving the last-good payload, success path clears `is_stale` and swaps in the new payload).

---

## 5. Item #4 — Connector reconnect/reauthorize modal too small

**Problem reported:** the data-source reconnect/reauthorize modal was small enough that pasting a credential from another window (a text-selection drag that starts inside the modal and releases over the backdrop) would dismiss the modal, and the modal itself was too small at "at least 80% of the screen."

- `web-ui/components/tablescope/database-connectors/connection-modal.tsx` and `google-sheets-connection-modal.tsx`:
  - Modal box resized from a fixed `max-w-lg` / `max-w-md` to `w-[80vw]` (a floor, not a cap) with a generous `max-w-[1400px]` ceiling that only engages on ultra-wide monitors — never undercuts 80vw on any normal desktop width.
  - Backdrop dismiss-on-click fixed: previously `onClick={onClose}` fired on *any* click event whose `target` resolved to the backdrop at mouseup — including a text-selection drag that starts inside an input and releases outside the modal. Now a `useRef<boolean>` tracks whether `onMouseDown` also landed on the backdrop; the modal only closes when **both** mousedown and click targeted the backdrop directly.

No backend changes, no tests needed beyond typecheck/lint (pure layout/interaction fix, no new logic branches).

---

## 6. Migration

```bash
cd platform-api
alembic upgrade head
```

`0094_email_verification`:
- `ALTER TABLE users ADD COLUMN email_verified BOOLEAN NOT NULL DEFAULT false;`
- `ALTER TABLE users ADD COLUMN email_verified_at TIMESTAMPTZ;`
- `CREATE TABLE email_verification_tokens (...)` with FKs to `tenants`/`users` (both `ON DELETE CASCADE`) and a unique index on `token_hash`.

Existing users: `email_verified` defaults to `false` for everyone, including users who already have working Supabase credentials today. This is cosmetic only — nothing re-gates an *existing* user's ability to sign in; the gate only applies to the one-time credential-email send at creation, which for existing users already happened. No backfill needed.

---

## 7. Verification

| Suite | Result |
|---|---|
| `platform-api` `ruff check` (touched files) | clean |
| `platform-api` `mypy` (touched files) | clean |
| `platform-api` `pytest tests/test_email_verification.py` (new) | 6 passed |
| `platform-api` `pytest tests/test_billing.py` | 32 passed, 2 failed — **pre-existing, unrelated** (`test_provision_isolated_data_plane`, `test_provision_isolated_vpn_awaits_details` fail on `data_plane_status` because the sandbox has no real S3 config for isolated-tier VDB provisioning; confirmed identical failure on `origin/UX-design-03` before this branch's changes via `git stash`) |
| `platform-api` `pytest tests/test_tenants.py tests/test_allowed_domains.py` | 18 passed |
| `platform-api` `pytest tests/test_project_insight_rebuild.py` | 11 passed (7 pre-existing + 4 new) |
| `platform-api` `pytest tests/test_home_intelligence_insights_cache.py` | 4 passed |
| `platform-api` `pytest tests/test_ai_dashboard_designer.py` | 35 passed |
| `platform-api` `pytest -q` (full suite) | **1908 passed, 12 failed, 4 skipped** (18m1s) — the 12 failures are pre-existing and unrelated: 2 are the `test_provision_isolated_*` S3-config failures above; 3 are `test_business_insight_phase1.py` (`redis.exceptions.ConnectionError` — no Redis reachable in this sandbox, and Business Insight was not touched by this branch); 2 are `test_ai_dashboard_pipeline.py`/`test_ask_pipeline.py` visualization-engine tests unrelated to any of the 4 items; 4 are `test_percent_change_summary.py` (date-window arithmetic against `_monthly_series()`, unrelated to insight-card persistence); 1 is `test_visualization_engine.py::test_many_categories_is_horizontal_bar`. The 4 skips are the VPN/SMB E2E tests (no live endpoint configured). None touch any file this branch changed. |
| `web-ui` `tsc --noEmit` | clean |
| `web-ui` `next lint` | clean (same pre-existing `max-lines`/`exhaustive-deps` warnings as `origin/UX-design-03`, no new ones) |
| `web-ui` `vitest run` | 598 / 608 passed, 1 file / 10 tests failed — **pre-existing, unrelated** (`components/tablescope/home/intelligence-card.test.tsx`: `ChartSuggestionDialog` renders without a `QueryClientProvider` wrapper in that test file; confirmed identical failure on `origin/UX-design-03` before this branch's changes via `git stash`) |

```bash
cd platform-api && pytest -q && ruff check app tests && python -m mypy app
cd ../web-ui && npx tsc --noEmit && npx next lint && npx vitest run
```

---

## 8. Deploy

1. Run the migration (§6) before deploying app code that reads `users.email_verified` / `email_verification_tokens`.
2. No environment variables or feature flags are introduced — the two-step flow is unconditional for every new tenant/user creation from the moment this deploys.
3. Confirm `app_base_url` (used to build the `verify-email` link, same setting `set-password` links already use) is correct for the target environment — an unreachable/incorrect base URL breaks the confirmation link, not just cosmetically.
4. Confirm the `account_confirmation` email template renders correctly in whatever email-preview tooling this repo uses — it was defined but never actually sent before this change.

## 9. Verify live

1. **Item #1:** create a tenant/invite a user with a real inbox you control. Confirm you receive the confirmation email first (not a password-setup link), click it, land on `/verify-email` showing "Email confirmed", then receive a second email with the actual password-setup link. Confirm a second click on the same confirmation link doesn't error (idempotent).
2. **Item #2:** generate a new AI dashboard; confirm no "Best Improvement Opportunities" panel appears and there's no visible gap where it used to be.
3. **Item #3:** click Analyze/Refresh on a Project Insight page, immediately navigate to another page, then back — confirm the in-progress indicator is still showing if the run hasn't finished, and clears automatically once it has (poll every 5s).
4. **Item #4:** open a reconnect/reauthorize modal for any data source, resize the browser to a typical desktop width, confirm the modal fills at least 80% of the viewport width; paste a credential from another window/tab into a field inside the modal and confirm the modal does not close.

## 10. Report back

Reply with the full-suite `pytest -q` and `vitest run` counts once run in an environment with Redis/S3/Teiid reachable (this sandbox has none of the three, hence the pre-existing failures noted in §7), and confirm the `alembic upgrade head` output shows `0094_email_verification` applied cleanly.
