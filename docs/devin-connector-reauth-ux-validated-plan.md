# Devin: merge and deploy — connector reauthorization UX

**Repository:** `lhoskins/tablescope-lh`
**Branch:** `fix/connector-reauth-ux`
**Merge target:** `UX-design-03`
**Branch base:** `UX-design-03` tip (`259ccbd6`) at time of branching

**`platform-api/` + `web-ui/` + `docker-compose.yml`/`.env.example` · no migration · all tests green**

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

### 5. A second, wider bug found live-testing this fix: reconnecting didn't fix an
   already-created table

Live-testing this branch surfaced a follow-on bug: after fixing the redirect URI and
successfully reauthorizing Google Drive, "Create Data Source" worked again — but clicking
an **already-created** table (e.g. "SAPPHIRE Leads") still showed the reauthorize prompt.

Root cause: `complete_authorization`'s in-place credential update (part 2 above) updates
`ConnectorCredential.secret_encrypted`, but Teiid's own resource adapter for an
already-registered Google Sheets source holds its own **copy** of the refresh token from
whenever it was confirmed/last re-registered — it does not read back from
`ConnectorCredential` on every query. Reconnecting the credential alone never reached that
already-registered source, so it kept failing on the stale token even though the
connection was "successfully" reconnected. A `reregister_live_sources_for_credential`
helper already existed for exactly this (used by the periodic `google_drive_token_refresh`
cron job on a proactive token refresh) but was never called from the manual-reconnect path.

Asked whether this generalizes: **yes, and worse** — ServiceNow, Salesforce, HubSpot, and
QuickBooks "live" sources (`SaasObjectDataSource.sync_mode == "live"`) are registered into
Teiid the same way, with their own baked-in copy of the username/password/access token.
`PATCH /saas-sources/credentials/{id}` (`update_credential`, exactly what the new SaaS
"Reconnect" button calls) had the identical gap for all four connectors, and — unlike
Google Drive — three of them (ServiceNow, Salesforce, HubSpot) had *no* re-registration
mechanism at all, not even a periodic one; QuickBooks had one, but only from its own cron
job, never from a manual reconnect.

**Fix:**
- `google_drive/registration.py`: `reregister_live_sources_for_credential(session,
  credential)` extracted as a public helper (previously private to
  `google_drive_token_refresh.py`); now called from `complete_authorization`'s in-place
  update branch immediately after the credential commits.
- `saas_source_service.py`: new `reregister_live_saas_sources_for_credential(session,
  credential)`, generalizing the same pattern (previously QuickBooks-only, private to
  `quickbooks_token_refresh.py`) to all four live-translator connector types. Re-derives
  each connector's registration fields from the *current* decrypted config and re-registers
  every `SaasObjectDataSource` with `sync_mode == "live"` backed by that credential, using
  each connector's own `TeiidRegistrationService.register_<type>_source` call. Best-effort
  per source (a failure on one source is logged, not raised).
- `saas_sources.py`: `update_credential` now calls this immediately after a config change
  commits. A display-name-only update (no config change) skips it — nothing to re-register.
- `quickbooks_token_refresh.py`: its private duplicate of this logic replaced with a call
  to the shared function (no behavior change to the cron job itself, just deduplicated).

### 6. A third bug found live-testing #5's fix: the query-time reauth detection was
   Google-Sheets-only

After #5 shipped, live-testing surfaced a third, narrower bug in the *query.py* reauth
detection built earlier in this branch (item 3 above): it correctly recognized a Google
Sheets translator failure (`ds_<id>_google-sheets`) but never generalized to the other four
live-translator connector types. Clicking on an already-created ServiceNow table with a
rejected credential (confirmed live: `TEIID30504 ds_42_servicenow: ServiceNow HTTP 401:
{"error":{"message":"User is not authenticated"...}`) still surfaced the raw Teiid error
instead of the reauthorize prompt, even though the ServiceNow "Create Data Source" picker
correctly showed the Reconnect action for the very same broken credential — a visibly
inconsistent experience for the exact scenario this branch exists to fix.

**Fix:**
- `query_sql_helpers.py`: `SourceReauthRequiredError` now carries `data_source_id` +
  `connector_type` (was `file_source_meta_id`, implicitly Google-Sheets-only). The detection
  regex (`_live_translator_reauth_match`, was `_google_sheets_reauth_source_id`) now matches
  `ds_<id>_(google-sheets|servicenow|salesforce|hubspot|quickbooks)`, and the auth-hint
  pattern was widened to also catch `HTTP 400/401/403` and "not authenticated" (observed in
  the real ServiceNow translator error) alongside the existing token/refresh/invalid_grant
  wording (observed in the real Google translator error).
- `query.py`: `_reauth_required_error` now resolves the credential differently depending on
  `connector_type` — via `FileSourceMeta.live_source_params` for Google Sheets (unchanged),
  or via `SaasObjectDataSource.credential_id` (joined on `database_data_source_id`) for the
  other four. The 409 detail now also carries `connectorType` (translated from Teiid's
  internal `"google-sheets"` spelling to the frontend's `"google_drive"` convention; the
  other four pass through unchanged) so the frontend can pick the right reconnect UI.
- Frontend: `ApiError` gained `connectorType: string | null`. `DataReviewModal` ("click on a
  table") now branches on it: Google Drive still opens `GoogleSheetsConnectionModal` as
  before; the four SaaS types now fetch the credential (`listSaasCredentials`) and open the
  same `ConnectionModal` reconnect flow `saas-source-modal.tsx` already uses, retrying the
  preview automatically on success. Extracted `saasCredentialAsCreatedConnection` from
  `saas-source-modal.tsx` into `lib/api/connectors.ts` so both call sites share it.

### Files changed

**Backend:** `app/connectors/base.py`, `app/connectors/saas/{servicenow,hubspot,quickbooks,salesforce}.py`,
`app/services/google_drive/{oauth,client,registration}.py`, `app/services/saas_source_service.py`,
`app/routes/spreadsheet_connections.py`, `app/routes/saas_sources.py`, `app/routes/query.py`,
`app/routes/query_sql_helpers.py`, `app/tasks/{google_drive_token_refresh,quickbooks_token_refresh}.py`.

**Backend tests (new/updated):** `tests/test_saas_connectors.py`,
`tests/test_spreadsheet_connections_routes.py` (+1: reauthorizing re-registers an
already-confirmed Google Sheet), `tests/test_saas_sources_reauth.py` (new; +3 on the
SaaS re-registration fix), `tests/test_query_datasource_reauth.py` (new; covers Google
Sheets, ServiceNow, and the generalized `_live_translator_reauth_match` unit tests for
all five connector types).

**Frontend:** `lib/api-client.ts`, `lib/api/connectors.ts`,
`components/tablescope/database-connectors/google-sheets-connection-modal.tsx`,
`components/tablescope/data-source-builder/{google-sheets-source-modal,saas-source-modal,data-review-modal}.tsx`.

**Infra (unrelated bug found while live-testing this branch, fixed alongside it):**
`docker-compose.yml`, `.env.example` — `GOOGLE_DRIVE_CLIENT_ID`/`_CLIENT_SECRET`/`_REDIRECT_URI`
were never wired into platform-api's environment block at all, so setting them in `.env`
had no effect on a compose deployment; the container always saw the empty defaults and a
misconfigured/stale redirect sent the browser to a dead URL after Google's consent screen.
`GOOGLE_DRIVE_REDIRECT_URI` now defaults to `${APP_BASE_URL}/connector-callbacks/google`.
This wiring fix ships with the merge below like everything else on this branch — it's a
plain repo change. **It does not by itself make Google Drive work anywhere**: the actual
client ID/secret and (only if `APP_BASE_URL` doesn't already resolve correctly for this
deployment) an explicit `GOOGLE_DRIVE_REDIRECT_URI` still have to be set in that
environment's real `.env`, which is not part of this repo and cannot be supplied by a
merge — see step 0 under Verify live.

All new backend tests were proven fail-before/pass-after via `git stash` on the touched
files.

## Verification

| Suite | Result |
|---|---|
| `pytest -q tests/test_saas_sources_reauth.py tests/test_saas_connectors.py tests/test_spreadsheet_connections_routes.py tests/test_google_drive_oauth.py tests/test_google_drive_client.py tests/test_query_datasource_reauth.py tests/test_query_datasource_authorization.py tests/test_query_datasource_global_filters.py tests/test_project_table_schema.py tests/test_datasource_lifecycle.py` | 92 passed, 0 regressions |
| `ruff check` (all touched backend files, incl. `saas_source_service.py`/`registration.py`/both token-refresh tasks) | clean |
| `mypy` (same files) | clean |
| `npm run typecheck` (web-ui) | clean |
| `npm run lint` (web-ui) | clean — pre-existing `max-lines`/`exhaustive-deps` warnings on unrelated files only |
| `npm run build` (web-ui) | succeeds |
| Full `pytest -q` (whole platform-api suite) | 1903 passed, 12 failed, 4 skipped in 1055s. All 12 failures confirmed pre-existing on `UX-design-03` — identical set documented in every prior full run on this base (`test_billing.py` x2 provisioning tests broken by the tenant-private-S3 data-plane feature, `test_visualization_engine.py`, `test_percent_change_summary.py` x4, `test_ai_dashboard_pipeline.py`, `test_ask_pipeline.py`, `test_business_insight_phase1.py` x3 snapshot-staleness tests) — none touch any file this branch changes. |

```bash
cd platform-api
pytest -q
ruff check app/connectors/base.py app/connectors/saas/hubspot.py app/connectors/saas/quickbooks.py \
  app/connectors/saas/salesforce.py app/connectors/saas/servicenow.py app/routes/query.py \
  app/routes/query_sql_helpers.py app/routes/saas_sources.py app/routes/spreadsheet_connections.py \
  app/services/google_drive/client.py app/services/google_drive/oauth.py \
  app/services/google_drive/registration.py app/services/saas_source_service.py \
  app/tasks/google_drive_token_refresh.py app/tasks/quickbooks_token_refresh.py
mypy app/connectors/base.py app/connectors/saas/hubspot.py app/connectors/saas/quickbooks.py \
  app/connectors/saas/salesforce.py app/connectors/saas/servicenow.py app/routes/query.py \
  app/routes/query_sql_helpers.py app/routes/saas_sources.py app/routes/spreadsheet_connections.py \
  app/services/google_drive/client.py app/services/google_drive/oauth.py \
  app/services/google_drive/registration.py app/services/saas_source_service.py \
  app/tasks/google_drive_token_refresh.py app/tasks/quickbooks_token_refresh.py

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

0. **Host-level, not part of this merge:** confirm `APP_BASE_URL` is correct for this
   deployment (so the new `GOOGLE_DRIVE_REDIRECT_URI` default resolves to a real,
   reachable URL), or set `GOOGLE_DRIVE_REDIRECT_URI` explicitly if it doesn't. Confirm
   `GOOGLE_DRIVE_CLIENT_ID`/`_CLIENT_SECRET` are set in this environment's `.env`. Confirm
   the exact same redirect URI is registered under "Authorized redirect URIs" on that
   OAuth client in Google Cloud Console (APIs & Services → Credentials) — a mismatch here
   either makes Google reject the request outright or sends the browser back to a dead
   URL after consent. None of this is a git change; it's environment/secrets
   configuration that has to be done directly on the host regardless of when this branch
   merges.
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
   completing reauthorization **actually loads the preview** after clicking it — not just
   that the reauthorize popup completes. This is the exact live finding: reauthorizing
   alone did not fix an already-created source until `reregister_live_sources_for_credential`
   was wired into the callback, so re-clicking the same table after reconnecting is the
   real proof, not just a green "connected" state.
4. Repeat step 3 for an already-created ServiceNow/Salesforce/HubSpot/QuickBooks table
   after reconnecting its credential via PATCH (the "Reconnect" action from step 2): confirm
   clicking the table shows a "Reconnect <Connector>" button (not the raw
   `TEIID30504 ... HTTP 401 ... not authenticated` string) and that completing it loads the
   preview. This is the second live finding on this exact flow — the query-time reauth
   detection originally only recognized Google Sheets' Teiid naming, so clicking an
   already-created ServiceNow table kept showing the raw error even after "Create Data
   Source" correctly offered Reconnect for the same credential; confirm the two are now
   consistent.
5. Confirm an unrelated query failure (e.g. a malformed saved query) still shows a plain
   error, not a reauth prompt.

## Report back
