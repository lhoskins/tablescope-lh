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

@WebServlet("/getSchemas")
public class GetSchemasServlet extends HttpServlet {

    private static final String JDBC_URL = "jdbc:postgresql://64.52.108.62:35442/myvdb";
    private static final String USER = "test";
    private static final String PASSWORD = "test";

    @Override
    protected void doGet(HttpServletRequest req, HttpServletResponse res) throws ServletException, IOException {
        try {
            // Create a connection to PostgreSQL database
            try (Connection conn = DriverManager.getConnection(JDBC_URL, USER, PASSWORD)) {
                // Execute SQL query
                String sql = "SELECT DISTINCT schema_name FROM information_schema.schemata WHERE schema_name NOT LIKE 'pg_%' AND schema_name != 'information_schema'";
                try (PreparedStatement stmt = conn.prepareStatement(sql);
                     ResultSet rs = stmt.executeQuery()) {
                    // Process query result
                    List<String> schemas = new ArrayList<>();
                    while (rs.next()) {
                        schemas.add(rs.getString("schema_name"));
                    }

                    // Send JSON response
                    res.setContentType("application/json");
                    PrintWriter out = res.getWriter();
                    out.println("[");
                    for (int i = 0; i < schemas.size(); i++) {
                        out.println("\"" + schemas.get(i) + "\"");
                        if (i < schemas.size() - 1) {
                            out.println(",");
                        }
                    }
                    out.println("]");
                }
            }
        } catch (SQLException e) {
            e.printStackTrace();
            res.setStatus(500);
            res.getWriter().print("Internal server error");
        }
    }
}
