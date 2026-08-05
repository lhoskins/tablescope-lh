# Devin-ready plan: fix ServiceNow Teiid translator query failures on date/typed columns

## Reported symptom

Querying `alm_asset_SERVICENOW` (an asset table registered through the
ServiceNow custom Teiid translator) fails with all 97 columns selected. The
user isolated it experimentally: removing 12 columns from the `SELECT` list
makes the exact same query succeed. Every one of the 12 removed columns is a
genuine ServiceNow date/datetime field:

`sys_updated_on`, `depreciation_date`, `sn_itam_common_disposal_date`,
`install_date`, `last_attestation_date`, `sn_itam_common_last_audit_date`,
`cmn_lease_expiration_date`, `delivery_date`, `order_date`, `purchase_date`,
`retirement_date`, `warranty_expiration`.

## Root cause (verified against the actual translator source, not guessed)

Three files make up the ServiceNow live Teiid translator:
`wildfly/translator-servicenow-src/org/teiid/translator/servicenow/{ServiceNowConnection,ServiceNowExecution,ServiceNowExecutionFactory}.java`,
compiled to `translator-servicenow-1.0.0.jar` and deployed as a WildFly
module under both `wildfly/modules/system/layers/{base,dv}/org/jboss/teiid/translator/servicenow/main/`.

1. **`ServiceNowConnection.java`** queries ServiceNow's Table API with
   `sysparm_display_value=false` (confirmed at the URL-building call site).
   This is a well-known ServiceNow REST behavior: with display values off,
   **every field comes back as a JSON string**, including numbers, booleans,
   and dates — and an unset field comes back as an **empty string `""`**,
   never JSON `null`.

2. **Column types are correctly declared.** On the Python side,
   `app/connectors/saas/servicenow.py`'s `_TYPE_MAP` maps ServiceNow's
   `glide_date_time` → Postgres `timestamptz` and `glide_date` → `date`;
   `database_introspection_service.map_to_teiid_type()` then maps those to
   Teiid `timestamp`/`date`. So the VDB's physical model DDL for
   `alm_asset_SERVICENOW` correctly declares e.g. `install_date` as Teiid
   type `date`. This part is not the bug.

3. **The bug is in `ServiceNowExecution.java`'s `convertValue()`**
   (`wildfly/translator-servicenow-src/org/teiid/translator/servicenow/ServiceNowExecution.java`,
   current lines 115-131):
   ```java
   private Object convertValue(JsonValue v) {
       if (v == null || v == JsonValue.NULL) {
           return null;
       }
       switch (v.getValueType()) {
           case STRING:
               return ((javax.json.JsonString) v).getString();
           ...
       }
   }
   ```
   It has **no awareness of the target column's declared Teiid type** — a
   JSON string value is always handed back to Teiid as a plain Java
   `String`, regardless of whether the column is declared `date`,
   `timestamp`, `integer`, `double`, or `boolean`. Teiid then falls back to
   its own implicit `String → X` conversion for the declared type. That
   conversion throws for values that don't parse (most importantly, an
   **empty string handed to a date/timestamp conversion throws**, since
   there is no valid empty-string date). One bad value on one row aborts the
   *entire* result set — which exactly matches the observed behavior: with
   97 columns projected across every row of `alm_asset`, at least one asset
   has at least one of those 12 date fields unset; with them removed, no row
   can trigger the failure anymore.

   This is a **general type-conversion gap**, not date-specific — the exact
   same crash is latent for any blank numeric field (`cost`, `quantity`,
   `resale_price`, `cmn_monthly_lease_payment`, …) or any field whose Teiid
   type isn't `string`. It hasn't been hit yet only because no row in this
   result set happened to have a blank value in one of those columns. The
   fix below is written to close the gap generally, not just for dates.

## Fix

Modify **`wildfly/translator-servicenow-src/org/teiid/translator/servicenow/ServiceNowExecution.java`**
only. No changes needed to `ServiceNowConnection.java`, `ServiceNowExecutionFactory.java`,
or anything on the Python side — the column-type declarations are already
correct.

Approach: resolve each output column's **Teiid runtime type** from
`RuntimeMetadata` (the same lookup that already resolves `NAMEINSOURCE`, so
no new metadata calls are introduced — this replaces the previous
`sourceColumnNames()` helper, which was actually being called twice per
query, once for the `sysparm_fields` string and once again in the result
loop; the replacement calls it once), and convert each raw ServiceNow string
to the correct Java type for that column, using `java.time` (thread-safe,
unlike `SimpleDateFormat`). Blank or unparseable values map to `null`
instead of throwing, so one bad field on one row can never abort the query.

Full replacement file:

```java
package org.teiid.translator.servicenow;

import java.math.BigDecimal;
import java.sql.Date;
import java.sql.Time;
import java.sql.Timestamp;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.List;

import javax.json.JsonObject;
import javax.json.JsonValue;

import org.teiid.language.*;
import org.teiid.language.visitor.AbstractLanguageVisitor;
import org.teiid.metadata.RuntimeMetadata;
import org.teiid.translator.DataNotAvailableException;
import org.teiid.translator.ExecutionContext;
import org.teiid.translator.ResultSetExecution;
import org.teiid.translator.TranslatorException;

/**
 * Executes a Teiid {@link Select} against the ServiceNow Table API.
 *
 * Pushes down table, column projection, simple predicates and limit/offset.
 * Unsupported predicates are omitted; Teiid's engine filters the returned rows
 * in memory, so correctness is preserved even for expressions we cannot push.
 */
public class ServiceNowExecution implements ResultSetExecution {

    private static final DateTimeFormatter SN_DATETIME_FMT =
            DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");
    private static final DateTimeFormatter SN_DATE_FMT =
            DateTimeFormatter.ofPattern("yyyy-MM-dd");
    private static final DateTimeFormatter SN_TIME_FMT =
            DateTimeFormatter.ofPattern("HH:mm:ss");

    private final Select command;
    private final ServiceNowConnection connection;
    private final ExecutionContext context;
    private final RuntimeMetadata metadata;

    private List<List<Object>> results;
    private Iterator<List<Object>> iterator;
    private List<String> outputColumns;

    public ServiceNowExecution(Select command, ServiceNowConnection connection, ExecutionContext context, RuntimeMetadata metadata) {
        this.command = command;
        this.connection = connection;
        this.context = context;
        this.metadata = metadata;
    }

    @Override
    public void execute() throws TranslatorException {
        QueryContext ctx = new QueryContext();
        ctx.visitNode(command);
        if (command.getLimit() != null) {
            ctx.visitNode(command.getLimit());
        }

        this.outputColumns = ctx.columns.isEmpty() ? ctx.allColumns : ctx.columns;
        String sourceTable = ctx.sourceTableName != null ? ctx.sourceTableName : ctx.tableName;
        List<ColumnMapping> mappings = columnMappings(ctx);

        StringBuilder fieldList = new StringBuilder();
        for (int i = 0; i < mappings.size(); i++) {
            if (i > 0) {
                fieldList.append(",");
            }
            fieldList.append(mappings.get(i).sourceName);
        }
        String fields = fieldList.toString();
        String query = ctx.sysparmQuery;
        int limit = ctx.limit;
        int offset = ctx.offset;

        results = new ArrayList<>();
        for (JsonObject row : connection.query(sourceTable, query, fields, limit, offset)) {
            List<Object> record = new ArrayList<>(mappings.size());
            for (ColumnMapping mapping : mappings) {
                record.add(convertValue(row.get(mapping.sourceName), mapping.teiidType));
            }
            results.add(record);
        }
        iterator = results.iterator();
    }

    /**
     * Resolves each output column's ServiceNow field name (NAMEINSOURCE, when
     * declared) and its Teiid runtime type, so returned JSON values can be
     * coerced to match the type the VDB declared for that column instead of
     * relying on Teiid's implicit String conversion -- which throws (and
     * fails the whole query) on values like the empty-string ServiceNow
     * sends for any unset field, regardless of the field's real type.
     */
    private List<ColumnMapping> columnMappings(QueryContext ctx) {
        List<ColumnMapping> mappings = new ArrayList<>(this.outputColumns.size());
        for (String col : this.outputColumns) {
            String src = col;
            String teiidType = "string";
            try {
                org.teiid.metadata.Column column = null;
                if (ctx.schemaName != null && ctx.tableName != null) {
                    column = metadata.getColumn(ctx.schemaName, ctx.tableName, col);
                }
                if (column == null && ctx.tableName != null) {
                    column = metadata.getColumn(ctx.tableName + "." + col);
                }
                if (column != null) {
                    if (column.getNameInSource() != null && !column.getNameInSource().isEmpty()) {
                        src = column.getNameInSource();
                    }
                    if (column.getRuntimeType() != null && !column.getRuntimeType().isEmpty()) {
                        teiidType = column.getRuntimeType();
                    }
                }
            } catch (TranslatorException e) {
                // fall back to the Teiid column name / string type
            }
            // strip surrounding double quotes that some source DDLs embed
            if (src.startsWith("\"") && src.endsWith("\"")) {
                src = src.substring(1, src.length() - 1);
            }
            mappings.add(new ColumnMapping(src, teiidType));
        }
        return mappings;
    }

    @Override
    public List<?> next() throws TranslatorException, DataNotAvailableException {
        if (iterator != null && iterator.hasNext()) {
            return iterator.next();
        }
        return null;
    }

    @Override
    public void close() {
        // no-op
    }

    @Override
    public void cancel() throws TranslatorException {
        // no-op
    }

    /**
     * Converts a raw ServiceNow JSON value to the Java type Teiid expects for
     * the target column, based on the column's declared Teiid runtime type.
     *
     * ServiceNow's Table API (queried here with sysparm_display_value=false)
     * returns every field -- dates, numbers, booleans included -- as a JSON
     * string, and represents "no value" as an empty string rather than JSON
     * null. Handing that empty string to Teiid's implicit conversion for a
     * non-string column (e.g. String -> Timestamp) throws and fails the
     * entire result set. Converting explicitly here, with blank or
     * unparseable values mapped to null instead of propagating an exception,
     * means one unset field on one row can never take down the whole query.
     */
    private Object convertValue(JsonValue v, String teiidType) {
        String raw = rawStringValue(v);
        if (raw == null) {
            return null;
        }
        raw = raw.trim();
        if (raw.isEmpty()) {
            return null;
        }
        String type = teiidType == null ? "string" : teiidType.toLowerCase();
        try {
            switch (type) {
                case "timestamp":
                    return Timestamp.valueOf(parseDateTime(raw));
                case "date":
                    return Date.valueOf(parseDate(raw));
                case "time":
                    return Time.valueOf(LocalTime.parse(raw, SN_TIME_FMT));
                case "integer":
                    return (int) Double.parseDouble(raw);
                case "long":
                    return (long) Double.parseDouble(raw);
                case "short":
                    return (short) Double.parseDouble(raw);
                case "double":
                case "float":
                    return Double.parseDouble(raw);
                case "bigdecimal":
                    return new BigDecimal(raw);
                case "boolean":
                    return Boolean.valueOf("true".equalsIgnoreCase(raw) || "1".equals(raw));
                default:
                    return raw;
            }
        } catch (Exception e) {
            // ServiceNow sent a value that doesn't match the column's
            // declared type (e.g. a non-standard placeholder) -- surface it
            // as null rather than aborting the query.
            return null;
        }
    }

    private String rawStringValue(JsonValue v) {
        if (v == null || v == JsonValue.NULL) {
            return null;
        }
        switch (v.getValueType()) {
            case STRING:
                return ((javax.json.JsonString) v).getString();
            case NUMBER:
                return v.toString();
            case TRUE:
                return "true";
            case FALSE:
                return "false";
            default:
                return v.toString();
        }
    }

    private LocalDateTime parseDateTime(String raw) {
        if (raw.length() <= 10) {
            // a date-only value supplied for a timestamp column
            return LocalDate.parse(raw, SN_DATE_FMT).atStartOfDay();
        }
        return LocalDateTime.parse(raw, SN_DATETIME_FMT);
    }

    private LocalDate parseDate(String raw) {
        if (raw.length() > 10) {
            // a datetime value supplied for a date-only column
            return LocalDateTime.parse(raw, SN_DATETIME_FMT).toLocalDate();
        }
        return LocalDate.parse(raw, SN_DATE_FMT);
    }

    private static class ColumnMapping {
        final String sourceName;
        final String teiidType;

        ColumnMapping(String sourceName, String teiidType) {
            this.sourceName = sourceName;
            this.teiidType = teiidType;
        }
    }

    /**
     * Extracts table, columns, predicates and limit/offset from the Teiid AST.
     */
    private static class QueryContext extends AbstractLanguageVisitor {

        String schemaName;
        String tableName;
        String sourceTableName;
        final List<String> columns = new ArrayList<>();
        final List<String> allColumns = new ArrayList<>();
        String sysparmQuery = "";
        int limit = 0;
        int offset = 0;

        @Override
        public void visit(Select obj) {
            if (obj.getFrom() != null && !obj.getFrom().isEmpty()) {
                TableReference tr = obj.getFrom().get(0);
                if (tr instanceof NamedTable) {
                    NamedTable nt = (NamedTable) tr;
                    String fullName = nt.getName();
                    if (fullName != null && fullName.contains(".")) {
                        int dot = fullName.lastIndexOf('.');
                        schemaName = fullName.substring(0, dot);
                        tableName = fullName.substring(dot + 1);
                    } else {
                        tableName = fullName;
                    }
                    org.teiid.metadata.Table meta = nt.getMetadataObject();
                    if (meta != null) {
                        String nis = meta.getNameInSource();
                        if (nis != null && !nis.isEmpty()) {
                            sourceTableName = nis;
                        }
                    }
                }
            }

            for (DerivedColumn dc : obj.getDerivedColumns()) {
                if (dc.getExpression() instanceof ColumnReference) {
                    ColumnReference cr = (ColumnReference) dc.getExpression();
                    columns.add(cr.getName());
                }
            }

            if (obj.getWhere() != null) {
                sysparmQuery = buildQuery(obj.getWhere());
            }
        }

        @Override
        public void visit(Limit obj) {
            limit = obj.getRowLimit();
            offset = obj.getRowOffset();
        }

        @Override
        public void visit(ColumnReference obj) {
            String name = obj.getName();
            if (!allColumns.contains(name)) {
                allColumns.add(name);
            }
        }

        private String buildQuery(Condition c) {
            if (c instanceof Comparison) {
                return buildComparison((Comparison) c);
            }
            if (c instanceof AndOr) {
                AndOr ao = (AndOr) c;
                String sep = ao.getOperator() == AndOr.Operator.AND ? "^" : "^OR^";
                String left = buildQuery(ao.getLeftCondition());
                String right = buildQuery(ao.getRightCondition());
                if (left.isEmpty()) return right;
                if (right.isEmpty()) return left;
                return left + sep + right;
            }
            if (c instanceof Like) {
                Like l = (Like) c;
                if (!l.isNegated()) {
                    String left = exprToString(l.getLeftExpression());
                    String right = exprToString(l.getRightExpression());
                    if (!left.isEmpty() && !right.isEmpty()) {
                        return left + "LIKE" + right;
                    }
                }
            }
            if (c instanceof In) {
                In in = (In) c;
                if (!in.isNegated()) {
                    String left = exprToString(in.getLeftExpression());
                    if (!left.isEmpty()) {
                        StringBuilder sb = new StringBuilder(left).append("IN");
                        boolean first = true;
                        for (Expression e : in.getRightExpressions()) {
                            if (!first) sb.append(",");
                            first = false;
                            sb.append(exprToString(e));
                        }
                        return sb.toString();
                    }
                }
            }
            if (c instanceof IsNull) {
                IsNull in = (IsNull) c;
                String expr = exprToString(in.getExpression());
                if (!expr.isEmpty()) {
                    return expr + (in.isNegated() ? "ISNOTEMPTY" : "ISEMPTY");
                }
            }
            return "";
        }

        private String buildComparison(Comparison comp) {
            String left = exprToString(comp.getLeftExpression());
            String right = exprToString(comp.getRightExpression());
            if (left.isEmpty() || right.isEmpty() || right.equals("NULL")) {
                return "";
            }
            String op;
            switch (comp.getOperator()) {
                case EQ: op = "="; break;
                case NE: op = "!="; break;
                case GT: op = ">"; break;
                case GE: op = ">="; break;
                case LT: op = "<"; break;
                case LE: op = "<="; break;
                default: op = "=";
            }
            return left + op + right;
        }

        private String exprToString(Expression e) {
            if (e instanceof ColumnReference) {
                return ((ColumnReference) e).getName();
            }
            if (e instanceof Literal) {
                Object v = ((Literal) e).getValue();
                return v == null ? "NULL" : v.toString();
            }
            return "";
        }
    }
}
```

(Everything from `QueryContext` onward is unchanged from the current file —
included in full above purely so this is a drop-in replacement, not a diff
to hand-apply.)

## Build and deploy

There's no `pom.xml`/build script committed for this translator (it's
source-only under `wildfly/translator-servicenow-src/`); the deployed jars
were compiled out of band. Rebuild the same way:

1. Compile the three source files
   (`ServiceNowConnection.java`, `ServiceNowExecution.java`,
   `ServiceNowExecutionFactory.java`) against a classpath containing the
   Teiid translator API and JSON-P classes the WildFly module already
   declares as dependencies (see
   `wildfly/modules/system/layers/base/org/jboss/teiid/translator/servicenow/main/module.xml`):
   `org.jboss.teiid.api`, `org.jboss.teiid.common-core`, `javax.json.api`,
   `javax.resource.api`, `javax.api` — these WildFly module jars are
   available on disk under `wildfly/modules/system/layers/**` and can be
   pointed to directly on `javac -cp`.
2. Jar the compiled classes with the same layout the existing jar has
   (verified via `unzip -l`): `META-INF/MANIFEST.MF`,
   `META-INF/services/org.teiid.translator.ExecutionFactory` (single line:
   `org.teiid.translator.servicenow.ServiceNowExecutionFactory`), and the
   compiled `.class` files under `org/teiid/translator/servicenow/`.
3. Replace `translator-servicenow-1.0.0.jar` in **both**
   `wildfly/modules/system/layers/base/org/jboss/teiid/translator/servicenow/main/`
   and
   `wildfly/modules/system/layers/dv/org/jboss/teiid/translator/servicenow/main/`
   (both layers ship the identical jar today — keep them identical).
4. Restart/redeploy the WildFly/Teiid instance so the module reloads with
   the new jar. `module.xml` itself is unchanged — no WildFly configuration
   changes needed, only the jar contents.

## Test plan

1. **Live verification (primary — this bug only reproduces against real
   ServiceNow data)**: re-run the exact failing query from the report —
   `SELECT` all 97 columns from `alm_asset_SERVICENOW` — and confirm it
   returns rows instead of failing. Confirm the previously-removed date
   columns (`sys_updated_on`, `depreciation_date`,
   `sn_itam_common_disposal_date`, `install_date`, `last_attestation_date`,
   `sn_itam_common_last_audit_date`, `cmn_lease_expiration_date`,
   `delivery_date`, `order_date`, `purchase_date`, `retirement_date`,
   `warranty_expiration`) come back with real date values where set and
   `NULL` where the underlying ServiceNow record has them unset (rather than
   an error).
2. Spot-check a numeric column that's commonly blank on some assets (e.g.
   `resale_price`, `salvage_value`, `cmn_monthly_lease_payment`) — confirm
   blank values come back as `NULL` rather than erroring, since this fix
   closes the same gap for every non-string type, not only dates.
3. Confirm an unrelated, already-working query against a different
   ServiceNow table (or a narrower column set) still returns identical data
   to before the change — this is a behavior-preserving fix for populated
   values, not a reformatting of them.
4. If any Java unit tests exist for this translator, add one for
   `convertValue`/`parseDateTime`/`parseDate` covering: a normal datetime
   string (`"2024-01-01 08:30:00"`), a date-only string against a
   `timestamp`-typed column (defensive fallback), an empty string against
   `date`/`timestamp`/`integer`/`boolean` types (all must return `null`, not
   throw), and a malformed string against a typed column (must return `null`,
   not throw). If no test harness exists for this translator source yet,
   note that as a gap rather than skip verification — the live query test in
   step 1 is the load-bearing check here.

## Out of scope

- No changes to `ServiceNowConnection.java` (paging/query-building logic is
  correct) or `ServiceNowExecutionFactory.java` (capability declarations are
  unaffected).
- No changes to the Python-side type mapping
  (`app/connectors/saas/servicenow.py`, `database_introspection_service.py`)
  — those already declare the correct Teiid column types; the gap was purely
  in how the Java execution honored them.
- This does not address ServiceNow API rate limits, pagination correctness,
  or any other translator behavior — scoped strictly to the type-conversion
  crash.
