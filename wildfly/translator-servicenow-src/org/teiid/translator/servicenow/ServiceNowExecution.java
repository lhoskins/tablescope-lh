package org.teiid.translator.servicenow;

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
        String fields = String.join(",", this.outputColumns);
        String query = ctx.sysparmQuery;
        int limit = ctx.limit;
        int offset = ctx.offset;

        results = new ArrayList<>();
        for (JsonObject row : connection.query(ctx.tableName, query, fields, limit, offset)) {
            List<Object> record = new ArrayList<>(this.outputColumns.size());
            for (String col : this.outputColumns) {
                record.add(convertValue(row.get(col)));
            }
            results.add(record);
        }
        iterator = results.iterator();
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

    /**
     * Extracts table, columns, predicates and limit/offset from the Teiid AST.
     */
    private static class QueryContext extends AbstractLanguageVisitor {

        String tableName;
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
                    tableName = ((NamedTable) tr).getName();
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
