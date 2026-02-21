package cloud.tablescope;

import com.google.gson.Gson;
import javax.servlet.ServletException;
import javax.servlet.annotation.WebServlet;
import javax.servlet.http.HttpServlet;
import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.io.PrintWriter;
import java.sql.*;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.logging.Level;
import java.util.logging.Logger;

@WebServlet("/LimitTopBottom")
public class FetchTableDataLimitTopBottomServlet extends HttpServlet {

    private static final String JDBC_URL = "jdbc:postgresql://64.52.108.62:35442/myvdbtest";
    private static final String USER = "test";
    private static final String PASSWORD = "test";

    private static final Logger LOGGER = Logger.getLogger(FetchTableDataLimitTopBottomServlet.class.getName());

    @Override
    protected void doGet(HttpServletRequest req, HttpServletResponse res) throws ServletException, IOException {
        LOGGER.log(Level.INFO, "Received GET request");

        res.setHeader("Access-Control-Allow-Origin", "*");
        res.setHeader("Access-Control-Allow-Methods", "GET");
        res.setHeader("Access-Control-Allow-Headers", "Content-Type");

        res.setContentType("application/json");
        PrintWriter out = res.getWriter();

        String tableName = req.getParameter("tableName");
        if (tableName == null || tableName.isEmpty()) {
            LOGGER.log(Level.WARNING, "Missing or empty tableName parameter");
            res.setStatus(HttpServletResponse.SC_BAD_REQUEST);
            out.println("{\"error\":\"Missing or empty tableName parameter\"}");
            return;
        }

        try {
            String orderByColumn = getFirstColumnName(tableName);
            if (orderByColumn == null) {
                LOGGER.log(Level.WARNING, "Failed to determine any column for ordering in table: " + tableName);
                res.setStatus(HttpServletResponse.SC_BAD_REQUEST);
                out.println("{\"error\":\"Failed to determine any column for ordering in table: " + tableName + "\"}");
                return;
            }

            List<Map<String, Object>> tableData = fetchTopAndBottomRows(tableName, orderByColumn);
            String jsonResponse = new Gson().toJson(tableData);
            out.println(jsonResponse);
            LOGGER.log(Level.INFO, "Successfully fetched top/bottom rows for table: " + tableName);
        } catch (SQLException e) {
            LOGGER.log(Level.SEVERE, "Failed to fetch top/bottom rows for table: " + tableName, e);
            res.setStatus(HttpServletResponse.SC_INTERNAL_SERVER_ERROR);
            out.println("{\"error\":\"Failed to fetch data: " + e.getMessage() + "\"}");
        }
    }

    private String getFirstColumnName(String tableName) throws SQLException {
        try (Connection connection = DriverManager.getConnection(JDBC_URL, USER, PASSWORD)) {
            DatabaseMetaData metaData = connection.getMetaData();
            ResultSet columns = metaData.getColumns(null, null, tableName, null);
            if (columns.next()) {
                return columns.getString("COLUMN_NAME");
            }
        }
        return null;
    }

    private List<Map<String, Object>> fetchTopAndBottomRows(String tableName, String orderByColumn) throws SQLException {
        List<Map<String, Object>> tableData = new ArrayList<>();
        try (Connection connection = DriverManager.getConnection(JDBC_URL, USER, PASSWORD);
             Statement stmt = connection.createStatement()) {

            String topQuery = "SELECT * FROM (" +
                              "SELECT *, ROW_NUMBER() OVER (ORDER BY " + orderByColumn + " ASC) AS row_id " +
                              "FROM " + tableName + " " +
                              ") AS topRows WHERE row_id <= 5";
            ResultSet topRs = stmt.executeQuery(topQuery);
            tableData.addAll(extractRowsFromResultSet(topRs));

            String bottomQuery = "SELECT * FROM (" +
                                 "SELECT *, ROW_NUMBER() OVER (ORDER BY " + orderByColumn + " DESC) AS row_id " +
                                 "FROM " + tableName + " " +
                                 ") AS bottomRows WHERE row_id <= 5";
            ResultSet bottomRs = stmt.executeQuery(bottomQuery);
            tableData.addAll(extractRowsFromResultSet(bottomRs));
        }
        return tableData;
    }

    private List<Map<String, Object>> extractRowsFromResultSet(ResultSet rs) throws SQLException {
        List<Map<String, Object>> rows = new ArrayList<>();
        ResultSetMetaData rsMetaData = rs.getMetaData();
        int columnCount = rsMetaData.getColumnCount();

        while (rs.next()) {
            Map<String, Object> row = new HashMap<>();
            for (int i = 1; i <= columnCount; i++) {
                row.put(rsMetaData.getColumnName(i), rs.getObject(i));
            }
            rows.add(row);
        }
        return rows;
    }
}
