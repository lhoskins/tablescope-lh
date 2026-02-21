import java.io.IOException;
import java.io.PrintWriter;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.List;
import javax.servlet.ServletException;
import javax.servlet.annotation.WebServlet;
import javax.servlet.http.HttpServlet;
import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpServletResponse;
import com.google.gson.Gson;

@WebServlet("/getColumns")
public class GetColumnsServlet extends HttpServlet {

    private static final String JDBC_URL = "jdbc:postgresql://64.52.108.62:35442/myvdbtest";
    private static final String USER = "test";
    private static final String PASSWORD = "test";

    @Override
    protected void doGet(HttpServletRequest req, HttpServletResponse res) throws ServletException, IOException {
        try {
            String tablesParam = req.getParameter("tables");
            if (tablesParam == null || tablesParam.isEmpty()) {
                res.setStatus(400);
                res.getWriter().print("Tables parameter is required");
                return;
            }

            String[] tables = tablesParam.split(",");
            if (tables.length == 0) {
                res.setStatus(400);
                res.getWriter().print("Tables parameter cannot be empty");
                return;
            }

            // Create a connection to PostgreSQL database
            try (Connection conn = DriverManager.getConnection(JDBC_URL, USER, PASSWORD)) {
                String placeholders = "";
                for (int i = 0; i < tables.length; i++) {
                    placeholders += "?,";
                }
                placeholders = placeholders.substring(0, placeholders.length() - 1); // Remove the trailing comma
                
                String query = "SELECT table_name AS TableName, column_name AS Name FROM information_schema.columns WHERE table_name IN (" + placeholders + ")";
                try (PreparedStatement stmt = conn.prepareStatement(query)) {
                    for (int i = 0; i < tables.length; i++) {
                        stmt.setString(i + 1, tables[i]);
                    }
                    
                    try (ResultSet rs = stmt.executeQuery()) {
                        List<Column> columns = new ArrayList<>();
                        while (rs.next()) {
                            String tableName = rs.getString("TableName");
                            String name = rs.getString("Name");
                            columns.add(new Column(tableName, name));
                        }
                        // Send JSON response
                        res.setContentType("application/json");
                        PrintWriter out = res.getWriter();
                        out.println(new Gson().toJson(columns));
                    }
                }
            }
        } catch (SQLException e) {
            e.printStackTrace();
            res.setStatus(500);
            res.getWriter().print("Internal server error");
        }
    }

    // Define a POJO to represent column information
    private class Column {
        private String tableName;
        private String name;

        public Column(String tableName, String name) {
            this.tableName = tableName;
            this.name = name;
        }

        // Getters and setters (if needed)
    }
}
