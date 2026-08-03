# Devin-ready plan: add Databricks and Snowflake as native Teiid-federated database connectors

## Context — connector architecture audit (verified against `devin/r-echarts-e2e-validation`)

Three distinct connector architectures exist in this codebase today:

1. **Native Teiid JDBC translator** (PostgreSQL, MySQL, SQL Server, Oracle) —
   `platform-api/app/services/database_introspection_service.py`'s `DB_TYPES`
   maps each engine to a real Teiid translator name (`"postgresql"`,
   `"mysql5"`, `"sqlserver"`, `"oracle"`) and a JDBC URL template. Teiid
   itself opens the live connection to the source database via its own
   JDBC driver (bundled as a WildFly module under
   `wildfly/modules/system/layers/base/**`); platform-api only introspects
   (via a matching SQLAlchemy dialect) for schema discovery and registers
   the source. Query traffic never passes through platform-api.

2. **Custom Teiid translator over REST** (ServiceNow, new) — 629 lines of
   Java (`wildfly/translator-servicenow-src/org/teiid/translator/servicenow/`),
   compiled to `translator-servicenow-1.0.0.jar` and deployed as a WildFly
   module. Registered via `register_servicenow_source()` in
   `teiid_registration_service.py`. Teiid opens live HTTP connections to
   ServiceNow's REST API directly — no staging table, no Python sync step.
   This was necessary because ServiceNow has no JDBC endpoint.

3. **Sync-to-staging-table** (HubSpot, Salesforce, QuickBooks) — per
   `app/connectors/base.py`'s own docstring: a Python connector class
   fetches records from the SaaS REST API and writes them into a Postgres
   staging table, which is then registered in Teiid "through the existing
   database-table pipeline" (i.e., as an ordinary Postgres source). **Teiid
   never talks to HubSpot/Salesforce/QuickBooks directly** — only to
   platform-api's own materialized copy, refreshed on sync.

**Databricks and Snowflake both have mature, officially-supported JDBC
drivers**, so they belong in category 1 (native Teiid JDBC translator, the
same pattern as Postgres/MySQL/SQL Server/Oracle) — not a custom Java
translator like ServiceNow, which was only necessary because ServiceNow has
no JDBC path. This plan follows category 1 exclusively.

**Not in scope for this plan** (flagged for a separate decision, not
assumed either way): migrating HubSpot/Salesforce/QuickBooks off the
sync-to-staging pattern onto live Teiid translators. Worth noting for that
future decision: Teiid already **ships a built-in `salesforce` translator**
(`wildfly/modules/.../org/jboss/teiid/translator/salesforce/`, already
deployed, `translator-salesforce-16.0.0.jar`) — migrating Salesforce
specifically could reuse this out-of-the-box translator rather than
requiring new custom Java, unlike HubSpot/QuickBooks which have no Teiid
built-in and would need a ServiceNow-style custom translator each. This is
worth a dedicated, separate plan once you decide whether to pursue it.

## Translator choice for each new engine

- **Snowflake**: no Snowflake-specific translator is bundled in this
  WildFly install (checked `wildfly/modules/system/layers/*/org/jboss/teiid/translator/`
  — only generic `jdbc` is present alongside the vendor-specific ones
  already in use). Use Teiid's generic `"jdbc"` translator
  (`translator-jdbc-16.0.0.jar`, already deployed) — this is Teiid's
  standard, supported fallback for any JDBC-compliant source without a
  dedicated translator, and is a well-trodden path for Snowflake
  specifically (ANSI-SQL-compatible dialect).
- **Databricks**: also no dedicated translator bundled. Databricks SQL
  Warehouses are Spark-SQL-based; Teiid ships a `hive` translator
  (`wildfly/modules/.../org/jboss/teiid/translator/hive/`) which shares
  enough SQL-dialect heritage to be the right starting point. Fall back to
  generic `"jdbc"` if the `hive` translator's capability assumptions cause
  query-generation issues in testing (Phase 3 below is explicitly there to
  catch this before it ships).

## Phase 1 — Backend: register the two engines

`platform-api/app/services/database_introspection_service.py`:

1. Add two `DbTypeConfig` entries to `DB_TYPES`:
   ```python
   "snowflake": DbTypeConfig(
       db_type="snowflake",
       default_port=443,
       sa_dialect="snowflake",  # via the snowflake-sqlalchemy package
       teiid_translator="jdbc",
       jdbc_template="jdbc:snowflake://{host}:{port}/?db={database}",
       system_schemas=frozenset({"INFORMATION_SCHEMA"}),
   ),
   "databricks": DbTypeConfig(
       db_type="databricks",
       default_port=443,
       sa_dialect="databricks",  # via the databricks-sqlalchemy package
       teiid_translator="hive",
       jdbc_template="jdbc:databricks://{host}:{port}/default;transportMode=http;ssl=1;httpPath={database}",
       system_schemas=frozenset({"information_schema"}),
   ),
   ```
   Verify the exact JDBC URL forms against each vendor's current driver
   docs before finalizing — Snowflake's URL needs an account identifier
   (may require a new `ConnectionParams` field, e.g. `account`, rather than
   reusing `host`/`port` as-is — check whether `host` can just carry
   `<account>.snowflakecomputing.com` cleanly or needs its own field).
   Databricks' `httpPath` (the SQL Warehouse's HTTP path) doesn't map
   naturally onto the existing `database_name` field either — decide
   whether to reuse it (simplest, matches existing `{database}` template
   slot) or add a dedicated field; reusing keeps the schema/API surface
   unchanged, which is preferable unless it's confusing in the UI.
2. Add Python dependencies to `platform-api/requirements.txt`:
   `snowflake-sqlalchemy` (wraps `snowflake-connector-python`) and
   `databricks-sqlalchemy` (wraps `databricks-sql-connector`) — both are
   official, actively-maintained packages with SQLAlchemy dialects, so
   `_build_engine()`'s existing SQLAlchemy-based introspection path in the
   same file should work with minimal changes: extend the `if/elif` chain
   there (currently branching on `postgresql`/`mysql`/`sqlserver`/`oracle`
   for connect-arg quirks) with entries for the two new types, using each
   driver's actual auth model (Snowflake commonly uses account+user+password
   or key-pair auth; Databricks uses a personal access token rather than a
   traditional password — confirm which auth fields the existing
   `ConnectionParams`/`DatabaseConnection` model can carry as-is vs. needs
   extending).
3. Bundle the JDBC driver jars as new WildFly modules, following the exact
   existing pattern (see `wildfly/modules/system/layers/base/com/microsoft/sqlserver/main/mssql-jdbc-12.8.1.jre11.jar`
   for the shape to replicate): download the official Snowflake JDBC driver
   (`snowflake-jdbc-<version>.jar`) and Databricks JDBC driver
   (`DatabricksJDBC42-<version>.jar`), each into its own `module.xml` +
   jar directory under `wildfly/modules/system/layers/base/...`, registered
   so Teiid's `jdbc`/`hive` translator resource-adapters can load them.
4. No changes needed to `teiid_registration_service.py`'s
   `register_database_source()` — it's already generic over `cfg.teiid_translator`
   and `build_jdbc_url()`; adding the two new `DB_TYPES` entries is
   sufficient for it to register Snowflake/Databricks sources the same way
   it does Postgres/Oracle today.

## Phase 2 — Frontend

`web-ui/components/datasource/DatabaseTableWizard.tsx`:
```ts
export const DB_TYPES: DbType[] = [
  { value: "postgresql", label: "PostgreSQL", defaultPort: 5432, enabled: true },
  { value: "mysql", label: "MySQL", defaultPort: 3306, enabled: true },
  { value: "sqlserver", label: "SQL Server", defaultPort: 1433, enabled: true },
  { value: "oracle", label: "Oracle", defaultPort: 1521, enabled: true },
  { value: "snowflake", label: "Snowflake", defaultPort: 443, enabled: true },
  { value: "databricks", label: "Databricks", defaultPort: 443, enabled: true },
];
```
If Phase 1 ends up adding a Snowflake-account or Databricks-http-path field
to the connection form (per the note above), extend the wizard's
connection-details step accordingly — check whether the existing form is
generic enough (labeled fields keyed by `db_type`) to add a per-type extra
field without a structural rework, or whether it assumes exactly
host/port/database/username/password for every type.

## Phase 3 — Verification before considering this done

1. Unit tests for `get_db_type_config("snowflake")` /
   `get_db_type_config("databricks")` and `build_jdbc_url()` with each new
   type, mirroring existing coverage for the other four engines.
2. A live connection test against a real (test/trial-tier) Snowflake
   warehouse and Databricks SQL warehouse — introspection (schema/table
   listing) via the SQLAlchemy dialect, then registration + an actual
   federated `SELECT` through Teiid, not just through the introspection
   path. This is the step most likely to surface JDBC-URL or translator
   dialect issues (e.g., the `hive` translator not correctly generating
   Databricks-flavored SQL for some function/aggregate) — do not consider
   this plan complete until a real end-to-end query has been run through
   Teiid against both, not just "the driver connects."
3. Confirm both drivers' licenses permit bundling/redistribution in this
   deployment the way the existing `mssql-jdbc` driver is bundled (check
   the Snowflake and Databricks JDBC driver license terms specifically —
   some vendor JDBC drivers restrict redistribution more than others).

## Explicitly out of scope for this plan

- Migrating HubSpot, Salesforce, or QuickBooks off the sync-to-staging
  pattern. Flagged above with the Teiid-built-in-`salesforce`-translator
  finding for when that decision gets made, but not started here.
- A custom Java Teiid translator for either Databricks or Snowflake — not
  needed given both have real JDBC drivers; only pursue this path later if
  Phase 3's live testing reveals the generic `jdbc`/`hive` translators are
  insufficient for query patterns you actually need.
