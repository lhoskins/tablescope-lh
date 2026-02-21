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

@WebServlet("/getJoinFieldsColumns")
public class GetJoinFieldsColumnsServlet extends HttpServlet {

    private static final String JDBC_URL = "jdbc:postgresql://64.52.108.62:35442/myvdb";
    private static final String USER = "test";
    private static final String PASSWORD = "test";

    @Override
    protected void doGet(HttpServletRequest req, HttpServletResponse res) throws ServletException, IOException {
        try {
            // Retrieve tables parameter from request URL's query parameter
            String tablesParam = req.getParameter("tables");
            if (tablesParam == null || tablesParam.isEmpty()) {
                res.setStatus(400);
                res.getWriter().print("Tables parameter is required");
                return;
            }

            // Split tables parameter into individual table names
            String[] tables = tablesParam.split(",");
            if (tables.length < 2) {
                res.setStatus(400);
                res.getWriter().print("At least two tables are required to fetch join fields");
                return;
            }

            // Create a connection to PostgreSQL database
            try (Connection conn = DriverManager.getConnection(JDBC_URL, USER, PASSWORD)) {
                // Create the SQL query to retrieve join fields (columns)
                StringBuilder query = new StringBuilder();
                query.append("SELECT DISTINCT c1.column_name || ',' || c2.column_name AS JoinField ")
                     .append("FROM information_schema.columns c1 ")
                     .append("CROSS JOIN information_schema.columns c2 ")
                     .append("WHERE ");

                // Add conditions for each table
                for (int i = 0; i < tables.length; i++) {
                    if (i > 0) {
                        query.append("AND ");
                    }
                    query.append("c").append(i + 1).append(".table_name = ?");
                    if (i < tables.length - 1) {
                        query.append(" AND ");
                    }
                }

                // Execute the query
                List<String> joinFields = new ArrayList<>();
                try (PreparedStatement stmt = conn.prepareStatement(query.toString())) {
                    for (int i = 0; i < tables.length; i++) {
                        stmt.setString(i + 1, tables[i]);
                    }
                    try (ResultSet rs = stmt.executeQuery()) {
                        // Process query result
                        while (rs.next()) {
                            joinFields.add(rs.getString("JoinField"));
                        }
                    }
                }

                // Send JSON response
                res.setContentType("application/json");
                PrintWriter out = res.getWriter();
                out.println(joinFields);
            }
        } catch (SQLException e) {
            e.printStackTrace();
            res.setStatus(500);
            res.getWriter().print("Internal server error");
        }
    }
}
