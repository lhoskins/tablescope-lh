# Devin-ready plan: migrate HubSpot and QuickBooks to live Teiid translators

## Context — what's confirmed as of this branch (`devin/r-echarts-e2e-validation` @ `88a0fb86`)

Salesforce was just migrated to a live Teiid translator (PR #125,
`87ac1082`) using Teiid's **built-in** `salesforce-41` resource adapter —
no custom Java was needed there because Teiid ships a Salesforce
translator out of the box. **HubSpot and QuickBooks have no Teiid
built-in translator**, so they need a **custom Java translator over
REST**, the same pattern used for ServiceNow (`3f319d42`,
`wildfly/translator-servicenow-src/`). This plan follows that template
closely — it is largely mechanical for HubSpot, with one real design
problem for QuickBooks (OAuth token expiry) called out below.

Current architecture, confirmed by reading the code:

| Connector | Pattern | Auth |
|---|---|---|
| Postgres/MySQL/SQL Server/Oracle | Native Teiid JDBC translator | DB credentials |
| ServiceNow | Custom Java Teiid translator, HTTP Basic per request | username/password (static, never expires) |
| Salesforce | Built-in `salesforce-41` Teiid translator via JCA connection factory | username/password/security token (static) |
| HubSpot | Sync-to-Postgres-staging (`app/connectors/saas/hubspot.py`) | Private App bearer token (**static, does not expire**) |
| QuickBooks | Sync-to-Postgres-staging (`app/connectors/saas/quickbooks.py`) | OAuth2 access token (**expires in ~1 hour**, requires refresh_token) |

The staging-table path being replaced funnels through
`saas_source_service.create_saas_source()`, which already branches on
`is_live_translator` (`servicenow` or `salesforce` today) to skip the
Postgres staging table and instead call a `register_*_source()` method on
`TeiidRegistrationService`. Adding `hubspot` and `quickbooks` to that
branch is the integration point for both.

## Why HubSpot is straightforward and QuickBooks is not

**HubSpot**'s Private App access token is long-lived (does not expire
until revoked), exactly like ServiceNow's static credentials — the
`ServiceNowConnection`/`ServiceNowExecution`/`ServiceNowExecutionFactory`
Java classes can be ported almost line-for-line.

**QuickBooks**'s OAuth2 access token expires in ~1 hour. A live Teiid
translator issuing HTTP calls per query, using a token captured once at
VDB-registration time, will start failing with 401s within an hour of
the source being created — this is a real functional gap, not a detail
to skip. Phase 2 below designs around it using the existing reconcile
mechanism rather than adding OAuth logic inside the Java translator.

## Phase 1 — HubSpot: custom Java Teiid translator (port of the ServiceNow pattern)

New source tree `wildfly/translator-hubspot-src/org/teiid/translator/hubspot/`,
mirroring `wildfly/translator-servicenow-src/.../servicenow/` file-for-file:

1. **`HubSpotConnection.java`** — port of `ServiceNowConnection.java`:
   - Base URL fixed to `https://api.hubapi.com` (no per-instance URL
     needed, unlike ServiceNow).
   - `Authorization: Bearer <token>` instead of HTTP Basic.
   - Endpoint: `GET /crm/v3/objects/{table}` with query params
     `properties` (comma-joined field list, matches `hubspot.py`'s
     `params["properties"]`), `archived=false`, `limit` (HubSpot caps at
     100/page, vs. ServiceNow's 200).
   - **Pagination difference to design around**: HubSpot uses an opaque
     cursor (`paging.next.after`), not `sysparm_offset`. There is no way
     to jump directly to an arbitrary offset the way ServiceNow's
     `sysparm_offset` allows. Two options — recommend the first:
     - (a) Set `supportsRowOffset() { return false; }` in the
       ExecutionFactory (Teiid then compensates any `OFFSET` in memory
       after reading from the start) — simplest, correct, matches actual
       HubSpot API capabilities honestly.
     - (b) Walk the cursor chain from the beginning to reach the
       requested offset — wasted round-trips for large offsets, not
       worth the complexity for a BI query pattern that's typically
       full-table scans.
   - Response shape differs: items are `{"id", "properties": {...},
     "createdAt", "updatedAt", "archived"}` — properties live one level
     deep, so `HubSpotExecution`'s row-building step should read from
     `item.getJsonObject("properties")` for anything that isn't
     `id`/`createdAt`/`updatedAt`/`archived`.
2. **`HubSpotExecution.java`** — port of `ServiceNowExecution.java`,
   adjusted for the nested `properties` object read above.
3. **`HubSpotExecutionFactory.java`** — port of
   `ServiceNowExecutionFactory.java`:
   - `@Translator(name = "hubspot", ...)`.
   - One `@TranslatorProperty` for `Access Token` (`masked = true`)
     instead of instance URL/username/password.
   - Same capability set as ServiceNow (`supportsGroupBy`,
     `supportsAggregates*`, joins, etc. all `false` — push nothing down
     except row limit, comparisons, IN, LIKE, IS NULL, OR/NOT), except
     `supportsRowOffset()` per the pagination note above.
4. **`org.teiid.translator.ExecutionFactory` services file** — add the
   HubSpot factory class alongside the ServiceNow one (same file
   ServiceNow's translator registers itself in;
   `wildfly/modules/.../servicenow/main/META-INF/services/...` —
   confirm the exact ServiceNow jar's internal path before mirroring).
5. Compile to `translator-hubspot-1.0.0.jar`, deploy as a WildFly module
   under `wildfly/modules/system/layers/{dv,base}/org/jboss/teiid/translator/hubspot/main/`
   (`module.xml` + jar), and register it in
   `wildfly/standalone/configuration/standalone-teiid.xml` and
   `standalone.xml` — copy the exact ServiceNow entries and rename.

## Phase 2 — QuickBooks: custom Java Teiid translator + token-refresh design

Java translator structure is the same three-file port as HubSpot
(`QuickBooksConnection`/`QuickBooksExecution`/`QuickBooksExecutionFactory`,
in a new `wildfly/translator-quickbooks-src/`), with these
QuickBooks-specific differences:

- Base URL depends on `environment` (`production` vs `sandbox`, exactly
  as `quickbooks.py`'s `_PRODUCTION_BASE`/`_SANDBOX_BASE`), plus a
  `realm_id` path segment: `GET /v3/company/{realm}/query?query=...`.
- Uses the SQL-like `query` API (`SELECT * FROM {Object} STARTPOSITION n
  MAXRESULTS m`) rather than a REST list endpoint — this actually
  supports true offset/limit natively, so no HubSpot-style
  `supportsRowOffset` compromise is needed here.
- Nested `MetaData.CreateTime` / `MetaData.LastUpdatedTime` fields (used
  for the `created_time`/`updated_time` base columns) need a
  dotted-path `name_in_source` convention (e.g. `"MetaData.CreateTime"`)
  that the Java execution splits on `.` to descend into the nested
  object — flag this explicitly in `QuickBooksExecution.java`, it's the
  one place the row-mapping isn't a flat top-level key lookup.

**Token refresh — the real design decision.** Do not embed OAuth
refresh logic in the Java translator; that would require the translator
to call back into platform-api to persist a rotated refresh token (Intuit
invalidates the previous refresh token on every use), which is a new
kind of dependency (Java → platform-api auth) this codebase doesn't have
anywhere else. Instead, reuse the existing reconcile mechanism that
already re-pushes credentials to Teiid:

1. Extend `ConnectorCredential`'s QuickBooks config to store `client_id`,
   `client_secret`, and `refresh_token` alongside the existing
   `access_token`/`realm_id`/`environment` (frontend changes in Phase 3).
2. Add a new arq periodic job (same worker infra used elsewhere in this
   codebase, e.g. `platform-api/app/workers/`) that runs every ~15
   minutes: for each QuickBooks `ConnectorCredential` nearing expiry
   (store `expires_at` alongside the token, computed from OAuth's
   `expires_in` at refresh time), POST to Intuit's token endpoint
   (`https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer`,
   `grant_type=refresh_token`, HTTP Basic `client_id:client_secret`),
   get back a new `access_token` + rotated `refresh_token`, and:
   - update the encrypted `ConnectorCredential` row, and
   - call `register_quickbooks_source(..., force=True)` again (mirrors
     what `reconcile_database_sources()` already does for other sources)
     so the Java translator's `Access Token` config property in the live
     VDB model gets updated to the fresh token.
3. This keeps all OAuth complexity in Python (where `httpx` + the
   existing encryption/session plumbing already live) and treats the
   Teiid-side credential the same way every other reconciled source's
   credential is already treated — no new Java-to-Python dependency.

15 minutes comfortably beats the 1-hour access-token lifetime even with
some job-runner jitter; tune down further only if testing shows access
tokens expiring faster than documented.

## Phase 3 — Backend wiring (Python)

`platform-api/app/services/saas_source_service.py`:
- Extend `is_live_translator` to `connector_type in ("servicenow",
  "salesforce", "hubspot", "quickbooks")`.
- Extend the `saas_username`/`saas_password`/`saas_instance_url`
  extraction block with `elif connector_type == "hubspot"` (just the
  token, no instance URL — pass `""`) and `elif connector_type ==
  "quickbooks"` (token + realm + environment + the new client_id/secret/
  refresh_token fields, all needed to seed the periodic refresh job).
- Extend `run_sync()`'s live-translator short-circuit list the same way
  Salesforce was added (`if saas.connector_type in ("servicenow",
  "salesforce", "hubspot", "quickbooks")`).

`platform-api/app/services/teiid_registration_service.py`:
- Add `register_hubspot_source()` and `register_quickbooks_source()`,
  each a close copy of `register_salesforce_source()`/
  `register_servicenow_source()` — same payload shape posted to
  `VDBManagementServlet`'s `createDatabaseSource`, with
  `"translator": "hubspot"` / `"translator": "quickbooks"`.
- Extend `reconcile_database_sources()`'s `elif` chain with
  `ds.db_type == "hubspot"` / `"quickbooks"` branches, matching the
  Salesforce branch added in `87ac1082`.

`platform-api/app/services/database_introspection_service.py`:
- Extend `source_identifier()` with HubSpot and QuickBooks base-column
  maps, following the `_SALESFORCE_BASE_COLUMN_MAP` pattern already
  there:
  ```python
  _HUBSPOT_BASE_COLUMN_MAP = {
      "hubspot_id": "id",
      "created_at": "createdAt",
      "updated_at": "updatedAt",
      # "archived" already matches; user-selected fields already use
      # their HubSpot property names and pass through unchanged.
  }
  _QUICKBOOKS_BASE_COLUMN_MAP = {
      "quickbooks_id": "Id",
      "sync_token": "SyncToken",
      "created_time": "MetaData.CreateTime",
      "updated_time": "MetaData.LastUpdatedTime",
      # user-selected top-level fields already use their QuickBooks key
      # names and pass through unchanged.
  }
  ```

`apache-maven-3.9.6/MyProject/project-TeiidExcelImporterTest/.../VDBManagementServlet.java`:
- No changes needed beyond what already exists for the generic
  "physical model with a custom translator name + no JDBC datasource"
  path (`isServiceNow`-style branch) — extend that branch's condition to
  also match `"hubspot"`/`"quickbooks"` translators (same
  `buildServiceNowModelBlock`-style DDL generation, parameterized by
  translator name — check whether it needs renaming to something
  translator-agnostic like `buildRestTranslatorModelBlock` now that a
  third consumer exists, to avoid ServiceNow-specific naming leaking
  into shared code).

## Phase 4 — Frontend (QuickBooks only; HubSpot needs no changes)

`web-ui/components/datasource/SaasSourceWizard.tsx`:
- HubSpot's form already only collects `access_token` — no changes
  needed; it already satisfies everything the new translator needs.
- QuickBooks' `qb` state (currently `{access_token, realm_id,
  environment}`) needs three new fields: `client_id`, `client_secret`,
  `refresh_token`, with corresponding form inputs (mirror how Salesforce's
  form added `client_id`/`client_secret` fields) and `credValid()`
  updated to require them.
- `ConnectorsMenu.tsx` needs no changes — HubSpot/QuickBooks are already
  listed there; only what happens after selection changes.

## Phase 5 — Migration/cutover decision (flagged, not assumed)

Existing HubSpot/QuickBooks sources created before this ships are on the
Postgres-staging path and will keep working as-is — this plan does
**not** force-migrate them (that would mean re-registering every
existing source in Teiid and discarding sync history, a separate,
riskier piece of work). Recommend: only **newly created** HubSpot/
QuickBooks sources use the live translator after this ships; existing
staged sources are left alone unless/until the user explicitly asks for
a migration pass. Confirm this default before implementation — if
instead you want existing sources force-migrated on deploy, that needs
its own plan (backfill script + Teiid re-registration + staging table
cleanup).

## Phase 6 — Verification before considering this done

1. Unit tests for the new `source_identifier()` map entries (HubSpot,
   QuickBooks), mirroring existing Salesforce/Oracle coverage.
2. Unit tests for `register_hubspot_source()`/`register_quickbooks_source()`
   payload shape, mirroring existing ServiceNow/Salesforce registration
   tests.
3. A live end-to-end test against a real (sandbox/trial) HubSpot Private
   App and a real QuickBooks sandbox company: create the source, confirm
   the live SELECT returns rows through Teiid (not just that the Java
   translator's HTTP call succeeds standalone) — same bar set in the
   Databricks/Snowflake connector plan (docs/devin-databricks-snowflake-connectors-validated-plan.md).
4. For QuickBooks specifically: a test that forces the access token past
   its expiry (or mocks `expires_at` in the past) and confirms the
   periodic refresh job actually refreshes it and the subsequent live
   query still succeeds — this is the one failure mode that has no
   equivalent in any existing connector, so it needs its own explicit
   test, not just reuse of existing reconcile tests.
5. Confirm HubSpot's and QuickBooks's current rate limits (both enforce
   per-second/per-10-second caps) are acceptable for BI-style full-table
   scans hitting the API on every query with no local cache — flag to
   the user if a query pattern (e.g. dashboard auto-refresh) risks
   tripping rate limits, since unlike the old staging path there is no
   longer a local copy to absorb repeated reads.

## Explicitly out of scope for this plan

- Migrating existing (pre-this-change) HubSpot/QuickBooks sources off
  staging — see Phase 5.
- Any change to the HubSpot/QuickBooks *object* or *field* coverage —
  this plan changes only how already-supported objects are queried
  (live vs. staged), not what's supported.
- QuickBooks OAuth *initial* authorization flow (obtaining the first
  access/refresh token pair) — out of scope; assumed to already exist or
  be handled the same way it is today (the wizard currently expects the
  user to paste a token they obtained elsewhere). If there's no existing
  OAuth "Connect to QuickBooks" browser flow, obtaining a `refresh_token`
  for Phase 2 to use will need one — confirm whether this already exists
  before starting, since it changes Phase 4's scope from "add three
  fields" to "add three fields or build an OAuth redirect flow."
