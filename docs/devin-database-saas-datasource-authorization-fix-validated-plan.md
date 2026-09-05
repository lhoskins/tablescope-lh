# Devin: merge and deploy — database/SaaS datasource authorization fix

**Repository:** `lhoskins/tablescope-lh`
**Branch:** `fix/query-authorization-database-datasources`
**Merge target:** `UX-design-03`
**Branch base:** `UX-design-03` tip (`6897825e`) at time of branching

**`platform-api/` only · no migration · all tests green**

---

## Context

The user reported 4 screenshots from the Data Source Builder:

1. Google Sheets connector modal: "Google rejected the refresh token" / "No supported Google Drive files found."
2. ServiceNow connector modal: "ServiceNow rejected the credentials." / "No objects found for this connector."
3. Previewing the "SAPPHIRE Leads" (Google Sheets) data source: `Google token refresh failed 400: {"error": "invalid_grant", "error_description": "Token has been expired or revoked."}`
4. Previewing the "change_request" (ServiceNow) data source: `Unauthorized table reference: change_request_SERVICENOW`

The user suspected recent security work broke the SaaS/database connectors. Investigation found **two unrelated problems**, only one of which is a code bug.

## Finding 1 (not a code bug): expired/revoked Google and ServiceNow credentials

Screenshots 1–3 are real, remote-service-level rejections — Google's OAuth server returning `invalid_grant: Token has been expired or revoked` and the ServiceNow instance returning an authentication failure. I checked:

- `app/services/crypto.py` (Fernet encryption for stored secrets) — unchanged by any recent commit, and a key-mismatch/decrypt failure would surface as a local `ValueError`/500, not a clean "Google rejected"/"ServiceNow rejected" message from the remote service itself.
- No commit touching `connector_credential.py`, Google Drive OAuth, or ServiceNow credential handling appears anywhere near the recent TS-ISO security work (`e189ec9e`, `b5f57435`) — those commits touch VDB password encryption and project-access policy, not SaaS/OAuth credential storage at all.

**Conclusion: these two connectors' stored credentials are genuinely expired/revoked/incorrect and need to be reconnected through the UI** (Google Drive: re-authorize via OAuth; ServiceNow: re-enter/verify instance URL, username, and password in the connector's Edit/Test flow). This is not something a code change can fix.

## Finding 2 (confirmed code bug, fixed on this branch): incomplete table authorization allowlist

Screenshot 4's `Unauthorized table reference: change_request_SERVICENOW` **is** a real regression, traced to its exact origin:

- TS-ISO-002 (commit `e189ec9e`, "Fix tenant/project isolation gaps... unauthorized SQL...") added a real, necessary fix: `/api/query/datasource` previously executed any caller-supplied SQL/table name with **no allowlist check at all**. The fix built `allowed_tables` from `project_table_schema()` and gates both the plain-tableName preview path (`app/routes/query.py`) and the SQL path (`sql_authorization.py`'s `authorize_sql`, called from every attempt in `query_sql_helpers.py`'s repair loop) against it.
- `project_table_schema()` (`app/services/teiid_sql/string_filters.py`) only ever queried `FileSourceMeta` — the table for **uploaded-file sources**. Every JDBC database connector and every SaaS connector object (ServiceNow, HubSpot, Salesforce, QuickBooks, live-translated Google Sheets, etc.) is registered as a `DatabaseDataSource` row instead (confirmed: `app/services/saas_source_service.py` creates `DatabaseDataSource` rows for SaaS objects, and `generate_view_name()` in `app/services/teiid_registration_service/naming.py` produces exactly `"change_request_SERVICENOW"` for a ServiceNow object named "change_request" — this is the correct, legitimately-generated view name, not a naming bug).
- Net effect, confirmed by reproducing it exactly: in a project that also has ≥1 uploaded file (so `allowed_tables` is non-empty), any database/SaaS-sourced table is wrongly rejected as unauthorized. **Worse**, in a project with zero uploaded files, `allowed_tables` is always empty, and `authorize_sql`'s `if allowed_tables:` guard silently skips the entire allowlist check — meaning the exact vulnerability TS-ISO-002 was built to close is not actually closed for any all-database/all-SaaS project.

**Fix:** `project_table_schema()` now also queries active, non-archived `DatabaseDataSource` rows for the project (mirroring the union pattern already used correctly in `app/routes/projects_datasources.py`), including each source's registered `DataSourceColumn` rows as its column schema, keyed by `teiid_view_name`. This single change:
- makes every legitimate database/SaaS table pass the allowlist correctly,
- makes the allowlist actually non-empty (and therefore actually enforced) for all-database/all-SaaS projects, closing the fail-open gap,
- also improves AI SQL-generation/repair quality for these tables, since `project_table_schema()` is the same schema-context source used by `ai_proxy_ask_and_run.py`, `home_intelligence_suite.py`, and `ai_proxy.py` (previously these had zero column context for any database/SaaS table).

`project_source_label_map()` (the sibling helper that rewrites raw Google-Sheets-header labels to SQL-safe field names) was left unchanged — database/SaaS columns are already registered under sanitized Teiid-safe identifiers at source, so there's no raw-label-vs-field split to rewrite for them the way spaced Google Sheets headers need.

### Files changed

| File | Change |
|---|---|
| `platform-api/app/services/teiid_sql/string_filters.py` | `project_table_schema()` now unions `FileSourceMeta` and active/non-archived `DatabaseDataSource` rows |
| `platform-api/tests/test_project_table_schema.py` (new) | 3 unit tests: SaaS table included alongside a file source; archived/draft `DatabaseDataSource` rows excluded; a database-only project (no files) still gets a non-empty allowlist |
| `platform-api/tests/test_query_datasource_authorization.py` | +1 route-level regression test reproducing the exact live scenario (a project with an uploaded CSV *and* a ServiceNow-object table, previewed via the plain-tableName path) |

All 4 new tests were proven fail-before/pass-after via `git stash` — the route-level test reproduces the exact reported `403 Unauthorized table reference: change_request_SERVICENOW` pre-fix.

## Verification

| Suite | Result |
|---|---|
| `pytest tests/test_project_table_schema.py tests/test_query_datasource_authorization.py -q` | 8 passed, 0 regressions |
| `pytest -q -k "query or sql_authorization or database_source or saas or project_table_schema or ask_and_run or home_intelligence"` | 207 passed, 0 regressions |
| `ruff check app/services/teiid_sql/string_filters.py tests/test_project_table_schema.py tests/test_query_datasource_authorization.py` | clean |
| `mypy app/services/teiid_sql/string_filters.py` | clean |
| Full `pytest -q` (whole platform-api suite) | FULL_SUITE_RESULT_PLACEHOLDER |

```bash
cd platform-api
pytest -q
ruff check app/services/teiid_sql/string_filters.py tests/test_project_table_schema.py tests/test_query_datasource_authorization.py
mypy app/services/teiid_sql/string_filters.py
```

## Merge

```bash
git fetch origin --prune
git checkout UX-design-03
git pull --ff-only origin UX-design-03
git merge --no-ff origin/fix/query-authorization-database-datasources \
  -m "Merge: fix incomplete table authorization allowlist for database/SaaS sources"
```

No migration, no terraform, no web-ui changes. No conflicts expected — the change is additive within one existing function.

## Deploy

```bash
docker compose build platform-api platform-api-worker
docker compose up -d platform-api platform-api-worker
```

## Verify live

1. In a project that has at least one uploaded file, preview a database-connector or SaaS-connector table (e.g. the ServiceNow "change_request" object). Confirm it no longer returns `Unauthorized table reference` and the preview renders.
2. In a project with only database/SaaS sources (no uploaded files), run a saved query or dashboard widget referencing one of them and confirm it still executes (i.e. the fix didn't newly break the previously-silently-passing all-database case) — then confirm a query referencing a table that is genuinely *not* part of that project's sources is still correctly rejected with `403 Unauthorized table reference`.
3. Separately, reconnect the Google Drive and ServiceNow Dev connectors shown in the screenshots (re-authorize OAuth for Google; re-verify instance URL/username/password for ServiceNow) — this is an operational credential fix, not something this deploy changes.

## Report back

Confirm both live-verification checks pass, and confirm the Google Drive / ServiceNow credentials have been reconnected separately (outside this deploy).

---

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01M7j8CDCHCdwHpw9FrRhLN5
