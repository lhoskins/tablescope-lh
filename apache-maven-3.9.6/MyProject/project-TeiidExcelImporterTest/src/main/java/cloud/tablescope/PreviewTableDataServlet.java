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

@WebServlet("/PreviewTableData")
public class PreviewTableDataServlet extends HttpServlet {

  private static final String JDBC_URL = "jdbc:postgresql://64.52.108.62:35442/myvdbtest";
  private static final String USER = "test";
  private static final String PASSWORD = "test";

  @Override
  protected void doGet(HttpServletRequest req, HttpServletResponse res) throws ServletException, IOException {
    res.setHeader("Access-Control-Allow-Origin", "*");
    res.setHeader("Access-Control-Allow-Methods", "POST, GET, OPTIONS, DELETE");
    res.setHeader("Access-Control-Max-Age", "3600");
    res.setHeader("Access-Control-Allow-Headers", "Content-Type, Access-Control-Allow-Headers, Authorization, X-Requested-With");

 // Handle preflight requests
    if ("OPTIONS".equalsIgnoreCase(req.getMethod())) {
      res.setStatus(HttpServletResponse.SC_OK);
      return;
    }

    res.setContentType("application/json");
    PrintWriter out = res.getWriter();

    String query = req.getParameter("query");
    if (query == null || query.isEmpty()) {
      res.setStatus(HttpServletResponse.SC_BAD_REQUEST);
      out.println("{\"error\":\"Missing or empty query parameter\"}");
      return;
    }

    try {
      List<Map<String, Object>> tableData = fetchTableData(query);
      String jsonResponse = new Gson().toJson(tableData);
      out.println(jsonResponse);
    } catch (Exception e) {
      res.setStatus(HttpServletResponse.SC_INTERNAL_SERVER_ERROR);
      out.println("{\"error\":\"Failed to fetch data: " + e.getMessage() + "\"}");
    }
  }

  private List<Map<String, Object>> fetchTableData(String query) throws SQLException {
    List<Map<String, Object>> tableData = new ArrayList<>();

    try (Connection connection = DriverManager.getConnection(JDBC_URL, USER, PASSWORD)) {
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
}
