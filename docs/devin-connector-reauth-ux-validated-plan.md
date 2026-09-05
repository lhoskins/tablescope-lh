# Devin: merge and deploy — connector reauthorization UX

**Repository:** `lhoskins/tablescope-lh`
**Branch:** `fix/connector-reauth-ux`
**Merge target:** `UX-design-03`
**Branch base:** `UX-design-03` tip (`259ccbd6`) at time of branching

**`platform-api/` + `web-ui/` · no migration · all tests green**

---

## Context

Follow-up to `fix/query-authorization-database-datasources` (merged as `259ccbd6`). That
fix closed a real allowlist bug but correctly diagnosed screenshots 1–3 (Google Drive
"Google rejected the refresh token" / ServiceNow "rejected the credentials" / a live
Google Sheets preview failing with a raw Teiid token-refresh error) as **not a code bug**
— those are genuinely expired/revoked credentials that need reconnecting.

The user then asked for exactly that reconnect flow: *"when a token expires and a Google
Drive connection or SaaS connection already exists, I should be able to click Create Data
Source in the connect list and get reauthorized if needed by going to the Google
authorization page. When I click on a table I expect the same behavior to reauthorize if
needed and not just hang."*

Today, every one of these failures reaches the UI as a bare error string with no recovery
path — the user has to leave the Data Source Builder, find the connection in a different
screen, and redo it from scratch. This branch makes the failure self-service: the UI
detects "this connector needs reconnecting" and offers a reconnect action right where the
failure happened, then automatically retries.

## What was found

Google Drive OAuth (`google_drive/oauth.py`, `client.py`) and all 4 SaaS connectors
(ServiceNow/HubSpot/QuickBooks/Salesforce) already had a `_safe_error()` helper that
distinguished "credentials/token rejected" (401/403, or 400/401/403 for Salesforce) from
other failures **in the human-readable message text only** — callers had no structural way
to detect "reconnect needed" versus any other failure, so every route just returned a
generic 400/502/409-with-plain-string.

A second, structurally different gap: an **already-created** Google Sheets data source is
queried live through Teiid (not through platform-api's own Google Drive client) — Teiid's
own resource adapter holds the refresh token and fails the query itself when Google rejects
it, surfacing as a raw string like:

```
Query failed: TEIID30504 ds_378_google-sheets: Google token refresh failed 400 ...
```

via `/api/query/datasource` (`app/routes/query.py`). This is a completely separate code
path from the browse-time Google Drive/SaaS routes and needed its own fix.

## Fix

### 1. Structured `requires_reauth` signal (backend)

- `GoogleOAuthError`, `GoogleDriveError` (`google_drive/oauth.py`, `client.py`) and
  `SaasConnectorError` (`connectors/base.py`) all gained a `requires_reauth: bool = False`
  field, set `True` at the specific raise sites that mean "the stored credential itself is
  invalid": Google refresh rejected (`resp.status_code >= 400`), Google Drive API 401, and
  each SaaS connector's 401/403 (400/401/403 for Salesforce specifically, matching that
  connector's own `_safe_error` convention).
- `spreadsheet_connections.py` and `saas_sources.py` now map `requires_reauth=True` errors
  to `HTTPException(409, detail={"code": "CONNECTOR_REAUTH_REQUIRED", "message": ...})`
  instead of a plain 400/502 — `"code"` was deliberately chosen to match the frontend's
  *existing* `payload.detail.code` extraction convention in `lib/api-client.ts`.

### 2. In-place Google Drive reconnect (new backend capability)

Previously, reauthorizing an existing Google Drive connection always created a **new**
`ConnectorCredential` row, leaving the old broken one orphaned as a duplicate. The
stateless, Fernet-encrypted OAuth state token (`create_state_token`/`verify_state_token`)
now optionally carries a `credential_id`, so:

- `POST /spreadsheet-connections/authorize` accepts an optional `{"credential_id": int}`
  body (validated to belong to the caller's tenant).
- `POST /spreadsheet-connections/callback` updates that existing credential's
  `secret_encrypted` in place instead of creating a new row when the state token carries
  one, then `await session.refresh(credential)` (required — accessing attributes on an
  updated-in-place ORM object after `commit()` without a refresh raises
  `sqlalchemy.exc.MissingGreenlet` outside an async greenlet context).

### 3. Live-query reauth detection (`app/routes/query.py`, new)

`query_sql_helpers._run_sql` now recognizes a Google Sheets token failure by the
datasource name Teiid itself reports (`ds_<FileSourceMeta.id>_google-sheets`, generated
deterministically at registration time) combined with an auth-related hint in the message
(`token|refresh|invalid_grant|unauthoriz|credential`), and raises a new
`SourceReauthRequiredError(file_source_meta_id=...)` instead of a bare 502. `query.py`
catches this at both call sites in `query_datasource` (the plain-tableName path and the
SQL-with-repair path), resolves the failing source back to its
`ConnectorCredential` via `FileSourceMeta.live_source_params["connector_credential_id"]`,
and returns the same `409 {"code": "CONNECTOR_REAUTH_REQUIRED", "credentialId": ...}`
shape — falling back to a reauth prompt with no credential id (never back to a dead-end
502) if that lookup fails for any reason. An unrelated Teiid failure against the same
source (e.g. a genuinely bad query) is left as a plain 502 — only a message that also
looks auth-related is reclassified.

### 4. Frontend: detect + reconnect at the point of failure

- `lib/api-client.ts`: `ApiError` gained `code: string | null` and `credentialId: number |
  null`, both parsed from `detail.code`/`detail.credentialId` when the backend returns the
  structured shape above.
- `lib/api/connectors.ts`: `authorizeGoogleSheets(credentialId?: number)` now forwards
  `credential_id` to `/spreadsheet-connections/authorize` when given.
- `database-connectors/google-sheets-connection-modal.tsx`: accepts an optional
  `credentialId` prop, reauthorizing that connection in place (copy switches to
  "Reconnect Google Drive" when set).
- `data-source-builder/google-sheets-source-modal.tsx` ("Select Google Sheet", opened by
  **Create Data Source**): every fetch (`listGoogleDriveFiles`, `listGoogleSheetTabs`,
  `detectGoogleSheetTables`) now detects `err.code === "CONNECTOR_REAUTH_REQUIRED"` and
  shows a "Reauthorize" banner that opens the (nested) reconnect modal, then retries the
  file list automatically on success.
- `data-source-builder/saas-source-modal.tsx` ("Select objects", opened by **Create Data
  Source** for ServiceNow/HubSpot/QuickBooks/Salesforce): same detection on
  `listSaaSObjects`/`listSaaSFields`, reusing the existing `ConnectionModal` in edit mode
  (`updateSaasCredential` already updates in place — no duplicate-row problem exists for
  SaaS credentials), retrying on success.
- `data-source-builder/data-review-modal.tsx` ("click on a table" preview, the reported
  "hang"): `previewCreatedSource` failures now check the same `code`; on
  `CONNECTOR_REAUTH_REQUIRED` the dead-end red error box is replaced with a "Reauthorize
  Google Drive" button (using the `credentialId` the backend resolved, scoping the reconnect
  to the right connection), which retries the preview automatically once reconnected.

### Files changed

**Backend:** `app/connectors/base.py`, `app/connectors/saas/{servicenow,hubspot,quickbooks,salesforce}.py`,
`app/services/google_drive/{oauth,client}.py`, `app/routes/spreadsheet_connections.py`,
`app/routes/saas_sources.py`, `app/routes/query.py`, `app/routes/query_sql_helpers.py`.

**Backend tests (new/updated):** `tests/test_saas_connectors.py`,
`tests/test_spreadsheet_connections_routes.py`, `tests/test_saas_sources_reauth.py` (new),
`tests/test_query_datasource_reauth.py` (new).

**Frontend:** `lib/api-client.ts`, `lib/api/connectors.ts`,
`components/tablescope/database-connectors/google-sheets-connection-modal.tsx`,
`components/tablescope/data-source-builder/{google-sheets-source-modal,saas-source-modal,data-review-modal}.tsx`.

All new backend tests were proven fail-before/pass-after via `git stash` on the touched
files.

## Verification

| Suite | Result |
|---|---|
| `pytest -q tests/test_saas_sources_reauth.py tests/test_saas_connectors.py tests/test_spreadsheet_connections_routes.py tests/test_google_drive_oauth.py tests/test_google_drive_client.py tests/test_query_datasource_reauth.py tests/test_query_datasource_authorization.py tests/test_query_datasource_global_filters.py tests/test_project_table_schema.py` | 79 passed, 0 regressions |
| `ruff check` (all 11 touched backend files) | clean |
| `mypy` (all 11 touched backend files) | clean |
| `npm run typecheck` (web-ui) | clean |
| `npm run lint` (web-ui) | clean — pre-existing `max-lines`/`exhaustive-deps` warnings on unrelated files only |
| `npm run build` (web-ui) | succeeds |
| Full `pytest -q` (whole platform-api suite) | 1894 passed, 12 failed, 4 skipped in 1061s. All 12 failures confirmed pre-existing on `UX-design-03` (identical to the 12 documented in the `fix/query-authorization-database-datasources` merge doc): `test_billing.py::test_provision_isolated_data_plane`/`test_provision_isolated_vpn_awaits_details` (broken by the tenant-private-S3 data-plane feature's fail-closed storage resolver, unrelated), `test_visualization_engine.py::test_many_categories_is_horizontal_bar`, `test_percent_change_summary.py` (4 tests), `test_ai_dashboard_pipeline.py::test_correct_widget_converts_oversized_pie`, `test_ask_pipeline.py::test_matrix_resolves_to_heatmap_not_a_narrowed_bar`, `test_business_insight_phase1.py` (3 snapshot-staleness tests) — none touch any file this branch changes. |

```bash
cd platform-api
pytest -q
ruff check app/connectors/base.py app/connectors/saas/hubspot.py app/connectors/saas/quickbooks.py \
  app/connectors/saas/salesforce.py app/connectors/saas/servicenow.py app/routes/query.py \
  app/routes/query_sql_helpers.py app/routes/saas_sources.py app/routes/spreadsheet_connections.py \
  app/services/google_drive/client.py app/services/google_drive/oauth.py
mypy app/connectors/base.py app/connectors/saas/hubspot.py app/connectors/saas/quickbooks.py \
  app/connectors/saas/salesforce.py app/connectors/saas/servicenow.py app/routes/query.py \
  app/routes/query_sql_helpers.py app/routes/saas_sources.py app/routes/spreadsheet_connections.py \
  app/services/google_drive/client.py app/services/google_drive/oauth.py

cd ../web-ui
npm ci --no-audit --no-fund
npm run typecheck
npm run lint
npm run build
```

## Merge

```bash
git fetch origin --prune
git checkout UX-design-03
git pull --ff-only origin UX-design-03
git merge --no-ff origin/fix/connector-reauth-ux \
  -m "Merge: connector reauthorization UX (Google Drive + SaaS)"
```

No migration, no terraform. No conflicts expected — every backend change is additive
within existing functions/routes; every frontend change is additive within existing
components (new props with defaults, new branches in existing catch blocks).

## Deploy

```bash
docker compose build platform-api platform-api-worker web-ui
docker compose up -d platform-api platform-api-worker web-ui
```

## Verify live

1. Let a Google Drive connection's stored token go invalid (or use a tenant where it
   already has). In the Data Source Builder, click **Create Data Source** on that
   connection: confirm a "Reauthorize" banner appears (not a dead-end error), clicking it
   opens the Google consent popup, and completing it reloads the file list in the same
   modal — no duplicate connection is created (check `/api/connectors/created` still shows
   one Google Drive row).
2. Repeat for a SaaS connector (e.g. ServiceNow) with a rejected credential: confirm
   **Create Data Source** shows a "Reconnect" action that opens the existing
   edit-connection form, and saving retries the object list.
3. Preview an **already-created** Google Sheets data source whose token has expired
   (click on its table in the tree): confirm it now shows a "Reauthorize Google Drive"
   button instead of the raw `TEIID30504 ... Google token refresh failed` string, and that
   completing reauthorization automatically loads the preview.
4. Confirm an unrelated query failure (e.g. a malformed saved query) still shows a plain
   error, not a reauth prompt.

## Report back
