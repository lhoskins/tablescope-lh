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
        
        // 1. Authenticate the request (Redash → Servlet)
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
     * 
     * Expected JSON body:
     * {
     *   "org_id": 1,
     *   "vdb_id": "1234567",  // 7-digit random number
     *   "username": "vdb_user_dev",
     *   "password": "secure_password",
     *   "teiid_host": "64.52.108.62",
     *   "teiid_port": 10000,
     *   "vdb_type": "user",  // "user" or "shared" (optional, defaults to org-level for backward compatibility)
     *   "user_id": 123       // Required if vdb_type is "user"
     * }
     * 
     * Behavior:
     * - If vdb_type is "user": creates VDB in /Customer/{org_id}/{user_id}/vdb/
     * - If vdb_type is "shared": creates VDB in /Customer/{org_id}/shared/vdb/
     * - If vdb_type is not specified: creates VDB in /Customer/{org_id}/vdb/ (legacy org-level)
     * - If VDB file exists, redeploy it
     * - If VDB doesn't exist, create new VDB from template
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
                        vdbContent = readFile(existingVdb.getAbsolutePath());
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
                        writeFile(newVdbFilePath, vdbContent);
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
                // This ensures we don't redeploy while file processing is updating the VDB
                if (!VDBLockManager.acquireLock(existingVdb.getAbsolutePath())) {
                    log("Failed to acquire VDB lock for redeployment: " + existingVdb.getAbsolutePath());
                    response.setStatus(HttpServletResponse.SC_SERVICE_UNAVAILABLE);
                    out.println(createErrorResponse("VDB is currently being modified. Please try again."));
                    return;
                }
                try {
                    // Connect to Teiid Admin API
                    Admin admin = AdminFactory.getInstance().createAdmin(
                        teiidHost, teiidPort,
                        teiidAdminUser, teiidAdminPassword.toCharArray()
                    );
                    
                    try {
                        // Undeploy existing VDB
                        try {
                            admin.undeploy(existingVdbId + "-vdb.xml");
                            log("Existing VDB undeployed: " + existingVdbId);
                        } catch (Exception e) {
                            log("Warning: Failed to undeploy VDB (may not be deployed): " + e.getMessage());
                        }
                        
                        // Redeploy with updated configuration
                        try (InputStream inputStream = new FileInputStream(existingVdb)) {
                            admin.deploy(existingVdbId + "-vdb.xml", inputStream);
                        }
                        log("VDB redeployed successfully: " + existingVdbId);
                        
                    } finally {
                        admin.close();
                    }
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
                if (!customerDir.mkdirs()) {
                    response.setStatus(HttpServletResponse.SC_INTERNAL_SERVER_ERROR);
                    out.println(createErrorResponse("Failed to create customer folder: " + customerFolder));
                    return;
                }
                log("Created customer folder: " + customerFolder);
                setFolderPermissions(customerFolder);
            }
            
            // Create vdb folder if it doesn't exist
            // vdbDir already declared above, reuse it
            if (!vdbDir.exists()) {
                if (!vdbDir.mkdirs()) {
                    response.setStatus(HttpServletResponse.SC_INTERNAL_SERVER_ERROR);
                    out.println(createErrorResponse("Failed to create vdb folder: " + vdbFolder));
                    return;
                }
                log("Created vdb folder: " + vdbFolder);
                setFolderPermissions(vdbFolder);
            }
            
            // Create uploads folder if it doesn't exist
            File uploadsDir = new File(uploadsFolder);
            if (!uploadsDir.exists()) {
                if (!uploadsDir.mkdirs()) {
                    response.setStatus(HttpServletResponse.SC_INTERNAL_SERVER_ERROR);
                    out.println(createErrorResponse("Failed to create uploads folder: " + uploadsFolder));
                    return;
                }
                log("Created uploads folder: " + uploadsFolder);
                setFolderPermissions(uploadsFolder);
            }
            
            // 5. Read template VDB XML from hardcoded path
            if (!new File(templatePath).exists()) {
                response.setStatus(HttpServletResponse.SC_NOT_FOUND);
                out.println(createErrorResponse("Template VDB not found at: " + templatePath));
                return;
            }
            
            String vdbXml = readFile(templatePath);
            log("Template VDB loaded from: " + templatePath);
            
            // 6. Replace VDB name with 7-digit ID (only the <vdb> element, not model names)
            // Match the vdb element's name attribute specifically
            vdbXml = vdbXml.replaceFirst("<vdb\\s+name=\"[^\"]+\"", "<vdb name=\"" + vdbId + "\"");
            log("VDB name replaced with: " + vdbId);
            
            // Also update any hardcoded VDB name references in the virtual model views
            // This ensures system_info view and other references use the correct VDB ID
            vdbXml = vdbXml.replaceAll("'MyVDBTest'", "'" + vdbId + "'");
            vdbXml = vdbXml.replaceAll("'vdb_production'", "'" + vdbId + "'");
            log("VDB name references updated in views");
            
            // 7. Update file paths to use customer uploads folder
            vdbXml = updateFilePaths(vdbXml, uploadsFolder);
            
            // 8. Configure VDB credentials (if needed by your Teiid setup)
            vdbXml = configureVDBCredentials(vdbXml, vdbUsername, vdbPassword);
            
            // 9. Write new VDB file to customer folder
            // Acquire lock for this VDB to prevent race conditions with TeiidExcelImporterTest
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
                    writeFile(vdbFilePath, vdbXml);
                    log("SUCCESS: VDB file written to: " + vdbFilePath);
                    
                    // Verify the file was actually created (reuse vdbFile variable from line 180)
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
                Admin admin = AdminFactory.getInstance().createAdmin(
                    teiidHost, teiidPort,
                    teiidAdminUser, teiidAdminPassword.toCharArray()
                );
                
                try {
                    try (InputStream inputStream = new FileInputStream(vdbFilePath)) {
                        admin.deploy(vdbId + "-vdb.xml", inputStream);
                    }
                    log("VDB deployed to Teiid successfully: " + vdbId);
                } finally {
                    admin.close();
                }
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
     * 
     * Expected JSON body:
     * {
     *   "org_id": 1,
     *   "vdb_id": "1234567",
     *   "teiid_host": "64.52.108.62",
     *   "teiid_port": 10000,
     *   "vdb_type": "user",  // "user" or "shared" (optional, defaults to org-level)
     *   "user_id": 123       // Required if vdb_type is "user"
     * }
     * 
     * Behavior:
     * - Undeploys VDB from Teiid server
     * - Moves VDB file to archive folder instead of deleting
     * - Creates archive folder if it doesn't exist
     * - Supports user, shared, and org-level VDB types
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
                // User VDB: /Customer/{org_id}/{user_id}/vdb/
                customerFolder = vdbBasePath + "/customers/" + orgId + "/" + userId;
                vdbFolder = customerFolder + "/vdb";
                log("Using user VDB path for user " + userId);
            } else if ("shared".equals(vdbType)) {
                // Shared VDB: /Customer/{org_id}/shared/vdb/
                customerFolder = vdbBasePath + "/customers/" + orgId + "/shared";
                vdbFolder = customerFolder + "/vdb";
                log("Using shared VDB path for organization " + orgId);
            } else {
                // Legacy org-level VDB: /Customer/{org_id}/vdb/
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
                    // Continue anyway - we'll try to archive but may fail
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
     * 
     * Expected JSON body:
     * {
     *   "vdb_id": "vdb_development",
     *   "username": "new_username",
     *   "password": "new_password",
     *   "teiid_host": "64.52.108.62",
     *   "teiid_port": 10000
     * }
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
            String vdbPath = findVDBFile(vdbId);
            if (vdbPath == null) {
                response.setStatus(HttpServletResponse.SC_NOT_FOUND);
                out.println(createErrorResponse("VDB file not found: " + vdbId));
                return;
            }
            
            // 2. Read existing VDB configuration
            String vdbXml = readFile(vdbPath);
            
            // 3. Update VDB user credentials in VDB XML
            vdbXml = configureVDBCredentials(vdbXml, newUsername, newPassword);
            
            // 4. Write updated VDB file
            writeFile(vdbPath, vdbXml);
            
            log("VDB file updated with new credentials: " + vdbPath);
            
            // 5. Redeploy VDB using Teiid Admin credentials
            Admin admin = AdminFactory.getInstance().createAdmin(
                teiidHost,
                teiidPort,
                teiidAdminUser,
                teiidAdminPassword.toCharArray()
            );
            
            try {
                // Undeploy old version
                admin.undeploy(vdbId + "-vdb.xml");
                log("VDB undeployed: " + vdbId);
                
                // Deploy new version
                try (InputStream inputStream = new FileInputStream(vdbPath)) {
                    admin.deploy(vdbId + "-vdb.xml", inputStream);
                }
                log("VDB redeployed with new credentials: " + vdbId);
            } finally {
                admin.close();
            }
            
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
     * 
     * This is used after updating the VDB file (e.g., changing file paths)
     * to make Teiid reload the VDB with the new configuration.
     * 
     * Expected JSON body:
     * {
     *   "vdb_id": "vdb_production",
     *   "vdb_file_path": "/opt/wildfly/teiidfiles/customers/1/vdb/vdb_production-vdb.xml",
     *   "teiid_host": "64.52.108.62",
     *   "teiid_port": 10000
     * }
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
                vdbFilePath = findVDBFile(vdbId);
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
            
            // 3. Connect to Teiid Admin API
            Admin admin = AdminFactory.getInstance().createAdmin(
                teiidHost,
                teiidPort,
                teiidAdminUser,
                teiidAdminPassword.toCharArray()
            );
            
            try {
                // 4. Undeploy existing VDB
                try {
                    admin.undeploy(vdbId + "-vdb.xml");
                    log("VDB undeployed: " + vdbId);
                } catch (Exception e) {
                    log("Warning: Failed to undeploy VDB (may not be deployed): " + e.getMessage());
                }
                
                // 5. Redeploy VDB with updated file
                try (InputStream inputStream = new FileInputStream(vdbFilePath)) {
                    admin.deploy(vdbId + "-vdb.xml", inputStream);
                }
                log("VDB redeployed successfully: " + vdbId);
                
            } finally {
                admin.close();
            }
            
            // 6. Return success response
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
     * 
     * Expected JSON body:
     * {
     *   "vdb_id": "vdb_development",
     *   "teiid_host": "64.52.108.62",
     *   "teiid_port": 10000
     * }
     * 
     * Returns:
     * {
     *   "success": true,
     *   "vdb_id": "vdb_development",
     *   "status": "ACTIVE|LOADING|FAILED|NOT_FOUND",
     *   "version": "1",
     *   "models": [...],
     *   "response_time": 123
     * }
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
                    // VDB not found on server
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
                
                // Get VDB status
                String status = vdb.getStatus().toString(); // ACTIVE, LOADING, FAILED, etc.
                
                // Build response
                response.setStatus(HttpServletResponse.SC_OK);
                JSONObject statusResponse = new JSONObject();
                statusResponse.put("success", true);
                statusResponse.put("vdb_id", vdbId);
                statusResponse.put("status", status);
                statusResponse.put("version", vdb.getVersion());
                statusResponse.put("response_time", responseTime);
                statusResponse.put("description", vdb.getDescription());
                
                // Add model information
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
            response.setStatus(HttpServletResponse.SC_OK); // Return 200 with error status
            JSONObject errorResponse = new JSONObject();
            errorResponse.put("success", false);
            errorResponse.put("vdb_id", vdbId);
            errorResponse.put("status", "ERROR");
            errorResponse.put("response_time", responseTime);
            errorResponse.put("error", e.getMessage());
            out.println(errorResponse.toString());
        }
    }
    
    // ========================================================================
    // Helper Methods
    // ========================================================================
    
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
     * Read file content as string
     */
    private String readFile(String filePath) throws IOException {
        log("Reading file: " + filePath);
        byte[] bytes = Files.readAllBytes(Paths.get(filePath));
        String content = new String(bytes, "UTF-8");
        log("File read successfully: " + filePath + " (" + bytes.length + " bytes)");
        return content;
    }
    
    /**
     * Write string content to file
     */
    private void writeFile(String filePath, String content) throws IOException {
        log("Writing file: " + filePath + " (" + content.length() + " characters)");
        
        // Ensure parent directory exists
        File file = new File(filePath);
        File parentDir = file.getParentFile();
        if (parentDir != null && !parentDir.exists()) {
            log("Creating parent directory: " + parentDir.getAbsolutePath());
            if (!parentDir.mkdirs()) {
                throw new IOException("Failed to create parent directory: " + parentDir.getAbsolutePath());
            }
        }
        
        // Write file
        Files.write(Paths.get(filePath), content.getBytes("UTF-8"));
        log("File written successfully: " + filePath);
        
        // Verify file was created
        if (!file.exists()) {
            throw new IOException("File was not created: " + filePath);
        }
        log("File verified: " + filePath + " (" + file.length() + " bytes)");
    }
    
    /**
     * Validate that a folder exists
     */
    private boolean validateFolderExists(String folderPath) {
        File folder = new File(folderPath);
        return folder.exists() && folder.isDirectory();
    }
    
    /**
     * Create folder if it doesn't exist (including parent directories)
     * 
     * @param folderPath Path to folder to create
     * @return true if folder exists or was created successfully, false otherwise
     */
    private boolean createFolderIfNotExists(String folderPath) {
        try {
            File folder = new File(folderPath);
            
            // If folder already exists, return true
            if (folder.exists() && folder.isDirectory()) {
                log("Folder already exists: " + folderPath);
                return true;
            }
            
            // Create folder and all parent directories
            boolean created = folder.mkdirs();
            
            if (created) {
                log("Created folder: " + folderPath);
                return true;
            } else {
                log("Failed to create folder: " + folderPath);
                return false;
            }
            
        } catch (Exception e) {
            log("Error creating folder: " + folderPath + " - " + e.getMessage(), e);
            return false;
        }
    }
    
    /**
     * Update file paths in VDB XML to use relative paths for multi-tenancy.
     * 
     * This method converts absolute paths to relative paths that work with
     * AllowParentPaths=true in standalone.xml. The standalone.xml should have:
     * - ParentDirectory=/opt/wildfly/teiidfiles/customers
     * - AllowParentPaths=true
     * 
     * Then VDB files use relative paths like:
     * - '1/uploads/filename.xlsx' for org_id 1
     * - '2/uploads/filename.xlsx' for org_id 2
     * 
     * This method comprehensively updates all file path references in the VDB XML
     * to use relative paths for complete data isolation.
     * 
     * Handles multiple file path patterns:
     * 1. LOCATION attributes with file:// protocol
     * 2. LOCATION attributes without protocol (teiid_excel:FILE syntax)
     * 3. ParentDirectory properties (removed - use standalone.xml config)
     * 4. Importer properties (removed)
     * 5. Connection URL properties
     * 6. General file paths in model definitions
     * 
     * @param vdbXml The VDB XML content
     * @param uploadsFolder The customer's uploads folder path (e.g., /opt/wildfly/teiidfiles/customers/1/uploads)
     * @return Updated VDB XML with relative paths
     */
    private String updateFilePaths(String vdbXml, String uploadsFolder) {
        try {
            log("Converting file paths to relative format for: " + uploadsFolder);
            
            String updatedXml = vdbXml;
            
            // Extract org_id and optional user_id from uploads_folder path
            // uploads_folder formats:
            //   - Org-level: /opt/wildfly/teiidfiles/customers/{org_id}/uploads
            //   - User-level: /opt/wildfly/teiidfiles/customers/{org_id}/{user_id}/uploads
            //   - Shared: /opt/wildfly/teiidfiles/customers/{org_id}/shared/uploads
            Pattern userPattern = Pattern.compile("/customers/(\\d+)/(\\d+)/uploads");
            Pattern sharedPattern = Pattern.compile("/customers/(\\d+)/shared/uploads");
            Pattern orgPattern = Pattern.compile("/customers/(\\d+)/uploads");
            
            Matcher userMatcher = userPattern.matcher(uploadsFolder);
            Matcher sharedMatcher = sharedPattern.matcher(uploadsFolder);
            Matcher orgMatcher = orgPattern.matcher(uploadsFolder);
            
            String relativePathPrefix;
            
            if (userMatcher.find()) {
                // User-level VDB: {org_id}/{user_id}/uploads
                String orgId = userMatcher.group(1);
                String userId = userMatcher.group(2);
                relativePathPrefix = orgId + "/" + userId + "/uploads";
                log("Using user-level relative path prefix: " + relativePathPrefix + "/");
            } else if (sharedMatcher.find()) {
                // Shared VDB: {org_id}/shared/uploads
                String orgId = sharedMatcher.group(1);
                relativePathPrefix = orgId + "/shared/uploads";
                log("Using shared relative path prefix: " + relativePathPrefix + "/");
            } else if (orgMatcher.find()) {
                // Org-level VDB: {org_id}/uploads
                String orgId = orgMatcher.group(1);
                relativePathPrefix = orgId + "/uploads";
                log("Using org-level relative path prefix: " + relativePathPrefix + "/");
            } else {
                log("Warning: Could not extract path components from uploads_folder: " + uploadsFolder);
                log("Falling back to absolute paths");
                return updateFilePathsAbsolute(vdbXml, uploadsFolder);
            }
            
            // Pattern 1: LOCATION attribute with file:// protocol
            // Example: LOCATION='file:///opt/wildfly/teiidfiles/.../data.xlsx'
            // Replace with: LOCATION='file:///{org_id}/uploads/data.xlsx'
            String pattern1 = "LOCATION='file:///opt/wildfly/teiidfiles/(?:excelFilesTest|CSVFiles|customers/\\d+/uploads)/([^']+)'";
            String replacement1 = "LOCATION='file:///" + relativePathPrefix + "/$1'";
            updatedXml = updatedXml.replaceAll(pattern1, replacement1);
            
            // Catch-all for other file:// paths
            String pattern1b = "LOCATION='file:///opt/wildfly/teiidfiles/([^']+)'";
            String replacement1b = "LOCATION='file:///" + relativePathPrefix + "/$1'";
            updatedXml = updatedXml.replaceAll(pattern1b, replacement1b);
            
            // Pattern 2: LOCATION without protocol (teiid_excel:FILE syntax)
            // Example: "teiid_excel:FILE" '/opt/wildfly/teiidfiles/.../file.xlsx'
            // Replace with: "teiid_excel:FILE" '{org_id}/uploads/file.xlsx'
            String pattern2 = "\"teiid_excel:FILE\"\\s+'/opt/wildfly/teiidfiles/(?:excelFilesTest|CSVFiles|customers/\\d+/uploads)/([^']+)'";
            String replacement2 = "\"teiid_excel:FILE\" '" + relativePathPrefix + "/$1'";
            updatedXml = updatedXml.replaceAll(pattern2, replacement2);
            
            // Catch-all for other teiid_excel:FILE paths
            String pattern2b = "\"teiid_excel:FILE\"\\s+'/opt/wildfly/teiidfiles/([^']+)'";
            String replacement2b = "\"teiid_excel:FILE\" '" + relativePathPrefix + "/$1'";
            updatedXml = updatedXml.replaceAll(pattern2b, replacement2b);
            
            // Pattern 3: Remove ParentDirectory properties from VDB
            // (ParentDirectory should be configured in standalone.xml, not per-VDB)
            updatedXml = updatedXml.replaceAll("\\s*<property name=\"ParentDirectory\" value=\"[^\"]*\"/>\\s*\\n?", "");
            
            // Pattern 4: Remove Importer ParentDirectory
            updatedXml = updatedXml.replaceAll("\\s*<property name=\"importer\\.ParentDirectory\" value=\"[^\"]*\"/>\\s*\\n?", "");
            
            // Pattern 5: Connection URL with file:// protocol
            // Example: <property name="connection-url" value="file:///opt/wildfly/teiidfiles/.../data.xlsx"/>
            String pattern5 = "<property name=\"connection-url\" value=\"file:///opt/wildfly/teiidfiles/(?:excelFilesTest|CSVFiles|customers/\\d+/uploads)/([^\"]+)\"";
            String replacement5 = "<property name=\"connection-url\" value=\"file:///" + relativePathPrefix + "/$1\"";
            updatedXml = updatedXml.replaceAll(pattern5, replacement5);
            
            // Catch-all for other connection-url paths
            String pattern5b = "<property name=\"connection-url\" value=\"file:///opt/wildfly/teiidfiles/([^\"]+)\"";
            String replacement5b = "<property name=\"connection-url\" value=\"file:///" + relativePathPrefix + "/$1\"";
            updatedXml = updatedXml.replaceAll(pattern5b, replacement5b);
            
            // Pattern 6: LOCATION without file:// protocol (plain paths)
            // Example: LOCATION='/opt/wildfly/teiidfiles/.../file.xlsx'
            // Replace with: LOCATION='{org_id}/uploads/file.xlsx'
            String pattern6 = "LOCATION='/opt/wildfly/teiidfiles/(?:excelFilesTest|CSVFiles|customers/\\d+/uploads)/([^']+)'";
            String replacement6 = "LOCATION='" + relativePathPrefix + "/$1'";
            updatedXml = updatedXml.replaceAll(pattern6, replacement6);
            
            // Catch-all for other LOCATION paths
            String pattern6b = "LOCATION='/opt/wildfly/teiidfiles/([^']+)'";
            String replacement6b = "LOCATION='" + relativePathPrefix + "/$1'";
            updatedXml = updatedXml.replaceAll(pattern6b, replacement6b);
            
            log("File paths converted to relative format successfully");
            
            return updatedXml;
            
        } catch (Exception e) {
            log("Error updating file paths: " + e.getMessage(), e);
            // Return original XML if update fails to avoid breaking VDB
            return vdbXml;
        }
    }
    
    /**
     * Fallback method: Update file paths using absolute paths (legacy behavior).
     * Used when relative path extraction fails.
     */
    private String updateFilePathsAbsolute(String vdbXml, String uploadsFolder) {
        try {
            log("Using absolute paths for customer folder: " + uploadsFolder);
            
            String updatedXml = vdbXml;
            
            // Pattern 1: LOCATION attribute with file:// protocol
            String pattern1 = "LOCATION='file:///opt/wildfly/teiidfiles/([^']+)'";
            String replacement1 = "LOCATION='file://" + uploadsFolder + "/$1'";
            updatedXml = updatedXml.replaceAll(pattern1, replacement1);
            
            // Pattern 2: LOCATION attribute without protocol
            String pattern2 = "LOCATION='/opt/wildfly/teiidfiles/([^']+)'";
            String replacement2 = "LOCATION='" + uploadsFolder + "/$1'";
            updatedXml = updatedXml.replaceAll(pattern2, replacement2);
            
            // Pattern 3: ParentDirectory property
            String pattern3 = "<property name=\"ParentDirectory\" value=\"/opt/wildfly/teiidfiles\"";
            String replacement3 = "<property name=\"ParentDirectory\" value=\"" + uploadsFolder + "\"";
            updatedXml = updatedXml.replace(pattern3, replacement3);
            
            // Pattern 4: Importer property for file paths
            String pattern4 = "<property name=\"importer\\.ParentDirectory\" value=\"/opt/wildfly/teiidfiles\"";
            String replacement4 = "<property name=\"importer.ParentDirectory\" value=\"" + uploadsFolder + "\"";
            updatedXml = updatedXml.replace(pattern4, replacement4);
            
            // Pattern 5: File data source connection-url
            String pattern5 = "<property name=\"connection-url\" value=\"file:///opt/wildfly/teiidfiles/([^\"]+)\"";
            String replacement5 = "<property name=\"connection-url\" value=\"file://" + uploadsFolder + "/$1\"";
            updatedXml = updatedXml.replaceAll(pattern5, replacement5);
            
            // Pattern 6: Excel/CSV file paths in model definitions (without quotes)
            String pattern6 = "/opt/wildfly/teiidfiles/([^\\s<>\"']+)";
            String replacement6 = uploadsFolder + "/$1";
            updatedXml = updatedXml.replaceAll(pattern6, replacement6);
            
            log("File paths updated successfully using absolute paths");
            
            return updatedXml;
            
        } catch (Exception e) {
            log("Error updating file paths: " + e.getMessage(), e);
            return vdbXml;
        }
    }
    
    /**
     * Configure VDB credentials in VDB XML
     * 
     * Note: This implementation depends on your Teiid authentication mechanism.
     * Some setups use data-role based authentication, others use JAAS.
     * Adjust this method based on your specific Teiid configuration.
     */
    private String configureVDBCredentials(String vdbXml, String username, String password) {
        // Example implementation for data-role based authentication
        // This is a placeholder - adjust based on your Teiid setup
        
        // If your VDB uses data-roles, you might add something like:
        // <data-role name="user-role" any-authenticated="true">
        //     <mapped-role-name>user</mapped-role-name>
        // </data-role>
        
        // For now, return unchanged - credentials are typically managed
        // at the Teiid server level, not in VDB XML
        return vdbXml;
    }
    
    /**
     * Deploy VDB to Teiid server
     * 
     * @param vdbId VDB identifier
     * @param vdbFilePath Path to VDB XML file
     * @param teiidHost Teiid management host (from Redash config)
     * @param teiidPort Teiid management port (from Redash config)
     */
    private void deployVDBToTeiid(String vdbId, String vdbFilePath, String teiidHost, int teiidPort) throws Exception {
        log("Connecting to Teiid management at " + teiidHost + ":" + teiidPort);
        
        Admin admin = AdminFactory.getInstance().createAdmin(
            teiidHost,
            teiidPort,
            teiidAdminUser,
            teiidAdminPassword.toCharArray()
        );
        
        try (InputStream inputStream = new FileInputStream(vdbFilePath)) {
            admin.deploy(vdbId + "-vdb.xml", inputStream);
            log("VDB deployed to Teiid: " + vdbId);
        } finally {
            admin.close();
        }
    }
    
    /**
     * Find VDB file (search in customer folders first, then base path).
     * 
     * Searches for VDB files in the following order:
     * 1. Customer folders: /opt/wildfly/teiidfiles/customers/star/vdb/
     * 2. Base path: /opt/wildfly/teiidfiles/ (for backward compatibility)
     * 
     * @param vdbId The VDB identifier
     * @return Full path to VDB file, or null if not found
     */
    /**
     * Register an external database table as a queryable data source inside an
     * existing user VDB.
     *
     * Steps:
     *  1. Ensure a WildFly JDBC datasource exists (Teiid Admin API), so the
     *     physical model has a live JNDI connection.
     *  2. Insert a PHYSICAL model (CREATE FOREIGN TABLE) for the table.
     *  3. Insert a VIEW over that model into the MyCompany virtual model so it
     *     joins transparently with file-backed views.
     *  4. Undeploy + redeploy the VDB.
     *
     * The password is used only to create the datasource and is never logged.
     */
    private void createDatabaseSource(HttpServletRequest request, HttpServletResponse response, PrintWriter out)
            throws IOException {

        JSONObject body = parseRequestBody(request);

        String[] required = {"vdb_id", "org_id", "db_type", "translator", "jdbc_url",
                "username", "password", "model_name", "teiid_table_name",
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
        String password = body.getString("password");
        String modelName = body.getString("model_name");
        String teiidTableName = body.getString("teiid_table_name");
        String jndiName = body.getString("jndi_name");
        String dsName = body.getString("ds_name");
        String viewName = body.getString("view_name");
        String tableName = body.getString("table_name");
        String schemaName = body.optString("schema_name", "");
        JSONArray columns = body.optJSONArray("columns");

        // Teiid admin endpoint (local to this WildFly node).
        String teiidHost = body.optString("teiid_host", "localhost");
        int teiidPort = body.has("teiid_port") ? body.getInt("teiid_port") : 9990;

        log("createDatabaseSource: vdb_id=" + vdbId + ", org_id=" + orgId
                + ", user_id=" + userId + ", db_type=" + dbType
                + ", model=" + modelName + ", view=" + viewName + ", table=" + tableName);

        // 1. Locate the VDB XML file. User VDBs live under {org}/{user}/vdb/.
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
            vdbFilePath = findVDBFile(vdbId);
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
            // 2. Ensure the WildFly JDBC datasource exists.
            Admin admin = AdminFactory.getInstance().createAdmin(
                    teiidHost, teiidPort, teiidAdminUser, teiidAdminPassword.toCharArray());
            try {
                ensureDataSource(dsName, dbType, jdbcUrl, username, password);

                // 3. Edit the VDB XML: add the physical model + the view.
                String vdbXml = readFile(vdbFilePath);

                if (vdbXml.contains("<model name=\"" + modelName + "\"")) {
                    log("Model " + modelName + " already present in VDB; skipping model insert.");
                } else {
                    String modelBlock = buildPhysicalModelBlock(
                            modelName, dsName, translator, jndiName,
                            teiidTableName, schemaName, tableName, columns);
                    vdbXml = insertBefore(vdbXml, "</vdb>", modelBlock);
                }

                String viewStmt = "CREATE VIEW " + viewName + " AS SELECT * FROM "
                        + modelName + "." + teiidTableName + ";";
                if (vdbXml.contains("CREATE VIEW " + viewName + " ")) {
                    log("View " + viewName + " already present in VDB; skipping view insert.");
                } else {
                    vdbXml = insertBefore(vdbXml, "-- Place new View above", viewStmt + NEWLINE());
                }

                writeFile(vdbFilePath, vdbXml);

                // 4. Redeploy the VDB.
                try {
                    admin.undeploy(vdbId + "-vdb.xml");
                    log("VDB undeployed: " + vdbId);
                } catch (Exception e) {
                    log("Warning: undeploy failed (may not be deployed): " + e.getMessage());
                }
                try (InputStream inputStream = new FileInputStream(vdbFilePath)) {
                    admin.deploy(vdbId + "-vdb.xml", inputStream);
                }
                log("VDB redeployed with database source: " + vdbId);
            } finally {
                admin.close();
            }

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

    /** Map a db_type to the WildFly JDBC driver (template) name. */
    private String driverNameFor(String dbType) {
        if ("postgresql".equalsIgnoreCase(dbType)) return "postgresql";
        if ("mysql".equalsIgnoreCase(dbType)) return "mysql";
        if ("sqlserver".equalsIgnoreCase(dbType)) return "sqlserver";
        if ("oracle".equalsIgnoreCase(dbType)) return "oracle";
        return dbType;
    }

    /** Create the WildFly JDBC datasource if it does not already exist. */
    private void ensureDataSource(String dsName, String dbType,
                                  String jdbcUrl, String username, String password) throws Exception {
        if (dataSourceExists(dsName)) {
            log("Datasource already exists: " + dsName);
            return;
        }

        String driver = driverNameFor(dbType);
        String escUser = username == null ? "" : username.replace("\\", "\\\\").replace("\"", "\\\"");
        String escPass = password == null ? "" : password.replace("\\", "\\\\").replace("\"", "\\\"");

        // Use the server's own CLI (correct version + local auth) to avoid the
        // bundled Teiid admin client building a composite incompatible with the
        // running WildFly management model.
        String command = "/subsystem=datasources/data-source=" + dsName + ":add("
                + "jndi-name=java:/" + dsName
                + ", driver-name=" + driver
                + ", connection-url=" + jdbcUrl
                + ", user-name=\"" + escUser + "\""
                + ", password=\"" + escPass + "\""
                + ", enabled=true)";

        log("Creating datasource " + dsName + " with driver " + driver + " via CLI");
        String result = runCli(command);
        if (result == null || result.indexOf("\"outcome\" => \"success\"") < 0) {
            throw new Exception("CLI datasource creation failed: " + result);
        }
        log("Datasource created: " + dsName);
    }

    /** Return true if a WildFly data-source with this name already exists. */
    private boolean dataSourceExists(String dsName) {
        try {
            String out = runCli("/subsystem=datasources:read-children-names(child-type=data-source)");
            return out != null && out.contains("\"" + dsName + "\"");
        } catch (Exception e) {
            log("Warning: could not list datasources: " + e.getMessage());
            return false;
        }
    }

    /** Run a jboss-cli command against the local management interface (local auth). */
    private String runCli(String command) throws Exception {
        String jbossHome = System.getProperty("jboss.home.dir", "/opt/wildfly");
        ProcessBuilder pb = new ProcessBuilder(
                jbossHome + "/bin/jboss-cli.sh",
                "--connect",
                "--controller=localhost:9990",
                "--command=" + command);
        pb.redirectErrorStream(true);
        Process p = pb.start();
        StringBuilder sb = new StringBuilder();
        try (BufferedReader reader = new BufferedReader(
                new InputStreamReader(p.getInputStream(), "UTF-8"))) {
            String line;
            while ((line = reader.readLine()) != null) {
                sb.append(line).append("\n");
            }
        }
        boolean finished = p.waitFor(60, java.util.concurrent.TimeUnit.SECONDS);
        if (!finished) {
            p.destroyForcibly();
            throw new Exception("jboss-cli timed out");
        }
        return sb.toString();
    }

    /** Build a PHYSICAL model block with an explicit CREATE FOREIGN TABLE. */
    private String buildPhysicalModelBlock(String modelName, String dsName, String translator,
                                           String jndiName, String teiidTableName, String schemaName,
                                           String tableName, JSONArray columns) {
        StringBuilder cols = new StringBuilder();
        if (columns != null && columns.length() > 0) {
            for (int i = 0; i < columns.length(); i++) {
                JSONObject c = columns.getJSONObject(i);
                String name = c.getString("name");
                String type = c.optString("teiid_type", "string");
                // Quoted source identifier; double internal quotes per SQL identifier rules.
                String quotedId = "\"" + name.replace("\"", "\"\"") + "\"";
                // Escape single quotes for the DDL NAMEINSOURCE string literal.
                String nameInSourceLiteral = quotedId.replace("'", "''");
                // Emit an explicit column NAMEINSOURCE so Teiid quotes names that it
                // would otherwise leave unquoted (e.g. leading/trailing spaces,
                // reserved words, mixed case), which Postgres then cannot resolve.
                cols.append("	").append(quotedId).append(" ").append(type)
                    .append(" OPTIONS (NAMEINSOURCE '").append(nameInSourceLiteral).append("')");
                if (i < columns.length() - 1) cols.append(",");
                cols.append("\n");
            }
        } else {
            // Fallback: a single passthrough column keeps the model valid.
            cols.append("	\"__row__\" string\n");
        }

        String nameInSource;
        if (schemaName != null && !schemaName.isEmpty()) {
            nameInSource = "\"" + schemaName + "\".\"" + tableName + "\"";
        } else {
            nameInSource = "\"" + tableName + "\"";
        }

        StringBuilder sb = new StringBuilder();
        sb.append("\n");
        sb.append("  <model name=\"").append(modelName).append("\" type=\"PHYSICAL\" visible=\"false\">\n");
        sb.append("    <source name=\"").append(dsName).append("\" translator-name=\"").append(translator)
          .append("\" connection-jndi-name=\"").append(jndiName).append("\"/>\n");
        sb.append("    <metadata type=\"DDL\">\n");
        sb.append("      <![CDATA[\n");
        sb.append("CREATE FOREIGN TABLE ").append(teiidTableName).append(" (\n");
        sb.append(cols);
        sb.append(") OPTIONS (NAMEINSOURCE '").append(nameInSource).append("');\n");
        sb.append("]]>\n");
        sb.append("    </metadata>\n");
        sb.append("  </model>\n");
        return sb.toString();
    }

    /** Insert {@code insertion} immediately before the first occurrence of {@code anchor}. */
    private String insertBefore(String content, String anchor, String insertion) {
        int idx = content.indexOf(anchor);
        if (idx < 0) {
            log("Warning: anchor not found for insertBefore: " + anchor);
            return content;
        }
        return content.substring(0, idx) + insertion + content.substring(idx);
    }

    private String NEWLINE() {
        return "\n";
    }

    private String findVDBFile(String vdbId) {
        String fileName = vdbId + "-vdb.xml";
        
        log("Searching for VDB file: " + fileName);
        
        // First, search in customer folders (preferred location for multi-tenancy)
        File customersDir = new File(vdbBasePath + "/customers");
        if (customersDir.exists() && customersDir.isDirectory()) {
            File[] orgDirs = customersDir.listFiles();
            if (orgDirs != null) {
                for (File orgDir : orgDirs) {
                    if (orgDir.isDirectory()) {
                        String vdbPath = orgDir.getAbsolutePath() + "/vdb/" + fileName;
                        if (new File(vdbPath).exists()) {
                            log("Found VDB file in customer folder: " + vdbPath);
                            return vdbPath;
                        }
                    }
                }
            }
        }
        
        // Fallback: Check base path (for backward compatibility with non-multi-tenant VDBs)
        String basePath = vdbBasePath + "/" + fileName;
        if (new File(basePath).exists()) {
            log("Found VDB file in base path: " + basePath);
            return basePath;
        }
        
        log("VDB file not found: " + fileName);
        return null;
    }
    
    /**
     * Delete VDB file from customer folder or base path.
     * 
     * @param vdbId The VDB identifier
     * @return true if file was deleted, false otherwise
     */
    private boolean deleteVDBFile(String vdbId) {
        String vdbPath = findVDBFile(vdbId);
        if (vdbPath != null) {
            File vdbFile = new File(vdbPath);
            boolean deleted = vdbFile.delete();
            if (deleted) {
                log("VDB file deleted successfully: " + vdbPath);
            } else {
                log("Failed to delete VDB file: " + vdbPath);
            }
            return deleted;
        } else {
            log("VDB file not found for deletion: " + vdbId + "-vdb.xml");
            return false;
        }
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
    
    /**
     * Set folder permissions to 2777 (rwxrwsrwx) with setgid bit
     * This ensures new files/folders inherit the group ownership
     */
    private void setFolderPermissions(String folderPath) {
        try {
            // Use chmod command to set permissions with setgid bit
            // 2777 = rwxrwsrwx (setgid bit + full permissions)
            ProcessBuilder pb = new ProcessBuilder("chmod", "2777", folderPath);
            Process process = pb.start();
            int exitCode = process.waitFor();
            
            if (exitCode == 0) {
                log("Set folder permissions to 2777 (with setgid): " + folderPath);
            } else {
                log("Warning: chmod command failed with exit code " + exitCode + " for: " + folderPath);
            }
        } catch (Exception e) {
            log("Warning: Failed to set folder permissions for " + folderPath + ": " + e.getMessage());
            // Don't fail the operation, just log the warning
        }
    }
}
