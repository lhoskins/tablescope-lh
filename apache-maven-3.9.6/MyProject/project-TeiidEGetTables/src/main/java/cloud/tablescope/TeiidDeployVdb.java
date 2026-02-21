import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.PrintWriter;
import javax.servlet.ServletException;
import javax.servlet.annotation.WebServlet;
import javax.servlet.http.HttpServlet;
import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpServletResponse;
import org.teiid.adminapi.Admin;
import org.teiid.adminapi.jboss.AdminFactory;

@WebServlet("/deployvdb")
public class TeiidDeployVdb extends HttpServlet {

    // Path to the VDB file
    private static final String VDB_FILE_PATH = "/opt/wildfly/teiidfiles/myvdb-vdb.xml";

    @Override
    protected void doGet(HttpServletRequest request, HttpServletResponse response)
            throws ServletException, IOException {
        doPost(request, response); // Delegate GET requests to doPost
    }

    @Override
    protected void doPost(HttpServletRequest request, HttpServletResponse response)
            throws ServletException, IOException {
        response.setContentType("text/plain");
        PrintWriter out = response.getWriter();
        
        // Deploy the VDB
        deployVDB(out);
    }

    private void deployVDB(PrintWriter out) {
        try {
            // Create Teiid admin instance
            Admin admin = AdminFactory.getInstance().createAdmin("64.52.108.62", 10000, "admin", "admin".toCharArray());
            
            // Read VDB file
            try (InputStream inputStream = new FileInputStream(VDB_FILE_PATH)) {
                // Deploy VDB
                admin.deploy("myvdb-vdb.xml", inputStream); // Assuming "myvdb" is the VDB name
                out.println("VDB deployed successfully!");
            }
        } catch (Exception e) {
            e.printStackTrace();
            out.println("Failed to deploy VDB: " + e.getMessage());
        }
    }
}
