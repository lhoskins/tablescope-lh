import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.PrintWriter;
import java.sql.Connection;
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

import org.teiid.adminapi.Admin;
import org.teiid.adminapi.AdminFactory;
import org.teiid.adminapi.VDB;

import com.google.gson.Gson;

@WebServlet("/getTables")
public class GetTablesServlet extends HttpServlet {

    private DataSource dataSource;

    // Path to the VDB file
    private static final String VDB_FILE_PATH = "/opt/wildfly/teiidfiles/myvdb-vdb.xml";

    @Override
    public void init() throws ServletException {
        try {
            // Lookup the Teiid DataSource using JNDI and store it for future use
            Context context = new InitialContext();
            dataSource = (DataSource) context.lookup("java:/myvdb");
        } catch (NamingException e) {
            throw new ServletException("Error initializing DataSource", e);
        }
    }

    @Override
    protected void doGet(HttpServletRequest req, HttpServletResponse res) throws ServletException, IOException {
        try {
            // Check if the VDB is deployed, if not deploy it
            if (!isVDBDeployed()) {
                deployVDB();
            }

            // Retrieve schema parameter from request URL's query parameter
            String schema = req.getParameter("schema");
            if (schema == null || schema.isEmpty()) {
                res.setStatus(400);
                res.getWriter().print("Schema parameter is required");
                return;
            }

            // Removed session check (public endpoint)

            // Create a connection to Teiid using the DataSource
            try (Connection conn = getConnection()) {
                // Execute SQL query to retrieve table names for the given schema
                String sql = "SELECT DISTINCT Name FROM SYS.Tables WHERE SchemaName = ?";
                try (PreparedStatement stmt = conn.prepareStatement(sql)) {
                    stmt.setString(1, schema);
                    try (ResultSet rs = stmt.executeQuery()) {
                        // Process query result
                        List<String> tables = new ArrayList<>();
                        while (rs.next()) {
                            tables.add(rs.getString("Name"));
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

    private boolean isVDBDeployed() throws Exception {
        // Create Teiid admin instance
        Admin admin = AdminFactory.getInstance().createAdmin("64.52.108.62", 10000, "admin", "admin".toCharArray());

        // Check if VDB is deployed
        VDB vdb = admin.getVDB("myvdb");
        return vdb != null && vdb.getStatus().equals(VDB.Status.ACTIVE);
    }

    private Connection getConnection() throws SQLException {
        // Attempt to get a connection from the DataSource
        Connection conn = dataSource.getConnection();

        // If the connection is closed, attempt to reopen it
        if (conn.isClosed()) {
            conn = dataSource.getConnection();
        }

        return conn;
    }

    private void deployVDB() {
        try {
            // Create Teiid admin instance
            Admin admin = AdminFactory.getInstance().createAdmin("64.52.108.62", 10000, "admin", "admin".toCharArray());

            // Undeploy existing VDB if it exists
            admin.undeploy("myvdb");

            // Read VDB file
            try (InputStream inputStream = new FileInputStream(VDB_FILE_PATH)) {
                // Deploy VDB
                admin.deploy("myvdb-vdb.xml", inputStream); // Assuming "myvdb" is the VDB name
            }
        } catch (Exception e) {
            e.printStackTrace();
            // Log error
            log("Failed to deploy VDB: " + e.getMessage());
        }
    }

    @Override
    protected void doPost(HttpServletRequest request, HttpServletResponse response)
            throws ServletException, IOException {
        response.setContentType("text/plain");
        PrintWriter out = response.getWriter();

        // Deploy the VDB
        deployVDB();
        out.println("VDB deployed successfully!");
    }
}
