# Devin-ready plan: 8 bugs, issues, and enhancements

**Verified base:** `origin/devin/r-echarts-e2e-validation` @ `d6f49e69` — re-verify at implementation time.

Every root cause below was traced against the actual code (not guessed). Where a fix is small and mechanical, the exact file/line/change is given directly. Where it's genuinely a design/scope question (items 1 and 6), that's called out explicitly rather than assumed away.

Recommend splitting this into separate PRs by risk tier so a bad one doesn't block the rest:
- **Tier A — isolated, low-risk bug fixes**: items 2, 3, 5, 8 (each touches 1-3 files, no shared blast radius between them).
- **Tier B — relocation, no logic change**: item 4.
- **Tier C — investigation + hardening, no user-facing behavior change**: item 7.
- **Tier D — design decision required before implementing**: item 1.
- **Tier E — larger, multi-phase feature gap**: item 6.

---

## Item 1 — LLM Framework not visible in Settings menu

### Finding

Not a bug. `web-ui/components/tablescope/settings/settings-nav.tsx` (~line 216-221) gates the LLM Framework nav entry with:

```ts
{
  key: "llm-framework",
  label: "LLM Framework",
  href: "/admin/settings/llm-framework",
  icon: IconRobot,
  section: "Platform Administration",
  visible: () => isPlatformAdmin(user),
},
```

`isPlatformAdmin()` (`web-ui/lib/ui/permissions.ts:10-13`) requires `user.isSuperAdmin === true` or `user.rawRole === "root_admin"` — genuinely platform-level, not tenant-admin. This is by design: it sits in the "Platform Administration" nav section alongside "Tenants" and "Users," both gated the same way. A regular tenant admin (even the tenant owner) is not expected to see it under the current design.

### What this means for you specifically

If your account previously showed LLM Framework and now doesn't, your account's `is_super_admin` flag or `role` almost certainly changed between then and now — this connects directly to item 7 below, where the same question ("did my account's privilege level change") comes up independently. **Recommend Devin's first step here is not a code change** — query your current user row (`SELECT id, email, role, is_super_admin FROM users WHERE email = '<your email>'`) and tell you exactly what it is today, resolving the ambiguity before deciding whether this is "working as designed" or "your account got downgraded and that's the actual bug."

### Decision needed before implementation

Once your actual current privilege level is confirmed, there are two different valid fixes depending on what you want:
- **(a)** If your account should have platform-admin rights and doesn't, restore `is_super_admin`/`role=root_admin` on your account — no code change needed at all.
- **(b)** If LLM Framework should actually be visible to tenant admins too (not just platform admins) — that's a real product-design change: relax `visible: () => isPlatformAdmin(user)` to `visible: () => isAdmin(user)` (matching the gate most other Settings entries use, e.g. Two-Factor Authentication, Allowed Domains), and add a tenant-scoping layer to the backend LLM Framework routes if one doesn't already exist (they may currently assume a platform-wide, not per-tenant, model catalog — verify before loosening the nav gate, since showing the page without matching backend scoping would either expose cross-tenant data or just 403 on load).

Do not implement (b) without an explicit answer to "should tenant admins manage LLM models for their own tenant, or is this platform-operator-only by design" — that's a product call, not something to infer from the bug report alone.

---

## Item 2 — File URL import: source appears then disappears, never gets created

### Root cause (traced, not guessed)

`web-ui/app/projects/[id]/data-source-builder/page.tsx`:
```tsx
const { data: identity } = useCurrentUser();
...
<DataSourceBuilderWorkspace
  tenantName={identity?.tenant.name ?? ""}
  ...
/>
```

`useCurrentUser()` is a React Query hook — `identity` is `undefined` until the request resolves, so `tenantName` starts as `""` on first render and later flips to the real tenant name once the query completes.

`web-ui/components/tablescope/data-source-builder/workspace.tsx` (~line 168-171):
```tsx
useEffect(() => {
  void useBuilderStore.persist.rehydrate();
  ensureTenant(tenantName);
}, [ensureTenant, tenantName]);
```

This effect re-fires every time `tenantName`'s *value* changes — including the `"" → realTenantName` transition on a fresh page load. `ensureTenant()` in `web-ui/lib/stores/data-source-builder-store.ts` (~line 262-274):

```ts
ensureTenant: (key) =>
  set((state) =>
    state.tenantKey === key
      ? {}
      : {
          tenantKey: key,
          sources: [],          // <-- wipes the session
          activeSourceId: null,
          projects: [],
          activeView: "session",
          allDataSourceSelection: {},
          createdKeys: [],
        },
  ),
```

Any time `ensureTenant` is called with a key different from the currently-stored `tenantKey`, it resets `sources: []` unconditionally. On a fresh page load, this fires **twice** in quick succession: once with `key=""` (setting `tenantKey=""`), then again moments later with the real tenant name (`tenantKey !== ""`, so it wipes again). If a File URL import (`acquire`/profile/stage round-trip, which takes real seconds) completes and calls `addSource()` during or just before that second `ensureTenant` call, the just-added source gets wiped by the reset that follows — exactly matching "appears for a second and then disappears." This is a genuine race condition, not something specific to File URL logically, but URL imports are the acquisition method most likely to take long enough to lose the race (local file uploads and the network browse-and-pick flow are comparatively faster from click to `addSource()`).

### Fix

In `workspace.tsx`, guard the effect so it never calls `ensureTenant` with an unresolved/empty tenant name:

```tsx
useEffect(() => {
  if (!tenantName) return;
  void useBuilderStore.persist.rehydrate();
  ensureTenant(tenantName);
}, [ensureTenant, tenantName]);
```

This is the minimal, safe fix — it stops the spurious `ensureTenant("")` call entirely, so the effect only fires once (when `tenantName` first becomes the real value) instead of twice. Also apply the same guard at the other `ensureTenant` call site, `web-ui/components/tablescope/project/project-file-dropzone.tsx:30`, which has the identical pattern and is presumably vulnerable to the same race.

### Verification

1. Regression test: mount `DataSourceBuilderWorkspace` with `tenantName` starting as `""` then updating to a real value (simulate the same prop transition React Query causes); assert `ensureTenant` is called exactly once, with the real name, and that a source added between the two prop values is never wiped. Write this test first, confirm it fails against the current code (reproducing the bug deterministically instead of relying on network timing), then confirm the fix passes it.
2. Manual: on a hard-refreshed (not warm-cached) Data Source Builder page, immediately submit a File URL import as fast as possible after the page paints — confirm the created source persists in "Active Data Sources in this Session" and successfully proceeds to Step 2.

---

## Item 3 — Network File "Browse" modal: no button to select a file at the share root

### Root cause (traced, exact line)

`web-ui/components/tablescope/data-source-builder/network-repository-modal.tsx`:

```ts
function fileNameOf(path: string): string {
  const parts = path.split(/[\\/]/).filter(Boolean);
  return parts.length > 1 ? parts[parts.length - 1] : "";
}
```

Used in the row-rendering gate:
```tsx
{entry.kind === "file" && fileNameOf(entry.path) && (
  <Button variant="primary" size="sm" ... onClick={() => void pickFile(entry)}>
    {importing ? <IconLoader2 .../> : "Import"}
  </Button>
)}
```

For a file sitting directly in the root of a share (e.g. `sample.csv` in `\\10.250.10.229\repository`, exactly as in your screenshot), `entry.path` is a single segment with no separator. `path.split(/[\\/]/).filter(Boolean)` yields `["sample.csv"]` — one element — so `parts.length > 1` is `false`, and `fileNameOf` returns `""`. An empty string is falsy in the JSX `&&` chain, so **the entire Import button is suppressed** for any root-level file. This exactly matches the screenshot: the file name shows (rendered separately via `entry.name`, which is unaffected by this bug), but no button appears next to it.

This bug is latent for any share where files aren't nested at least one folder deep — which is a completely normal, common layout (your `sample.csv` test file is a perfectly reasonable repro case, not an edge case).

### Fix

`fileNameOf(entry.path)` is unnecessary as a gate at all — `entry.name` is already available and already used for display two lines below. Replace the gate condition with just the entry-kind check:

```tsx
{entry.kind === "file" && (
  <Button variant="primary" size="sm" ... onClick={() => void pickFile(entry)}>
    {importing ? <IconLoader2 .../> : "Import"}
  </Button>
)}
```

`fileNameOf()` can be deleted entirely if nothing else calls it (confirm via grep before removing — it may still be used by `uncPath()` or elsewhere in the same file; if so, leave the helper but stop using it as a truthy gate).

### Verification

1. Add a component test rendering `NetworkRepositoryModal` with a mocked `browseNetworkConnection` response containing a file entry with a single-segment `path` (e.g. `path: "sample.csv"`) — assert the Import button renders and is clickable. Confirm this test fails against current code, passes after the fix.
2. Manual: browse a network connection whose root contains at least one file with no subfolder nesting; confirm an Import button appears and successfully creates a data source.

---

## Item 4 — Move "Allowed Host" under Settings → Security, below Allowed Domains

### Current state (traced)

- **Backend** (leave as-is — already correctly scoped): `platform-api/app/routes/file_imports.py`'s `hosts_router` (prefix `/network-file-hosts`) — `GET/POST /network-file-hosts`, `PATCH/DELETE /network-file-hosts/{id}`. Backed by `NetworkFileHost` model (`platform-api/app/models/network_file_host.py`). No reason to move these — they're already tenant/role-scoped correctly and consumed by `get_approved_smb_hosts()` in `smb_gateway.py`, which the acquisition/browse code already depends on. Moving backend routes would only add churn (re-plumbing imports, re-verifying tenant scoping) for zero functional benefit.
- **Frontend** (this is what actually needs to move): `web-ui/app/admin/repositories/page.tsx` currently has a 3-tab layout (`"connectors" | "network-connections" | "allowed-hosts"`), with the `"allowed-hosts"` tab labeled "Allowed SMB hosts" rendering `NetworkHostsPanel` (`web-ui/app/admin/repositories/network-hosts-panel.tsx`). This lives under **Integrations** in Settings nav today, not **Security**.
- **Target pattern to match**: Allowed Domains — nav entry `key: "allowed-domains"`, `section: "Security"`, in `settings-nav.tsx` right above where the new entry goes; page at `web-ui/app/admin/allowed-domains/page.tsx` (re-exported at `/admin/settings/allowed-domains/page.tsx`).

### Plan

1. Remove the `"allowed-hosts"` tab from `web-ui/app/admin/repositories/page.tsx` (2 tabs remain: Connectors, Network Connections). Since `/admin/settings/repositories/page.tsx` just re-exports this same component, this one edit fixes both URLs.
2. Create a new page, e.g. `web-ui/app/admin/allowed-hosts/page.tsx` (with a `/admin/settings/allowed-hosts/page.tsx` re-export, matching the Allowed Domains pattern exactly), rendering the existing `NetworkHostsPanel` component moved to this new location (or kept in place and just imported from the new page — either is fine, but pick one canonical location and update the other reference, don't leave the component under `app/admin/repositories/` if its only consumer is now the Security page).
3. Add a new nav entry in `settings-nav.tsx`, immediately after the `allowed-domains` entry, `section: "Security"`, e.g.:
   ```ts
   {
     key: "allowed-hosts",
     label: "Allowed Hosts",
     href: "/admin/settings/allowed-hosts",
     icon: IconLock, // or another distinct icon — confirm with design, don't just duplicate Allowed Domains' icon
     section: "Security",
     visible: () => isAdmin(user),
   },
   ```
4. No backend, API contract, or database changes.

### Bonus cleanup (optional, flagged not required)

While in this area: `web-ui/components/tablescope/data-source-builder/network-security-panel.tsx` (`NetworkSecurityPanel`) is a near-duplicate CRUD implementation hitting the same `/network-file-hosts` endpoints, confirmed **not imported anywhere** in the codebase — dead code. Safe to delete in the same PR if you want, or leave for a separate cleanup pass; either way it's unrelated to this relocation and carries zero risk either way.

### Verification

1. Confirm `/admin/settings/repositories` no longer shows an "Allowed SMB hosts" tab.
2. Confirm `/admin/settings/allowed-hosts` renders the same CRUD UI that used to live under Repositories, and that add/edit/delete still work against the unchanged backend.
3. Grep the repo for `"allowed-hosts"`, `NetworkHostsPanel`, `"Allowed SMB hosts"` post-change to confirm no dangling references to the old tab location remain (a prior audit found none besides the tab itself, but re-verify after the edit).

---

## Item 5 — Add "Export SQL" before "Download PNG" on Project/Business Insight cards

### Current state (traced)

Project Insight and Business Insight (home) cards render through the **same** component tree — there is only one action-icon-cluster implementation to change, not two:

`IntelligenceWorkspace` → `insight-section.tsx` → `IntelligenceCard` (`web-ui/components/tablescope/home/intelligence-card/intelligence-card.tsx`) → `InsightCardActionToolbar` (`web-ui/components/tablescope/insights/insight-card-action-toolbar.tsx`).

The action row (`insight-card-action-toolbar.tsx`, ~line 260-340) currently orders: Create Action → Explain → divider → Agree/Disagree → feedback status → Chart options → divider → Add to dashboard → **Download PNG** → Export to CSV.

- `card.sql?: string` already exists on `InsightCard` (`web-ui/lib/api/home-intelligence/insight-card.ts`, ~line 78-82) — "Raw SQL... optional, only present when the insight was generated from a successfully executed query." It's already read elsewhere in the same toolbar file for the "Add to dashboard" enablement check (`card.sql?.trim()`).
- PNG export pattern (`intelligence-card.tsx` ~line 122-130, mirrored by CSV ~132-140): a `use...Exporting` boolean state, an async handler calling a `lib/insights/export-*.ts` helper, toast on failure via `useToasts`.
- No existing "export/copy/download SQL" pattern anywhere in the codebase to reuse — `IconCode` is used elsewhere purely as a "this represents SQL" visual marker, never for export/download, but it's a reasonable icon choice for the new button given that convention.

### Plan

1. New file `web-ui/lib/insights/export-sql.ts`, mirroring `export-png.ts`'s `triggerDownload` pattern but as a plain text blob (no image rendering involved):
   ```ts
   export function exportInsightCardSql(sql: string, filename: string) {
     const blob = new Blob([sql], { type: "text/plain" });
     const url = URL.createObjectURL(blob);
     triggerDownload(url, filename);
     URL.revokeObjectURL(url);
   }
   export function insightSqlFilename(card: InsightCard): string {
     // mirror insightPngFilename / insightCsvFilename's naming convention
   }
   ```
2. In `intelligence-card.tsx`, add `isSqlExporting` state and a `handleExportSql` handler following the exact shape of `handleDownloadPng`/`handleExportCsv` (disabled when `!card.sql?.trim()`, same tooltip-disabled-reason pattern already used for "Add to dashboard").
3. In `insight-card-action-toolbar.tsx`, add the new `onExportSql`/`isSqlExporting` props, and insert a new `IconButton` (using the existing local `IconButton` helper, `IconCode` icon, `h-11 w-11`/size-18 to match siblings) **immediately before** the Download PNG button.
4. Thread the new props through `intelligence-card-props.tsx` if that's where the prop surface is centrally typed (confirm during implementation).

No backend changes — this is a pure client-side export of already-available data, identical in shape to how CSV export already works.

### Verification

1. Component test: render a card with `sql` set, click Export SQL, assert a download is triggered with the correct filename/content. Render a card with no `sql`, assert the button is disabled with the expected tooltip reason (mirroring the existing "Add to dashboard" disabled-reason test if one exists).
2. Manual: confirm the icon appears in the right position on both a Business Insight (home) card and a Project Insight card (same component, but verify both surfaces since they're reached via different parent screens).

---

## Item 6 — "Turn on LLM Framework to be fully operational" + browse Hugging Face model descriptions before install

This is two distinct, real gaps — not one item, and they're different sizes of work. Recommend treating them as separate PRs even though they're both "LLM Framework."

### 6a. Browse/read model descriptions before staging (smaller, self-contained)

**Root cause (traced)**: `HuggingFaceCatalogClient._parse_model_info()` (`platform-api/app/services/llm_catalog_client.py`) populates the `description` field as:
```python
description=card.get("language") or payload.get("description"),
```
`card` is the model's parsed `cardData` YAML front-matter (license/language/tags/datasets) — this line surfaces a **language code** (e.g. `"en"`), not the model's actual description or README. Hugging Face's model API doesn't return README body text in this endpoint at all; the actual description/model-card content lives in the README file itself, fetchable from `https://huggingface.co/{repo_id}/raw/main/README.md` (or via the Hub API's tree/file-content endpoints).

Separately, and independently broken: the backend already has `GET /llm-framework/catalog/detail` (`llm_framework_catalog.py`) and the frontend already has a typed client wrapper `getLLMCatalogDetail()` (`web-ui/lib/api/llm-framework.ts:245`) — but it is **never called from any component**. `catalog-panel.tsx` goes straight from a search-result row to the Stage action, with no click-through detail view at all.

**Plan**:
1. Backend: fix `_parse_model_info()` to fetch and surface real description content. Two sub-options, pick based on cost/complexity tolerance:
   - **(a) Minimal**: stop mislabeling `card.get("language")` as description; if HF's model-info payload has no usable description field, leave it `None` rather than showing a language code as if it were one.
   - **(b) Full fix, matches what you actually asked for**: fetch `README.md` content (via the URL pattern above or the Hub API) for the specific model when the user requests detail (i.e., in the `/catalog/detail` handler, not in bulk search results — fetching every search result's README would be slow and wasteful), parse/strip YAML front-matter, return the rendered markdown body as `description`/a new `readme` field.
2. Frontend: build the missing browse/detail step — clicking a search-result card should open a detail view (modal or expand-in-place) that calls the now-functional `getLLMCatalogDetail()`, rendering the description/README content, license, file list (`siblings`), and any other detail-endpoint fields, with the Stage action moved into (or also available from) that detail view rather than only the compact search-row card.
3. This does not require any feature-flag changes — `llm_framework_hf_catalog_enabled` is already on by default; this is purely fixing broken/missing functionality within an already-enabled phase.

### 6b. "Fully operational" — activation doesn't actually serve inference

**Root cause (traced)**: this is a bigger gap than a simple flag flip.

- `llm_deployment_enabled` and `llm_dynamic_routing_enabled` are both `False` by default (`platform-api/app/config.py`), with explicit comments: `llm_deployment_enabled` — *"Kept off until the deployment agent and canary pipeline are wired"*; `llm_dynamic_routing_enabled` — *"Phase 4: allow dynamic routing profile changes and activation."* These are intentionally-incomplete-phase flags, not accidentally-off toggles.
- Even with both flags on, the install/approve/activate pipeline (`platform-api/app/services/llm_deployment.py`) terminates at: Ollama has the model file installed, and `LLMInstallation.status`/`LLMDeployment.status`/`LLMRoutingProfile.is_active` are set in the database. **Nothing in `ai-server/` reads `LLMRoutingProfile` or `LLMInstallation` to decide which model actually serves a request.** Activation today updates bookkeeping rows; it does not connect to any live inference-serving code path.

**This means "turn on LLM Framework to be fully operational" is not a config change — it's a real, un-scoped feature: wiring `ai-server`'s actual model-selection/inference code to read the active `LLMRoutingProfile` and route requests to the corresponding installed Ollama model.** That's a meaningful chunk of new work (need to: identify every place `ai-server` currently hardcodes or config-selects its model, replace that with a lookup against the routing profile that platform-api's LLM Framework maintains, handle the case where the active model changes while requests are in flight, handle fallback/failure if the "active" model isn't actually reachable, etc.) — not something to fold into this batch of fixes.

**Recommendation**: don't attempt 6b in the same pass as everything else in this plan. Treat it as its own follow-up Devin-ready plan once you've decided how much of it you actually want (e.g., do you want dynamic per-tenant model routing, or just "the platform operator can swap the one model ai-server uses without a redeploy"? The scope differs a lot between those two answers, and it's worth having Devin do a proper discovery/spike on `ai-server`'s current model-selection code before committing to an approach — mirroring the Phase-0-spike pattern used for the LDAP/SSO plan earlier in this project).

For **this** plan, the concrete, scoped deliverable is 6a only. Flag 6b to the user as "real gap, needs its own dedicated plan" rather than attempting it here.

---

## Item 7 — Self-assigned Admin role while a Member: security check

### Investigation result: no privilege-escalation vulnerability found

Checked both role-change surfaces:

**Project role**: `PUT /projects/{project_id}/members/{user_id}/role` (`platform-api/app/routes/projects_members.py:193-227`):
```python
if project.owner_id != context.user_id and context.role != "admin":
    caller_member = await session.get(ProjectMember, (project_id, context.user_id))
    if caller_member is None or caller_member.role != "admin":
        raise HTTPException(status_code=403, detail="Only project owner or admin can update roles")
```
This correctly requires the caller to already be the project owner, hold tenant-level `admin` role, or already be a project-level admin before they can change **anyone's** role — including their own, since there's no exemption checking `user_id == context.user_id`. There's no path for a genuine plain "member" (no elevated role at any level) to reach this successfully.

**Tenant role**: `PUT /tenants/{tenant_id}/users/{user_id}` (`platform-api/app/routes/tenants_users.py:199-225`), gated by `Depends(_require_user_management)` — same shape, requires the caller to already have tenant user-management rights.

**Conclusion**: for you to have successfully set your own role to Admin, your account must have already held tenant-admin (or project-admin, or project-owner) rights *before* making that change — which is completely ordinary, expected behavior for an admin managing their own membership, not a bug. This is consistent with your own note about test-account elevation. Recommend Devin's first step (same as item 1) is to just show you your account's actual current `role`/`is_super_admin` values directly, rather than guessing.

### Real gap found (worth fixing regardless of what happened here)

**Neither endpoint writes an audit event.** Grepped for `AuditEvent(` in both route files and the relevant services — zero hits. This means a question like "did I really do this, and when" currently has no answer anywhere in the product, which is exactly the position you're in now. Given `AuditEvent`/`audit_events` is already an established, working pattern in this codebase (used by `tenants_security_policy.py` for `enforce_2fa` changes — see the LDAP/SSO plan work earlier for the exact code shape to copy), extend both `update_member_role` and `update_user` to log an `AuditEvent` on every role change: `event_type="member_role_change"`/`"tenant_user_role_change"`, `scope` set to the old→new role transition, and — specifically useful for exactly this kind of question going forward — a distinct flag/note when `user_id == context.user_id` (self-change), so a future "did I do this to myself" question has a direct, queryable answer instead of requiring code archaeology.

### Plan

1. Add `AuditEvent` logging to `update_member_role` (`projects_members.py`) and `update_user`'s role-change branch (`tenants_users.py`), following the exact pattern in `tenants_security_policy.py::_set_enforce_2fa`.
2. Optional, low-priority hardening: add a confirmation-dialog UX nudge on the frontend when an admin is about to change their *own* role specifically (distinct from changing someone else's) — not a security fix, just guards against an admin accidentally locking themselves out. Not required, flag as nice-to-have.
3. No changes to the authorization logic itself — it's already correct.

### Verification

Add a test asserting a plain member (no admin role at project or tenant level) gets 403 attempting to change any role, including their own — confirming the existing protection explicitly rather than just inferring it from a code read. Add a test confirming an `AuditEvent` row is created on a successful role change, with the self-change flag set correctly when `user_id == context.user_id`.

---

## Item 8 — Percent Change Summary: toggle for period statistics, default off

### Current state (traced)

`web-ui/components/tablescope/home/percent-change-summary-table.tsx` already has a fully-built, always-rendered "Period Statistics" column group (8 columns: Latest, Min, Max, Median, Avg, Std Dev, Cumulative, n — from `stat-fields.tsx`/`stat-labels.tsx`/`stat-cell.tsx`), unconditionally shown after the per-period percent-change cells. The backend (`platform-api/app/services/percent_change_summary/`) computes `SummaryStatistics` unconditionally for every row — there's no existing query param to skip it.

### Plan (frontend-only; this satisfies "toggle to turn off/on")

1. In `percent-change-summary-panel.tsx` (the parent control-bar component, ~line 165-190, alongside the existing `interval`/`range`/`search`/`sort` local state), add `const [showStatistics, setShowStatistics] = useState(false);` — **default `false`, matching your explicit "Default is off" requirement** (this is a behavior change from today's always-on rendering, not just adding a toggle next to existing behavior).
2. Add a `Switch` control (reuse `web-ui/components/ui/switch.tsx`, same component/pattern as `share-toggle.tsx`) in the panel's control bar, labeled something like "Show period statistics."
3. Pass `showStatistics` down to `PercentChangeSummaryTable` as a new prop; conditionally render the "Period Statistics" header column-group and the corresponding `STAT_FIELDS` body cells, and adjust `totalColumns`/`colgroup` sizing to account for the group being present or absent (these are currently sized assuming the stat columns always exist — don't just CSS-hide them, actually exclude them from the column-count math or the table layout will show empty trailing space).
4. Persist the choice via `localStorage`, following the exact pattern already used in `sidebar.tsx` for its collapse-state (read on mount in a `useEffect`, write on toggle, wrapped in try/catch for private-browsing/storage-disabled safety) — key suggestion: `tablescope-pcs-show-statistics`.

### Explicitly out of scope for this item

Skipping the *computation* server-side when the toggle is off (as opposed to just not rendering it) would require adding an `include_statistics` param to `PercentChangeSummaryRequest` and short-circuiting `_calculate_period_statistics()` — flagged as an optional performance follow-on, not required to satisfy the actual request (a UI show/hide toggle), and not worth the added API-contract surface unless the computation is measurably expensive at your current data volumes.

### Verification

1. Component test: default render has `showStatistics=false`, confirm the stat columns are absent (not just hidden) and column count math is correct. Toggle on, confirm columns appear with correct data.
2. Manual: load the Percent Change Summary page fresh — confirm stats are off by default; toggle on, refresh the page, confirm the choice persisted (localStorage).

---

## Summary: files touched per item

| Item | Primary files |
|---|---|
| 1 | None (decision-gated; possibly `settings-nav.tsx` + backend tenant-scoping if (b) is chosen) |
| 2 | `web-ui/components/tablescope/data-source-builder/workspace.tsx`, `web-ui/components/tablescope/project/project-file-dropzone.tsx` |
| 3 | `web-ui/components/tablescope/data-source-builder/network-repository-modal.tsx` |
| 4 | `web-ui/app/admin/repositories/page.tsx`, new `web-ui/app/admin/allowed-hosts/page.tsx` (+ settings re-export), `web-ui/components/tablescope/settings/settings-nav.tsx` |
| 5 | `web-ui/components/tablescope/insights/insight-card-action-toolbar.tsx`, `web-ui/components/tablescope/home/intelligence-card/intelligence-card.tsx`, new `web-ui/lib/insights/export-sql.ts` |
| 6a | `platform-api/app/services/llm_catalog_client.py`, `platform-api/app/routes/llm_framework_catalog.py`, `web-ui/app/admin/llm-framework/catalog-panel.tsx` |
| 6b | Out of scope for this plan — separate discovery/plan needed |
| 7 | `platform-api/app/routes/projects_members.py`, `platform-api/app/routes/tenants_users.py` |
| 8 | `web-ui/components/tablescope/home/percent-change-summary-panel.tsx`, `percent-change-summary-table.tsx` and its `stat-*` submodules |
