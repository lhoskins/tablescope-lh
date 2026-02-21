package cloud.tablescope;

import javax.servlet.ServletException;
import javax.servlet.annotation.WebServlet;
import javax.servlet.http.HttpServlet;
import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.io.PrintWriter;
import org.teiid.adminapi.Admin;
import org.teiid.adminapi.jboss.AdminFactory;

/**
 * Servlet to invalidate Teiid result set cache when files are uploaded/replaced.
 * This ensures queries always return fresh data after file updates.
 */
@WebServlet("/invalidate-cache")
public class CacheInvalidationServlet extends HttpServlet {
    
    private static final String TEIID_HOST = "localhost";
    private static final int TEIID_PORT = 10000;
    private static final String TEIID_USER = "admin";
    private static final String TEIID_PASSWORD = "admin";
    private static final String VDB_NAME = "MyVDBTest";
    private static final String VDB_VERSION = "1";
    private static final String MODEL_NAME = "ExcelSourceModel";
    
    @Override
    protected void doPost(HttpServletRequest request, HttpServletResponse response) 
            throws ServletException, IOException {
        
        response.setContentType("application/json");
        response.setCharacterEncoding("UTF-8");
        PrintWriter out = response.getWriter();
        
        String tableName = request.getParameter("table_name");
        String action = request.getParameter("action"); // "table" or "all"
        
        try {
            // Connect to Teiid Admin API
            Admin admin = AdminFactory.getInstance().createAdmin(
                TEIID_HOST, TEIID_PORT, TEIID_USER, TEIID_PASSWORD.toCharArray()
            );
            
            if ("all".equals(action)) {
                // Clear all cache for the VDB
                admin.clearCache("QUERY_SERVICE_RESULT_SET_CACHE");
                
                out.write("{\"status\": \"success\", \"message\": \"All cache cleared for VDB: " + VDB_NAME + "\"}");
                System.out.println("[CacheInvalidation] Cleared all cache for VDB: " + VDB_NAME);
                
            } else if (tableName != null && !tableName.isEmpty()) {
                // Clear cache for specific table (clear all for now, Teiid API doesn't support granular clearing)
                admin.clearCache("QUERY_SERVICE_RESULT_SET_CACHE");
                
                out.write("{\"status\": \"success\", \"message\": \"Cache cleared for table: " + tableName + "\"}");
                System.out.println("[CacheInvalidation] Cleared cache for table: " + tableName);
                
            } else {
                response.setStatus(HttpServletResponse.SC_BAD_REQUEST);
                out.write("{\"status\": \"error\", \"message\": \"Missing table_name or action parameter\"}");
                return;
            }
            
            admin.close();
            response.setStatus(HttpServletResponse.SC_OK);
            
        } catch (Exception e) {
            response.setStatus(HttpServletResponse.SC_INTERNAL_SERVER_ERROR);
            out.write("{\"status\": \"error\", \"message\": \"" + e.getMessage() + "\"}");
            System.err.println("[CacheInvalidation] Error: " + e.getMessage());
            e.printStackTrace();
        }
    }
    
    @Override
    protected void doGet(HttpServletRequest request, HttpServletResponse response) 
            throws ServletException, IOException {
        
        response.setContentType("application/json");
        response.setCharacterEncoding("UTF-8");
        PrintWriter out = response.getWriter();
        
        out.write("{\"status\": \"info\", \"message\": \"Cache invalidation endpoint. Use POST with table_name parameter.\"}");
        response.setStatus(HttpServletResponse.SC_OK);
    }
}
