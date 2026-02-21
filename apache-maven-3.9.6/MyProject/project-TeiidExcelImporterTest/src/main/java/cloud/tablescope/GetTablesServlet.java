import java.io.IOException;
import java.io.PrintWriter;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.List;
import javax.naming.Context;
import javax.naming.InitialContext;
import javax.naming.NamingException;
import javax.servlet.ServletException;
import javax.servlet.annotation.WebServlet;
import javax.servlet.http.HttpServlet;
import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpServletResponse;
import javax.sql.DataSource;
import com.google.gson.Gson;

@WebServlet("/getTables")
public class GetTablesServlet extends HttpServlet {

  private static final String JDBC_URL = "jdbc:postgresql://64.52.108.62:35442/myvdbtest";
  private static final String USER = "test";
  private static final String PASSWORD = "test";

  @Override
  protected void doGet(HttpServletRequest req, HttpServletResponse res) throws ServletException, IOException {
    try {
      // Retrieve schema parameter from request URL's query parameter
      String schema = req.getParameter("schema");
      if (schema == null || schema.isEmpty()) {
        res.setStatus(400);
        res.getWriter().print("Schema parameter is required");
        return;
      }

      // Removed session check (public endpoint)

      // Create a connection to PostgreSQL database
      try (Connection conn = DriverManager.getConnection(JDBC_URL, USER, PASSWORD)) {
        // Execute SQL query to retrieve table names for the given schema
        String sql = "SELECT DISTINCT table_name FROM information_schema.tables WHERE table_schema = ?";
        try (PreparedStatement stmt = conn.prepareStatement(sql)) {
          stmt.setString(1, schema);
          try (ResultSet rs = stmt.executeQuery()) {
            // Process query result
            List<String> tables = new ArrayList<>();
            while (rs.next()) {
              tables.add(rs.getString("table_name"));
            }

            // Convert list of table names to JSON
            String jsonTables = new Gson().toJson(tables);

            // Send JSON response
            res.setContentType("application/json");
            PrintWriter out = res.getWriter();
            out.println(jsonTables);
          }
        }
      }
    } catch (SQLException e) {
      e.printStackTrace();
      res.setStatus(500);
      res.getWriter().print("Internal server error");

      // Log the error
      log("Error retrieving tables: " + e.getMessage());
    }
  }
}
