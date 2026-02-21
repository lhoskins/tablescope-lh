package cloud.tablescope;

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
import javax.servlet.ServletException;
import javax.servlet.annotation.WebServlet;
import javax.servlet.http.HttpServlet;
import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpServletResponse;
import com.google.gson.Gson;

@WebServlet("/getdatatype")
public class GetDataTypeServlet extends HttpServlet {

    private static final String JDBC_URL = "jdbc:postgresql://64.52.108.62:35442/myvdbtest";
    private static final String USER = "test";
    private static final String PASSWORD = "test";

    @Override
    protected void doGet(HttpServletRequest req, HttpServletResponse res) throws ServletException, IOException {
        res.setHeader("Access-Control-Allow-Origin", "*");
        res.setHeader("Access-Control-Allow-Methods", "POST, GET, OPTIONS, DELETE");
        res.setHeader("Access-Control-Max-Age", "3600");
        res.setHeader("Access-Control-Allow-Headers", "Content-Type, Access-Control-Allow-Headers, Authorization, X-Requested-With");

        res.setContentType("application/json");
        PrintWriter out = res.getWriter();

        String tablesParam = req.getParameter("tables");
        String columnsParam = req.getParameter("columns");
        if (tablesParam == null || tablesParam.isEmpty() || columnsParam == null || columnsParam.isEmpty()) {
            res.setStatus(HttpServletResponse.SC_BAD_REQUEST);
            out.println("{\"error\":\"Missing or empty tables or columns parameter\"}");
            return;
        }

        try {
            List<Map<String, Object>> dataTypes = getDataTypes(tablesParam, columnsParam);
            String jsonResponse = new Gson().toJson(dataTypes);
            out.println(jsonResponse);
        } catch (Exception e) {
            res.setStatus(HttpServletResponse.SC_INTERNAL_SERVER_ERROR);
            out.println("{\"error\":\"Failed to fetch data types for table: " + e.getMessage() + "\"}");
        }
    }

    private List<Map<String, Object>> getDataTypes(String tablesParam, String columnsParam) throws SQLException {
        List<Map<String, Object>> dataTypes = new ArrayList<>();

        String[] tables = tablesParam.split(",");
        String[] columns = columnsParam.split(",");

        try (Connection connection = DriverManager.getConnection(JDBC_URL, USER, PASSWORD)) {
            for (String table : tables) {
                for (String column : columns) {
                    String query = "SELECT column_name, data_type, character_maximum_length FROM information_schema.columns WHERE table_name = '" + table + "' AND column_name = '" + column + "'";
                    try (Statement stmt = connection.createStatement(); ResultSet rs = stmt.executeQuery(query)) {
                        while (rs.next()) {
                            Map<String, Object> row = new HashMap<>();
                            row.put("name", rs.getString("column_name"));
                            row.put("dataType", rs.getString("data_type"));
                            row.put("length", rs.getInt("character_maximum_length"));
                            dataTypes.add(row);
                        }
                    }
                }
            }
        }

        return dataTypes;
    }
}
