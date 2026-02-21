package cloud.tablescope;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.regex.*;
import javax.servlet.ServletException;
import javax.servlet.annotation.WebServlet;
import javax.servlet.http.*;
import org.json.JSONArray;
import org.json.JSONObject;
import org.teiid.adminapi.Admin;
import org.teiid.adminapi.jboss.AdminFactory;

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

    private static final String TEIID_HOST = "localhost";
    private static final int TEIID_PORT = 10000;
    private static final String TEIID_USER = "admin";
    private static final String TEIID_PASSWORD = "admin";
    private static final String CUSTOMER_BASE_PATH = "/opt/wildfly/teiidfiles/customers";
    private static final String DDL_TYPE_FOREIGN_TABLE = "FOREIGN_TABLE";
    private static final String DDL_TYPE_VIEW = "VIEW";

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

            String userVdbPath = findUserVDBPath(orgId, userId);
            String sharedVdbPath = findSharedVDBPath(orgId);

            if (userVdbPath == null) {
                throw new Exception("User VDB not found for org " + orgId + ", user " + userId);
            }
            if (sharedVdbPath == null) {
                throw new Exception("Shared VDB not found for org " + orgId);
            }

            log("[VDB_MIGRATION] User VDB: " + userVdbPath);
            log("[VDB_MIGRATION] Shared VDB: " + sharedVdbPath);

            MigrationResult result;
            if ("to_shared".equals(migrationType)) {
                result = migrateToSharedVDB(userVdbPath, sharedVdbPath, datasources);
            } else if ("to_private".equals(migrationType)) {
                result = migrateToPrivateVDB(userVdbPath, sharedVdbPath, datasources);
            } else {
                throw new Exception("Invalid migration type: " + migrationType);
            }

            redeployVDB(userVdbPath, orgId, userId);
            redeployVDB(sharedVdbPath, orgId, null);

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

    private static class MigrationResult {
        int tablesMigrated = 0;
        int viewsMigrated = 0;
    }

    private static class DDLResult {
        String ddl;
        String type;
        DDLResult(String ddl, String type) {
            this.ddl = ddl;
            this.type = type;
        }
    }


    private MigrationResult migrateToSharedVDB(String userVdbPath, String sharedVdbPath, JSONArray datasources)
            throws Exception {
        log("[VDB_MIGRATION] Starting migration to shared VDB");
        
        // Read VDB files as text to preserve CDATA and comments
        String userVdbContent = readVdbAsText(userVdbPath);
        String sharedVdbContent = readVdbAsText(sharedVdbPath);
        
        MigrationResult result = new MigrationResult();

        for (int i = 0; i < datasources.length(); i++) {
            JSONObject ds = datasources.getJSONObject(i);
            String foreignTableName = ds.getString("foreign_table_name");
            String privateFilePath = ds.getString("private_file_path");
            String sharedFilePath = ds.getString("shared_file_path");
            String fileType = ds.optString("file_type", detectFileType(privateFilePath));

            log("[VDB_MIGRATION] Migrating: " + foreignTableName + " (type: " + fileType + ")");
            log("[VDB_MIGRATION] Path: " + privateFilePath + " -> " + sharedFilePath);

            // Extract DDL from user VDB (text-based)
            DDLResult ddlResult = extractDDLFromText(userVdbContent, foreignTableName, fileType);

            if (ddlResult != null && ddlResult.ddl != null && !ddlResult.ddl.trim().isEmpty()) {
                log("[VDB_MIGRATION] Found " + ddlResult.type + " DDL, length: " + ddlResult.ddl.length());
                
                // Update file paths in DDL
                String updatedDDL = updateFilePaths(ddlResult.ddl, privateFilePath, sharedFilePath, ddlResult.type);
                
                // Add DDL to shared VDB (text-based)
                sharedVdbContent = addDDLToVDBText(sharedVdbContent, updatedDDL, ddlResult.type);
                
                // Remove DDL from user VDB (text-based)
                userVdbContent = removeDDLFromVDBText(userVdbContent, foreignTableName, ddlResult.type);

                if (DDL_TYPE_FOREIGN_TABLE.equals(ddlResult.type)) {
                    result.tablesMigrated++;
                    
                    // For Excel files, also migrate the corresponding _XLSX VIEW
                    String xlsxViewName = foreignTableName + "_XLSX";
                    String xlsxViewDDL = extractViewDDLFromText(userVdbContent, xlsxViewName);
                    if (xlsxViewDDL != null && !xlsxViewDDL.trim().isEmpty()) {
                        log("[VDB_MIGRATION] Also migrating corresponding VIEW: " + xlsxViewName);
                        // Update VIEW to reference the table directly (not through ExcelSourceModel)
                        // This is needed because the VIEW will be in MyCompany model, not ExcelSourceModel
                        xlsxViewDDL = xlsxViewDDL.replace("FROM ExcelSourceModel." + foreignTableName, "FROM " + foreignTableName);
                        log("[VDB_MIGRATION] Updated VIEW to reference table directly: " + foreignTableName);
                        // Add VIEW to shared VDB
                        sharedVdbContent = addDDLToVDBText(sharedVdbContent, xlsxViewDDL, DDL_TYPE_VIEW);
                        // Remove VIEW from user VDB
                        userVdbContent = removeDDLFromVDBText(userVdbContent, xlsxViewName, DDL_TYPE_VIEW);
                        result.viewsMigrated++;
                    }
                } else {
                    result.viewsMigrated++;
                }
            } else {
                log("[VDB_MIGRATION] WARNING: DDL not found for: " + foreignTableName);
            }
        }

        // Write VDB files preserving CDATA and comments
        writeVdbAsText(userVdbPath, userVdbContent);
        writeVdbAsText(sharedVdbPath, sharedVdbContent);
        
        return result;
    }

    private MigrationResult migrateToPrivateVDB(String userVdbPath, String sharedVdbPath, JSONArray datasources)
            throws Exception {
        log("[VDB_MIGRATION] Starting migration to private VDB");
        
        // Read VDB files as text to preserve CDATA and comments
        String userVdbContent = readVdbAsText(userVdbPath);
        String sharedVdbContent = readVdbAsText(sharedVdbPath);
        
        MigrationResult result = new MigrationResult();

        for (int i = 0; i < datasources.length(); i++) {
            JSONObject ds = datasources.getJSONObject(i);
            String foreignTableName = ds.getString("foreign_table_name");
            String privateFilePath = ds.getString("private_file_path");
            String sharedFilePath = ds.getString("shared_file_path");
            String fileType = ds.optString("file_type", detectFileType(sharedFilePath));

            // Extract DDL from shared VDB (text-based)
            DDLResult ddlResult = extractDDLFromText(sharedVdbContent, foreignTableName, fileType);

            if (ddlResult != null && ddlResult.ddl != null && !ddlResult.ddl.trim().isEmpty()) {
                String updatedDDL = updateFilePaths(ddlResult.ddl, sharedFilePath, privateFilePath, ddlResult.type);
                
                // Add DDL to user VDB (text-based)
                userVdbContent = addDDLToVDBText(userVdbContent, updatedDDL, ddlResult.type);
                
                // Remove DDL from shared VDB (text-based)
                sharedVdbContent = removeDDLFromVDBText(sharedVdbContent, foreignTableName, ddlResult.type);

                if (DDL_TYPE_FOREIGN_TABLE.equals(ddlResult.type)) {
                    result.tablesMigrated++;
                    
                    // For Excel files, also migrate the corresponding _XLSX VIEW
                    String xlsxViewName = foreignTableName + "_XLSX";
                    String xlsxViewDDL = extractViewDDLFromText(sharedVdbContent, xlsxViewName);
                    if (xlsxViewDDL != null && !xlsxViewDDL.trim().isEmpty()) {
                        log("[VDB_MIGRATION] Also migrating corresponding VIEW: " + xlsxViewName);
                        // Update VIEW to reference through ExcelSourceModel (needed for user VDB)
                        xlsxViewDDL = xlsxViewDDL.replace("FROM " + foreignTableName, "FROM ExcelSourceModel." + foreignTableName);
                        log("[VDB_MIGRATION] Updated VIEW to reference through ExcelSourceModel: " + foreignTableName);
                        // Add VIEW to user VDB
                        userVdbContent = addDDLToVDBText(userVdbContent, xlsxViewDDL, DDL_TYPE_VIEW);
                        // Remove VIEW from shared VDB
                        sharedVdbContent = removeDDLFromVDBText(sharedVdbContent, xlsxViewName, DDL_TYPE_VIEW);
                        result.viewsMigrated++;
                    }
                } else {
                    result.viewsMigrated++;
                }
            }
        }

        // Write VDB files preserving CDATA and comments
        writeVdbAsText(userVdbPath, userVdbContent);
        writeVdbAsText(sharedVdbPath, sharedVdbContent);
        
        return result;
    }


    private String detectFileType(String filePath) {
        if (filePath == null) return "excel";
        String lowerPath = filePath.toLowerCase();
        if (lowerPath.endsWith(".csv") || lowerPath.endsWith(".txt")) {
            return "csv_txt";
        }
        return "excel";
    }

    /**
     * Extract DDL from VDB content using text-based parsing.
     * This preserves CDATA sections and comments.
     */
    private DDLResult extractDDLFromText(String vdbContent, String tableName, String fileType) {
        if ("csv_txt".equals(fileType)) {
            String viewDDL = extractViewDDLFromText(vdbContent, tableName);
            if (viewDDL != null) return new DDLResult(viewDDL, DDL_TYPE_VIEW);
            String tableDDL = extractForeignTableDDLFromText(vdbContent, tableName);
            if (tableDDL != null) return new DDLResult(tableDDL, DDL_TYPE_FOREIGN_TABLE);
        } else {
            String tableDDL = extractForeignTableDDLFromText(vdbContent, tableName);
            if (tableDDL != null) return new DDLResult(tableDDL, DDL_TYPE_FOREIGN_TABLE);
            String viewDDL = extractViewDDLFromText(vdbContent, tableName);
            if (viewDDL != null) return new DDLResult(viewDDL, DDL_TYPE_VIEW);
        }
        return null;
    }

    /**
     * Extract FOREIGN TABLE DDL from VDB text content.
     * Handles both CDATA sections and plain text metadata.
     */
    private String extractForeignTableDDLFromText(String vdbContent, String tableName) {
        String searchPattern = "CREATE FOREIGN TABLE " + tableName;
        
        // First try to find in CDATA sections
        Pattern cdataPattern = Pattern.compile("<!\\[CDATA\\[(.*?)\\]\\]>", Pattern.DOTALL);
        Matcher cdataMatcher = cdataPattern.matcher(vdbContent);
        
        while (cdataMatcher.find()) {
            String ddlContent = cdataMatcher.group(1);
            if (ddlContent.contains(searchPattern)) {
                log("[VDB_MIGRATION] Found FOREIGN TABLE in CDATA section");
                return extractDDLBlock(ddlContent, tableName, "CREATE FOREIGN TABLE");
            }
        }
        
        // Fallback: try to find in metadata element without CDATA (handles stripped files)
        if (vdbContent.contains(searchPattern)) {
            // Match metadata content that may span multiple lines and contain the DDL
            Pattern metaPattern = Pattern.compile("<metadata[^>]*type=\"DDL\"[^>]*>([\\s\\S]*?)</metadata>", Pattern.DOTALL);
            Matcher metaMatcher = metaPattern.matcher(vdbContent);
            while (metaMatcher.find()) {
                String ddlContent = metaMatcher.group(1);
                // Skip if this is a CDATA section (already handled above)
                if (ddlContent.trim().startsWith("<![CDATA[")) continue;
                
                if (ddlContent.contains(searchPattern)) {
                    log("[VDB_MIGRATION] Found FOREIGN TABLE in plain metadata (no CDATA)");
                    return extractDDLBlock(ddlContent, tableName, "CREATE FOREIGN TABLE");
                }
            }
        }
        
        return null;
    }

    /**
     * Extract VIEW DDL from VDB text content.
     * Handles both CDATA sections and plain text metadata.
     */
    private String extractViewDDLFromText(String vdbContent, String tableName) {
        String searchPattern = "CREATE VIEW " + tableName;
        
        // First try to find in CDATA sections
        Pattern cdataPattern = Pattern.compile("<!\\[CDATA\\[(.*?)\\]\\]>", Pattern.DOTALL);
        Matcher cdataMatcher = cdataPattern.matcher(vdbContent);
        
        while (cdataMatcher.find()) {
            String ddlContent = cdataMatcher.group(1);
            if (ddlContent.contains(searchPattern)) {
                log("[VDB_MIGRATION] Found VIEW in CDATA section");
                return extractDDLBlock(ddlContent, tableName, "CREATE VIEW");
            }
        }
        
        // Fallback: try to find in metadata element without CDATA (handles stripped files)
        if (vdbContent.contains(searchPattern)) {
            // Match metadata content that may span multiple lines and contain the DDL
            Pattern metaPattern = Pattern.compile("<metadata[^>]*type=\"DDL\"[^>]*>([\\s\\S]*?)</metadata>", Pattern.DOTALL);
            Matcher metaMatcher = metaPattern.matcher(vdbContent);
            while (metaMatcher.find()) {
                String ddlContent = metaMatcher.group(1);
                // Skip if this is a CDATA section (already handled above)
                if (ddlContent.trim().startsWith("<![CDATA[")) continue;
                
                if (ddlContent.contains(searchPattern)) {
                    log("[VDB_MIGRATION] Found VIEW in plain metadata (no CDATA)");
                    return extractDDLBlock(ddlContent, tableName, "CREATE VIEW");
                }
            }
        }
        
        return null;
    }

    private String extractDDLBlock(String fullDDL, String tableName, String createKeyword) {
        String startPattern = createKeyword + " " + tableName;
        int startIndex = fullDDL.indexOf(startPattern);
        if (startIndex == -1) return null;

        int endIndex = fullDDL.length();
        int nextFT = fullDDL.indexOf("CREATE FOREIGN TABLE", startIndex + startPattern.length());
        int nextView = fullDDL.indexOf("CREATE VIEW", startIndex + startPattern.length());
        int nextComment = fullDDL.indexOf("-- Place new", startIndex + startPattern.length());

        if (nextFT != -1 && nextFT < endIndex) endIndex = nextFT;
        if (nextView != -1 && nextView < endIndex) endIndex = nextView;
        if (nextComment != -1 && nextComment < endIndex) endIndex = nextComment;

        return fullDDL.substring(startIndex, endIndex).trim();
    }


    private String updateFilePaths(String ddl, String oldPath, String newPath, String ddlType) {
        String updatedDDL = ddl;

        if (DDL_TYPE_VIEW.equals(ddlType)) {
            // CSV/TXT: path in getTextFiles('path')
            updatedDDL = updatedDDL.replace("getTextFiles('" + oldPath + "')", "getTextFiles('" + newPath + "')");
            String oldRel = extractRelativePath(oldPath);
            String newRel = extractRelativePath(newPath);
            if (oldRel != null && newRel != null && !oldRel.equals(newRel)) {
                updatedDDL = updatedDDL.replace("getTextFiles('" + oldRel + "')", "getTextFiles('" + newRel + "')");
            }
        } else {
            // Excel: path in teiid_excel:FILE option
            updatedDDL = updatedDDL.replace(oldPath, newPath);
            String oldRel = extractRelativePath(oldPath);
            String newRel = extractRelativePath(newPath);
            if (oldRel != null && newRel != null && !oldRel.equals(newRel)) {
                updatedDDL = updatedDDL.replace(oldRel, newRel);
            }
        }

        String oldFileName = new File(oldPath).getName();
        String newFileName = new File(newPath).getName();
        if (!oldFileName.equals(newFileName)) {
            updatedDDL = updatedDDL.replace(oldFileName, newFileName);
        }
        return updatedDDL;
    }

    private String extractRelativePath(String fullPath) {
        if (fullPath == null) return null;
        int idx = fullPath.indexOf("customers/");
        if (idx != -1) return fullPath.substring(idx + "customers/".length());
        return fullPath;
    }

    /**
     * Add DDL to VDB using text-based manipulation.
     * Preserves CDATA sections and comments.
     * If no CDATA exists, wraps content in CDATA.
     * - VIEWs are added to MyCompany model ABOVE "-- Place new View above"
     * - FOREIGN TABLEs are added to ExcelSourceModel BELOW "-- Place Foreign Table Below"
     */
    private String addDDLToVDBText(String vdbContent, String ddl, String ddlType) {
        // Determine target model and insertion point based on DDL type
        String targetModel;
        String insertionComment;
        boolean insertBefore; // true = insert before comment, false = insert after comment
        
        if (DDL_TYPE_VIEW.equals(ddlType)) {
            targetModel = "MyCompany";
            insertionComment = "-- Place new View above";
            insertBefore = true; // VIEWs go ABOVE the comment
        } else {
            targetModel = "ExcelSourceModel";
            insertionComment = "-- Place Foreign Table Below";
            insertBefore = false; // FOREIGN TABLEs go BELOW the comment
        }
        
        // Pattern to find the correct model's metadata element with CDATA
        // This pattern accounts for content between <model> and <metadata> tags
        String modelPattern = "<model[^>]*name=\"" + targetModel + "\"[^>]*>[\\s\\S]*?<metadata[^>]*type=\"DDL\"[^>]*>\\s*<!\\[CDATA\\[([\\s\\S]*?)\\]\\]>\\s*</metadata>";
        
        Pattern cdataPattern = Pattern.compile(modelPattern, Pattern.DOTALL);
        Matcher matcher = cdataPattern.matcher(vdbContent);
        
        if (matcher.find()) {
            String existingDDL = matcher.group(1);
            int metadataStart = vdbContent.indexOf("<metadata", matcher.start());
            int cdataStart = vdbContent.indexOf("<![CDATA[", metadataStart);
            int cdataEnd = vdbContent.indexOf("]]>", cdataStart);
            
            // Find insertion point based on comment
            String newDDL;
            int commentIdx = existingDDL.indexOf(insertionComment);
            if (commentIdx != -1) {
                if (insertBefore) {
                    // Insert BEFORE the comment (for VIEWs)
                    String ddlBefore = existingDDL.substring(0, commentIdx);
                    String ddlAfter = existingDDL.substring(commentIdx);
                    newDDL = ddlBefore + ddl + "\n\n" + ddlAfter;
                } else {
                    // Insert AFTER the comment (for FOREIGN TABLEs)
                    // Find the end of the comment line
                    int lineEnd = existingDDL.indexOf('\n', commentIdx);
                    if (lineEnd == -1) lineEnd = existingDDL.length();
                    String ddlBefore = existingDDL.substring(0, lineEnd + 1);
                    String ddlAfter = existingDDL.substring(lineEnd + 1);
                    newDDL = ddlBefore + "\n" + ddl + ddlAfter;
                }
            } else {
                // No comment found, append at end
                newDDL = existingDDL + "\n\n" + ddl;
            }
            
            log("[VDB_MIGRATION] Added " + ddlType + " to " + targetModel + " model " + (insertBefore ? "above" : "below") + " comment");
            
            // Replace just the CDATA content
            String before = vdbContent.substring(0, cdataStart + "<![CDATA[".length());
            String after = vdbContent.substring(cdataEnd);
            return before + newDDL + after;
        }
        
        // Fallback: try without CDATA (handles stripped files)
        String noCdataModelPattern = "<model[^>]*name=\"" + targetModel + "\"[^>]*>[\\s\\S]*?<metadata[^>]*type=\"DDL\"[^>]*>([\\s\\S]*?)</metadata>";
        
        Pattern noCdataPattern = Pattern.compile(noCdataModelPattern, Pattern.DOTALL);
        Matcher noCdataMatcher = noCdataPattern.matcher(vdbContent);
        
        if (noCdataMatcher.find()) {
            String existingDDL = noCdataMatcher.group(1);
            
            // Skip if this already has CDATA (shouldn't happen but be safe)
            if (existingDDL.trim().startsWith("<![CDATA[")) {
                log("[VDB_MIGRATION] WARNING: Unexpected CDATA in fallback pattern, skipping");
                return vdbContent;
            }
            
            int metadataStart = vdbContent.indexOf("<metadata", noCdataMatcher.start());
            int metadataTagEnd = vdbContent.indexOf(">", metadataStart) + 1;
            int metadataEnd = vdbContent.indexOf("</metadata>", metadataStart);
            
            // Find insertion point based on comment
            String newDDL;
            int commentIdx = existingDDL.indexOf(insertionComment);
            if (commentIdx != -1) {
                if (insertBefore) {
                    // Insert BEFORE the comment (for VIEWs)
                    String ddlBefore = existingDDL.substring(0, commentIdx);
                    String ddlAfter = existingDDL.substring(commentIdx);
                    newDDL = ddlBefore + ddl + "\n\n" + ddlAfter;
                } else {
                    // Insert AFTER the comment (for FOREIGN TABLEs)
                    int lineEnd = existingDDL.indexOf('\n', commentIdx);
                    if (lineEnd == -1) lineEnd = existingDDL.length();
                    String ddlBefore = existingDDL.substring(0, lineEnd + 1);
                    String ddlAfter = existingDDL.substring(lineEnd + 1);
                    newDDL = ddlBefore + "\n" + ddl + ddlAfter;
                }
            } else {
                // No comment found, append at end
                newDDL = existingDDL + "\n\n" + ddl;
            }
            
            // Wrap in CDATA when adding to ensure proper format
            log("[VDB_MIGRATION] Added " + ddlType + " to " + targetModel + " model and wrapped in CDATA");
            String before = vdbContent.substring(0, metadataTagEnd);
            String after = vdbContent.substring(metadataEnd);
            return before + "\n      <![CDATA[\n" + newDDL.trim() + "\n]]>\n    " + after;
        }
        
        log("[VDB_MIGRATION] WARNING: Could not find metadata element to add " + ddlType + " to " + targetModel);
        return vdbContent;
    }

    /**
     * Remove DDL from VDB using text-based manipulation.
     * Preserves CDATA sections and comments.
     */
    private String removeDDLFromVDBText(String vdbContent, String tableName, String ddlType) {
        String keyword = DDL_TYPE_VIEW.equals(ddlType) ? "CREATE VIEW" : "CREATE FOREIGN TABLE";
        String searchPattern = keyword + " " + tableName;
        
        // First try to find in CDATA section
        Pattern cdataPattern = Pattern.compile(
            "(<metadata[^>]*type=\"DDL\"[^>]*>\\s*<!\\[CDATA\\[)(.*?)(\\]\\]>\\s*</metadata>)",
            Pattern.DOTALL
        );
        Matcher matcher = cdataPattern.matcher(vdbContent);
        
        while (matcher.find()) {
            String existingDDL = matcher.group(2);
            if (existingDDL.contains(searchPattern)) {
                String before = matcher.group(1);
                String after = matcher.group(3);
                
                // Extract and remove the DDL block
                String block = extractDDLBlock(existingDDL, tableName, keyword);
                if (block != null) {
                    String updatedDDL = existingDDL.replace(block, "");
                    // Clean up multiple newlines
                    updatedDDL = updatedDDL.replaceAll("\n{3,}", "\n\n");
                    
                    log("[VDB_MIGRATION] Removed DDL from CDATA section");
                    return vdbContent.substring(0, matcher.start()) + 
                           before + updatedDDL + after + 
                           vdbContent.substring(matcher.end());
                }
            }
        }
        
        // Fallback: try without CDATA (handles stripped files)
        Pattern noCdataPattern = Pattern.compile(
            "(<metadata[^>]*type=\"DDL\"[^>]*>)([\\s\\S]*?)(</metadata>)",
            Pattern.DOTALL
        );
        Matcher noCdataMatcher = noCdataPattern.matcher(vdbContent);
        
        while (noCdataMatcher.find()) {
            String existingDDL = noCdataMatcher.group(2);
            // Skip if this has CDATA (already handled above)
            if (existingDDL.trim().startsWith("<![CDATA[")) continue;
            
            if (existingDDL.contains(searchPattern)) {
                String before = noCdataMatcher.group(1);
                String after = noCdataMatcher.group(3);
                
                // Extract and remove the DDL block
                String block = extractDDLBlock(existingDDL, tableName, keyword);
                if (block != null) {
                    String updatedDDL = existingDDL.replace(block, "");
                    // Clean up multiple newlines
                    updatedDDL = updatedDDL.replaceAll("\n{3,}", "\n\n");
                    
                    // Wrap in CDATA to ensure proper format
                    log("[VDB_MIGRATION] Removed DDL and wrapped remaining in CDATA");
                    return vdbContent.substring(0, noCdataMatcher.start()) + 
                           before + "\n      <![CDATA[\n" + updatedDDL.trim() + "\n]]>\n    " + after + 
                           vdbContent.substring(noCdataMatcher.end());
                }
            }
        }
        
        log("[VDB_MIGRATION] WARNING: Could not find DDL to remove for: " + tableName);
        return vdbContent;
    }


    /**
     * Read VDB file as text to preserve CDATA sections and comments.
     */
    private String readVdbAsText(String vdbPath) throws Exception {
        return new String(Files.readAllBytes(Paths.get(vdbPath)), StandardCharsets.UTF_8);
    }

    /**
     * Write VDB content as text, preserving CDATA sections and comments.
     * Creates a backup before writing.
     * Ensures all metadata elements have CDATA sections.
     */
    private void writeVdbAsText(String vdbPath, String content) throws Exception {
        // Create backup
        String backupPath = vdbPath + ".backup_migration_" + System.currentTimeMillis();
        Files.copy(Paths.get(vdbPath), Paths.get(backupPath), StandardCopyOption.REPLACE_EXISTING);
        log("[VDB_MIGRATION] Created backup: " + backupPath);
        
        // Ensure all metadata elements have CDATA sections
        content = ensureCDATASections(content);
        
        // Write content
        Files.write(Paths.get(vdbPath), content.getBytes(StandardCharsets.UTF_8));
        log("[VDB_MIGRATION] Wrote VDB file: " + vdbPath);
    }
    
    /**
     * Ensure all metadata type="DDL" elements have CDATA sections.
     * This fixes VDB files that had CDATA stripped by Teiid deployment.
     */
    private String ensureCDATASections(String vdbContent) {
        // Pattern to find metadata elements without CDATA
        Pattern noCdataPattern = Pattern.compile(
            "(<metadata[^>]*type=\"DDL\"[^>]*>)([\\s\\S]*?)(</metadata>)",
            Pattern.DOTALL
        );
        
        StringBuffer result = new StringBuffer();
        Matcher matcher = noCdataPattern.matcher(vdbContent);
        
        while (matcher.find()) {
            String before = matcher.group(1);
            String content = matcher.group(2);
            String after = matcher.group(3);
            
            // Check if already has CDATA
            String trimmedContent = content.trim();
            if (trimmedContent.startsWith("<![CDATA[") && trimmedContent.endsWith("]]>")) {
                // Already has CDATA, keep as-is
                matcher.appendReplacement(result, Matcher.quoteReplacement(matcher.group(0)));
            } else {
                // Wrap in CDATA
                String wrapped = before + "\n      <![CDATA[\n" + trimmedContent + "\n]]>\n    " + after;
                matcher.appendReplacement(result, Matcher.quoteReplacement(wrapped));
                log("[VDB_MIGRATION] Wrapped metadata content in CDATA");
            }
        }
        matcher.appendTail(result);
        
        return result.toString();
    }

    private void redeployVDB(String vdbPath, int orgId, Integer userId) throws Exception {
        String vdbFileName = new File(vdbPath).getName();
        log("[VDB_MIGRATION] Redeploying VDB: " + vdbFileName);

        // Save the current file content before deployment (with CDATA preserved)
        String originalContent = readVdbAsText(vdbPath);
        
        Admin admin = AdminFactory.getInstance().createAdmin(
            TEIID_HOST, TEIID_PORT, TEIID_USER, TEIID_PASSWORD.toCharArray()
        );
        try (InputStream inputStream = new FileInputStream(vdbPath)) {
            admin.deploy(vdbFileName, inputStream);
            log("[VDB_MIGRATION] VDB deployed: " + vdbFileName);
        } finally {
            admin.close();
        }
        
        // Restore the original file content to preserve CDATA sections
        // Teiid's deploy() may have modified the file, stripping CDATA
        // The VDB is already loaded in Teiid's memory correctly
        Files.write(Paths.get(vdbPath), originalContent.getBytes(StandardCharsets.UTF_8));
        log("[VDB_MIGRATION] Restored VDB file with CDATA preserved: " + vdbPath);
    }

    private String findUserVDBPath(int orgId, int userId) {
        String vdbDir = CUSTOMER_BASE_PATH + "/" + orgId + "/" + userId + "/vdb";
        File dir = new File(vdbDir);
        if (!dir.exists() || !dir.isDirectory()) return null;
        File[] vdbFiles = dir.listFiles((d, name) -> name.endsWith("-vdb.xml"));
        if (vdbFiles != null && vdbFiles.length > 0) {
            return vdbFiles[0].getAbsolutePath();
        }
        return null;
    }

    private String findSharedVDBPath(int orgId) {
        // First try the shared VDB directory (new structure for shared projects)
        // This is where the shared_vdbs table points to
        String sharedVdbDir = CUSTOMER_BASE_PATH + "/" + orgId + "/shared/vdb";
        File sharedDir = new File(sharedVdbDir);
        if (sharedDir.exists() && sharedDir.isDirectory()) {
            File[] vdbFiles = sharedDir.listFiles((d, name) -> name.endsWith("-vdb.xml"));
            if (vdbFiles != null && vdbFiles.length > 0) {
                log("[VDB_MIGRATION] Found shared VDB in shared/vdb directory: " + vdbFiles[0].getAbsolutePath());
                return vdbFiles[0].getAbsolutePath();
            }
        }
        
        // Fallback to organization VDB directory (legacy structure)
        // This is where organization_vdbs table points to
        String orgVdbDir = CUSTOMER_BASE_PATH + "/" + orgId + "/vdb";
        File orgDir = new File(orgVdbDir);
        if (orgDir.exists() && orgDir.isDirectory()) {
            File[] vdbFiles = orgDir.listFiles((d, name) -> name.endsWith("-vdb.xml"));
            if (vdbFiles != null && vdbFiles.length > 0) {
                log("[VDB_MIGRATION] Found shared VDB in org vdb directory (legacy): " + vdbFiles[0].getAbsolutePath());
                return vdbFiles[0].getAbsolutePath();
            }
        }
        
        log("[VDB_MIGRATION] WARNING: No shared VDB found for org " + orgId);
        return null;
    }
}
