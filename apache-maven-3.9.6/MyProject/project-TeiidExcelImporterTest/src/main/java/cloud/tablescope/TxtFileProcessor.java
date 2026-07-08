package cloud.tablescope;

import java.io.*;
import java.util.*;
import java.util.regex.*;
import java.util.stream.Collectors;

public class TxtFileProcessor {

    // Store mapping of original column names to transformed names
    private Map<String, String> columnNameMapping = new HashMap<>();
    
    // SQL Reserved Keywords (comprehensive list)
    private static final Set<String> RESERVED_KEYWORDS = new HashSet<>(Arrays.asList(
        "DATE", "TIME", "TIMESTAMP", "YEAR", "MONTH", "DAY", "HOUR", "MINUTE", "SECOND",
        "SELECT", "FROM", "WHERE", "ORDER", "GROUP", "BY", "HAVING", "LIMIT", "OFFSET",
        "INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "ALTER", "TABLE", "VIEW", "INDEX",
        "JOIN", "INNER", "LEFT", "RIGHT", "OUTER", "CROSS", "ON", "USING",
        "AND", "OR", "NOT", "IN", "EXISTS", "BETWEEN", "LIKE", "IS", "NULL",
        "AS", "DISTINCT", "ALL", "ANY", "SOME", "UNION", "INTERSECT", "EXCEPT",
        "CASE", "WHEN", "THEN", "ELSE", "END",
        "USER", "ROLE", "GRANT", "REVOKE", "COMMIT", "ROLLBACK",
        "PRIMARY", "FOREIGN", "KEY", "REFERENCES", "CONSTRAINT", "UNIQUE",
        "DEFAULT", "CHECK", "CASCADE", "RESTRICT"
    ));
    
    /**
     * Check if a column name needs quoting due to:
     * 1. Being a reserved keyword
     * 2. Containing special characters (spaces, slashes, etc.)
     * 3. Starting with a number
     */
    private boolean needsQuoting(String columnName) {
        if (columnName == null || columnName.isEmpty()) {
            return false;
        }
        
        // Check if it's a reserved keyword
        if (RESERVED_KEYWORDS.contains(columnName.toUpperCase())) {
            return true;
        }
        
        // Check if it contains special characters or spaces
        // Allow only alphanumeric and underscore without quoting
        if (!columnName.matches("^[a-zA-Z_][a-zA-Z0-9_]*$")) {
            return true;
        }
        
        return false;
    }
    
    /**
     * Quote a column name if needed
     */
    private String quoteIfNeeded(String columnName) {
        if (needsQuoting(columnName)) {
            return "\"" + columnName + "\"";
        }
        return columnName;
    }
    
    public List<String> getColumnNames(String filePath) throws IOException {
        List<String> columnNames = new ArrayList<>();
        Set<String> usedNames = new HashSet<>(); // Track used names to handle duplicates
        columnNameMapping.clear(); // Clear previous mappings
        
        try (BufferedReader reader = new BufferedReader(new FileReader(filePath))) {
            String headerLine = reader.readLine();
            if (headerLine == null) {
                return null; // No header row found in the file
            }
            String delimiter = getFileExtension(filePath).equals("csv") ? "," : "\t";
            String[] headers = headerLine.split(Pattern.quote(delimiter));
            for (int i = 0; i < headers.length; i++) {
                String header = headers[i];
                // Keep the EXACT original header from CSV (with spaces, etc.)
                String originalHeaderFromCSV = header.trim();
                
                // Transform for use as SQL column name (replace spaces, remove special chars)
                String columnName = originalHeaderFromCSV.replaceAll("\\s+", "_").replaceAll("[./:()]", "");
                
                // If column name is empty after transformation, generate a default name
                boolean isGenerated = false;
                if (columnName.isEmpty()) {
                    columnName = "Column" + (i + 1);
                    isGenerated = true;
                    System.out.println("[TxtFileProcessor] Empty column name at position " + (i + 1) + ", using: " + columnName);
                }
                
                // Fix: Prefix column names that start with a digit (invalid SQL identifiers)
                if (!columnName.isEmpty() && Character.isDigit(columnName.charAt(0))) {
                    String originalName = columnName;
                    columnName = "Col_" + columnName;
                    System.out.println("[TxtFileProcessor] Column " + i + " starts with digit, renamed '" + originalName + "' to '" + columnName + "'");
                }
                
                // Preserve the original logical column name. Reserved words
                // (Date, Order, Group, Select, ...) are handled by quoting in
                // the generated DDL/SQL via quoteIfNeeded, not by renaming.
                String transformedName = columnName;

                // Fix: Handle duplicate column names by appending suffix
                String baseTransformedName = transformedName;
                int suffix = 1;
                while (usedNames.contains(transformedName.toUpperCase())) {
                    transformedName = baseTransformedName + "_" + suffix;
                    suffix++;
                    System.out.println("[TxtFileProcessor] Duplicate column name, renamed to '" + transformedName + "'");
                }
                usedNames.add(transformedName.toUpperCase());
                
                // Map: transformed SQL name -> original CSV header
                // For generated names, map to the generated name itself (not empty string)
                // This is what TEXTTABLE needs to match against the actual CSV file
                if (isGenerated) {
                    columnNameMapping.put(transformedName, transformedName);
                } else {
                    columnNameMapping.put(transformedName, originalHeaderFromCSV);
                }
                columnNames.add(transformedName);
            }
        }
        return columnNames;
    }

    public String generateView(String fileName, List<String> columnNames) {
        return generateView(fileName, fileName, columnNames);
    }
    
    /**
     * Generate view with separate file name and relative file path.
     * 
     * @param fileName The original file name (used for view naming and extension detection)
     * @param relativeFilePath The relative file path to use in getTextFiles (e.g., "2/uploads/file.csv")
     * @param columnNames List of column names
     * @return The view definition DDL
     */
    public String generateView(String fileName, String relativeFilePath, List<String> columnNames) {
        String extension = getFileExtension(fileName);
        String delimiter = extension.equals("csv") ? "," : "\t";
        
        // Generate view name with uppercase extension to match Excel file naming convention
        // e.g., "sales.txt" -> "sales_TXT", "data.csv" -> "data_CSV"
        // This matches how Redash creates data source names from uploaded files
        String fileNameWithoutExtension = fileName.substring(0, fileName.lastIndexOf('.'));
        String viewName = fileNameWithoutExtension.replaceAll("\\s+", "_") + "_" + extension.toUpperCase();
        StringBuilder viewDefinition = new StringBuilder();
        viewDefinition.append("CREATE VIEW ").append("\"").append(viewName).append("\"").append(" (\n");
        for (String columnName : columnNames) {
            // Use the original column name for NAMEINSOURCE
            String sourceColumnName = columnNameMapping.getOrDefault(columnName, columnName);
            // Quote the view column identifier when it is a reserved word or
            // contains special characters, matching the SELECT/TEXTTABLE clauses
            // below. Without this an unquoted reserved word (e.g. "Month") fails
            // DDL parsing and the entire VDB is marked FAILED.
            viewDefinition.append(quoteIfNeeded(columnName)).append(" string(4000) OPTIONS(NAMEINSOURCE '").append(sourceColumnName).append("', UPDATABLE 'FALSE'),\n");
        }
        viewDefinition.deleteCharAt(viewDefinition.length() - 2); // Remove the last comma
        viewDefinition.append(") AS\n");
        viewDefinition.append("SELECT \n");
        viewDefinition.append(columnNames.stream().map(col -> {
            // In SELECT clause, reference the TEXTTABLE column alias (which uses the original source column name)
            String sourceCol = columnNameMapping.getOrDefault(col, col);
            // Quote if needed to match TEXTTABLE column definition
            if (needsQuoting(sourceCol)) {
                return "A.\"" + sourceCol + "\"";
            } else {
                return "A." + sourceCol;
            }
        }).collect(Collectors.joining(", ")));
        viewDefinition.append("\nFROM\n");
        // Use relativeFilePath instead of fileName for multi-tenancy support
        viewDefinition.append("(EXEC CSVSourceModel.getTextFiles('").append(relativeFilePath).append("')) AS f,\n");
        viewDefinition.append("TEXTTABLE(f.file COLUMNS ");
        viewDefinition.append(columnNames.stream().map(col -> {
            String sourceCol = columnNameMapping.getOrDefault(col, col);
            // TEXTTABLE column names need quotes if they contain spaces or are reserved keywords
            // This allows Teiid to parse them correctly
            if (needsQuoting(sourceCol)) {
                return "\"" + sourceCol + "\" string";
            } else {
                return sourceCol + " string";
            }
        }).collect(Collectors.joining(", ")));
        viewDefinition.append(" DELIMITER '").append(delimiter).append("' HEADER) AS A;");
        return viewDefinition.toString();
    }

    private String getFileExtension(String fileName) {
        int lastIndexOfDot = fileName.lastIndexOf('.');
        if (lastIndexOfDot == -1) {
            return "";
        }
        return fileName.substring(lastIndexOfDot + 1);
    }
}
