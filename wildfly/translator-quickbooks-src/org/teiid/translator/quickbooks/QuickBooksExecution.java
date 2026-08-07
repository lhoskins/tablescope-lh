package org.teiid.translator.quickbooks;

import java.util.ArrayList;
import java.util.Iterator;
import java.util.List;

import javax.json.JsonObject;
import javax.json.JsonValue;

import org.teiid.language.ColumnReference;
import org.teiid.language.DerivedColumn;
import org.teiid.language.Limit;
import org.teiid.language.NamedTable;
import org.teiid.language.Select;
import org.teiid.language.TableReference;
import org.teiid.language.visitor.AbstractLanguageVisitor;
import org.teiid.metadata.RuntimeMetadata;
import org.teiid.translator.DataNotAvailableException;
import org.teiid.translator.ExecutionContext;
import org.teiid.translator.ResultSetExecution;
import org.teiid.translator.TranslatorException;

/**
 * Executes a Teiid {@link Select} against the QuickBooks Online query API.
 *
 * Pushes down table, column projection, row limit and offset.  Unsupported
 * predicates are omitted; Teiid's engine filters the returned rows in memory.
 */
public class QuickBooksExecution implements ResultSetExecution {

    private final Select command;
    private final QuickBooksConnection connection;
    private final ExecutionContext context;
    private final RuntimeMetadata metadata;

    private List<List<Object>> results;
    private Iterator<List<Object>> iterator;
    private List<String> outputColumns;

    public QuickBooksExecution(Select command, QuickBooksConnection connection, ExecutionContext context, RuntimeMetadata metadata) {
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

        this.outputColumns = ctx.columns;
        if (this.outputColumns.isEmpty()) {
            try {
                org.teiid.metadata.Table tableMeta = metadata.getTable(ctx.schemaName, ctx.tableName);
                if (tableMeta != null) {
                    for (org.teiid.metadata.Column c : tableMeta.getColumns()) {
                        this.outputColumns.add(c.getName());
                    }
                }
            } catch (Exception e) {
                // Fallback: leave columns empty and the query will return no rows.
            }
        }
        String sourceTable = ctx.sourceTableName != null ? ctx.sourceTableName : ctx.tableName;
        List<String> srcNames = sourceColumnNames(ctx);
        String fields = String.join(",", srcNames);
        int limit = ctx.limit;
        int offset = ctx.offset;

        results = new ArrayList<>();
        for (JsonObject row : connection.query(sourceTable, "", fields, limit, offset)) {
            List<Object> record = new ArrayList<>(this.outputColumns.size());
            for (String col : srcNames) {
                record.add(getCell(row, col));
            }
            results.add(record);
        }
        iterator = results.iterator();
    }

    private List<String> sourceColumnNames(QueryContext ctx) throws TranslatorException {
        List<String> names = new ArrayList<>(this.outputColumns.size());
        for (String col : this.outputColumns) {
            String src = col;
            try {
                org.teiid.metadata.Column column = null;
                if (ctx.schemaName != null && ctx.tableName != null) {
                    column = metadata.getColumn(ctx.schemaName, ctx.tableName, col);
                }
                if (column == null && ctx.tableName != null) {
                    column = metadata.getColumn(ctx.tableName + "." + col);
                }
                if (column != null && column.getNameInSource() != null
                        && !column.getNameInSource().isEmpty()) {
                    src = column.getNameInSource();
                }
            } catch (TranslatorException e) {
                // fall back to the Teiid column name
            }
            if (src.startsWith("\"") && src.endsWith("\"")) {
                src = src.substring(1, src.length() - 1);
            }
            names.add(src);
        }
        return names;
    }

    private Object getCell(JsonObject row, String src) {
        if (row == null || src == null) {
            return null;
        }
        JsonValue current = row;
        String[] parts = src.split("\\.");
        for (int i = 0; i < parts.length; i++) {
            if (current == null || current == JsonValue.NULL) {
                return null;
            }
            if (current.getValueType() != JsonValue.ValueType.OBJECT) {
                return null;
            }
            JsonObject obj = (JsonObject) current;
            if (!obj.containsKey(parts[i])) {
                return null;
            }
            if (i == parts.length - 1) {
                return convertValue(obj.get(parts[i]));
            }
            current = obj.get(parts[i]);
        }
        return null;
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

    private Object convertValue(JsonValue v) {
        if (v == null || v == JsonValue.NULL) {
            return null;
        }
        switch (v.getValueType()) {
            case STRING:
                return ((javax.json.JsonString) v).getString();
            case NUMBER:
                return ((javax.json.JsonNumber) v).numberValue();
            case TRUE:
                return Boolean.TRUE;
            case FALSE:
                return Boolean.FALSE;
            default:
                return v.toString();
        }
    }

    private static class QueryContext extends AbstractLanguageVisitor {

        String schemaName;
        String tableName;
        String sourceTableName;
        final List<String> columns = new ArrayList<>();
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
        }

        @Override
        public void visit(Limit obj) {
            limit = obj.getRowLimit();
            offset = obj.getRowOffset();
        }
    }
}
