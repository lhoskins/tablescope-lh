package cloud.tablescope;

import java.io.*;
import javax.servlet.ServletException;
import javax.servlet.annotation.WebServlet;
import javax.servlet.http.*;
import org.json.JSONArray;
import org.json.JSONObject;

/**
 * Servlet for handling VDB migration operations.
 * Supports both Excel (FOREIGN TABLE) and CSV/TXT (VIEW) file types.
 *
 * IMPORTANT: This servlet uses text-based XML manipulation to preserve:
 * - CDATA sections in metadata elements
 * - XML comments containing ParentDirectory paths
 * - Original file formatting
 */
@WebServlet("/migrate-vdb")
public class VDBMigrationServlet extends HttpServlet {

    @Override
    protected void doPost(HttpServletRequest request, HttpServletResponse response)
            throws ServletException, IOException {
        response.setHeader("Access-Control-Allow-Origin", "*");
        response.setHeader("Access-Control-Allow-Methods", "POST, OPTIONS");
        response.setHeader("Access-Control-Allow-Headers", "Content-Type");
        response.setContentType("application/json");
        PrintWriter out = response.getWriter();

        try {
            StringBuilder jsonBuffer = new StringBuilder();
            String line;
            BufferedReader reader = request.getReader();
            while ((line = reader.readLine()) != null) {
                jsonBuffer.append(line);
            }
            JSONObject requestJson = new JSONObject(jsonBuffer.toString());
            log("[VDB_MIGRATION] Received request: " + requestJson.toString());

            int orgId = requestJson.getInt("org_id");
            int userId = requestJson.getInt("user_id");
            String migrationType = requestJson.getString("migration_type");
            JSONArray datasources = requestJson.getJSONArray("datasources");

            VDBFileLocator fileLocator = new VDBFileLocator();
            String userVdbPath = fileLocator.findUserVDBPath(orgId, userId);
            String sharedVdbPath = fileLocator.findSharedVDBPath(orgId);

            if (userVdbPath == null) {
                throw new Exception("User VDB not found for org " + orgId + ", user " + userId);
            }
            if (sharedVdbPath == null) {
                throw new Exception("Shared VDB not found for org " + orgId);
            }

            log("[VDB_MIGRATION] User VDB: " + userVdbPath);
            log("[VDB_MIGRATION] Shared VDB: " + sharedVdbPath);

            VDBMigrationOrchestrator.MigrationResult result;
            if ("to_shared".equals(migrationType)) {
                result = VDBMigrationOrchestrator.migrateToSharedVDB(userVdbPath, sharedVdbPath, datasources);
            } else if ("to_private".equals(migrationType)) {
                result = VDBMigrationOrchestrator.migrateToPrivateVDB(userVdbPath, sharedVdbPath, datasources);
            } else {
                throw new Exception("Invalid migration type: " + migrationType);
            }

            TeiidDeployHelper deployHelper = new TeiidDeployHelper();
            deployHelper.deployPreservingOriginal(userVdbPath);
            deployHelper.deployPreservingOriginal(sharedVdbPath);

            JSONObject responseJson = new JSONObject();
            responseJson.put("status", "success");
            responseJson.put("message", "Migrated " + result.tablesMigrated + " tables, " + result.viewsMigrated + " views");
            JSONObject data = new JSONObject();
            data.put("tables_migrated", result.tablesMigrated);
            data.put("views_migrated", result.viewsMigrated);
            data.put("user_vdb_redeployed", true);
            data.put("shared_vdb_redeployed", true);
            responseJson.put("data", data);
            out.println(responseJson.toString());

        } catch (Exception e) {
            log("[VDB_MIGRATION] Error: " + e.getMessage());
            e.printStackTrace();
            JSONObject errorJson = new JSONObject();
            errorJson.put("status", "error");
            errorJson.put("message", "Migration failed: " + e.getMessage());
            response.setStatus(HttpServletResponse.SC_INTERNAL_SERVER_ERROR);
            out.println(errorJson.toString());
        }
    }
}
