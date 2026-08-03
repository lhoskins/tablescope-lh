# Tablescope Devin-Ready Automated UI Test Plan

## 1. Mission

Build and execute a comprehensive automated browser test of Tablescope’s user-visible features and functions. Test the application as real users with different roles would experience it, record every finding with reproducible evidence, and propose a likely fix for each finding.

**This is an assessment-only mission. Do not fix application defects.**

The source-of-truth feature inventory is `Tablescope_Feature_Inventory_PR1-PR101.md`, covering PR #1 through PR #101. Every directly user-visible feature in that inventory must map to at least one automated UI test or to a clearly documented blocked/not-applicable disposition.

The execution catalog contains **352 automated UI scenarios across 23 suites**. Several scenarios are parameterized by role, browser, viewport, fixture shape, and tenant, so the resulting automated test count may be higher.

## 2. Non-negotiable operating rules

1. **Do not modify application behavior.** Do not change frontend, backend, AI server, R service, migrations, infrastructure, runtime configuration, production feature flags, or deployed code.
2. **Do not implement proposed fixes.** Findings may name likely files/components/services and describe a proposed correction, but no correction may be coded, committed, deployed, or tested as a fix.
3. **Permitted repository changes are test-only.** New or updated Playwright tests, test fixtures, test configuration, and generated reports may be added only under the repository’s established test/report locations.
4. **Do not weaken security to make tests pass.** Do not bypass RBAC, MFA, tenant isolation, signed requests, CSRF, rate limits, or authentication middleware.
5. **Do not use production for destructive scenarios.** Tenant deletion, user deletion, source deletion, repository scans, billing webhooks, MFA policy changes, and other material mutations require an approved disposable staging tenant/environment.
6. **Never delete or alter pre-existing user data.** Mutating tests may operate only on records created by the current run and prefixed with the run ID.
7. **Redact secrets and sensitive data.** Reports, screenshots, traces, videos, console logs, and network logs must not contain passwords, tokens, cookies, OTPs, connector credentials, signed URLs, document contents marked sensitive, or personal phone numbers.
8. **Do not classify missing configuration as an application defect.** Record it as `BLOCKED_CONFIGURATION` with the exact missing prerequisite.
9. **Do not silently skip tests.** Every planned scenario must finish as `PASS`, `FAIL`, `BLOCKED_CONFIGURATION`, `BLOCKED_ENVIRONMENT`, `NOT_APPLICABLE`, or `NOT_RUN` with a reason.
10. **Continue after noncritical failures.** Capture evidence, isolate the failed test, and continue other independent suites.

## 3. Required deliverables

Create the following test-only deliverables:

```text
tests/e2e/
  playwright.config.*
  fixtures/
  pages/
  specs/
  support/

artifacts/ui-test-run/<RUN_ID>/
  UI_TEST_EXECUTION_REPORT.md
  UI_FEATURE_COVERAGE_MATRIX.csv
  UI_FINDINGS_SUMMARY.csv
  findings/
    UI-FINDING-0001.md
    UI-FINDING-0002.md
    ...
  playwright-report/
  junit.xml
  test-results/
    screenshots/
    traces/
    videos/
    console/
    network/
```

The final Devin response must provide:

- the test run ID, environment, commit SHA, and time window;
- counts by result and severity;
- the coverage percentage against the UI feature inventory;
- a link/path to `UI_TEST_EXECUTION_REPORT.md`;
- a link/path to `UI_FEATURE_COVERAGE_MATRIX.csv`;
- a link/path to `UI_FINDINGS_SUMMARY.csv`;
- a list of blocked suites and missing prerequisites;
- confirmation that no application fix was implemented.

## 4. Source scope and traceability

### 4.1 Direct UI scope

Directly automate the user-facing behavior represented by these inventory families:

`AUTH`, `UX`, `PROJ`, `DATA`, `QUERY`, `SCOPE`, `DASH`, `VIZ`, `DOC`, `REF`, `REPO`, `META`, `KG`, `AI`, `BI`, `PI`, `HOME`, `FB`, `CTX`, `ACT`, `ANL`, and `ADMIN`.

### 4.2 Indirect UI scope

Validate `PLAT` and `OPS` features only through observable UI behavior, such as tenant routing, data-plane status, service health indicators, successful query routing, retry/error messages, and stale-while-revalidate behavior.

### 4.3 Not part of this UI mission

Do not directly test:

- Terraform resource creation or teardown;
- raw Docker/Compose behavior;
- host firewall rule implementation;
- server-only AWS cost-governance commands;
- unit-level statistical correctness already covered by backend/R tests;
- internal database schema details except through visible persistence behavior;
- API-only contracts that have no user-facing effect.

List these inventory items in the coverage matrix as `INDIRECT` or `OUT_OF_UI_SCOPE`, with rationale.

## 5. Automation stack

Use the repository’s existing browser automation framework when present. If none exists, use Playwright with TypeScript.

Required behavior:

- Chromium is mandatory; Firefox and WebKit run at least the smoke and critical-path suites.
- Use stable accessibility locators in this order: role/name, label, placeholder, test ID, then narrowly scoped CSS.
- Do not use arbitrary fixed sleeps. Poll visible state, API completion, SSE completion, or element readiness with bounded timeouts.
- Capture screenshot and trace on first retry and final failure.
- Capture browser console errors and failed network requests for every test.
- Save videos for failed tests only.
- Default retries: 1 locally/staging, 2 in CI for tests marked retry-safe.
- Mark a test `FLAKY/INTERMITTENT` if it fails and passes on retry; still create a finding.
- Run independent read-only suites in parallel. Serialize tests that mutate the same tenant, project, dashboard, insight cache, or MFA policy.
- Use Page Objects or task helpers for login, project navigation, uploads, AI wait states, findings capture, and cleanup.

## 6. Required environment variables and test identities

Do not hard-code credentials or secrets.

```text
TABLESCOPE_E2E_BASE_URL=
TABLESCOPE_E2E_ENVIRONMENT=staging|preprod|production-readonly
TABLESCOPE_E2E_RUN_ID=

E2E_ROOT_ADMIN_EMAIL=
E2E_ROOT_ADMIN_PASSWORD=
E2E_TENANT_ADMIN_EMAIL=
E2E_TENANT_ADMIN_PASSWORD=
E2E_PROJECT_ADMIN_EMAIL=
E2E_PROJECT_ADMIN_PASSWORD=
E2E_EDITOR_EMAIL=
E2E_EDITOR_PASSWORD=
E2E_VIEWER_EMAIL=
E2E_VIEWER_PASSWORD=
E2E_REVIEWER_EMAIL=
E2E_REVIEWER_PASSWORD=
E2E_SECOND_TENANT_USER_EMAIL=
E2E_SECOND_TENANT_USER_PASSWORD=

E2E_MFA_TEST_PHONE=
E2E_MFA_TEST_CODE_SOURCE=
E2E_STRIPE_TEST_MODE=false
E2E_TEST_SMB_AVAILABLE=false
E2E_TEST_SMB_HOST=
E2E_TEST_SMB_SHARE=
E2E_TEST_SMB_USERNAME=
E2E_TEST_SMB_PASSWORD=
```

Minimum test identities:

| Identity | Required capabilities |
| --- | --- |
| Root/platform administrator | Tenant and data-plane administration, platform settings |
| Tenant administrator | Users, tenant settings, 2FA, repositories, reference/company library, AI governance |
| Project owner/admin | Membership, project settings, data sources, scopes, dashboards, actions, context |
| Project editor | Create/edit project content without administrative access |
| Viewer | Read-only project and insight access |
| Insight reviewer | Review queue, claim, request information, disposition |
| Second-tenant user | Negative tenant-isolation verification |

If any identity is unavailable, run every unaffected test and classify dependent cases as blocked.

## 7. Environment safety gate

Before any test:

1. Record the base URL, page title, application version/commit if exposed, browser versions, viewport, locale, and timezone.
2. Determine whether the target is production.
3. If production:
   - run only explicitly read-only tests;
   - do not upload, create, update, delete, invite, change MFA, run repository scans, clear caches, or trigger billing/provisioning;
   - mark those tests `BLOCKED_ENVIRONMENT`.
4. Verify credentials belong to designated automation accounts.
5. Verify the second-tenant account cannot see the primary test tenant.
6. Generate a unique prefix: `e2e-<RUN_ID>-`.
7. Create a cleanup registry containing only IDs created during this run.
8. If the environment cannot be positively identified, stop mutation tests and continue read-only tests.

## 8. Test data package

Create or reuse non-sensitive synthetic fixtures:

### 8.1 Structured files

- small CSV with text, integers, decimals, booleans, dates, nulls, and duplicates;
- CSV with Teiid-reserved headers: `Date`, `Order`, `Group`, `Select`, `Function`, `System`;
- replacement CSV with the same logical source and changed rows/columns;
- XLS and XLSX versions;
- nested JSON and XML suitable for flattening;
- high-cardinality category data with more than 25 categories;
- time-series data with at least 36 periods and two measures;
- scalar KPI data;
- two-category-dimension heatmap data;
- hierarchy data for treemap/sunburst/tree;
- source/target/value data for Sankey;
- stage/value data for funnel;
- two-measure scatter data;
- multi-table relationship data with one-to-many and intentionally unsafe many-to-many examples.

### 8.2 Documents

- PDF, DOCX, PPTX, TXT, and Markdown documents containing synthetic business content;
- a Policy, Procedure, Runbook, and Postmortem designed to form a document family;
- one duplicate-title document;
- one malformed/unsupported file for negative testing;
- documents referencing governed tags, KPIs, entities, and project risks.

### 8.3 Project fixtures

- private project owned by the project-admin account;
- shared project with Admin, Editor, and Viewer members;
- project with no data;
- project with structured data only;
- project with documents only;
- rich project using the existing Demo Company Installer or equivalent synthetic content;
- two projects with similar names to test project-selection ambiguity;
- second-tenant project with a known unique name for isolation checks.

### 8.4 External fixtures

- approved HTTP URLs for successful, redirected, duplicate, oversized, unsupported, paywalled/manual, and failed bulk-import rows;
- disposable SMB share when configured;
- Stripe test-mode event source when configured;
- MFA provider sandbox/test number when configured.

## 9. Global assertions applied to every test

For every route and workflow, assert as applicable:

- expected URL, page title, heading, breadcrumb, active navigation, and tenant/project context;
- no uncaught JavaScript exception;
- no unexpected HTTP 4xx/5xx or failed resource request;
- no visible raw stack trace, secrets, SQL in prose-only answers, or internal identifiers where a friendly label is expected;
- loading, empty, success, partial, stale, and error states are understandable;
- actions are present, hidden, or disabled according to role;
- state persists after reload when the feature promises persistence;
- mutation results appear without requiring an unrelated navigation/reload;
- keyboard focus is visible and logical;
- dialogs have accessible names, trap focus, support Escape when safe, and restore focus;
- generated names, screenshots, and artifacts use the run prefix;
- tenant/project data from another account never appears.

## 10. Automated test suites

Each scenario below must be represented in the feature coverage matrix with its inventory feature IDs.

### Suite UI-00 — Preflight and route inventory

- **UI-00-001:** Open the tenant landing/login route and verify the application loads without fatal console or network errors.
- **UI-00-002:** Capture all navigation groups and visible routes for every test identity.
- **UI-00-003:** Enumerate visible buttons, links, inputs, tabs, menus, switches, table row actions, and dialog triggers on each route.
- **UI-00-004:** Compare discovered controls with the planned test manifest; report every untested interactive control as a coverage gap.
- **UI-00-005:** Verify unknown routes and unauthorized routes display the expected not-found or access-denied experience without leaking content.
- **UI-00-006:** Verify direct deep links restore the correct tenant, project, breadcrumb, and active navigation.

### Suite UI-01 — Authentication, account setup, MFA, and session behavior

- **UI-01-001:** Valid tenant email/password login reaches the authenticated Home page.
- **UI-01-002:** Invalid password shows a safe error without revealing whether an account exists.
- **UI-01-003:** A login session for one tenant cannot be exchanged into another tenant by changing the slug.
- **UI-01-004:** Expired/stale local session does not prevent a new login.
- **UI-01-005:** Forgot Password submits, confirms delivery safely, and uses the tenant-specific return URL.
- **UI-01-006:** Invite/account-setup link opens the set-password page and successful setup returns to the correct tenant.
- **UI-01-007:** Expired/invalid invite and recovery links show actionable errors.
- **UI-01-008:** Manual logout returns to `/<tenant>/login`.
- **UI-01-009:** Idle logout returns to `/<tenant>` and prevents use of protected routes until reauthentication.
- **UI-01-010:** Tenant with 2FA enforcement OFF still requires MFA for privileged roles but not ordinary members.
- **UI-01-011:** Tenant with 2FA enforcement ON requires MFA for every member.
- **UI-01-012:** MFA setup defaults to United States and accepts/normalizes a valid national number.
- **UI-01-013:** Invalid phone formats are rejected without truncation or layout overflow.
- **UI-01-014:** OTP entry supports typing, paste, backspace/delete, arrows, Home/End, autofill, and focus.
- **UI-01-015:** Invalid OTP shows a safe error and retains a usable retry state.
- **UI-01-016:** Resend is disabled during cooldown and enabled afterward.
- **UI-01-017:** Successful MFA returns to the originally requested protected route.
- **UI-01-018:** AAL1 session cannot access an AAL2-protected screen through direct navigation or browser back.

### Suite UI-02 — Application shell, navigation, responsive layout, and Home

- **UI-02-001:** Sidebar groups, labels, icons, ordering, and active state match the signed-in role.
- **UI-02-002:** Collapse/expand sidebar changes workspace width and persists for the expected session scope.
- **UI-02-003:** Home/project shell transition preserves user, tenant, project, breadcrumb, and counts.
- **UI-02-004:** Home greeting, hero prompt, quick prompts, quick actions, and recent-project table render from live data.
- **UI-02-005:** Home prompt routes to the most recently updated accessible project.
- **UI-02-006:** Home prompt routes to project creation when the user has no project.
- **UI-02-007:** Recent project counts and AI status match the underlying visible project content.
- **UI-02-008:** Administration and reviewer navigation is hidden from unauthorized users.
- **UI-02-009:** Direct route access remains blocked even when a hidden navigation item’s URL is manually entered.
- **UI-02-010:** Desktop, 1280px, tablet, and mobile widths have no clipped navigation, overlapping controls, or unintended horizontal scroll.
- **UI-02-011:** Business Insight and chart-heavy routes expose one vertical page scrollbar and allow reaching the final card.
- **UI-02-012:** Keyboard-only navigation reaches sidebar, top bar, main content, menus, and dialogs in a logical order.

### Suite UI-03 — Projects and project membership

- **UI-03-001:** Create a private project and verify only the owner can discover/open it.
- **UI-03-002:** Create/share a project and verify active members can discover/open it.
- **UI-03-003:** Rename/edit a project and verify the updated name appears across Home, sidebar, breadcrumb, and lists.
- **UI-03-004:** Project Overview counts and AI-ready state reflect data sources, queries, documents, dashboards, actions, and processing state.
- **UI-03-005:** Recent query/data-source rows open their full project workspace destinations.
- **UI-03-006:** Project owner/admin opens Members and sees addable users excluding owner and existing members.
- **UI-03-007:** Add Viewer, Editor, and Admin members and verify each role’s resulting controls.
- **UI-03-008:** Change a member role and verify permissions update after session refresh.
- **UI-03-009:** Deactivate a member; verify inactive state and loss of project access.
- **UI-03-010:** Permanently delete a run-created member only in disposable staging and verify removal.
- **UI-03-011:** Viewer sees membership read-only and cannot invoke mutation endpoints through the UI.
- **UI-03-012:** Added member receives/links to the correct tenant and project when email testing is configured.
- **UI-03-013:** Project counts in navigation update after content creation/deletion.
- **UI-03-014:** Second-tenant user cannot discover the project through lists, search, or direct URL.

### Suite UI-04 — Data Sources and AI-assisted upload

- **UI-04-001:** Global Data Sources route renders the upload area, search, source list, shared-by state, and source metadata.
- **UI-04-002:** Project Data Sources route renders only project-associated sources with schema/detail views.
- **UI-04-003:** Upload CSV into a selected project and verify analyzing, review, completion, source creation, and queryability.
- **UI-04-004:** Upload XLS and XLSX and verify correct filename/type display and schema.
- **UI-04-005:** Upload nested JSON and verify flattening, visible JSON identity, schema, and query result.
- **UI-04-006:** Upload XML and verify flattening, visible XML identity, schema, and query result.
- **UI-04-007:** Upload a reserved-header CSV and verify the VDB remains usable and original headers are queryable.
- **UI-04-008:** Upload screen shows governed tag chips, KPI suggestions, and relationship hints when returned.
- **UI-04-009:** Add/remove/toggle suggested tag chips during review and verify saved metadata.
- **UI-04-010:** Search finds a source by name and clears correctly.
- **UI-04-011:** Clicking a source opens live tabular preview with expected columns and rows.
- **UI-04-012:** Drag a replacement file onto a file source; cancel leaves the source unchanged.
- **UI-04-013:** Confirm replacement; verify updated rows/schema and continued queryability after reload.
- **UI-04-014:** Replace with an invalid file and verify safe failure without breaking unrelated sources/VDB.
- **UI-04-015:** Authorized user removes a source from a project without deleting the underlying source.
- **UI-04-016:** Unauthorized user cannot see or activate project-removal controls.
- **UI-04-017:** Database connector creation exposes required fields, validation, success, and safe error states when a sandbox connector is configured.
- **UI-04-018:** SaaS connector entries and connected-source badges behave correctly when sandbox integrations are configured.
- **UI-04-019:** Unsupported/oversized/malformed upload shows an actionable error and creates no partial source.
- **UI-04-020:** Project Overview upload always associates content with the active project.

### Suite UI-05 — Queries, SQL Editor, visual builder, preview, and results

- **UI-05-001:** Query list renders totals, AI/shared status, search, filters, last run, and runtime fields.
- **UI-05-002:** Create, edit, save, execute, and reopen a SQL query.
- **UI-05-003:** SQL Editor schema browser inserts/selects allowed source fields without changing project context.
- **UI-05-004:** Inline rename updates the query in the list, detail view, and Overview.
- **UI-05-005:** Origin and visibility filters return the correct rows and compose with search.
- **UI-05-006:** Selected query context panel shows SQL and metadata.
- **UI-05-007:** Visual builder accepts primary/secondary sources and creates a valid configured join.
- **UI-05-008:** Group By and Order By expand from the collapsed default and affect results.
- **UI-05-009:** Result grid renders typed values, empty values, and large result navigation without layout failure.
- **UI-05-010:** Query execution failure shows a useful error and preserves editable SQL.
- **UI-05-011:** Generate Query with AI returns an executable project-scoped query.
- **UI-05-012:** AI-unavailable path creates only the documented safe heuristic query and clearly indicates its limitations if visible.
- **UI-05-013:** Recommended-query preview executes before save and shows summary, chart/KPI/table, data grid, sources, and hidden SQL.
- **UI-05-014:** Show SQL expands/collapses and never exposes SQL in a prose-only response.
- **UI-05-015:** Save Query is unavailable before preview and works from a successful preview.
- **UI-05-016:** Preview error does not offer a misleading successful save state.
- **UI-05-017:** Add preview to dashboard opens the scoped dashboard workflow and creates the expected widget.
- **UI-05-018:** Common date formats execute through Teiid-compatible normalization.
- **UI-05-019:** AI-generated aggregate query has a valid GROUP BY and executes.
- **UI-05-020:** Successful zero-row query shows a no-results state while preserving SQL inspection.

### Suite UI-06 — Scope Navigation, builder, and drill-down

- **UI-06-001:** Scope Navigation lists named scope sets with enabled state and AI/manual origin.
- **UI-06-002:** Create, rename, enable, disable, and delete a run-created scope set.
- **UI-06-003:** Open builder and drag query/table cards to the canvas.
- **UI-06-004:** Connect source and target fields and save the map.
- **UI-06-005:** Create a multi-field mapping and verify grouping/match mode after reload.
- **UI-06-006:** Canvas positions, pan, and zoom persist as designed.
- **UI-06-007:** Click a relationship line and verify source/target, fields, mode, direction, enabled state, origin, and confidence.
- **UI-06-008:** Edit, reverse, and delete a relationship from the line popup.
- **UI-06-009:** Request AI Suggest and verify directional suggestions, confidence, and rationale.
- **UI-06-010:** Accept a suggestion, save, reload, and verify AI origin/confidence persist.
- **UI-06-011:** Generate AI Scopes creates/updates the AI Generated Scopes set and shows progress/error state.
- **UI-06-012:** Enabling auto-scope causes a new/updated query to receive supported scopes.
- **UI-06-013:** Query list and grid scope indicators refresh after map changes.
- **UI-06-014:** Clicking a scoped cell opens/filters the target query with the clicked value.
- **UI-06-015:** Disabling the mapping removes the drill-down affordance without relying on a stale project flag.

### Suite UI-07 — Dashboards, widgets, filters, and grid layout

- **UI-07-001:** Dashboard list shows status, AI origin, view count, widget count, and New Dashboard action.
- **UI-07-002:** Create, rename/edit, open, and delete a run-created dashboard.
- **UI-07-003:** Add a widget and verify source, chart type, X/Y, aggregation, group by, sort, Top N, filters, date granularity, and size controls.
- **UI-07-004:** Smart column detection exposes appropriate fields/types.
- **UI-07-005:** SUM, AVG, COUNT, MIN, and MAX produce expected visible values.
- **UI-07-006:** Day, Week, Month, Quarter, and Year granularity group supported dates correctly.
- **UI-07-007:** Per-widget filters affect only the target widget.
- **UI-07-008:** Dashboard date, multi-select, numeric-range, and text filters apply to compatible widgets.
- **UI-07-009:** Group-by results render multiple/stacked series with correct labels.
- **UI-07-010:** Drag widget position and verify persistence after reload.
- **UI-07-011:** Resize widget horizontally and vertically and verify persistence after reload.
- **UI-07-012:** Narrow breakpoints clamp/repack widgets without overwriting saved desktop dimensions.
- **UI-07-013:** Pin widget to Home and verify the live pin renders and refreshes.
- **UI-07-014:** Generate Dashboard returns narrative, findings, actions, and more than one valid widget for a rich project.
- **UI-07-015:** A single failing planned widget does not remove successful siblings or collapse the whole dashboard.
- **UI-07-016:** Show Data toggles the widget’s table without changing the chart.
- **UI-07-017:** Save generated dashboard creates the dashboard and preserves chart options.
- **UI-07-018:** Viewer can view but cannot edit layout/configuration.

### Suite UI-08 — ECharts rendering and Chart Suggestion

- **UI-08-001:** Verify a representative fixture renders every enabled chart family offered by the catalog without a client exception.
- **UI-08-002:** Verify line, area, bar, pie/donut, combo, scatter, radar, radial bar, treemap, funnel, Sankey, gauge, and heatmap core families.
- **UI-08-003:** Verify extended families when offered: effect scatter, sunburst, tree, graph, parallel, lines, candlestick, boxplot, pictorial bar, theme river, and map.
- **UI-08-004:** Chart options for legend, grid, labels, stacking, orientation, curves, reference lines, radii, and axis rotation update the preview and persist.
- **UI-08-005:** High-cardinality categories default to a readable horizontal Top-N chart while the table retains all rows.
- **UI-08-006:** Scalar positive data offers KPI/gauge; time series does not incorrectly offer gauge.
- **UI-08-007:** Two measures can offer scatter/combo; two categorical dimensions plus a measure can offer heatmap.
- **UI-08-008:** Identifier columns are not treated as business categories when a better dimension exists.
- **UI-08-009:** Chart Suggestion opens from Business and Project Insight cards.
- **UI-08-010:** Every candidate preview renders using the card’s actual roles/data.
- **UI-08-011:** Apply a new chart and verify it persists after reload and in pin/dashboard flows.
- **UI-08-012:** Weak-fit data safely falls back to table.
- **UI-08-013:** User-requested horizontal bar or donut is honored only when shape-valid.
- **UI-08-014:** Hidden accessibility data remains available to assistive technology without creating a second scrollbar.

### Suite UI-09 — Documents and Document Families

- **UI-09-001:** Upload PDF, DOCX, PPTX, TXT, and Markdown project documents.
- **UI-09-002:** Each document progresses through processing/indexing to active or a clear error state.
- **UI-09-003:** Documents list supports search/selection and shows type, status, summary, extraction, and relationship counts.
- **UI-09-004:** Expand document card and verify AI summary, tags, KPIs, entities, and suggested questions.
- **UI-09-005:** Duplicate/malformed/unsupported document produces the expected validation or processing state without breaking the list.
- **UI-09-006:** Policy/Procedure/Runbook/Postmortem files auto-link or suggest the expected family based on confidence.
- **UI-09-007:** Suggested family displays name, role, reason, related members, and confidence.
- **UI-09-008:** Accept a family suggestion and verify linked state after reload.
- **UI-09-009:** Change a document’s family and verify both old/new family views update.
- **UI-09-010:** Remove a family assignment and verify the card and graph update.
- **UI-09-011:** Family drawer shows summary, purpose, members, relationships, supported KPIs, processes, dashboards/questions, and missing documents.
- **UI-09-012:** Rebuild family summary shows progress and updated content.
- **UI-09-013:** Reprocess a document and verify family metadata is preserved or correctly rebuilt.
- **UI-09-014:** Delete/archive a run-created family member and verify obsolete edges/family state disappear from the UI.
- **UI-09-015:** Viewer cannot access document/family mutation actions.

### Suite UI-10 — Reference and Company Libraries

- **UI-10-001:** Root admin sees Industry Library; tenant admin sees Company Library; project user sees Project Library tabs according to permissions.
- **UI-10-002:** Unauthorized roles cannot access write actions by hidden control or direct route.
- **UI-10-003:** Upload each supported reference format and observe processing to active/error.
- **UI-10-004:** Metadata-only stubs show Needs document; processed items show the correct status.
- **UI-10-005:** Starter-catalog title matching autofills issuer/domain/source/version.
- **UI-10-006:** Duplicate detection prevents unintended duplicate records and can fill an existing stub.
- **UI-10-007:** Edit, download, reprocess, and supersede a run-created reference.
- **UI-10-008:** Company inherited references appear in project Inherited.
- **UI-10-009:** Remove and re-add an inherited reference.
- **UI-10-010:** Generate project suggestions, approve one, and dismiss one.
- **UI-10-011:** Create an addition request and verify it appears in the expected requester state.
- **UI-10-012:** Bulk URL CSV validates rows as Ready, Skipped, or Error before import.
- **UI-10-013:** Bulk import shows live progress, final counts, retry-failed, and downloadable failure report.
- **UI-10-014:** Redirect, duplicate, paywalled/manual, unsupported type, oversized, and failed URL rows receive the expected disposition.
- **UI-10-015:** Tenant/project isolation prevents another tenant from viewing Company/Project references.

### Suite UI-11 — Repository intelligence

- **UI-11-001:** Tenant admin opens Repositories from Settings and sees connection list/profile UI.
- **UI-11-002:** Create UNC connection form validates host/share/path/user requirements and never redisplays a password.
- **UI-11-003:** Traversal, wildcard, drive-letter, and URI-scheme paths are rejected safely.
- **UI-11-004:** Test Connection shows success for configured sandbox or actionable sanitized failure.
- **UI-11-005:** Start scan, observe queued/running/completed state, and prevent a duplicate concurrent scan.
- **UI-11-006:** Scan history and heartbeat/stalled state are understandable.
- **UI-11-007:** Item browser paginates and shows new/changed/deleted/extraction status.
- **UI-11-008:** Rescan detects changed and missing synthetic files.
- **UI-11-009:** Governance-blocked extraction displays a governed status without leaking credentials or server paths.
- **UI-11-010:** Viewer and non-admin users cannot create, test, or scan repository connections.

### Suite UI-12 — Metadata Catalog, Relationship Map, Knowledge Graph, and Audit Log

- **UI-12-001:** Metadata Catalog lists project tables/documents and supports search/selection.
- **UI-12-002:** Selected table shows summary, status, fields, type, AI description, null %, distinct count, samples, and AI inclusion.
- **UI-12-003:** Selected document shows available profile/relationship information.
- **UI-12-004:** Relationship Map renders data source, query, document, dashboard, attribute, and family nodes available to the project.
- **UI-12-005:** Graph filters change visible nodes/edges without losing selection context.
- **UI-12-006:** Selected node panel lists connected edges and graph statistics.
- **UI-12-007:** Family/document subgraph filtering shows only the relevant graph.
- **UI-12-008:** Trigger an allowed document change and verify graph stale/build/rebuilt status through the UI.
- **UI-12-009:** Incremental rebuild completes and dependent Project/Business Insight eventually refreshes.
- **UI-12-010:** Failed/degraded graph state shows a usable explanation and retains safe existing information.
- **UI-12-011:** Audit Log filters All, AI, Queries, Data access, and Dashboards correctly.
- **UI-12-012:** Audit events display timestamp, actor, label, title, and detail in newest-first order.
- **UI-12-013:** Audit summary counts match visible event categories.
- **UI-12-014:** Cross-tenant direct URLs return not found/access denied and never graph/catalog data.

### Suite UI-13 — AI Assistant and conversational analytics

- **UI-13-001:** Global AI Assistant starts New chat, sends a prompt, renders a response, and stores the conversation.
- **UI-13-002:** Conversation list selects/resumes a previous thread and delete removes only the selected user-owned thread.
- **UI-13-003:** Project Ask TableScope lists only the current user’s project-scoped conversations.
- **UI-13-004:** A quantitative question executes and renders summary, chart, grid, and collapsed SQL.
- **UI-13-005:** A prose/document question renders prose and references without forcing a chart or exposing SQL.
- **UI-13-006:** Zero-row data question stays structured with a clear no-results state.
- **UI-13-007:** “Change it to a line chart” changes the chart without re-running prior SQL.
- **UI-13-008:** “Sort descending” or filter follow-up generates/executes a refined query using prior context.
- **UI-13-009:** Explain follow-up displays the analytical method/evidence when available.
- **UI-13-010:** Retry creates the expected new/updated turn without duplicating a completed turn.
- **UI-13-011:** Rename and delete a conversation persist after reload.
- **UI-13-012:** Duplicate client submission does not create duplicate turns.
- **UI-13-013:** Project Overview Ask Anything creates/resumes the same conversation inline.
- **UI-13-014:** New chat clears inline context and first message creates the new thread.
- **UI-13-015:** Open in AI Assistant deep-links to the exact inline conversation.
- **UI-13-016:** Similar project names do not silently change the active project; ambiguous scope is confirmed or remains explicit.
- **UI-13-017:** AI busy/unavailable/error state is actionable, does not show a raw exception, and does not erase prior successful turns.
- **UI-13-018:** Second-tenant/project content cannot be retrieved through prompts or conversation URLs.

### Suite UI-14 — Business Insight

- **UI-14-001:** Business Insight loads Risks, Trends, Opportunities, and Deeper Analysis from accessible projects.
- **UI-14-002:** Risks, Trends, and Opportunities start collapsed and expand independently.
- **UI-14-003:** Project filter defaults to all projects and supports individual selection, Select all, and Clear.
- **UI-14-004:** Partial/empty project selection updates cards/counts and hides cross-project synthesis.
- **UI-14-005:** Refresh keeps prior cards visible and shows per-project Analyzing state until each completes.
- **UI-14-006:** Last-updated state changes only after successful completion.
- **UI-14-007:** Stream disconnect/reload returns to persisted results and background completion does not lose the run.
- **UI-14-008:** AI contention/partial failure preserves successful projects and prior good snapshots.
- **UI-14-009:** Data-bearing project receives grounded fallback cards when the AI plan is empty/unavailable.
- **UI-14-010:** Nonfinancial project receives a real period/volume trend rather than a canned spending trend.
- **UI-14-011:** Threshold/status and upcoming-date fixtures create grounded risk cards.
- **UI-14-012:** Entity/measure fixture creates a grounded opportunity ranking.
- **UI-14-013:** Valid relationships produce cross-table cards with multiple source tables and lineage.
- **UI-14-014:** Unsafe many-to-many/fan-out candidate is rejected or clearly not surfaced.
- **UI-14-015:** Multi-table cards are not dropped merely because single-table card limit is reached.
- **UI-14-016:** Refresh with unchanged context produces stable card identities and substantially stable plan/card set.
- **UI-14-017:** Governed KPI appears only when required fields exist and is cited on the card.
- **UI-14-018:** Evidence-equivalent cards with different wording are deduplicated.
- **UI-14-019:** Explain shows confidence score, factors, caps, gaps, and suggested confidence improvements.
- **UI-14-020:** Subsequent refresh shows New/up/down/flat trend badge with polarity-aware color.
- **UI-14-021:** Multi-entity enabled project emits card type, entities, evidence status, analysis, and lineage.
- **UI-14-022:** Deeper Analysis can surface representative YoY/MoM, actual-vs-target, anomaly/change point, forecast, drivers/contribution, or co-movement results supported by fixtures.
- **UI-14-023:** Immaterial result is not presented as a significant executive finding.
- **UI-14-024:** More Actions independently expands source/action controls for one card without affecting another.
- **UI-14-025:** No standing warning banner, raw Markdown markers, duplicate report-builder panel, or inaccessible final card remains.

### Suite UI-15 — Project Insight

- **UI-15-001:** Project Insight renders executive summary and available Risks, Trends, Opportunities, Deeper Analysis, Questions, and Recommendations for the active project.
- **UI-15-002:** Summary colors/labels match critical, warning, opportunity, and recommendation meaning.
- **UI-15-003:** Collapsible panels have correct defaults, counts, keyboard behavior, and independent state.
- **UI-15-004:** Trend results appear only in the Trends area, not a duplicate panel.
- **UI-15-005:** Initial navigation hydrates the last snapshot without forcing a blank full rebuild.
- **UI-15-006:** Stale snapshot remains visible while event-driven rebuild runs and clears stale state on success.
- **UI-15-007:** Manual refresh shows progress and updates generated time only after success.
- **UI-15-008:** Scoped Insights & Opportunities request analyzes only the active project.
- **UI-15-009:** Card renders chart and governed analytical method/provenance when data-backed.
- **UI-15-010:** Card without raw SQL/result derives analytical method from chart series rather than showing an empty/broken panel.
- **UI-15-011:** Chart Suggestion, Pin to Home, Add to Dashboard, Explain, feedback, and +Action behave consistently with Business Insight.
- **UI-15-012:** Duplicate pin is prevented and the pinned state is visible in the header.
- **UI-15-013:** More Actions hides/reveals data sources and actions accessibly.
- **UI-15-014:** Recommended query preview executes before save.
- **UI-15-015:** Recommended dashboard builds multiple usable widgets for the rich project.
- **UI-15-016:** Recommended KPI references a governed metric supported by project fields.
- **UI-15-017:** Viewer lacks mutation actions but retains permitted card details.
- **UI-15-018:** Other-project and other-tenant snapshot URLs do not reveal data.

### Suite UI-16 — Home pins and saved insight/dashboard content

- **UI-16-001:** Pin Business Insight card from its header; pinned card appears on Home.
- **UI-16-002:** Pin Project Insight card; duplicate fingerprint pin is blocked/reflected.
- **UI-16-003:** Unpin removes only the selected pin.
- **UI-16-004:** Frozen insight preserves title, summary, chart, evidence, and actions expected for frozen state.
- **UI-16-005:** Live dashboard widget pin refreshes current query data.
- **UI-16-006:** Home grid fills real container width on initial load and reload.
- **UI-16-007:** Four KPI-sized pins can occupy one desktop row using expected default sizing.
- **UI-16-008:** Drag and all supported resize directions work without hidden/unusable hit areas.
- **UI-16-009:** Layout persists after reload and remains usable across breakpoints.
- **UI-16-010:** Narrow layouts do not overwrite desktop layout dimensions.
- **UI-16-011:** Failed layout save rolls back visibly and reports an error.
- **UI-16-012:** User cannot access another user’s pin by direct URL/API-driven navigation.

### Suite UI-17 — Explain, feedback, and governed review

- **UI-17-001:** Explain opens from Business and Project Insight and displays available summary, method, steps, source, SQL, evidence, assumptions, limitations, and confidence.
- **UI-17-002:** Legacy card without structured explanation shows a safe fallback.
- **UI-17-003:** Thumbs-up and thumbs-down open with the selected sentiment and no preselected incorrect sentiment.
- **UI-17-004:** Blank/whitespace comment cannot be submitted; valid comment and reason codes save.
- **UI-17-005:** User can edit, switch sentiment, withdraw, and resubmit their feedback.
- **UI-17-006:** Feedback state remains synchronized across Business Insight, Project Insight, and Home pin.
- **UI-17-007:** Agree feedback displays the documented not-required review state.
- **UI-17-008:** Disagree feedback enters the reviewer queue.
- **UI-17-009:** Reviewer filters queue by status, sentiment, and project.
- **UI-17-010:** Reviewer claims/acknowledges an item; a second reviewer receives conflict or disabled action.
- **UI-17-011:** Reviewer releases an item back to pending.
- **UI-17-012:** Request Info requires a comment and changes user-visible status.
- **UI-17-013:** Original submitter responds; item returns to in-review state.
- **UI-17-014:** Accepted/rejected disposition requires rationale and respects claimant/admin rules.
- **UI-17-015:** Editing an active disagreement increments revision and requeues as designed.
- **UI-17-016:** Personal and governance badges show Under Review/Disputed/Validated without revealing private comments.
- **UI-17-017:** Unauthorized user cannot open review routes or call review actions through the UI.
- **UI-17-018:** Other tenant’s feedback never appears in queue, batch state, card badge, or direct URL.

### Suite UI-18 — Project Business Context

- **UI-18-001:** Open Business Context and verify General Settings, Goals, Metrics & Targets, Risks, AI Context, and Audit tabs.
- **UI-18-002:** Create, edit, reorder, status, and delete a run-created goal.
- **UI-18-003:** Create/edit metric with aggregation/direction and verify display.
- **UI-18-004:** Create multiple targets, edit one, and delete one.
- **UI-18-005:** Create/edit/reorder/delete a run-created risk with severity, likelihood, impact, and review date.
- **UI-18-006:** Link goals to metrics/risks and risks to metrics; invalid cross-project IDs are not selectable/accepted.
- **UI-18-007:** Concurrent edit produces a visible conflict instead of silent overwrite.
- **UI-18-008:** Viewer sees context read-only.
- **UI-18-009:** AI Context preview reflects instructions, goals, metrics, risks, actions, and governed feedback within bounded output.
- **UI-18-010:** Disable AI context and verify the visible state and subsequent behavior expected by product design.
- **UI-18-011:** Project instructions are shown as guidance and cannot override blocked tenant AI methods.
- **UI-18-012:** Mutations appear in Audit History with actor and timestamp.
- **UI-18-013:** Context changes eventually mark/rebuild dependent Project Insight.
- **UI-18-014:** Second-tenant user cannot view or mutate context.

### Suite UI-19 — Project Actions

- **UI-19-001:** `+ Action` from a Business Insight prepopulates the correct project and source evidence.
- **UI-19-002:** `+ Action` from Project Insight/Home pin produces the same source linkage.
- **UI-19-003:** Project Actions list supports status, priority, owner, overdue, source, and text filters.
- **UI-19-004:** Action row/detail shows title, owner, due date, priority, status, progress, and source.
- **UI-19-005:** Create, edit, and archive a run-created action.
- **UI-19-006:** Create multiple required and optional/cancelled subtasks.
- **UI-19-007:** Completing required subtasks updates parent percent server-authoritatively.
- **UI-19-008:** All required subtasks at 100% auto-complete the parent.
- **UI-19-009:** Reopening a required subtask reopens the parent and lowers progress.
- **UI-19-010:** Cancelled subtasks are excluded from progress.
- **UI-19-011:** Source fingerprint/count prevents or clearly identifies duplicate insight actions.
- **UI-19-012:** Action/context change eventually affects subsequent project mitigation context.
- **UI-19-013:** Viewer cannot create/edit/archive actions or subtasks.
- **UI-19-014:** Action count in project navigation updates after creation/archive.

### Suite UI-20 — Analytical Methods, R provenance, and AI Governance

- **UI-20-001:** Analytical Methods page shows catalog totals, executable counts, tier/status/category filters, search, and pagination.
- **UI-20-002:** Method detail shows summary, applicability, intents, executor, method card, engine, and lifecycle status.
- **UI-20-003:** Administrator activates/deactivates an implemented method with confirmation and sees persisted state.
- **UI-20-004:** Method without an implementation has a disabled control and explanatory tooltip.
- **UI-20-005:** R-backed insight shows R Analytics badge only for successful R execution without fallback.
- **UI-20-006:** Analysis details show engine, method name/ID, status, quality, warnings, and fallback disclosure.
- **UI-20-007:** Python fallback hides the R-success badge and explicitly discloses fallback when details open.
- **UI-20-008:** AI Governance page lists method controls and current tenant policy.
- **UI-20-009:** Allow, fallback, and block policy changes require authorized role and persist with version/conflict handling.
- **UI-20-010:** Blocked method shows governance-aware user messaging in insight/conversation surfaces.
- **UI-20-011:** Bulk governance update changes only selected tenant capabilities.
- **UI-20-012:** Governance audit filters/paginates and records policy/method decisions.
- **UI-20-013:** Viewer can see permitted capability messaging but cannot edit policy.
- **UI-20-014:** Another tenant retains independent method activation/governance state.

### Suite UI-21 — Settings, tenant administration, users, and data planes

- **UI-21-001:** Settings opens the nested workspace and redirects to My Tenant by default.
- **UI-21-002:** Desktop navigation and mobile dropdown reach Tenant, Security, Libraries, Branding, Allowed Domains, Repositories, Analytical Methods, and AI Governance according to role.
- **UI-21-003:** My Tenant displays safe tenant/security information and does not expose users, VDB internals, locations, credentials, or cross-tenant IDs.
- **UI-21-004:** Tenant-wide 2FA switch requires confirmation, persists server state, and changes member behavior.
- **UI-21-005:** Tenant document reprocess requires confirmation and shows progress/result without supplying tenant ID.
- **UI-21-006:** Branding changes in disposable staging appear in shell/login without leaking to another tenant.
- **UI-21-007:** Allowed Domains create/edit/delete behavior is role-gated and persists.
- **UI-21-008:** Users page creates/invites a user without collecting an administrator-set password.
- **UI-21-009:** User deactivate and permanent delete operate only on run-created staging users.
- **UI-21-010:** Root admin sees platform tenant/data-plane tools; tenant admin does not see cross-tenant platform controls.
- **UI-21-011:** Data Planes list shows tier, status, subnet/IP, VPN state, connection ID, and health dimensions.
- **UI-21-012:** New Tenant validates No VPN versus Customer VPN requirements.
- **UI-21-013:** Provision Container and Run Health show progress and an actionable result in disposable staging.
- **UI-21-014:** Bind a disposable tenant to a data plane and verify its user-visible query path still works.
- **UI-21-015:** Delete disposable tenant only in approved staging; verify slug can subsequently be reused.
- **UI-21-016:** Admin cache-clear actions are role-gated, confirmed, audited, and scoped to Business or one Project Insight cache.

### Suite UI-22 — Accessibility, keyboard, error states, and visual regression

- **UI-22-001:** Run automated accessibility scan on every primary route for each representative role; report all serious/critical violations.
- **UI-22-002:** Verify headings, landmarks, accessible names, labels, table headers, dialog semantics, and status announcements.
- **UI-22-003:** Complete login, project navigation, query preview, scope toggle, card actions, feedback, and dialog close using keyboard only.
- **UI-22-004:** Verify visible focus and no keyboard traps except intentional modal focus containment.
- **UI-22-005:** Verify collapsed panels and More Actions expose `aria-expanded` and correct controlled region.
- **UI-22-006:** Verify chart has accessible fallback/data description and does not create overflow.
- **UI-22-007:** Capture baseline screenshots at 1920×1080, 1440×900, 1280×720, 768×1024, and 390×844 for primary routes.
- **UI-22-008:** Report overlaps, clipping, hidden actions, unreadable labels, excessive whitespace, double scrollbars, and horizontal page scroll.
- **UI-22-009:** Simulate API 401/403/404/409/422/500/503 and network timeout where harness support exists; verify safe, actionable UI states.
- **UI-22-010:** Verify retry/refresh controls do not duplicate mutations or erase last good content.
- **UI-22-011:** Verify toast/banner errors clear appropriately and standing warnings are not permanently displayed after recovery.
- **UI-22-012:** Verify no screenshot/trace includes secret inputs, session tokens, OTPs, or unredacted phone numbers.

## 11. Cross-role permission matrix

For every mutating control, run at least one authorized and one unauthorized check.

| Capability | Root | Tenant admin | Project admin/owner | Editor | Viewer | Reviewer |
| --- | --- | --- | --- | --- | --- | --- |
| Platform tenants/data planes | Yes | No | No | No | No | No |
| Tenant users/settings/2FA | Platform-dependent | Yes, own tenant | No | No | No | No |
| Project membership | Admin override | Admin override | Yes | No | Read-only | Read-only |
| Data/query/dashboard/document mutations | Admin override | Admin override | Yes | Yes where permitted | No | No unless separately permitted |
| Scope authoring | Admin override | Admin override | Yes | Yes | No | No |
| Project context/actions | Admin override | Admin override | Yes | Yes where permitted | Read-only | Read-only |
| Insight feedback | Own feedback | Own feedback | Own feedback | Own feedback | Own feedback | Own feedback + review permission |
| Review disposition | Admin override | Admin/reviewer mapping | Only with review permission | No | No | Yes |
| AI governance/method activation | Platform/tenant rules | Yes | No | No | Read-only capability state | No |

If actual product policy differs, report the observed policy and cite the applicable inventory/route behavior; do not alter permissions.

## 12. Findings protocol

### 12.1 When to create a finding

Create a finding for:

- incorrect or missing visible behavior;
- broken navigation/control/action;
- unexpected permission exposure or denial;
- data loss, wrong persistence, cross-project/tenant leakage;
- raw exception, console exception, unexpected failed request;
- misleading success or missing error state;
- inaccessible keyboard/screen-reader behavior;
- responsive/visual defect that blocks or materially degrades use;
- intermittent failure on retry;
- undocumented mismatch between inventory and current UI;
- a planned UI feature that cannot be found.

Do not create separate findings for the same root symptom on multiple browsers/routes. Create one primary finding and list all affected cases.

### 12.2 Severity

| Severity | Definition |
| --- | --- |
| **P0 Critical** | Cross-tenant/security exposure, unrecoverable data loss, widespread authentication bypass, or application unusable for all users |
| **P1 High** | Core user workflow unavailable, privileged control broken/exposed, major persistence failure, or widespread crash |
| **P2 Medium** | Feature partially works, important incorrect result/state, recoverable workflow failure, or material accessibility issue |
| **P3 Low** | Minor visual, copy, usability, or accessibility issue with a practical workaround |

### 12.3 Finding file template

Create one Markdown file per unique finding:

```markdown
# UI-FINDING-0001 — <Concise title>

## Classification
- Severity: P0 | P1 | P2 | P3
- Status: NEW | DUPLICATE | INTERMITTENT | BLOCKED
- Area: <workspace/feature>
- Feature inventory IDs: <IDs>
- Automated test IDs: <IDs>
- Environment: <URL/environment>
- Build/commit: <SHA/version>
- Browser/viewport: <browser/version/size>
- User role: <role>
- Frequency: <x/y attempts>

## Summary
<One-paragraph user impact>

## Preconditions
1. ...

## Reproduction steps
1. ...

## Expected result
...

## Actual result
...

## Evidence
- Screenshot: <relative path>
- Video: <relative path if available>
- Trace: <relative path>
- Console log: <relative path>
- Network log/request ID: <relative path or redacted ID>

## User impact
...

## Technical assessment
<Evidence-based likely layer/root cause. Clearly label inference.>

## Proposed fix — DO NOT IMPLEMENT
<Specific recommended correction, candidate components/services, validation needed, and risks.>

## Recommended regression coverage
- ...

## Related/duplicate findings
- ...
```

### 12.4 Proposed-fix requirements

Every failed finding must include a proposed fix, but Devin must not implement it. The proposed fix must:

- be supported by observed evidence;
- distinguish confirmed cause from inference;
- identify the likely frontend, API, worker, AI/R, data, or authorization layer;
- name candidate files/components only when repository inspection supports it;
- describe the expected corrected behavior;
- identify regression tests that should be added or updated;
- note security, tenant-isolation, migration, caching, or compatibility risks;
- avoid including secrets or copying sensitive payloads.

## 13. Execution report structure

`UI_TEST_EXECUTION_REPORT.md` must contain:

1. Executive summary.
2. Environment, build, browsers, roles, and time window.
3. Scope and explicit exclusions.
4. Test-data setup and cleanup result.
5. Results table by suite: total, pass, fail, blocked, not run, intermittent.
6. Results table by role.
7. Results table by browser/viewport.
8. Findings by severity.
9. Detailed finding links.
10. Coverage summary against all inventory IDs.
11. Blockers and missing prerequisites.
12. Observed performance/reliability notes.
13. Cleanup confirmation.
14. Explicit statement: **No application defects were fixed as part of this mission.**

## 14. Feature coverage matrix requirements

`UI_FEATURE_COVERAGE_MATRIX.csv` columns:

```text
feature_id,feature_name,inventory_section,ui_scope,direct_or_indirect,
test_ids,roles,browsers,result,finding_ids,blocked_reason,notes
```

Rules:

- One row per feature ID from the inventory.
- Multiple tests may map to one feature; one test may cover multiple tightly related features.
- No blank `result` cells.
- `ui_scope=false` requires `OUT_OF_UI_SCOPE` plus a specific rationale.
- Directly visible features cannot be marked out of scope merely because credentials or fixtures are missing; use a blocked result.
- Coverage percentage is `(PASS + FAIL + INTERMITTENT) / directly testable UI features`.

## 15. Findings summary requirements

`UI_FINDINGS_SUMMARY.csv` columns:

```text
finding_id,title,severity,status,area,feature_ids,test_ids,role,browser,
frequency,user_impact,proposed_fix_summary,evidence_path
```

Sort by severity, then area, then finding ID.

## 16. Execution order

Run in this order so foundational blockers are discovered early:

1. Preflight/environment safety.
2. Authentication and tenant isolation smoke.
3. Shell/navigation and permission discovery.
4. Synthetic test-data setup.
5. Projects, membership, and Data Sources.
6. Queries and scopes.
7. Dashboards and charts.
8. Documents, libraries, repositories, metadata, and graph.
9. AI Assistant, Business Insight, and Project Insight.
10. Home pins, feedback/review, context, and actions.
11. Methods, R provenance, governance, and Settings.
12. Cross-browser smoke, accessibility, responsive, and error-state passes.
13. Cleanup only run-created records.
14. Consolidate duplicates, write findings, coverage matrix, and final report.

If a foundational suite fails, continue every independent read-only suite and mark dependent scenarios with the exact blocker.

## 17. Definition of done

The mission is complete only when:

- every inventory feature ID has a coverage-matrix row;
- every directly user-visible feature is passed, failed, intermittent, or explicitly blocked;
- every failed/intermittent scenario has evidence and a unique or linked finding;
- every unique finding contains a proposed fix and recommended regression coverage;
- no application fix, migration, configuration change, or deployment was performed;
- no pre-existing user data was changed or deleted;
- run-created data was cleaned up or listed precisely if cleanup could not complete;
- secrets and personal data are absent from all artifacts;
- the final report is internally consistent with JUnit/Playwright counts;
- the final Devin response links all required report artifacts.

## 18. Final instruction to Devin

Execute this as a UI quality assessment, not an implementation sprint. Be exhaustive, evidence-driven, and role-aware. If a feature is broken, document it. If the probable fix is clear, propose it in the finding. **Do not alter application code or deploy a fix under any circumstance during this mission.**
