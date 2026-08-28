// VDBManagementServlet.java
package cloud.tablescope;

import java.io.*;
import java.nio.file.*;
import java.util.*;
import java.util.regex.*;
import javax.servlet.ServletException;
import javax.servlet.annotation.WebServlet;
import javax.servlet.http.*;
import org.json.JSONObject;
import org.json.JSONArray;
import org.teiid.adminapi.Admin;
import org.teiid.adminapi.jboss.AdminFactory;

/**
 * VDB Management Servlet for Redash Multi-Tenancy
 *
 * Provides REST API endpoints for managing VDB lifecycle:
 * - Create VDB from template
 * - Delete VDB
 * - Update VDB credentials
 *
 * Security:
 * - API key authentication (X-API-Key header)
 * - Credentials passed via HTTPS POST body
 * - Admin credentials for Teiid management
 *
 * Concurrency:
 * - Uses VDB-level locking to prevent race conditions with TeiidExcelImporterTest
 * - Ensures VDB modifications are atomic
 */
@WebServlet("/vdb-management/*")
public class VDBManagementServlet extends HttpServlet {


    // Teiid Admin credentials (for servlet to manage Teiid)
    // Note: Host and port are now passed via API request, not stored as instance variables
    private String teiidAdminUser;
    private String teiidAdminPassword;

    // Servlet API key (for Redash to authenticate to servlet)
    private String servletApiKey;

    // VDB files base path
    private String vdbBasePath;

    private VDBFileLocator vdbFileLocator;
    private TeiidDeployHelper teiidDeployHelper;

    @Override
    public void init() throws ServletException {
        super.init();

        // Load Teiid Admin credentials from environment (sensitive data only)
        teiidAdminUser = getEnvOrDefault("TEIID_ADMIN_USER", "admin");
        teiidAdminPassword = getEnvOrDefault("TEIID_ADMIN_PASSWORD", "admin");

        // NOTE: teiidAdminHost and teiidAdminPort are now passed via API request from Redash
        // This allows dynamic configuration through the Redash Teiid Config UI
        // No hardcoded defaults - configuration must come from Redash database

        // Load servlet API key
        servletApiKey = getEnvOrDefault("TEIID_SERVLET_API_KEY", "");

        // VDB files base path
        vdbBasePath = getEnvOrDefault("VDB_BASE_PATH", "/opt/wildfly/teiidfiles");

        vdbFileLocator = new VDBFileLocator(vdbBasePath);
        teiidDeployHelper = new TeiidDeployHelper(teiidAdminUser, teiidAdminPassword);

        log("VDBManagementServlet initialized");
        log("Teiid connection info will be provided via API requests from Redash");
        log("VDB Base Path: " + vdbBasePath);
    }

    /**
     * Handle CORS preflight requests
     */
    @Override
    protected void doOptions(HttpServletRequest request, HttpServletResponse response)
            throws ServletException, IOException {
        setCorsHeaders(response);
        response.setStatus(HttpServletResponse.SC_OK);
    }

    /**
     * Main POST handler - routes to specific actions
     */
    @Override
    protected void doPost(HttpServletRequest request, HttpServletResponse response)
            throws ServletException, IOException {

        setCorsHeaders(response);
        response.setContentType("application/json");
        PrintWriter out = response.getWriter();

        // 1. Authenticate the request (Redash -> Servlet)
        if (!authenticateRequest(request)) {
            response.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
            out.println(createErrorResponse("Invalid or missing API key"));
            return;
        }

        // 2. Route to appropriate action based on path
        String pathInfo = request.getPathInfo();

        try {
            if (pathInfo == null || pathInfo.equals("/")) {
                out.println(createErrorResponse("No action specified"));
                response.setStatus(HttpServletResponse.SC_BAD_REQUEST);
            } else if (pathInfo.equals("/createVDB")) {
                createVDB(request, response, out);
            } else if (pathInfo.equals("/deleteVDB")) {
                deleteVDB(request, response, out);
            } else if (pathInfo.equals("/updateVDBCredentials")) {
                updateVDBCredentials(request, response, out);
            } else if (pathInfo.equals("/checkVDBStatus")) {
                checkVDBStatus(request, response, out);
            } else if (pathInfo.equals("/redeployVDB")) {
                redeployVDB(request, response, out);
            } else if (pathInfo.equals("/createDatabaseSource")) {
                createDatabaseSource(request, response, out);
            } else {
                out.println(createErrorResponse("Unknown action: " + pathInfo));
                response.setStatus(HttpServletResponse.SC_NOT_FOUND);
            }
        } catch (Exception e) {
            log("Error processing request: " + e.getMessage(), e);
            response.setStatus(HttpServletResponse.SC_INTERNAL_SERVER_ERROR);
            out.println(createErrorResponse("Internal server error: " + e.getMessage()));
        }
    }

    /**
     * Create a new VDB from template or redeploy existing VDB
     */
    private void createVDB(HttpServletRequest request, HttpServletResponse response, PrintWriter out)
            throws IOException {

        // Parse request body
        JSONObject requestBody = parseRequestBody(request);

        // Validate required fields
        if (!requestBody.has("org_id") || !requestBody.has("vdb_id") ||
            !requestBody.has("username") || !requestBody.has("password") ||
            !requestBody.has("teiid_host") || !requestBody.has("teiid_port")) {
            response.setStatus(HttpServletResponse.SC_BAD_REQUEST);
            out.println(createErrorResponse("Missing required fields: org_id, vdb_id, username, password, teiid_host, teiid_port"));
            return;
        }

        int orgId = requestBody.getInt("org_id");
        String vdbId = requestBody.getString("vdb_id");  // 7-digit number
        String vdbUsername = requestBody.getString("username");
        String vdbPassword = requestBody.getString("password");

        // Read VDB type (optional, defaults to org-level for backward compatibility)
        String vdbType = requestBody.optString("vdb_type", "org");
        Integer userId = requestBody.has("user_id") ? requestBody.getInt("user_id") : null;

        // Validate vdb_type and user_id combination
        if ("user".equals(vdbType) && userId == null) {
            response.setStatus(HttpServletResponse.SC_BAD_REQUEST);
            out.println(createErrorResponse("user_id is required when vdb_type is 'user'"));
            return;
        }

        // Read Teiid connection info from request (from Redash database)
        String teiidHost = requestBody.getString("teiid_host");
        int teiidPort;
        try {
            teiidPort = requestBody.getInt("teiid_port");
        } catch (Exception e) {
            response.setStatus(HttpServletResponse.SC_BAD_REQUEST);
            out.println(createErrorResponse("Invalid teiid_port value. Must be a valid port number."));
            return;
        }

        log("Processing VDB request for org_id: " + orgId + ", vdb_id: " + vdbId + ", vdb_type: " + vdbType);
        if (userId != null) {
            log("User ID: " + userId);
        }
        log("Teiid connection: " + teiidHost + ":" + teiidPort);

        try {
            // 1. Define paths based on VDB type
            String customerFolder;
            String vdbFolder;
            String uploadsFolder;

            if ("user".equals(vdbType)) {
                // User VDB: /Customer/{org_id}/{user_id}/vdb/
                customerFolder = vdbBasePath + "/customers/" + orgId + "/" + userId;
                vdbFolder = customerFolder + "/vdb";
                uploadsFolder = customerFolder + "/uploads";
                log("Using user VDB path for user " + userId);
            } else if ("shared".equals(vdbType)) {
                // Shared VDB: /Customer/{org_id}/shared/vdb/
                customerFolder = vdbBasePath + "/customers/" + orgId + "/shared";
                vdbFolder = customerFolder + "/vdb";
                uploadsFolder = customerFolder + "/uploads";
                log("Using shared VDB path for organization " + orgId);
            } else {
                // Legacy org-level VDB: /Customer/{org_id}/vdb/
                customerFolder = vdbBasePath + "/customers/" + orgId;
                vdbFolder = customerFolder + "/vdb";
                uploadsFolder = customerFolder + "/uploads";
                log("Using organization-level VDB path (legacy mode)");
            }

            String vdbFilePath = vdbFolder + "/" + vdbId + "-vdb.xml";
            String templatePath = vdbBasePath + "/vdb_template/vdb_ template.xml";

            // 2. Check if VDB already exists
            File vdbFile = new File(vdbFilePath);
            File customerDir = new File(customerFolder);
            File vdbDir = new File(vdbFolder);

            // Check for any existing VDB file in VDB folder
            File existingVdb = null;
            if (vdbDir.exists()) {
                File[] vdbFiles = vdbDir.listFiles(new FilenameFilter() {
                    public boolean accept(File dir, String name) {
                        return name.endsWith("-vdb.xml");
                    }
                });
                if (vdbFiles != null && vdbFiles.length > 0) {
                    existingVdb = vdbFiles[0];  // Use first VDB found
                    log("Found existing VDB file: " + existingVdb.getName());
                }
            }

            // 3. If VDB exists, redeploy it
            if (existingVdb != null) {
                log("Existing VDB found: " + existingVdb.getAbsolutePath());

                // Extract VDB ID from filename
                String existingVdbId = existingVdb.getName().replace("-vdb.xml", "");

                // Check if the existing VDB ID matches the requested VDB ID
                if (!existingVdbId.equals(vdbId)) {
                    log("VDB ID mismatch: requested=" + vdbId + ", existing=" + existingVdbId);
                    log("Renaming VDB to match requested ID");

                    // Read existing VDB content
                    String vdbContent;
                    try {
                        vdbContent = vdbFileLocator.readFile(existingVdb.getAbsolutePath());
                    } catch (IOException e) {
                        log("ERROR: Failed to read existing VDB file: " + e.getMessage());
                        response.setStatus(HttpServletResponse.SC_INTERNAL_SERVER_ERROR);
                        out.println(createErrorResponse("Failed to read existing VDB file"));
                        return;
                    }

                    // Update VDB name in content to match requested ID
                    vdbContent = vdbContent.replaceAll("name=\"" + existingVdbId + "\"", "name=\"" + vdbId + "\"");

                    // Write to new file with requested VDB ID
                    String newVdbFilePath = vdbFolder + "/" + vdbId + "-vdb.xml";
                    try {
                        vdbFileLocator.writeFile(newVdbFilePath, vdbContent);
                    } catch (IOException e) {
                        log("ERROR: Failed to write VDB file with new ID: " + e.getMessage());
                        response.setStatus(HttpServletResponse.SC_INTERNAL_SERVER_ERROR);
                        out.println(createErrorResponse("Failed to write VDB file with new ID"));
                        return;
                    }

                    // Delete old VDB file
                    if (!existingVdb.delete()) {
                        log("WARNING: Failed to delete old VDB file: " + existingVdb.getAbsolutePath());
                    }

                    // Update references for deployment
                    existingVdbId = vdbId;
                    existingVdb = new File(newVdbFilePath);
                    log("VDB renamed successfully from " + existingVdbId + " to " + vdbId);
                }

                log("Redeploying existing VDB");

                // Acquire lock for this VDB to prevent race conditions with TeiidExcelImporterTest
                if (!VDBLockManager.acquireLock(existingVdb.getAbsolutePath())) {
                    log("Failed to acquire VDB lock for redeployment: " + existingVdb.getAbsolutePath());
                    response.setStatus(HttpServletResponse.SC_SERVICE_UNAVAILABLE);
                    out.println(createErrorResponse("VDB is currently being modified. Please try again."));
                    return;
                }
                try {
                    teiidDeployHelper.redeployVDB(existingVdb.getAbsolutePath(), existingVdbId + "-vdb.xml", teiidHost, teiidPort);
                } finally {
                    VDBLockManager.releaseLock(existingVdb.getAbsolutePath());
                }

                // Return success response
                response.setStatus(HttpServletResponse.SC_OK);
                JSONObject successResponse = new JSONObject();
                successResponse.put("success", true);
                successResponse.put("vdb_id", existingVdbId);
                successResponse.put("vdb_type", vdbType);
                successResponse.put("action", "redeployed");
                successResponse.put("status", "redeployed");
                successResponse.put("message", "Existing VDB redeployed successfully");
                out.println(successResponse.toString());
                return;
            }

            // 4. No existing VDB - create new one from template
            log("No existing VDB found, creating new VDB from template");

            // Create customer folder if it doesn't exist
            if (!customerDir.exists()) {
                if (!vdbFileLocator.createFolderIfNotExists(customerFolder)) {
                    response.setStatus(HttpServletResponse.SC_INTERNAL_SERVER_ERROR);
                    out.println(createErrorResponse("Failed to create customer folder: " + customerFolder));
                    return;
                }
                log("Created customer folder: " + customerFolder);
                vdbFileLocator.setFolderPermissions(customerFolder);
            }

            // Create vdb folder if it doesn't exist
            if (!vdbDir.exists()) {
                if (!vdbFileLocator.createFolderIfNotExists(vdbFolder)) {
                    response.setStatus(HttpServletResponse.SC_INTERNAL_SERVER_ERROR);
                    out.println(createErrorResponse("Failed to create vdb folder: " + vdbFolder));
                    return;
                }
                log("Created vdb folder: " + vdbFolder);
                vdbFileLocator.setFolderPermissions(vdbFolder);
            }

            // Create uploads folder if it doesn't exist
            File uploadsDir = new File(uploadsFolder);
            if (!uploadsDir.exists()) {
                if (!vdbFileLocator.createFolderIfNotExists(uploadsFolder)) {
                    response.setStatus(HttpServletResponse.SC_INTERNAL_SERVER_ERROR);
                    out.println(createErrorResponse("Failed to create uploads folder: " + uploadsFolder));
                    return;
                }
                log("Created uploads folder: " + uploadsFolder);
                vdbFileLocator.setFolderPermissions(uploadsFolder);
            }

            // 5. Read template VDB XML from hardcoded path
            if (!new File(templatePath).exists()) {
                response.setStatus(HttpServletResponse.SC_NOT_FOUND);
                out.println(createErrorResponse("Template VDB not found at: " + templatePath));
                return;
            }

            String vdbXml = vdbFileLocator.readFile(templatePath);
            log("Template VDB loaded from: " + templatePath);

            // 6. Replace VDB name with 7-digit ID (only the <vdb> element, not model names)
            vdbXml = vdbXml.replaceFirst("<vdb\\s+name=\"[^\"]+\"", "<vdb name=\"" + vdbId + "\"");
            log("VDB name replaced with: " + vdbId);

            // Also update any hardcoded VDB name references in the virtual model views
            vdbXml = vdbXml.replaceAll("'MyVDBTest'", "'" + vdbId + "'");
            vdbXml = vdbXml.replaceAll("'vdb_production'", "'" + vdbId + "'");
            log("VDB name references updated in views");

            // 7. Update file paths to use customer uploads folder
            vdbXml = VDBXmlBuilder.updateFilePaths(vdbXml, uploadsFolder);

            // 8. Configure VDB credentials (if needed by your Teiid setup)
            vdbXml = VDBXmlBuilder.configureVDBCredentials(vdbXml, vdbUsername, vdbPassword);

            // 9. Write new VDB file to customer folder
            if (!VDBLockManager.acquireLock(vdbFilePath)) {
                log("Failed to acquire VDB lock for creation: " + vdbFilePath);
                response.setStatus(HttpServletResponse.SC_SERVICE_UNAVAILABLE);
                out.println(createErrorResponse("VDB is currently being modified. Please try again."));
                return;
            }
            try {
                log("ATTEMPTING TO WRITE VDB FILE TO: " + vdbFilePath);
                log("VDB XML length: " + vdbXml.length() + " characters");

                try {
                    vdbFileLocator.writeFile(vdbFilePath, vdbXml);
                    log("SUCCESS: VDB file written to: " + vdbFilePath);

                    // Verify the file was actually created
                    vdbFile = new File(vdbFilePath);
                    if (vdbFile.exists()) {
                        log("VERIFIED: File exists at " + vdbFilePath + " with size " + vdbFile.length() + " bytes");
                    } else {
                        log("ERROR: File does not exist after write attempt!");
                        response.setStatus(HttpServletResponse.SC_INTERNAL_SERVER_ERROR);
                        out.println(createErrorResponse("VDB file was not created at: " + vdbFilePath));
                        return;
                    }
                } catch (Exception e) {
                    log("ERROR writing VDB file: " + e.getMessage());
                    e.printStackTrace();
                    response.setStatus(HttpServletResponse.SC_INTERNAL_SERVER_ERROR);
                    out.println(createErrorResponse("Failed to write VDB file: " + e.getMessage()));
                    return;
                }

                // DEBUG: Log the VDB XML content to help diagnose duplicate model name issues
                log("=== VDB XML Content (first 2000 chars) ===");
                log(vdbXml.substring(0, Math.min(2000, vdbXml.length())));
                log("=== End VDB XML Content ===");

                // 10. Deploy to Teiid using Admin API
                log("Deploying VDB to Teiid...");
                teiidDeployHelper.deployVDB(vdbFilePath, vdbId + "-vdb.xml", teiidHost, teiidPort);
            } finally {
                VDBLockManager.releaseLock(vdbFilePath);
            }

            // 11. Return success response
            response.setStatus(HttpServletResponse.SC_OK);
            JSONObject successResponse = new JSONObject();
            successResponse.put("success", true);
            successResponse.put("vdb_id", vdbId);
            successResponse.put("vdb_type", vdbType);
            successResponse.put("action", "created");
            successResponse.put("status", "success");
            successResponse.put("message", "VDB created and deployed successfully");
            out.println(successResponse.toString());

            log("VDB created successfully: " + vdbId + " (type: " + vdbType + ")");

        } catch (Exception e) {
            log("Failed to create/redeploy VDB: " + e.getMessage(), e);
            response.setStatus(HttpServletResponse.SC_INTERNAL_SERVER_ERROR);
            out.println(createErrorResponse("Failed to create/redeploy VDB: " + e.getMessage()));
        }
    }

    /**
     * Delete a VDB (archives the file instead of deleting)
     */
    private void deleteVDB(HttpServletRequest request, HttpServletResponse response, PrintWriter out)
            throws IOException {

        JSONObject requestBody = parseRequestBody(request);

        if (!requestBody.has("org_id") || !requestBody.has("vdb_id") ||
            !requestBody.has("teiid_host") || !requestBody.has("teiid_port")) {
            response.setStatus(HttpServletResponse.SC_BAD_REQUEST);
            out.println(createErrorResponse("Missing required fields: org_id, vdb_id, teiid_host, teiid_port"));
            return;
        }

        int orgId = requestBody.getInt("org_id");
        String vdbId = requestBody.getString("vdb_id");
        String teiidHost = requestBody.getString("teiid_host");
        int teiidPort;
        try {
            teiidPort = requestBody.getInt("teiid_port");
        } catch (Exception e) {
            response.setStatus(HttpServletResponse.SC_BAD_REQUEST);
            out.println(createErrorResponse("Invalid teiid_port value"));
            return;
        }

        // Read VDB type (optional, defaults to org-level for backward compatibility)
        String vdbType = requestBody.optString("vdb_type", "org");
        Integer userId = requestBody.has("user_id") ? requestBody.getInt("user_id") : null;

        // Validate vdb_type and user_id combination
        if ("user".equals(vdbType) && userId == null) {
            response.setStatus(HttpServletResponse.SC_BAD_REQUEST);
            out.println(createErrorResponse("user_id is required when vdb_type is 'user'"));
            return;
        }

        log("Deleting VDB: " + vdbId + " for org_id: " + orgId + ", vdb_type: " + vdbType);
        if (userId != null) {
            log("User ID: " + userId);
        }
        log("Teiid connection: " + teiidHost + ":" + teiidPort);

        try {
            // 1. Define paths based on VDB type
            String customerFolder;
            String vdbFolder;

            if ("user".equals(vdbType)) {
                customerFolder = vdbBasePath + "/customers/" + orgId + "/" + userId;
                vdbFolder = customerFolder + "/vdb";
                log("Using user VDB path for user " + userId);
            } else if ("shared".equals(vdbType)) {
                customerFolder = vdbBasePath + "/customers/" + orgId + "/shared";
                vdbFolder = customerFolder + "/vdb";
                log("Using shared VDB path for organization " + orgId);
            } else {
                customerFolder = vdbBasePath + "/customers/" + orgId;
                vdbFolder = customerFolder + "/vdb";
                log("Using organization-level VDB path (legacy mode)");
            }

            String vdbFilePath = vdbFolder + "/" + vdbId + "-vdb.xml";
            String archiveFolder = vdbFolder + "/archive";
            String archivePath = archiveFolder + "/" + vdbId + "-vdb.xml";

            // 2. Connect to Teiid Admin API (uses Teiid Admin credentials)
            Admin admin = AdminFactory.getInstance().createAdmin(
                teiidHost,
                teiidPort,
                teiidAdminUser,
                teiidAdminPassword.toCharArray()
            );

            // 3. Undeploy VDB
            try {
                admin.undeploy(vdbId + "-vdb.xml");
                log("VDB undeployed from Teiid: " + vdbId);
            } catch (Exception e) {
                log("Warning: Failed to undeploy VDB (may not exist): " + e.getMessage());
            } finally {
                admin.close();
            }

            // 4. Create archive folder if it doesn't exist
            File archiveDir = new File(archiveFolder);
            if (!archiveDir.exists()) {
                if (!archiveDir.mkdirs()) {
                    log("Warning: Failed to create archive folder: " + archiveFolder);
                } else {
                    log("Created archive folder: " + archiveFolder);
                }
            }

            // 5. Move VDB file to archive (don't delete)
            File vdbFile = new File(vdbFilePath);
            boolean archived = false;
            String archivedTo = null;

            if (vdbFile.exists()) {
                File archiveFile = new File(archivePath);

                // If archive file already exists, add timestamp to make it unique
                if (archiveFile.exists()) {
                    String timestamp = String.valueOf(System.currentTimeMillis());
                    archivePath = archiveFolder + "/" + vdbId + "_" + timestamp + "-vdb.xml";
                    archiveFile = new File(archivePath);
                    log("Archive file exists, using timestamped name: " + archivePath);
                }

                // Move file to archive
                archived = vdbFile.renameTo(archiveFile);
                if (archived) {
                    archivedTo = archivePath;
                    log("VDB file archived to: " + archivePath);
                } else {
                    log("Warning: Failed to archive VDB file from " + vdbFilePath + " to " + archivePath);
                }
            } else {
                log("Warning: VDB file not found at: " + vdbFilePath);
            }

            // 6. Return success response
            response.setStatus(HttpServletResponse.SC_OK);
            JSONObject successResponse = new JSONObject();
            successResponse.put("success", true);
            successResponse.put("vdb_id", vdbId);
            successResponse.put("vdb_type", vdbType);
            successResponse.put("archived", archived);
            if (archivedTo != null) {
                successResponse.put("archived_to", archivedTo);
            }
            successResponse.put("message", archived ?
                "VDB deleted and archived successfully" :
                "VDB undeployed (file not found or could not be archived)");
            out.println(successResponse.toString());

            log("VDB deletion completed: " + vdbId + " (type: " + vdbType + ")");

        } catch (Exception e) {
            log("Failed to delete VDB: " + e.getMessage(), e);
            response.setStatus(HttpServletResponse.SC_INTERNAL_SERVER_ERROR);
            out.println(createErrorResponse("Failed to delete VDB: " + e.getMessage()));
        }
    }

    /**
     * Update VDB credentials (credential rotation)
     */
    private void updateVDBCredentials(HttpServletRequest request, HttpServletResponse response, PrintWriter out)
            throws IOException {

        JSONObject requestBody = parseRequestBody(request);

        if (!requestBody.has("vdb_id") || !requestBody.has("username") || !requestBody.has("password") ||
            !requestBody.has("teiid_host") || !requestBody.has("teiid_port")) {
            response.setStatus(HttpServletResponse.SC_BAD_REQUEST);
            out.println(createErrorResponse("Missing required fields: vdb_id, username, password, teiid_host, teiid_port"));
            return;
        }

        String vdbId = requestBody.getString("vdb_id");
        String newUsername = requestBody.getString("username");
        String newPassword = requestBody.getString("password");
        String teiidHost = requestBody.getString("teiid_host");
        int teiidPort;
        try {
            teiidPort = requestBody.getInt("teiid_port");
        } catch (Exception e) {
            response.setStatus(HttpServletResponse.SC_BAD_REQUEST);
            out.println(createErrorResponse("Invalid teiid_port value"));
            return;
        }

        log("Updating credentials for VDB: " + vdbId);
        log("Teiid connection: " + teiidHost + ":" + teiidPort);

        try {
            // 1. Find existing VDB file
            String vdbPath = vdbFileLocator.findVDBFile(vdbId);
            if (vdbPath == null) {
                response.setStatus(HttpServletResponse.SC_NOT_FOUND);
                out.println(createErrorResponse("VDB file not found: " + vdbId));
                return;
            }

            // 2. Read existing VDB configuration
            String vdbXml = vdbFileLocator.readFile(vdbPath);

            // 3. Update VDB user credentials in VDB XML
            vdbXml = VDBXmlBuilder.configureVDBCredentials(vdbXml, newUsername, newPassword);

            // 4. Write updated VDB file
            vdbFileLocator.writeFile(vdbPath, vdbXml);

            log("VDB file updated with new credentials: " + vdbPath);

            // 5. Redeploy VDB using Teiid Admin credentials
            teiidDeployHelper.redeployVDB(vdbPath, vdbId + "-vdb.xml", teiidHost, teiidPort);

            // 6. Return success response
            response.setStatus(HttpServletResponse.SC_OK);
            JSONObject successResponse = new JSONObject();
            successResponse.put("success", true);
            successResponse.put("vdb_id", vdbId);
            successResponse.put("message", "VDB credentials updated successfully");
            out.println(successResponse.toString());

            log("VDB credentials updated successfully: " + vdbId);

        } catch (Exception e) {
            log("Failed to update VDB credentials: " + e.getMessage(), e);
            response.setStatus(HttpServletResponse.SC_INTERNAL_SERVER_ERROR);
            out.println(createErrorResponse("Failed to update VDB credentials: " + e.getMessage()));
        }
    }

    /**
     * Redeploy an existing VDB to Teiid
     */
    private void redeployVDB(HttpServletRequest request, HttpServletResponse response, PrintWriter out)
            throws IOException {

        JSONObject requestBody = parseRequestBody(request);

        if (!requestBody.has("vdb_id") || !requestBody.has("teiid_host") || !requestBody.has("teiid_port")) {
            response.setStatus(HttpServletResponse.SC_BAD_REQUEST);
            out.println(createErrorResponse("Missing required fields: vdb_id, teiid_host, teiid_port"));
            return;
        }

        String vdbId = requestBody.getString("vdb_id");
        String vdbFilePath = requestBody.optString("vdb_file_path", null);
        String teiidHost = requestBody.getString("teiid_host");
        int teiidPort;
        try {
            teiidPort = requestBody.getInt("teiid_port");
        } catch (Exception e) {
            response.setStatus(HttpServletResponse.SC_BAD_REQUEST);
            out.println(createErrorResponse("Invalid teiid_port value"));
            return;
        }

        log("Redeploying VDB: " + vdbId);
        log("Teiid connection: " + teiidHost + ":" + teiidPort);

        try {
            // 1. Find VDB file if path not provided
            if (vdbFilePath == null || vdbFilePath.isEmpty()) {
                vdbFilePath = vdbFileLocator.findVDBFile(vdbId);
                if (vdbFilePath == null) {
                    response.setStatus(HttpServletResponse.SC_NOT_FOUND);
                    out.println(createErrorResponse("VDB file not found: " + vdbId));
                    return;
                }
            }

            log("VDB file path: " + vdbFilePath);

            // 2. Verify VDB file exists
            if (!new File(vdbFilePath).exists()) {
                response.setStatus(HttpServletResponse.SC_NOT_FOUND);
                out.println(createErrorResponse("VDB file not found at: " + vdbFilePath));
                return;
            }

            // 3. Redeploy VDB
            teiidDeployHelper.redeployVDB(vdbFilePath, vdbId + "-vdb.xml", teiidHost, teiidPort);

            // 4. Return success response
            response.setStatus(HttpServletResponse.SC_OK);
            JSONObject successResponse = new JSONObject();
            successResponse.put("success", true);
            successResponse.put("vdb_id", vdbId);
            successResponse.put("vdb_file_path", vdbFilePath);
            successResponse.put("message", "VDB redeployed successfully");
            out.println(successResponse.toString());

            log("VDB redeploy completed: " + vdbId);

        } catch (Exception e) {
            log("Failed to redeploy VDB: " + e.getMessage(), e);
            response.setStatus(HttpServletResponse.SC_INTERNAL_SERVER_ERROR);
            out.println(createErrorResponse("Failed to redeploy VDB: " + e.getMessage()));
        }
    }

    /**
     * Check VDB deployment status on WildFly/Teiid server
     */
    private void checkVDBStatus(HttpServletRequest request, HttpServletResponse response, PrintWriter out)
            throws IOException {

        JSONObject requestBody = parseRequestBody(request);

        if (!requestBody.has("vdb_id") || !requestBody.has("teiid_host") || !requestBody.has("teiid_port")) {
            response.setStatus(HttpServletResponse.SC_BAD_REQUEST);
            out.println(createErrorResponse("Missing required fields: vdb_id, teiid_host, teiid_port"));
            return;
        }

        String vdbId = requestBody.getString("vdb_id");
        String teiidHost = requestBody.getString("teiid_host");
        int teiidPort;
        try {
            teiidPort = requestBody.getInt("teiid_port");
        } catch (Exception e) {
            response.setStatus(HttpServletResponse.SC_BAD_REQUEST);
            out.println(createErrorResponse("Invalid teiid_port value"));
            return;
        }

        log("Checking VDB status: " + vdbId);
        log("Teiid connection: " + teiidHost + ":" + teiidPort);

        long startTime = System.currentTimeMillis();

        try {
            // Connect to Teiid Admin API
            Admin admin = AdminFactory.getInstance().createAdmin(
                teiidHost,
                teiidPort,
                teiidAdminUser,
                teiidAdminPassword.toCharArray()
            );

            try {
                // Get VDB from Teiid
                org.teiid.adminapi.VDB vdb = admin.getVDB(vdbId, "1");

                long responseTime = System.currentTimeMillis() - startTime;

                if (vdb == null) {
                    response.setStatus(HttpServletResponse.SC_OK);
                    JSONObject statusResponse = new JSONObject();
                    statusResponse.put("success", true);
                    statusResponse.put("vdb_id", vdbId);
                    statusResponse.put("status", "NOT_FOUND");
                    statusResponse.put("response_time", responseTime);
                    statusResponse.put("message", "VDB not deployed on Teiid server");
                    out.println(statusResponse.toString());
                    return;
                }

                String status = vdb.getStatus().toString();

                response.setStatus(HttpServletResponse.SC_OK);
                JSONObject statusResponse = new JSONObject();
                statusResponse.put("success", true);
                statusResponse.put("vdb_id", vdbId);
                statusResponse.put("status", status);
                statusResponse.put("version", vdb.getVersion());
                statusResponse.put("response_time", responseTime);
                statusResponse.put("description", vdb.getDescription());

                List<String> models = new ArrayList<>();
                for (org.teiid.adminapi.Model model : vdb.getModels()) {
                    models.add(model.getName());
                }
                statusResponse.put("models", models);

                out.println(statusResponse.toString());

                log("VDB status checked successfully: " + vdbId + " - " + status + " (" + responseTime + "ms)");

            } finally {
                admin.close();
            }

        } catch (Exception e) {
            long responseTime = System.currentTimeMillis() - startTime;
            log("Failed to check VDB status: " + e.getMessage(), e);
            response.setStatus(HttpServletResponse.SC_OK);
            JSONObject errorResponse = new JSONObject();
            errorResponse.put("success", false);
            errorResponse.put("vdb_id", vdbId);
            errorResponse.put("status", "ERROR");
            errorResponse.put("response_time", responseTime);
            errorResponse.put("error", e.getMessage());
            out.println(errorResponse.toString());
        }
    }

    /**
     * Register an external database table as a queryable data source inside an
     * existing user VDB.
     */
    private void createDatabaseSource(HttpServletRequest request, HttpServletResponse response, PrintWriter out)
            throws IOException {

        JSONObject body = parseRequestBody(request);

        String[] required = {"vdb_id", "org_id", "db_type", "translator", "jdbc_url",
                "username", "model_name", "teiid_table_name",
                "jndi_name", "ds_name", "view_name", "table_name"};
        for (String key : required) {
            if (!body.has(key)) {
                response.setStatus(HttpServletResponse.SC_BAD_REQUEST);
                out.println(createErrorResponse("Missing required field: " + key));
                return;
            }
        }

        String vdbId = body.getString("vdb_id");
        int orgId = body.getInt("org_id");
        Integer userId = body.has("user_id") && !body.isNull("user_id") ? body.getInt("user_id") : null;
        String dbType = body.getString("db_type");
        String translator = body.getString("translator");
        String jdbcUrl = body.getString("jdbc_url");
        String username = body.getString("username");
        String password = body.optString("password", "");
        String modelName = body.getString("model_name");
        String teiidTableName = body.getString("teiid_table_name");
        String jndiName = body.getString("jndi_name");
        String dsName = body.getString("ds_name");
        String viewName = body.getString("view_name");
        String tableName = body.getString("table_name");
        String schemaName = body.optString("schema_name", "");
        JSONArray columns = body.optJSONArray("columns");

        boolean isServiceNow = "servicenow".equalsIgnoreCase(translator);
        boolean isSalesforce = WildFlyCliHelper.isSalesforceTranslator(translator);
        boolean isCustomTranslator = "hubspot".equalsIgnoreCase(translator) || "quickbooks".equalsIgnoreCase(translator);
        boolean isGoogleSpreadsheet = "google-spreadsheet".equalsIgnoreCase(translator);
        boolean force = body.optBoolean("force", false);
        String instanceUrl = body.optString("instance_url", isServiceNow || isSalesforce || isCustomTranslator ? jdbcUrl : "");
        if (isSalesforce) {
            instanceUrl = WildFlyCliHelper.normalizeSalesforceSoapUrl(instanceUrl);
        }
        String realmId = body.optString("realm_id", "");
        String environment = body.optString("environment", "production");
        String spreadsheetId = body.optString("spreadsheet_id", "");
        String clientId = body.optString("client_id", "");
        String clientSecret = body.optString("client_secret", "");

        String teiidHost = body.optString("teiid_host", "localhost");
        int teiidPort = body.has("teiid_port") ? body.getInt("teiid_port") : 9990;

        log("createDatabaseSource: vdb_id=" + vdbId + ", org_id=" + orgId
                + ", user_id=" + userId + ", db_type=" + dbType
                + ", model=" + modelName + ", view=" + viewName + ", table=" + tableName);

        // 1. Locate the VDB XML file.
        String vdbFilePath = null;
        if (userId != null) {
            String candidate = vdbBasePath + "/customers/" + orgId + "/" + userId
                    + "/vdb/" + vdbId + "-vdb.xml";
            if (new File(candidate).exists()) {
                vdbFilePath = candidate;
            }
        }
        if (vdbFilePath == null) {
            String shared = vdbBasePath + "/customers/" + orgId + "/shared/vdb/" + vdbId + "-vdb.xml";
            if (new File(shared).exists()) {
                vdbFilePath = shared;
            }
        }
        if (vdbFilePath == null) {
            vdbFilePath = vdbFileLocator.findVDBFile(vdbId);
        }
        if (vdbFilePath == null || !new File(vdbFilePath).exists()) {
            response.setStatus(HttpServletResponse.SC_NOT_FOUND);
            out.println(createErrorResponse("VDB file not found for vdb_id: " + vdbId));
            return;
        }

        if (!VDBLockManager.acquireLock(vdbFilePath)) {
            response.setStatus(HttpServletResponse.SC_CONFLICT);
            out.println(createErrorResponse("VDB is currently being modified. Please try again."));
            return;
        }

        try {
            // 2. Ensure the WildFly JDBC datasource or JCA connection factory exists.
            if (isGoogleSpreadsheet) {
                WildFlyCliHelper.ensureGoogleSpreadsheetConnectionFactory(dsName, spreadsheetId, password, clientId, clientSecret, "");
            } else if (isSalesforce) {
                WildFlyCliHelper.ensureSalesforceConnectionFactory(dsName, translator, instanceUrl, username, password);
            } else if (!isServiceNow && !isCustomTranslator) {
                WildFlyCliHelper.ensureDataSource(dsName, dbType, jdbcUrl, username, password);
            }

            // 3. Edit the VDB XML: add the physical model + the view.
            String vdbXml = vdbFileLocator.readFile(vdbFilePath);

            boolean modelExists = vdbXml.contains("<model name=\"" + modelName + "\"");
            if (modelExists && force) {
                log("Force mode: removing existing model/translator/view for " + modelName);
                vdbXml = VDBXmlBuilder.removeModelBlock(vdbXml, modelName);
                if (isServiceNow || isCustomTranslator) {
                    vdbXml = VDBXmlBuilder.removeTranslatorBlock(vdbXml, dsName + "_" + translator);
                }
                modelExists = false;
            }

            if (modelExists) {
                log("Model " + modelName + " already present in VDB; skipping model insert.");
            } else {
                String modelBlock;
                if (isServiceNow) {
                    String translatorDefName = dsName + "_servicenow";
                    modelBlock = VDBXmlBuilder.buildServiceNowModelBlock(
                            modelName, dsName, translatorDefName,
                            teiidTableName, tableName, columns);
                } else if (isCustomTranslator) {
                    String translatorDefName = dsName + "_" + translator;
                    modelBlock = VDBXmlBuilder.buildCustomHttpModelBlock(
                            modelName, dsName, translatorDefName,
                            teiidTableName, tableName, columns);
                } else if (isSalesforce || isGoogleSpreadsheet) {
                    modelBlock = VDBXmlBuilder.buildSalesforceModelBlock(
                            modelName, dsName, translator, jndiName,
                            teiidTableName, tableName, columns);
                } else {
                    modelBlock = VDBXmlBuilder.buildPhysicalModelBlock(
                            modelName, dsName, translator, jndiName,
                            teiidTableName, schemaName, tableName, columns);
                }
                // VDB schema requires all <model> elements before any <translator>.
                vdbXml = VDBXmlBuilder.insertBeforeFirst(vdbXml, modelBlock, "</vdb>", "  <translator name=\"");
                if (isServiceNow) {
                    String translatorDefName = dsName + "_servicenow";
                    if (!vdbXml.contains("<translator name=\"" + translatorDefName + "\"")) {
                        String translatorBlock = VDBXmlBuilder.buildServiceNowTranslatorBlock(translatorDefName, instanceUrl, username, password);
                        // Translators must follow all models.
                        vdbXml = VDBXmlBuilder.insertBefore(vdbXml, "</vdb>", translatorBlock);
                    }
                } else if (isCustomTranslator) {
                    String translatorDefName = dsName + "_" + translator;
                    if (!vdbXml.contains("<translator name=\"" + translatorDefName + "\"")) {
                        Map<String, String> props = new HashMap<>();
                        if (instanceUrl != null && !instanceUrl.isEmpty()) {
                            props.put("instanceUrl", instanceUrl);
                        }
                        if ("quickbooks".equalsIgnoreCase(translator) && realmId != null && !realmId.isEmpty()) {
                            props.put("realmId", realmId);
                        }
                        if (username != null && !username.isEmpty()) {
                            props.put("username", username);
                        }
                        if (password != null && !password.isEmpty()) {
                            props.put("password", password);
                        }
                        String translatorBlock = VDBXmlBuilder.buildCustomHttpTranslatorBlock(translatorDefName, translator, props);
                        vdbXml = VDBXmlBuilder.insertBefore(vdbXml, "</vdb>", translatorBlock);
                    }
                }
            }

            String viewStmt = "CREATE VIEW " + viewName + " AS SELECT * FROM "
                    + modelName + "." + teiidTableName + ";";
            boolean viewExists = vdbXml.contains("CREATE VIEW " + viewName + " ");
            if (viewExists && force) {
                log("Force mode: removing existing view " + viewName);
                vdbXml = VDBXmlBuilder.removeViewStmt(vdbXml, viewName);
                viewExists = false;
            }
            if (viewExists) {
                log("View " + viewName + " already present in VDB; skipping view insert.");
            } else {
                vdbXml = VDBXmlBuilder.insertBefore(vdbXml, "-- Place new View above", viewStmt + VDBXmlBuilder.newline());
            }

            vdbFileLocator.writeFile(vdbFilePath, vdbXml);

            // 4. Redeploy the VDB.
            teiidDeployHelper.redeployVDB(vdbFilePath, vdbId + "-vdb.xml", teiidHost, teiidPort);

            response.setStatus(HttpServletResponse.SC_OK);
            JSONObject ok = new JSONObject();
            ok.put("success", true);
            ok.put("vdb_id", vdbId);
            ok.put("model_name", modelName);
            ok.put("view_name", viewName);
            ok.put("message", "Database source registered successfully");
            out.println(ok.toString());
        } catch (Exception e) {
            log("Failed to register database source: " + e.getMessage(), e);
            response.setStatus(HttpServletResponse.SC_INTERNAL_SERVER_ERROR);
            out.println(createErrorResponse("Failed to register database source: " + e.getMessage()));
        } finally {
            VDBLockManager.releaseLock(vdbFilePath);
        }
    }

    /**
     * Authenticate request using API key
     */
    private boolean authenticateRequest(HttpServletRequest request) {
        // If no API key is configured, skip authentication (development mode)
        if (servletApiKey == null || servletApiKey.isEmpty()) {
            log("Warning: No API key configured, skipping authentication");
            return true;
        }

        String apiKey = request.getHeader("X-API-Key");
        return servletApiKey.equals(apiKey);
    }

    /**
     * Parse JSON request body
     */
    private JSONObject parseRequestBody(HttpServletRequest request) throws IOException {
        StringBuilder buffer = new StringBuilder();
        BufferedReader reader = request.getReader();
        String line;
        while ((line = reader.readLine()) != null) {
            buffer.append(line);
        }
        return new JSONObject(buffer.toString());
    }

    /**
     * Set CORS headers
     */
    private void setCorsHeaders(HttpServletResponse response) {
        response.setHeader("Access-Control-Allow-Origin", "*");
        response.setHeader("Access-Control-Allow-Methods", "POST, GET, OPTIONS, DELETE");
        response.setHeader("Access-Control-Allow-Headers", "Content-Type, X-API-Key, Authorization");
    }

    /**
     * Create error response JSON
     */
    private String createErrorResponse(String errorMessage) {
        JSONObject error = new JSONObject();
        error.put("success", false);
        error.put("error", errorMessage);
        return error.toString();
    }

    /**
     * Get environment variable or default value
     */
    private String getEnvOrDefault(String key, String defaultValue) {
        String value = System.getenv(key);
        return (value != null && !value.isEmpty()) ? value : defaultValue;
    }
}
