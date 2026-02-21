package cloud.tablescope;

import java.io.*;
import java.util.*;
import java.util.regex.*;
import javax.servlet.ServletException;
import javax.servlet.annotation.WebServlet;
import javax.servlet.http.*;
import org.json.JSONArray;
import org.json.JSONObject;

@WebServlet("/retrievesqlstatement")
public class RetrieveSQLStatementServlet extends HttpServlet {

    protected void doGet(HttpServletRequest request, HttpServletResponse response)
            throws ServletException, IOException {
        response.setHeader("Access-Control-Allow-Origin", "*");
        response.setHeader("Access-Control-Allow-Methods", "POST, GET, OPTIONS, DELETE");
        response.setHeader("Access-Control-Allow-Headers", "Content-Type, Access-Control-Allow-Headers, Authorization, X-Requested-With");
        response.setContentType("application/json");
        PrintWriter out = response.getWriter();
        JSONObject jsonResponse = new JSONObject();

        String viewName = request.getParameter("viewName");

        if (viewName == null || viewName.isEmpty()) {
            jsonResponse.put("error", "View name is required.");
            out.println(jsonResponse.toString());
            return;
        }

        String vdbFilePath = "/opt/wildfly/teiidfiles/myvdbtest-vdb.xml";

        try {
            String vdbContent = readFromFile(vdbFilePath);
            if (vdbContent == null) {
                jsonResponse.put("error", "Failed to read VDB file. Check file permissions or existence.");
                out.println(jsonResponse.toString());
                return;
            }

            // Extract SQL statement related to the provided view name
            String sqlStatement = extractSQLStatement(vdbContent, viewName);
            if (sqlStatement == null) {
                jsonResponse.put("error", "SQL statement not found for the specified view.");
            } else {
                jsonResponse.put("sqlStatement", sqlStatement);

                // Parse SQL statement for details
                JSONObject parsedDetails = parseSQLStatement(sqlStatement, viewName);
                jsonResponse.put("details", parsedDetails);
            }

        } catch (IOException e) {
            jsonResponse.put("error", "Failed to process file: " + e.getMessage());
        } catch (Exception e) {
            jsonResponse.put("error", "An error occurred: " + e.getMessage());
        }

        out.println(jsonResponse.toString());
    }

    private String readFromFile(String filePath) throws IOException {
        if (filePath == null || filePath.isEmpty()) {
            throw new IllegalArgumentException("File path is null or empty.");
        }

        StringBuilder content = new StringBuilder();
        try (BufferedReader reader = new BufferedReader(new FileReader(filePath))) {
            String line;
            while ((line = reader.readLine()) != null) {
                content.append(line).append("\n");
            }
        }
        return content.toString();
    }

    private String extractSQLStatement(String vdbContent, String viewName) {
        if (vdbContent == null || vdbContent.isEmpty()) {
            return null;
        }

        String sqlStatement = extractTXTCSVSQLStatement(vdbContent, viewName);
        if (sqlStatement == null) {
            sqlStatement = extractOtherSQLStatement(vdbContent, viewName);
        }
        return sqlStatement;
    }

    private String extractTXTCSVSQLStatement(String vdbContent, String viewName) {
        String regex = "CREATE VIEW\\s+" + Pattern.quote(viewName) + "\\s+\\(.*?\\)\\s+AS\\s+(SELECT\\s+.*?);";
        Pattern pattern = Pattern.compile(regex, Pattern.DOTALL);
        Matcher matcher = pattern.matcher(vdbContent);

        if (matcher.find()) {
            return matcher.group(1).trim();
        }
        return null;
    }

    private String extractOtherSQLStatement(String vdbContent, String viewName) {
        String regex = "CREATE VIEW\\s+" + Pattern.quote(viewName) + "\\s+AS\\s+(SELECT\\s+.*?);";
        Pattern pattern = Pattern.compile(regex, Pattern.DOTALL);
        Matcher matcher = pattern.matcher(vdbContent);

        if (matcher.find()) {
            return matcher.group(1).trim();
        }
        return null;
    }

    private JSONObject parseSQLStatement(String sqlStatement, String viewName) {
        JSONObject details = new JSONObject();

        // Extract primary and secondary tables and fields (join logic)
        Pattern tablePattern = Pattern.compile("FROM\\s+(\\S+)\\s+AS\\s+t1\\s+(LEFT JOIN|RIGHT JOIN|INNER JOIN|JOIN)\\s+(\\S+)\\s+AS\\s+t2");
        Matcher tableMatcher = tablePattern.matcher(sqlStatement);

        if (tableMatcher.find()) {
            // Handle joins
            details.put("PrimaryTableName", tableMatcher.group(1)); // Set PrimaryTableName from the SQL statement
            details.put("SecondaryTableName", tableMatcher.group(3));
            details.put("joinType", tableMatcher.group(2).trim().toUpperCase()); // Add join type to JSON

            // Extract join fields
            Pattern joinPattern = Pattern.compile("ON\\s+t1\\.(\\S+)\\s*=\\s+t2\\.(\\S+)");
            Matcher joinMatcher = joinPattern.matcher(sqlStatement);

            if (joinMatcher.find()) {
                details.put("joinPrimaryField", joinMatcher.group(1));
                details.put("joinSecondaryField", joinMatcher.group(2));
            }

            // Extract fields in SELECT clause
            Pattern fieldPattern = Pattern.compile("SELECT\\s+(.*?)\\s+FROM");
            Matcher fieldMatcher = fieldPattern.matcher(sqlStatement);

            if (fieldMatcher.find()) {
                String[] fields = fieldMatcher.group(1).split(",");
                List<String> primaryFields = new ArrayList<>();
                List<String> secondaryFields = new ArrayList<>();

                for (String field : fields) {
                    field = field.trim();
                    if (field.startsWith("t1.")) {
                        primaryFields.add(field.substring(3));
                    } else if (field.startsWith("t2.")) {
                        secondaryFields.add(field.substring(3));
                    }
                }

                details.put("primaryTableFields", primaryFields);
                details.put("secondaryTableFields", secondaryFields);
            }

            // Extract filters with t1 and t2 prefixes
            Pattern wherePattern = Pattern.compile("WHERE\\s+(.*?)\\s*(ORDER BY|$)");
            Matcher whereMatcher = wherePattern.matcher(sqlStatement);

            if (whereMatcher.find()) {
                String whereClause = whereMatcher.group(1).trim();
                JSONArray filters = parseFilters(whereClause, true);
                details.put("filters", filters);
            }

            // Extract sort orders with t1 and t2 prefixes
            Pattern orderByPattern = Pattern.compile("ORDER BY\\s+(.*)");
            Matcher orderByMatcher = orderByPattern.matcher(sqlStatement);

            if (orderByMatcher.find()) {
                String orderByClause = orderByMatcher.group(1).trim();
                JSONArray sortOrders = parseSortOrders(orderByClause, true);
                details.put("sortOrders", sortOrders);
            }
        } else {
            // Handle single table views (non-join logic)
            Pattern singleTablePattern = Pattern.compile("FROM\\s+(\\S+)(\\s+AS\\s+\\w+)?");
            Matcher singleTableMatcher = singleTablePattern.matcher(sqlStatement);

            if (singleTableMatcher.find()) {
                String primaryTableName = singleTableMatcher.group(1);

                // If PrimaryTableName is derived from an EXEC AS clause, replace with viewName
                if (primaryTableName.startsWith("(EXEC")) {
                    primaryTableName = viewName;
                }

                details.put("PrimaryTableName", primaryTableName); // Set PrimaryTableName from SQL statement

                // Extract fields in SELECT clause
                Pattern fieldPattern = Pattern.compile("SELECT\\s+(.*?)\\s+FROM");
                Matcher fieldMatcher = fieldPattern.matcher(sqlStatement);

                if (fieldMatcher.find()) {
                    String[] fields = fieldMatcher.group(1).split(",");
                    List<String> primaryFields = new ArrayList<>();

                    for (String field : fields) {
                        field = field.trim();
                        if (field.startsWith("A.")) {
                            primaryFields.add(field.substring(2));  // Remove "A." prefix
                        } else {
                            primaryFields.add(field);
                        }
                    }

                    details.put("primaryTableFields", primaryFields);
                }

                // Extract filters with t1 prefix
                Pattern wherePattern = Pattern.compile("WHERE\\s+(.*?)\\s*(ORDER BY|$)");
                Matcher whereMatcher = wherePattern.matcher(sqlStatement);

                if (whereMatcher.find()) {
                    String whereClause = whereMatcher.group(1).trim();
                    JSONArray filters = parseFilters(whereClause, true);  // Apply t1 prefix
                    details.put("filters", filters);
                }

                // Extract sort orders with t1 prefix
                Pattern orderByPattern = Pattern.compile("ORDER BY\\s+(.*)");
                Matcher orderByMatcher = orderByPattern.matcher(sqlStatement);

                if (orderByMatcher.find()) {
                    String orderByClause = orderByMatcher.group(1).trim();
                    JSONArray sortOrders = parseSortOrders(orderByClause, true);  // Apply t1 prefix
                    details.put("sortOrders", sortOrders);
                }
            }
        }

        return details;
    }

    private JSONArray parseFilters(String whereClause, boolean includePrefixes) {
        JSONArray filters = new JSONArray();
        String[] conditions = whereClause.split("\\s+(AND|OR)\\s+");
        Pattern conditionPattern = Pattern.compile("(\\S+)\\s*(=|LIKE)\\s*('.*?'|\\S+)");

        for (String condition : conditions) {
            Matcher conditionMatcher = conditionPattern.matcher(condition.trim());

            if (conditionMatcher.find()) {
                JSONObject filter = new JSONObject();
                String field = conditionMatcher.group(1);
                if (includePrefixes && !field.contains(".")) {
                    field = "t1." + field;  // Add t1 prefix for non-join views
                }
                filter.put("field", field);
                filter.put("operator", conditionMatcher.group(2));
                filter.put("value", conditionMatcher.group(3).replace("'", ""));
                filter.put("conjunction", condition.contains(" AND ") ? "AND" : "OR");

                filters.put(filter);
            }
        }

        return filters;
    }

    private JSONArray parseSortOrders(String orderByClause, boolean includePrefixes) {
        JSONArray sortOrders = new JSONArray();
        String[] orders = orderByClause.split(",");

        for (String order : orders) {
            String[] parts = order.trim().split("\\s+");
            String field = parts[0].replace("'", "").trim();
            if (includePrefixes && !field.contains(".")) {
                field = "t1." + field;  // Add t1 prefix for non-join views
            }
            JSONObject sortOrder = new JSONObject();
            sortOrder.put("field", field);
            sortOrder.put("operator", parts.length > 1 ? parts[1] : "ASC");
            sortOrders.put(sortOrder);
        }

        return sortOrders;
    }
}
