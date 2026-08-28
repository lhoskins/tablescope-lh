package org.teiid.translator.googlesheets;

import java.sql.Date;
import java.sql.Time;
import java.sql.Timestamp;
import java.time.Instant;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.List;
import javax.json.JsonArray;
import javax.json.JsonNumber;
import javax.json.JsonString;
import javax.json.JsonValue;
import org.teiid.language.ColumnReference;
import org.teiid.language.DerivedColumn;
import org.teiid.language.Limit;
import org.teiid.language.NamedTable;
import org.teiid.language.QueryExpression;
import org.teiid.language.Select;
import org.teiid.language.TableReference;
import org.teiid.metadata.Column;
import org.teiid.metadata.RuntimeMetadata;
import org.teiid.metadata.Table;
import org.teiid.translator.DataNotAvailableException;
import org.teiid.translator.ExecutionContext;
import org.teiid.translator.ResultSetExecution;
import org.teiid.translator.TranslatorException;

public class GoogleSheetsExecution implements ResultSetExecution {

    private final Select command;
    private final ExecutionContext executionContext;
    private final RuntimeMetadata metadata;
    private final GoogleSheetsConnection connection;
    private final String spreadsheetId;
    private final long baseMillis;

    private List<Column> outputColumns;
    private List<List<Object>> rows;
    private Iterator<List<Object>> rowIterator;

    public GoogleSheetsExecution(QueryExpression command, ExecutionContext executionContext,
            RuntimeMetadata metadata, GoogleSheetsConnection connection, String spreadsheetId) throws TranslatorException {
        if (!(command instanceof Select)) {
            throw new TranslatorException("Only SELECT is supported");
        }
        this.command = (Select) command;
        this.executionContext = executionContext;
        this.metadata = metadata;
        this.connection = connection;
        this.spreadsheetId = spreadsheetId;
        this.baseMillis = LocalDate.of(1899, 12, 30).atStartOfDay(ZoneOffset.UTC).toInstant().toEpochMilli();
    }

    @Override
    public void execute() throws TranslatorException {
        TableReference fromRef = command.getFrom().get(0);
        if (!(fromRef instanceof NamedTable)) {
            throw new TranslatorException("Only simple table references are supported");
        }
        NamedTable tableRef = (NamedTable) fromRef;
        Table table = tableRef.getMetadataObject();
        if (table == null) {
            throw new TranslatorException("No metadata for table " + tableRef.getName());
        }
        String range = table.getNameInSource();
        if (range == null || range.isEmpty()) {
            range = table.getSourceName();
        }
        if (range == null || range.isEmpty()) {
            range = tableRef.getName();
        }

        List<Column> tableColumns = new ArrayList<>(table.getColumns());
        outputColumns = new ArrayList<>();
        for (DerivedColumn dc : command.getDerivedColumns()) {
            if (dc.getExpression() instanceof ColumnReference) {
                ColumnReference cr = (ColumnReference) dc.getExpression();
                if ("*".equals(cr.getName())) {
                    outputColumns.addAll(tableColumns);
                } else {
                    Column col = cr.getMetadataObject();
                    if (col == null) {
                        col = findByName(tableColumns, cr.getName());
                    }
                    if (col == null) {
                        throw new TranslatorException("Column not found: " + cr.getName());
                    }
                    outputColumns.add(col);
                }
            } else {
                throw new TranslatorException("Only column references are supported");
            }
        }

        JsonArray values = connection.fetchValues(spreadsheetId, range);
        rows = new ArrayList<>();
        if (values != null && !values.isEmpty()) {
            for (int r = 1; r < values.size(); r++) {
                JsonValue rowValue = values.get(r);
                JsonArray row = (rowValue instanceof JsonArray) ? (JsonArray) rowValue : null;
                List<Object> record = new ArrayList<>(outputColumns.size());
                for (Column col : outputColumns) {
                    String src = col.getNameInSource();
                    if (src == null || src.isEmpty()) {
                        src = col.getSourceName();
                    }
                    if (src == null || src.isEmpty()) {
                        src = col.getName();
                    }
                    int idx = resolveIndex(src, tableColumns);
                    JsonValue cell = (row != null && idx >= 0 && idx < row.size()) ? row.get(idx) : null;
                    record.add(convert(cell, col));
                }
                rows.add(record);
            }
        }

        Limit limit = command.getLimit();
        if (limit != null) {
            int offset = limit.getRowOffset();
            int max = limit.getRowLimit();
            if (max <= 0) {
                max = Integer.MAX_VALUE;
            }
            int end = Math.min(offset + max, rows.size());
            if (offset > rows.size()) {
                end = 0;
            }
            if (offset > 0 || end < rows.size()) {
                rows = rows.subList(Math.max(0, offset), Math.max(0, end));
            }
        }

        rowIterator = rows.iterator();
    }

    private Column findByName(List<Column> columns, String name) {
        for (Column c : columns) {
            if (c.getName().equalsIgnoreCase(name)) {
                return c;
            }
        }
        return null;
    }

    private int resolveIndex(String src, List<Column> tableColumns) {
        if (src == null || src.isEmpty()) {
            return -1;
        }
        String trimmed = src.trim();
        if (trimmed.matches("^[A-Za-z]+$")) {
            return columnLetterToIndex(trimmed);
        }
        for (int i = 0; i < tableColumns.size(); i++) {
            Column c = tableColumns.get(i);
            String nis = c.getNameInSource();
            if (nis == null || nis.isEmpty()) {
                nis = c.getSourceName();
            }
            if (nis == null || nis.isEmpty()) {
                nis = c.getName();
            }
            if (trimmed.equalsIgnoreCase(nis)) {
                return i;
            }
        }
        try {
            return Integer.parseInt(trimmed);
        } catch (NumberFormatException e) {
            return -1;
        }
    }

    private int columnLetterToIndex(String letters) {
        int result = 0;
        for (char c : letters.toUpperCase().toCharArray()) {
            result = result * 26 + (c - 'A' + 1);
        }
        return result - 1;
    }

    private Object convert(JsonValue value, Column column) throws TranslatorException {
        if (value == null || value.getValueType() == JsonValue.ValueType.NULL) {
            return null;
        }
        String runtimeType = column.getDatatype().getRuntimeTypeName();
        if (runtimeType == null || runtimeType.isEmpty()) {
            runtimeType = "string";
        }
        runtimeType = runtimeType.toLowerCase();

        if (value.getValueType() == JsonValue.ValueType.NUMBER) {
            JsonNumber n = (JsonNumber) value;
            if ("integer".equals(runtimeType) || "int".equals(runtimeType)) {
                return n.longValue();
            }
            if ("long".equals(runtimeType)) {
                return n.longValue();
            }
            if ("double".equals(runtimeType) || "float".equals(runtimeType) || "bigdecimal".equals(runtimeType)) {
                return n.doubleValue();
            }
            if ("boolean".equals(runtimeType)) {
                return n.doubleValue() != 0.0;
            }
            if ("date".equals(runtimeType)) {
                return serialToDate(n.doubleValue());
            }
            if ("time".equals(runtimeType)) {
                return serialToTime(n.doubleValue());
            }
            if ("timestamp".equals(runtimeType) || "datetime".equals(runtimeType)) {
                return serialToTimestamp(n.doubleValue());
            }
        }

        if (value.getValueType() == JsonValue.ValueType.TRUE) {
            return Boolean.TRUE;
        }
        if (value.getValueType() == JsonValue.ValueType.FALSE) {
            return Boolean.FALSE;
        }

        String s = asString(value);
        if ("integer".equals(runtimeType) || "int".equals(runtimeType)) {
            try {
                return Long.parseLong(s);
            } catch (NumberFormatException e) {
                return null;
            }
        }
        if ("long".equals(runtimeType)) {
            try {
                return Long.parseLong(s);
            } catch (NumberFormatException e) {
                return null;
            }
        }
        if ("double".equals(runtimeType) || "float".equals(runtimeType) || "bigdecimal".equals(runtimeType)) {
            try {
                return Double.parseDouble(s);
            } catch (NumberFormatException e) {
                return null;
            }
        }
        if ("boolean".equals(runtimeType)) {
            return Boolean.parseBoolean(s);
        }
        if ("date".equals(runtimeType)) {
            try {
                return serialToDate(Double.parseDouble(s));
            } catch (NumberFormatException e) {
                return null;
            }
        }
        if ("time".equals(runtimeType)) {
            try {
                return serialToTime(Double.parseDouble(s));
            } catch (NumberFormatException e) {
                return null;
            }
        }
        if ("timestamp".equals(runtimeType) || "datetime".equals(runtimeType)) {
            try {
                return serialToTimestamp(Double.parseDouble(s));
            } catch (NumberFormatException e) {
                return null;
            }
        }
        return s;
    }

    private String asString(JsonValue v) {
        if (v.getValueType() == JsonValue.ValueType.STRING) {
            return ((JsonString) v).getString();
        }
        return v.toString();
    }

    private java.sql.Date serialToDate(double serial) {
        long whole = (long) serial;
        long millis = baseMillis + whole * 86400000L;
        return java.sql.Date.valueOf(LocalDateTime.ofInstant(Instant.ofEpochMilli(millis), ZoneOffset.UTC).toLocalDate());
    }

    private java.sql.Time serialToTime(double serial) {
        double frac = serial - Math.floor(serial);
        long millis = (long) (frac * 86400000L);
        return java.sql.Time.valueOf(LocalDateTime.ofInstant(Instant.ofEpochMilli(millis), ZoneOffset.UTC).toLocalTime());
    }

    private java.sql.Timestamp serialToTimestamp(double serial) {
        long whole = (long) serial;
        double frac = serial - whole;
        long millis = baseMillis + whole * 86400000L + (long) (frac * 86400000L);
        return java.sql.Timestamp.valueOf(LocalDateTime.ofInstant(Instant.ofEpochMilli(millis), ZoneOffset.UTC));
    }

    @Override
    public List<?> next() throws TranslatorException, DataNotAvailableException {
        if (rowIterator != null && rowIterator.hasNext()) {
            return rowIterator.next();
        }
        return null;
    }

    @Override
    public void close() {
    }

    @Override
    public void cancel() throws TranslatorException {
    }
}
