package cloud.tablescope;

import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import com.google.gson.Gson;

import javax.servlet.ServletException;
import javax.servlet.annotation.WebServlet;
import javax.servlet.http.HttpServlet;
import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpServletResponse;
import java.io.FileReader;
import java.io.IOException;
import java.io.PrintWriter;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.ResultSet;
import java.sql.ResultSetMetaData;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

@WebServlet("/fetchTableData")
public class FetchTableDataServlet extends HttpServlet {

    private static final String JDBC_URL = "jdbc:postgresql://64.52.108.62:35442/myvdbtest";
    private static final String USER = "test";
    private static final String PASSWORD = "test";
    private static final String DRILLDOWN_CONFIG_PATH = "/opt/redash-8.0.0-7/apps/tsTest/src/drilldownConfig.json"; // Update this path

    @Override
    protected void doGet(HttpServletRequest req, HttpServletResponse res) throws ServletException, IOException {
        res.setHeader("Access-Control-Allow-Origin", "*");
        res.setHeader("Access-Control-Allow-Methods", "POST, GET, OPTIONS, DELETE");
        res.setHeader("Access-Control-Max-Age", "3600");
        res.setHeader("Access-Control-Allow-Headers", "Content-Type, Access-Control-Allow-Headers, Authorization, X-Requested-With");

        res.setContentType("application/json");
        PrintWriter out = res.getWriter();

        String tableName = req.getParameter("tableName");
        String columnName = req.getParameter("columnName");
        String value = req.getParameter("value");

        if (tableName == null || tableName.isEmpty()) {
            res.setStatus(HttpServletResponse.SC_BAD_REQUEST);
            out.println("{\"error\":\"Missing or empty tableName parameter\"}");
            return;
        }

        try {
            // Check if drilldown configuration exists for the column
            JsonObject drilldownConfig = getDrilldownConfig();
            JsonObject drilldown = getDrilldownForColumn(drilldownConfig, columnName);

            List<Map<String, Object>> tableData;

            if (drilldown != null) {
                // Perform drilldown query
                String targetTable = drilldown.get("targetTable").getAsString();
                String targetColumn = drilldown.get("targetColumn").getAsString();
                tableData = fetchTableDataWithFilter(targetTable, targetColumn, value);
            } else {
                // Fetch data without drilldown
                tableData = fetchTableData(tableName);
            }

            String jsonResponse = new Gson().toJson(tableData);
            out.println(jsonResponse);
        } catch (Exception e) {
            res.setStatus(HttpServletResponse.SC_INTERNAL_SERVER_ERROR);
            out.println("{\"error\":\"Failed to fetch data for table: " + e.getMessage() + "\"}");
        }
    }

    private List<Map<String, Object>> fetchTableData(String tableName) throws SQLException {
        List<Map<String, Object>> tableData = new ArrayList<>();

        try (Connection connection = DriverManager.getConnection(JDBC_URL, USER, PASSWORD)) {
            String query = "SELECT * FROM " + tableName;
            try (Statement stmt = connection.createStatement(); ResultSet rs = stmt.executeQuery(query)) {
                ResultSetMetaData rsMetaData = rs.getMetaData();
                int columnCount = rsMetaData.getColumnCount();

                while (rs.next()) {
                    Map<String, Object> row = new HashMap<>();
                    for (int i = 1; i <= columnCount; i++) {
                        row.put(rsMetaData.getColumnName(i), rs.getObject(i));
                    }
                    tableData.add(row);
                }
            }
        }

        return tableData;
    }

    private List<Map<String, Object>> fetchTableDataWithFilter(String tableName, String columnName, String value) throws SQLException {
        List<Map<String, Object>> tableData = new ArrayList<>();

        try (Connection connection = DriverManager.getConnection(JDBC_URL, USER, PASSWORD)) {
            String query = "SELECT * FROM " + tableName + " WHERE " + columnName + " = '" + value + "'";
            try (Statement stmt = connection.createStatement(); ResultSet rs = stmt.executeQuery(query)) {
                ResultSetMetaData rsMetaData = rs.getMetaData();
                int columnCount = rsMetaData.getColumnCount();

                while (rs.next()) {
                    Map<String, Object> row = new HashMap<>();
                    for (int i = 1; i <= columnCount; i++) {
                        row.put(rsMetaData.getColumnName(i), rs.getObject(i));
                    }
                    tableData.add(row);
                }
            }
        }

        return tableData;
    }

    // Method to parse the drilldown configuration file
    private JsonObject getDrilldownConfig() throws IOException {
        JsonParser parser = new JsonParser();
        try (FileReader reader = new FileReader(DRILLDOWN_CONFIG_PATH)) {
            JsonElement jsonElement = parser.parse(reader);
            return jsonElement.getAsJsonObject();
        }
    }

    private JsonObject getDrilldownForColumn(JsonObject drilldownConfig, String columnName) {
        if (drilldownConfig != null && drilldownConfig.has("drilldowns")) {
            for (JsonElement drilldownElement : drilldownConfig.getAsJsonArray("drilldowns")) {
                JsonObject drilldown = drilldownElement.getAsJsonObject();
                if (drilldown.get("sourceColumn").getAsString().equals(columnName)) {
                    return drilldown;
                }
            }
        }
        return null;
    }
}
