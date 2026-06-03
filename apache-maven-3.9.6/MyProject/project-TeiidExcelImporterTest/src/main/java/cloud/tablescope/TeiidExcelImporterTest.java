package cloud.tablescope;

import java.io.*;
import java.util.*;
import java.util.regex.*;
import javax.servlet.ServletException;
import javax.servlet.annotation.MultipartConfig;
import javax.servlet.annotation.WebServlet;
import javax.servlet.http.*;
import org.apache.poi.ss.usermodel.*;
import org.apache.poi.hssf.usermodel.HSSFWorkbook;
import org.apache.poi.xssf.usermodel.XSSFWorkbook;
import org.teiid.adminapi.Admin;
import org.teiid.adminapi.jboss.AdminFactory;

@WebServlet("/upload")
@MultipartConfig
public class TeiidExcelImporterTest extends HttpServlet {

    private TxtFileProcessor txtFileProcessor = new TxtFileProcessor();

    protected void doPost(HttpServletRequest request, HttpServletResponse response)
            throws ServletException, IOException {
        response.setHeader("Access-Control-Allow-Origin", "*");
        response.setHeader("Access-Control-Allow-Methods", "POST, GET, OPTIONS, DELETE");
        response.setHeader("Access-Control-Allow-Headers", "Content-Type, Access-Control-Allow-Headers, Authorization, X-Requested-With");
        response.setContentType("application/json");
        PrintWriter out = response.getWriter();
        StringBuilder jsonResponse = new StringBuilder("{");

        Part filePart = request.getPart("file");
        if (filePart == null || filePart.getSize() == 0) {
            jsonResponse.append("\"error\": \"Please select a file to upload.\"}");
            out.println(jsonResponse.toString());
            return;
        }

        String fileName = filePart.getSubmittedFileName();
        
        // Get organization ID and user ID from request parameters (passed from frontend)
        String orgIdParam = request.getParameter("org_id");
        int orgId = (orgIdParam != null && !orgIdParam.isEmpty()) ? Integer.parseInt(orgIdParam) : 0;
        
        String userIdParam = request.getParameter("user_id");
        int userId = (userIdParam != null && !userIdParam.isEmpty()) ? Integer.parseInt(userIdParam) : 0;
        
        // Get VDB type parameter (determines which VDB to update)
        String vdbType = request.getParameter("vdb_type");
        if (vdbType == null || vdbType.isEmpty()) {
            // Default to user for backward compatibility when userId is provided
            vdbType = (userId > 0) ? "user" : "org";
        }
        
        System.out.println("[TeiidExcelImporterTest] VDB type from request: " + vdbType);
        
        // Determine paths based on VDB type
        String uploadPath;
        String archivePath;
        String vdbFilePath;
        String vdbDeploymentName;
        
        if (orgId > 0) {
            // Multi-tenant paths for customer-specific folders
            String customerBase;
            
            if ("shared".equals(vdbType)) {
                // Shared VDB: use shared folders
                customerBase = "/opt/wildfly/teiidfiles/customers/" + orgId + "/shared";
                uploadPath = customerBase + "/uploads";
                archivePath = customerBase + "/uploads/archive";
                
                System.out.println("[TeiidExcelImporterTest] Using SHARED VDB for org " + orgId);
                
                // Find shared VDB
                vdbFilePath = findVDBFileForShared(orgId);
                
                if (vdbFilePath == null) {
                    System.out.println("[TeiidExcelImporterTest] Shared VDB not found for org " + orgId);
                }
            } else if ("user".equals(vdbType) && userId > 0) {
                // User-level VDB isolation: use user-specific folders
                customerBase = "/opt/wildfly/teiidfiles/customers/" + orgId + "/" + userId;
                uploadPath = customerBase + "/uploads";
                archivePath = customerBase + "/uploads/archive";
                
                System.out.println("[TeiidExcelImporterTest] Using USER VDB for org " + orgId + ", user " + userId);
                
                // Find user-specific VDB - DO NOT fall back to org VDB for user uploads
                // This prevents views from being added to the wrong VDB
                vdbFilePath = findVDBFileForUser(orgId, userId);
                
                if (vdbFilePath == null) {
                    // User VDB not found - auto-provision it from template
                    System.out.println("[TeiidExcelImporterTest] User VDB not found for org " + orgId + ", user " + userId + ". Auto-provisioning...");
                    vdbFilePath = autoProvisionUserVDB(orgId, userId);
                    
                    if (vdbFilePath == null) {
                        System.err.println("[TeiidExcelImporterTest] Failed to auto-provision user VDB for org " + orgId + ", user " + userId);
                        jsonResponse.append("\"error\": \"Failed to auto-provision user VDB. Please contact administrator.\"}");
                        out.println(jsonResponse.toString());
                        return;
                    }
                    System.out.println("[TeiidExcelImporterTest] User VDB auto-provisioned successfully: " + vdbFilePath);
                }
            } else {
                // Organization-level VDB (legacy mode)
                customerBase = "/opt/wildfly/teiidfiles/customers/" + orgId;
                uploadPath = customerBase + "/uploads";
                archivePath = customerBase + "/uploads/archive";
                
                System.out.println("[TeiidExcelImporterTest] Using ORGANIZATION-level VDB for org " + orgId);
                
                // Find organization-level VDB
                vdbFilePath = findVDBFileForOrg(orgId);
            }
            
            if (vdbFilePath == null) {
                jsonResponse.append("\"error\": \"VDB file not found for organization ").append(orgId);
                if (userId > 0) {
                    jsonResponse.append(", user ").append(userId);
                }
                jsonResponse.append(". Please provision VDB first.\"}");
                out.println(jsonResponse.toString());
                return;
            }
            
            // Extract VDB deployment name from file path
            File vdbFile = new File(vdbFilePath);
            vdbDeploymentName = vdbFile.getName();
            
            System.out.println("[TeiidExcelImporterTest] Using VDB file: " + vdbFilePath);
            System.out.println("[TeiidExcelImporterTest] VDB deployment name: " + vdbDeploymentName);
        } else {
            // Fallback to global paths for backward compatibility
            uploadPath = "/opt/wildfly/teiidfiles/excelFilesTest/";
            archivePath = "/opt/wildfly/teiidfiles/excelFilesTest/archive";
            vdbFilePath = "/opt/wildfly/teiidfiles/myvdbtest-vdb.xml";
            vdbDeploymentName = "myvdbtest-vdb.xml";
        }
        
        // Check if this is a replace operation
        String replaceParam = request.getParameter("replace");
        boolean shouldReplace = "true".equals(replaceParam);

        // File upload process
        String modifiedFileName = fileName.replaceAll("\\s+", "_");
        String filePath = uploadPath + "/" + modifiedFileName;
        
        // Check if file already exists (may have been uploaded by Redash)
        File targetFile = new File(filePath);
        if (!targetFile.exists() || shouldReplace) {
            // Only save file if it doesn't exist or we're replacing
            try (InputStream inputStream = filePart.getInputStream();
                 OutputStream outputStream = new FileOutputStream(targetFile)) {
                byte[] buffer = new byte[1024];
                int bytesRead;
                while ((bytesRead = inputStream.read(buffer)) != -1) {
                    outputStream.write(buffer, 0, bytesRead);
                }
            } catch (IOException e) {
                jsonResponse.append("\"error\": \"Failed to upload file: ").append(e.getMessage()).append("\"}");
                out.println(jsonResponse.toString());
                return;
            }
        } else {
            // File already exists, skip upload (Redash already saved it)
            System.out.println("[TeiidExcelImporterTest] File already exists, skipping upload: " + filePath);
        }

        // Create archive file with date and timestamp (only if we uploaded the file)
        if (!targetFile.exists() || shouldReplace) {
            String archiveFileName = generateArchiveFileName(fileName);
            File archiveDir = new File(archivePath);
            if (!archiveDir.exists()) {
                archiveDir.mkdirs();
            }
            try (InputStream inputStream = filePart.getInputStream();
                 OutputStream outputStream = new FileOutputStream(new File(archivePath, archiveFileName))) {
                byte[] buffer = new byte[1024];
                int bytesRead;
                while ((bytesRead = inputStream.read(buffer)) != -1) {
                    outputStream.write(buffer, 0, bytesRead);
                }
            } catch (IOException e) {
                jsonResponse.append("\"error\": \"Failed to archive file: ").append(e.getMessage()).append("\"}");
                out.println(jsonResponse.toString());
                return;
            }
        }

        try {
            if (fileName.toLowerCase().endsWith(".txt") || fileName.toLowerCase().endsWith(".csv")) {
                processTxtFile(filePath, fileName, vdbFilePath, vdbDeploymentName, jsonResponse, shouldReplace, response, orgId, userId, vdbType);
            } else {
                // If file already exists, read from disk instead of upload stream
                if (targetFile.exists() && !shouldReplace) {
                    processExcelFileFromDisk(filePath, fileName, vdbFilePath, vdbDeploymentName, jsonResponse, shouldReplace, response, orgId, userId, vdbType);
                } else {
                    processExcelFile(filePart, fileName, vdbFilePath, vdbDeploymentName, jsonResponse, shouldReplace, response, orgId, userId, vdbType);
                }
            }
        } catch (IOException e) {
            jsonResponse.append("\"error\": \"Failed to process file: ").append(e.getMessage()).append("\"}");
            response.setStatus(HttpServletResponse.SC_INTERNAL_SERVER_ERROR);
        } catch (Exception e) {
            jsonResponse.append("\"error\": \"An error occurred: ").append(e.getMessage()).append("\"}");
            response.setStatus(HttpServletResponse.SC_INTERNAL_SERVER_ERROR);
        }

        out.println(jsonResponse.toString());
    }

    private void processTxtFile(String filePath, String fileName, String vdbFilePath, String vdbDeploymentName, StringBuilder jsonResponse, boolean shouldReplace, HttpServletResponse response, int orgId, int userId, String vdbType) throws IOException {
        System.out.println("[TeiidExcelImporterTest] Processing TXT/CSV file: " + filePath);
        System.out.println("[TeiidExcelImporterTest] VDB file path: " + vdbFilePath);
        System.out.println("[TeiidExcelImporterTest] VDB type: " + vdbType + ", orgId: " + orgId + ", userId: " + userId);
        
        // Verify the TXT/CSV file exists before processing
        File txtFile = new File(filePath);
        if (!txtFile.exists()) {
            System.err.println("[TeiidExcelImporterTest] ERROR: TXT/CSV file does not exist at: " + filePath);
            jsonResponse.append("\"error\": \"TXT/CSV file not found at: " + filePath + "\"}");
            return;
        }
        if (!txtFile.canRead()) {
            System.err.println("[TeiidExcelImporterTest] ERROR: TXT/CSV file is not readable: " + filePath);
            jsonResponse.append("\"error\": \"TXT/CSV file is not readable: " + filePath + "\"}");
            return;
        }
        System.out.println("[TeiidExcelImporterTest] TXT/CSV file exists and is readable: " + filePath + " (" + txtFile.length() + " bytes)");
        
        // Acquire lock for this VDB to prevent race conditions with VDBManagementServlet
        if (!VDBLockManager.acquireLock(vdbFilePath)) {
            System.err.println("[TeiidExcelImporterTest] Failed to acquire VDB lock for TXT processing: " + vdbFilePath);
            jsonResponse.append("\"error\": \"VDB is currently being modified by another process. Please try again.\"}");
            return;
        }
        try {
            processTxtFileInternal(filePath, fileName, vdbFilePath, vdbDeploymentName, jsonResponse, shouldReplace, response, orgId, userId, vdbType);
        } catch (Exception e) {
            System.err.println("[TeiidExcelImporterTest] ERROR in processTxtFileInternal: " + e.getMessage());
            e.printStackTrace();
            jsonResponse.append("\"error\": \"Failed to process TXT/CSV file: " + e.getMessage() + "\"}");
        } finally {
            VDBLockManager.releaseLock(vdbFilePath);
        }
    }
    
    private void processTxtFileInternal(String filePath, String fileName, String vdbFilePath, String vdbDeploymentName, StringBuilder jsonResponse, boolean shouldReplace, HttpServletResponse response, int orgId, int userId, String vdbType) throws IOException {
        System.out.println("[TeiidExcelImporterTest] processTxtFileInternal starting for: " + filePath);
        List<String> columnNames = txtFileProcessor.getColumnNames(filePath);
        if (columnNames == null) {
            System.err.println("[TeiidExcelImporterTest] ERROR: Invalid column names in TXT file (null returned).");
            jsonResponse.append("\"error\": \"Invalid column names in file.\"}");
            return;
        }
        System.out.println("[TeiidExcelImporterTest] TXT file columns: " + columnNames);

        // Build relative file path with org/user folder prefix for multi-tenancy
        String relativeFilePath;
        if (orgId > 0) {
            if ("shared".equals(vdbType)) {
                // Shared VDB: use {org_id}/shared/uploads/filename.csv
                relativeFilePath = orgId + "/shared/uploads/" + fileName.replaceAll("\\s+", "_");
            } else if (userId > 0) {
                // User-level VDB: use {org_id}/{user_id}/uploads/filename.csv
                relativeFilePath = orgId + "/" + userId + "/uploads/" + fileName.replaceAll("\\s+", "_");
            } else {
                // Org-level VDB: use {org_id}/uploads/filename.csv
                relativeFilePath = orgId + "/uploads/" + fileName.replaceAll("\\s+", "_");
            }
        } else {
            // Use just filename for backward compatibility
            relativeFilePath = fileName.replaceAll("\\s+", "_");
        }
        
        System.out.println("[TeiidExcelImporterTest] CSV/TXT file relative path: " + relativeFilePath);
        
        // Validate that the file exists at the expected location
        String fullFilePath = "/opt/wildfly/teiidfiles/customers/" + relativeFilePath;
        File actualFile = new File(fullFilePath);
        if (!actualFile.exists()) {
            System.err.println("[TeiidExcelImporterTest] ERROR: File does not exist at expected location: " + fullFilePath);
            System.err.println("[TeiidExcelImporterTest] VDB type: " + vdbType + ", orgId: " + orgId + ", userId: " + userId);
            jsonResponse.append("\"error\": \"File not found at expected location: " + relativeFilePath + ". Please check VDB type configuration.\"}");
            return;
        }
        if (!actualFile.canRead()) {
            System.err.println("[TeiidExcelImporterTest] ERROR: File exists but cannot be read: " + fullFilePath);
            jsonResponse.append("\"error\": \"File exists but cannot be read: " + relativeFilePath + "\"}");
            return;
        }
        System.out.println("[TeiidExcelImporterTest] File validated successfully at: " + fullFilePath);

        String viewDefinition = txtFileProcessor.generateView(fileName, relativeFilePath, columnNames);

        // Check if the file can be read before proceeding
        String vdbContent = readFromFile(vdbFilePath);
        if (vdbContent == null) {
            jsonResponse.append("\"error\": \"Failed to read VDB file. Check file permissions or existence.\"}");
            return;
        }

        // Check if the view already exists
        // Generate view name with uppercase extension to match Excel file naming convention
        // e.g., "sales.txt" -> "sales_TXT", "data.csv" -> "data_CSV"
        String fileExtension = fileName.substring(fileName.lastIndexOf('.') + 1);
        String fileNameWithoutExt = fileName.substring(0, fileName.lastIndexOf('.'));
        String viewName = fileNameWithoutExt.replaceAll("\\s+", "_") + "_" + fileExtension.toUpperCase();
        boolean viewExists = vdbContent.contains("CREATE VIEW " + viewName)
                || vdbContent.contains("CREATE VIEW \"" + viewName + "\"");
        
        if (viewExists && !shouldReplace) {
            // Return conflict status with HTTP 409
            response.setStatus(HttpServletResponse.SC_CONFLICT); // 409
            jsonResponse.append("\"status\": \"conflict\",");
            jsonResponse.append("\"message\": \"View already exists.\",");
            jsonResponse.append("\"existingName\": \"").append(viewName).append("\",");
            jsonResponse.append("\"fileName\": \"").append(fileName).append("\",");
            jsonResponse.append("\"requiresConfirmation\": true}");
            return;
        }
        
        if (viewExists && shouldReplace) {
            // Remove existing view before adding new one
            // Use the same view name format with uppercase extension
            vdbContent = removeTxtView(vdbContent, viewName);
        }

        // Insert the view only once
        if (!vdbContent.contains(viewDefinition)) {
            String modifiedContent = insertBefore(vdbContent, "-- Place new View above", viewDefinition + "\n");
            if (modifiedContent == null) {
                jsonResponse.append("\"error\": \"Failed to modify VDB content.\"}");
                return;
            }
            writeToFile(vdbFilePath, modifiedContent);
        } else {
            jsonResponse.append("\"message\": \"View already exists in the VDB content.\"}");
        }

        // Invalidate Teiid cache BEFORE deploying VDB to ensure clean cache for new data
        // Use the same view name format with uppercase extension (e.g., sales_TXT)
        invalidateTeiidCache(viewName);
        
        // Deploy the modified VDB
        deployVDB(vdbFilePath, vdbDeploymentName);
        
        jsonResponse.append("\"status\": \"success\",");
        jsonResponse.append("\"message\": \"").append(shouldReplace ? "File replaced successfully." : "File uploaded successfully.").append("\",");
        jsonResponse.append("\"data\": {\"fileName\": \"").append(fileName).append("\"}}");
    }

private void processExcelFileFromDisk(String filePath, String fileName, String vdbFilePath, String vdbDeploymentName, StringBuilder jsonResponse, boolean shouldReplace, HttpServletResponse response, int orgId, int userId, String vdbType) throws IOException {
    System.out.println("[TeiidExcelImporterTest] Processing Excel file from disk: " + filePath);
    System.out.println("[TeiidExcelImporterTest] VDB file path: " + vdbFilePath);
    System.out.println("[TeiidExcelImporterTest] VDB type: " + vdbType + ", orgId: " + orgId + ", userId: " + userId);
    
    // Verify the Excel file exists before processing
    File excelFile = new File(filePath);
    if (!excelFile.exists()) {
        System.err.println("[TeiidExcelImporterTest] ERROR: Excel file does not exist at: " + filePath);
        jsonResponse.append("\"error\": \"Excel file not found at: " + filePath + "\"}");
        return;
    }
    if (!excelFile.canRead()) {
        System.err.println("[TeiidExcelImporterTest] ERROR: Excel file is not readable: " + filePath);
        jsonResponse.append("\"error\": \"Excel file is not readable: " + filePath + "\"}");
        return;
    }
    System.out.println("[TeiidExcelImporterTest] Excel file exists and is readable: " + filePath + " (" + excelFile.length() + " bytes)");
    
    // Acquire lock for this VDB to prevent race conditions with VDBManagementServlet
    if (!VDBLockManager.acquireLock(vdbFilePath)) {
        System.err.println("[TeiidExcelImporterTest] Failed to acquire VDB lock for: " + vdbFilePath);
        jsonResponse.append("\"error\": \"VDB is currently being modified by another process. Please try again.\"}");
        return;
    }
    try {
        processExcelFileFromDiskInternal(filePath, fileName, vdbFilePath, vdbDeploymentName, jsonResponse, shouldReplace, response, orgId, userId, vdbType);
    } catch (Exception e) {
        System.err.println("[TeiidExcelImporterTest] ERROR in processExcelFileFromDiskInternal: " + e.getMessage());
        e.printStackTrace();
        jsonResponse.append("\"error\": \"Failed to process Excel file: " + e.getMessage() + "\"}");
    } finally {
        VDBLockManager.releaseLock(vdbFilePath);
    }
}

private void processExcelFileFromDiskInternal(String filePath, String fileName, String vdbFilePath, String vdbDeploymentName, StringBuilder jsonResponse, boolean shouldReplace, HttpServletResponse response, int orgId, int userId, String vdbType) throws IOException {
    System.out.println("[TeiidExcelImporterTest] processExcelFileFromDiskInternal starting for: " + filePath);
    try (FileInputStream fis = new FileInputStream(filePath)) {
        System.out.println("[TeiidExcelImporterTest] File opened successfully, reading column names...");
        List<String> columnNames = getColumnNamesFromStream(fis, fileName);
        if (columnNames == null) {
            System.err.println("[TeiidExcelImporterTest] ERROR: Invalid column names in file (null returned). File may have empty header cells.");
            jsonResponse.append("\"error\": \"Invalid column names in file. Check for empty header cells.\"}");
            return;
        }
        System.out.println("[TeiidExcelImporterTest] Found " + columnNames.size() + " columns: " + columnNames);

        // Abort if fieldname is empty
        for (String columnName : columnNames) {
            if (columnName.isEmpty()) {
                System.err.println("[TeiidExcelImporterTest] ERROR: Empty fieldname found in column names.");
                jsonResponse.append("\"error\": \"Empty fieldname found. Aborting.\"}");
                return;
            }
        }

        // Re-open file to get workbook
        try (FileInputStream fis2 = new FileInputStream(filePath)) {
            Workbook workbook = getWorkbook(fis2, fileName);
            Sheet sheet = workbook.getSheetAt(0);
            String firstSheetName = workbook.getSheetName(0);

            // Extract file name without extension
            Pattern fileNamePattern = Pattern.compile("^(.*?)\\.(.*?)$");
            Matcher matcher = fileNamePattern.matcher(fileName);
            String fileNameWithoutExtension = "";
            String fileExtension = "";
            if (matcher.find()) {
                fileNameWithoutExtension = matcher.group(1);
                fileExtension = matcher.group(2);
            }

            // Build foreign table definition with relative file path for multi-tenancy
            String relativeFilePath;
            if (orgId > 0) {
                if ("shared".equals(vdbType)) {
                    // Shared VDB: use {org_id}/shared/uploads/filename.xlsx
                    relativeFilePath = orgId + "/shared/uploads/" + fileName.replaceAll("\\s+", "_");
                } else if (userId > 0) {
                    // User-level VDB: use {org_id}/{user_id}/uploads/filename.xlsx
                    relativeFilePath = orgId + "/" + userId + "/uploads/" + fileName.replaceAll("\\s+", "_");
                } else {
                    // Org-level VDB: use {org_id}/uploads/filename.xlsx
                    relativeFilePath = orgId + "/uploads/" + fileName.replaceAll("\\s+", "_");
                }
            } else {
                // Use just filename for backward compatibility
                relativeFilePath = fileName.replaceAll("\\s+", "_");
            }
            
            // Validate that the file exists at the expected location
            String fullFilePath = "/opt/wildfly/teiidfiles/customers/" + relativeFilePath;
            File actualFile = new File(fullFilePath);
            if (!actualFile.exists()) {
                System.err.println("[TeiidExcelImporterTest] ERROR: File does not exist at expected location: " + fullFilePath);
                System.err.println("[TeiidExcelImporterTest] VDB type: " + vdbType + ", orgId: " + orgId + ", userId: " + userId);
                jsonResponse.append("\"error\": \"File not found at expected location: " + relativeFilePath + ". Please check VDB type configuration.\"}");
                return;
            }
            if (!actualFile.canRead()) {
                System.err.println("[TeiidExcelImporterTest] ERROR: File exists but cannot be read: " + fullFilePath);
                jsonResponse.append("\"error\": \"File exists but cannot be read: " + relativeFilePath + "\"}");
                return;
            }
            System.out.println("[TeiidExcelImporterTest] File validated successfully at: " + fullFilePath);
            
            StringBuilder foreignTableBlock = new StringBuilder();
            foreignTableBlock.append("CREATE FOREIGN TABLE \"").append(fileNameWithoutExtension.replaceAll("\\s+", "_")).append("\"(\n");
            foreignTableBlock.append("\tROW_ID integer OPTIONS (SEARCHABLE 'All_Except_Like', \"teiid_excel:CELL_NUMBER\" 'ROW_ID'),\n");
            for (int i = 0; i < columnNames.size(); i++) {
                String columnName = columnNames.get(i);
                foreignTableBlock.append("\t").append(columnName.replaceAll("\\s+", "_")).append(" string OPTIONS (SEARCHABLE 'Unsearchable', \"teiid_excel:CELL_NUMBER\" '").append(i + 1).append("'),\n");
            }
            foreignTableBlock.append("\tCONSTRAINT PK0 PRIMARY KEY(ROW_ID)\n");
            foreignTableBlock.append(") OPTIONS (\"NAMEINSOURCE\" '").append(firstSheetName).append("', \"teiid_excel:FILE\" '").append(relativeFilePath).append("', \"teiid_excel:FIRST_DATA_ROW_NUMBER\" '2');");

            // Read VDB content
            String vdbContent = readFromFile(vdbFilePath);
            if (vdbContent == null) {
                jsonResponse.append("\"error\": \"Failed to read VDB file. Check file permissions or existence.\"}");
                return;
            }

            // Check if foreign table already exists
            String normalizedTableName = fileNameWithoutExtension.replaceAll("\\s+", "_");
            boolean foreignTableExists = vdbContent.contains("CREATE FOREIGN TABLE " + normalizedTableName)
                    || vdbContent.contains("CREATE FOREIGN TABLE \"" + normalizedTableName + "\"");
            
            if (foreignTableExists && !shouldReplace) {
                response.setStatus(HttpServletResponse.SC_CONFLICT);
                jsonResponse.append("\"status\": \"conflict\",");
                jsonResponse.append("\"message\": \"Foreign Table already exists.\",");
                jsonResponse.append("\"existingName\": \"").append(normalizedTableName).append("\",");
                jsonResponse.append("\"fileName\": \"").append(fileName).append("\",");
                jsonResponse.append("\"requiresConfirmation\": true}");
                return;
            }
            
            if (foreignTableExists && shouldReplace) {
                vdbContent = removeForeignTableAndView(vdbContent, normalizedTableName);
            }

            // Create view
            String viewName = fileNameWithoutExtension.replaceAll("\\s+", "_") + "_" + fileExtension.toUpperCase();
            String columnsList = String.join(", ", columnNames);
            String viewDefinition = "SELECT " + columnsList + " FROM ExcelSourceModel.\"" + fileNameWithoutExtension.replaceAll("\\s+", "_") + "\"";
            String createViewStatement = "CREATE VIEW \"" + viewName + "\" AS " + viewDefinition + ";";

            // Update VDB
            String modifiedContent = updateVDB(vdbFilePath, vdbContent, foreignTableBlock.toString(), createViewStatement);
            if (modifiedContent == null) {
                jsonResponse.append("\"error\": \"Failed to modify VDB content.\"}");
                return;
            }

            writeToFile(vdbFilePath, modifiedContent);

            // Invalidate cache
            String normalizedFileName = fileName.replaceAll("\\s+", "_");
            String tableName = normalizedFileName.substring(0, normalizedFileName.lastIndexOf('.')).toUpperCase() + "_" + 
                              normalizedFileName.substring(normalizedFileName.lastIndexOf('.') + 1).toUpperCase();
            invalidateTeiidCache(tableName);
            
            // Deploy VDB
            deployVDB(vdbFilePath, vdbDeploymentName);
            
            jsonResponse.append("\"status\": \"success\",");
            jsonResponse.append("\"message\": \"").append(shouldReplace ? "File replaced successfully." : "File uploaded successfully.").append("\",");
            jsonResponse.append("\"data\": {\"fileName\": \"").append(fileName).append("\"}}");
            
            workbook.close();
        }
    }
}

private void processExcelFile(Part filePart, String fileName, String vdbFilePath, String vdbDeploymentName, StringBuilder jsonResponse, boolean shouldReplace, HttpServletResponse response, int orgId, int userId, String vdbType) throws IOException {
    List<String> columnNames = getColumnNames(filePart);
    if (columnNames == null) {
        jsonResponse.append("\"error\": \"Invalid column names in file.\"}");
        return; // Abort if column names are invalid
    }

    // Abort if fieldname is empty
    for (String columnName : columnNames) {
        if (columnName.isEmpty()) {
            jsonResponse.append("\"error\": \"Empty fieldname found. Aborting.\"}");
            return;
        }
    }

    Workbook workbook = getWorkbook(filePart.getInputStream(), fileName);
    Sheet sheet = workbook.getSheetAt(0); // Assuming the first sheet is the one of interest

    // Extracting the name of the first sheet
    String firstSheetName = workbook.getSheetName(0);

    // Extract file name without extension using regex
    Pattern fileNamePattern = Pattern.compile("^(.*?)\\.(.*?)$");
    Matcher matcher = fileNamePattern.matcher(fileName);
    String fileNameWithoutExtension = "";
    String fileExtension = "";
    if (matcher.find()) {
        fileNameWithoutExtension = matcher.group(1);
        fileExtension = matcher.group(2); // Add this line to get the file extension
    }

    // Build foreign table definition with relative file path for multi-tenancy
    String relativeFilePath;
    if (orgId > 0) {
        if ("shared".equals(vdbType)) {
            // Shared VDB: use {org_id}/shared/uploads/filename.xlsx
            relativeFilePath = orgId + "/shared/uploads/" + fileName.replaceAll("\\s+", "_");
        } else if (userId > 0) {
            // User-level VDB: use {org_id}/{user_id}/uploads/filename.xlsx
            relativeFilePath = orgId + "/" + userId + "/uploads/" + fileName.replaceAll("\\s+", "_");
        } else {
            // Org-level VDB: use {org_id}/uploads/filename.xlsx
            relativeFilePath = orgId + "/uploads/" + fileName.replaceAll("\\s+", "_");
        }
    } else {
        // Use just filename for backward compatibility
        relativeFilePath = fileName.replaceAll("\\s+", "_");
    }
    
    // Validate that the file exists at the expected location
    String fullFilePath = "/opt/wildfly/teiidfiles/customers/" + relativeFilePath;
    File actualFile = new File(fullFilePath);
    if (!actualFile.exists()) {
        System.err.println("[TeiidExcelImporterTest] ERROR: File does not exist at expected location: " + fullFilePath);
        System.err.println("[TeiidExcelImporterTest] VDB type: " + vdbType + ", orgId: " + orgId + ", userId: " + userId);
        jsonResponse.append("\"error\": \"File not found at expected location: " + relativeFilePath + ". Please check VDB type configuration.\"}");
        workbook.close();
        return;
    }
    if (!actualFile.canRead()) {
        System.err.println("[TeiidExcelImporterTest] ERROR: File exists but cannot be read: " + fullFilePath);
        jsonResponse.append("\"error\": \"File exists but cannot be read: " + relativeFilePath + "\"}");
        workbook.close();
        return;
    }
    System.out.println("[TeiidExcelImporterTest] File validated successfully at: " + fullFilePath);
    
    StringBuilder foreignTableBlock = new StringBuilder();
    foreignTableBlock.append("CREATE FOREIGN TABLE \"").append(fileNameWithoutExtension.replaceAll("\\s+", "_")).append("\"(\n");
    foreignTableBlock.append("\tROW_ID integer OPTIONS (SEARCHABLE 'All_Except_Like', \"teiid_excel:CELL_NUMBER\" 'ROW_ID'),\n");
    for (int i = 0; i < columnNames.size(); i++) {
        String columnName = columnNames.get(i);
        foreignTableBlock.append("\t").append(columnName.replaceAll("\\s+", "_")).append(" string OPTIONS (SEARCHABLE 'Unsearchable', \"teiid_excel:CELL_NUMBER\" '").append(i + 1).append("'),\n");
    }
    foreignTableBlock.append("\tCONSTRAINT PK0 PRIMARY KEY(ROW_ID)\n");
    foreignTableBlock.append(") OPTIONS (\"NAMEINSOURCE\" '").append(firstSheetName).append("', \"teiid_excel:FILE\" '").append(relativeFilePath).append("', \"teiid_excel:FIRST_DATA_ROW_NUMBER\" '2');");

    // Check if the file can be read before proceeding
    String vdbContent = readFromFile(vdbFilePath);
    if (vdbContent == null) {
        jsonResponse.append("\"error\": \"Failed to read VDB file. Check file permissions or existence.\"}");
        return;
    }

    // Check if the foreign table already exists
    String normalizedTableName = fileNameWithoutExtension.replaceAll("\\s+", "_");
    boolean foreignTableExists = vdbContent.contains("CREATE FOREIGN TABLE " + normalizedTableName)
            || vdbContent.contains("CREATE FOREIGN TABLE \"" + normalizedTableName + "\"");
    
    if (foreignTableExists && !shouldReplace) {
        // Return conflict status with HTTP 409
        response.setStatus(HttpServletResponse.SC_CONFLICT); // 409
        jsonResponse.append("\"status\": \"conflict\",");
        jsonResponse.append("\"message\": \"Foreign Table already exists.\",");
        jsonResponse.append("\"existingName\": \"").append(normalizedTableName).append("\",");
        jsonResponse.append("\"fileName\": \"").append(fileName).append("\",");
        jsonResponse.append("\"requiresConfirmation\": true}");
        return;
    }
    
    if (foreignTableExists && shouldReplace) {
        // Remove existing foreign table and view before adding new ones
        vdbContent = removeForeignTableAndView(vdbContent, normalizedTableName);
    }

    // Modify view name to include file extension with an underscore
    String viewName = fileNameWithoutExtension.replaceAll("\\s+", "_") + "_" + fileExtension.toUpperCase();
    
    // Generate a comma-separated list of column names
    String columnsList = String.join(", ", columnNames);

    // Construct the view definition with explicit column names
    String viewDefinition = "SELECT " + columnsList + " FROM ExcelSourceModel.\"" + fileNameWithoutExtension.replaceAll("\\s+", "_") + "\"";
    String createViewStatement = "CREATE VIEW \"" + viewName + "\" AS " + viewDefinition + ";";

    // Ensure the insertion point string is preserved and duplicates are removed
    String modifiedContent = updateVDB(vdbFilePath, vdbContent, foreignTableBlock.toString(), createViewStatement);
    if (modifiedContent == null) {
        jsonResponse.append("\"error\": \"Failed to modify VDB content.\"}");
        return;
    }

    writeToFile(vdbFilePath, modifiedContent);

    // Invalidate Teiid cache BEFORE deploying VDB to ensure clean cache for new data
    String normalizedFileName = fileName.replaceAll("\\s+", "_");
    String tableName = normalizedFileName.substring(0, normalizedFileName.lastIndexOf('.')).toUpperCase() + "_" + 
                      normalizedFileName.substring(normalizedFileName.lastIndexOf('.') + 1).toUpperCase();
    invalidateTeiidCache(tableName);
    
    // Deploy the modified VDB
    deployVDB(vdbFilePath, vdbDeploymentName);
    
    jsonResponse.append("\"status\": \"success\",");
    jsonResponse.append("\"message\": \"").append(shouldReplace ? "File replaced successfully." : "File uploaded successfully.").append("\",");
    jsonResponse.append("\"data\": {\"fileName\": \"").append(fileName).append("\"}}");
}


    private List<String> getColumnNamesFromStream(InputStream inputStream, String fileName) throws IOException {
        List<String> columnNames = new ArrayList<>();
        Set<String> usedNames = new HashSet<>(); // Track used names to handle duplicates
        Workbook workbook = null;
        try {
            System.out.println("[TeiidExcelImporterTest] getColumnNamesFromStream: Opening workbook for " + fileName);
            workbook = getWorkbook(inputStream, fileName);
            Sheet sheet = workbook.getSheetAt(0);
            System.out.println("[TeiidExcelImporterTest] getColumnNamesFromStream: Sheet name = " + sheet.getSheetName());

            Row headerRow = sheet.getRow(0);
            if (headerRow == null) {
                System.err.println("[TeiidExcelImporterTest] getColumnNamesFromStream: Header row is null!");
                return null;
            }
            int numColumns = headerRow.getLastCellNum();
            System.out.println("[TeiidExcelImporterTest] getColumnNamesFromStream: Found " + numColumns + " columns in header row (including empty trailing cells)");

            for (int i = 0; i < numColumns; i++) {
                Cell headerCell = headerRow.getCell(i);
                if (headerCell == null) {
                    // Skip null cells at the end (common in Excel files with empty trailing columns)
                    System.out.println("[TeiidExcelImporterTest] getColumnNamesFromStream: Header cell " + i + " is null, stopping column scan");
                    break;
                }
                String cellValue = "";
                try {
                    cellValue = headerCell.getStringCellValue();
                } catch (Exception e) {
                    // Cell might not be a string type, try to get it as a different type
                    System.out.println("[TeiidExcelImporterTest] getColumnNamesFromStream: Cell " + i + " is not a string, trying numeric...");
                    try {
                        cellValue = String.valueOf((int) headerCell.getNumericCellValue());
                    } catch (Exception e2) {
                        System.err.println("[TeiidExcelImporterTest] getColumnNamesFromStream: Could not read cell " + i + " value: " + e2.getMessage());
                        break;
                    }
                }
                String columnName = cellValue.trim().replaceAll("\\s+", "_").replaceAll("[./:()]", "");
                if (columnName.isEmpty()) {
                    // Empty column name means we've reached the end of actual data columns
                    System.out.println("[TeiidExcelImporterTest] getColumnNamesFromStream: Column " + i + " has empty name, stopping column scan");
                    break;
                }
                // Fix: Prefix column names that start with a digit (invalid SQL identifiers)
                if (Character.isDigit(columnName.charAt(0))) {
                    String originalName = columnName;
                    columnName = "Col_" + columnName;
                    System.out.println("[TeiidExcelImporterTest] getColumnNamesFromStream: Column " + i + " starts with digit, renamed '" + originalName + "' to '" + columnName + "'");
                }
                if (columnName.equalsIgnoreCase("Date")) {
                    columnName += "_";
                }
                // Fix: Handle duplicate column names by appending suffix
                String baseColumnName = columnName;
                int suffix = 1;
                while (usedNames.contains(columnName.toUpperCase())) {
                    columnName = baseColumnName + "_" + suffix;
                    suffix++;
                    System.out.println("[TeiidExcelImporterTest] getColumnNamesFromStream: Duplicate column name, renamed to '" + columnName + "'");
                }
                usedNames.add(columnName.toUpperCase());
                System.out.println("[TeiidExcelImporterTest] getColumnNamesFromStream: Column " + i + " = '" + columnName + "'");
                columnNames.add(columnName);
            }
            
            if (columnNames.isEmpty()) {
                System.err.println("[TeiidExcelImporterTest] getColumnNamesFromStream: No valid column names found!");
                return null;
            }
            
            System.out.println("[TeiidExcelImporterTest] getColumnNamesFromStream: Successfully extracted " + columnNames.size() + " column names");
        } catch (IOException e) {
            System.err.println("[TeiidExcelImporterTest] getColumnNamesFromStream: IOException - " + e.getMessage());
            throw new IOException("Failed to process column names: " + e.getMessage(), e);
        } finally {
            if (workbook != null) {
                workbook.close();
            }
        }
        return columnNames;
    }

    private List<String> getColumnNames(Part filePart) throws IOException {
        List<String> columnNames = new ArrayList<>();
        Set<String> usedNames = new HashSet<>(); // Track used names to handle duplicates
        Workbook workbook = null;
        try {
            String fileName = filePart.getSubmittedFileName();
            System.out.println("[TeiidExcelImporterTest] getColumnNames: Opening workbook for " + fileName);
            workbook = getWorkbook(filePart.getInputStream(), fileName);
            Sheet sheet = workbook.getSheetAt(0);
            System.out.println("[TeiidExcelImporterTest] getColumnNames: Sheet name = " + sheet.getSheetName());

            Row headerRow = sheet.getRow(0);
            if (headerRow == null) {
                System.err.println("[TeiidExcelImporterTest] getColumnNames: Header row is null!");
                return null;
            }
            int numColumns = headerRow.getLastCellNum();
            System.out.println("[TeiidExcelImporterTest] getColumnNames: Found " + numColumns + " columns in header row");

            for (int i = 0; i < numColumns; i++) {
                Cell headerCell = headerRow.getCell(i);
                if (headerCell == null) {
                    // Skip null cells at the end (common in Excel files with empty trailing columns)
                    System.out.println("[TeiidExcelImporterTest] getColumnNames: Header cell " + i + " is null, stopping column scan");
                    break;
                }
                String cellValue = "";
                try {
                    cellValue = headerCell.getStringCellValue();
                } catch (Exception e) {
                    // Cell might not be a string type, try to get it as a different type
                    System.out.println("[TeiidExcelImporterTest] getColumnNames: Cell " + i + " is not a string, trying numeric...");
                    try {
                        cellValue = String.valueOf((int) headerCell.getNumericCellValue());
                    } catch (Exception e2) {
                        System.err.println("[TeiidExcelImporterTest] getColumnNames: Could not read cell " + i + " value: " + e2.getMessage());
                        break;
                    }
                }
                String columnName = cellValue.trim().replaceAll("\\s+", "_").replaceAll("[./:()]", "");
                if (columnName.isEmpty()) {
                    // Empty column name means we've reached the end of actual data columns
                    System.out.println("[TeiidExcelImporterTest] getColumnNames: Column " + i + " has empty name, stopping column scan");
                    break;
                }
                // Fix: Prefix column names that start with a digit (invalid SQL identifiers)
                if (Character.isDigit(columnName.charAt(0))) {
                    String originalName = columnName;
                    columnName = "Col_" + columnName;
                    System.out.println("[TeiidExcelImporterTest] getColumnNames: Column " + i + " starts with digit, renamed '" + originalName + "' to '" + columnName + "'");
                }
                if (columnName.equalsIgnoreCase("Date")) {
                    columnName += "_";
                }
                // Fix: Handle duplicate column names by appending suffix
                String baseColumnName = columnName;
                int suffix = 1;
                while (usedNames.contains(columnName.toUpperCase())) {
                    columnName = baseColumnName + "_" + suffix;
                    suffix++;
                    System.out.println("[TeiidExcelImporterTest] getColumnNames: Duplicate column name, renamed to '" + columnName + "'");
                }
                usedNames.add(columnName.toUpperCase());
                System.out.println("[TeiidExcelImporterTest] getColumnNames: Column " + i + " = '" + columnName + "'");
                columnNames.add(columnName);
            }
            
            if (columnNames.isEmpty()) {
                System.err.println("[TeiidExcelImporterTest] getColumnNames: No valid column names found!");
                return null;
            }
            
            System.out.println("[TeiidExcelImporterTest] getColumnNames: Successfully extracted " + columnNames.size() + " column names");
        } catch (IOException e) {
            System.err.println("[TeiidExcelImporterTest] getColumnNames: IOException - " + e.getMessage());
            throw new IOException("Failed to process column names: " + e.getMessage(), e);
        } finally {
            if (workbook != null) {
                workbook.close();
            }
        }
        return columnNames;
    }

    private Workbook getWorkbook(InputStream inputStream, String fileName) throws IOException {
        if (fileName.toLowerCase().endsWith(".xls")) {
            return new HSSFWorkbook(inputStream);
        } else if (fileName.toLowerCase().endsWith(".xlsx")) {
            return new XSSFWorkbook(inputStream);
        } else {
            throw new IllegalArgumentException("Invalid file format. Only XLS and XLSX files are supported.");
        }
    }

    private String readFromFile(String filePath) throws IOException {
        if (filePath == null || filePath.isEmpty()) {
            throw new IllegalArgumentException("File path is null or empty.");
        }

        StringBuilder content = new StringBuilder();
        try (BufferedReader reader = new BufferedReader(new FileReader(filePath))) {
            String line;
            while ((line = reader.readLine()) != null) {
                content.append(line).append("\n");
            }
        }
        return content.toString();
    }

    private void writeToFile(String filePath, String content) throws IOException {
        if (filePath == null || filePath.isEmpty()) {
            throw new IllegalArgumentException("File path is null or empty.");
        }

        if (content == null) {
            throw new IllegalArgumentException("Content is null.");
        }

        try (BufferedWriter writer = new BufferedWriter(new FileWriter(filePath))) {
            writer.write(content);
        }
    }

    private String updateVDB(String vdbFilePath, String vdbContent, String foreignTableBlock, String createViewStatement) throws IOException {
        if (vdbFilePath == null || vdbFilePath.isEmpty()) {
            throw new IllegalArgumentException("VDB file path is null or empty.");
        }

        if (vdbContent == null || vdbContent.isEmpty()) {
            throw new IllegalArgumentException("VDB content is null or empty.");
        }

        if (foreignTableBlock == null || foreignTableBlock.isEmpty()) {
            throw new IllegalArgumentException("Foreign table block is null or empty.");
        }

        if (createViewStatement == null || createViewStatement.isEmpty()) {
            throw new IllegalArgumentException("Create view statement is null or empty.");
        }

        // Ensure we only insert if it doesn't already exist
        if (!vdbContent.contains(foreignTableBlock)) {
            vdbContent = insertAfter(vdbContent, "-- Place Foreign Table Below", foreignTableBlock + "\n");
        }

        if (!vdbContent.contains(createViewStatement)) {
            vdbContent = insertBefore(vdbContent, "-- Place new View above", createViewStatement + "\n");
        }

        return vdbContent;
    }

    private void deployVDB(String vdbFilePath, String vdbDeploymentName) {
        try {
            Admin admin = AdminFactory.getInstance().createAdmin("localhost", 9990, "admin", "admin".toCharArray());
            try (InputStream inputStream = new FileInputStream(vdbFilePath)) {
                admin.deploy(vdbDeploymentName, inputStream);
            }
        } catch (Exception e) {
            e.printStackTrace();
        }
    }

    private String insertBefore(String originalContent, String searchText, String insertion) {
        if (originalContent == null || originalContent.isEmpty()) {
            return null;
        }

        if (searchText == null || searchText.isEmpty()) {
            return originalContent + "\n" + insertion;
        }

        int index = originalContent.indexOf(searchText);
        if (index != -1) {
            // Add the insertion before the searchText
            return originalContent.substring(0, index) + insertion + "\n" + searchText + "\n" + originalContent.substring(index + searchText.length());
        } else {
            // If search text is not found, append the insertion at the end
            return originalContent + "\n" + insertion;
        }
    }

    private String insertAfter(String originalContent, String searchText, String insertion) {
        if (originalContent == null || originalContent.isEmpty()) {
            return null;
        }

        if (searchText == null || searchText.isEmpty()) {
            return originalContent + "\n" + insertion;
        }

        int index = originalContent.indexOf(searchText);
        if (index != -1) {
            return originalContent.substring(0, index + searchText.length()) + "\n" + insertion + "\n" + originalContent.substring(index + searchText.length());
        } else {
            // If search text is not found, append the insertion at the end
            return originalContent + "\n" + insertion;
        }
    }

    // Function to generate archive file name with date and timestamp
    private String generateArchiveFileName(String fileName) {
        Calendar calendar = Calendar.getInstance();
        String timestamp = String.format("%tY%<tm%<td-%<tH%<tM%<tS", calendar);
        String archiveFileName = fileName.replace(".", "-" + timestamp + ".");
        return archiveFileName;
    }
    
    // Remove foreign table and view from VDB content
    private String removeForeignTableAndView(String vdbContent, String normalizedName) {
        String modifiedContent = vdbContent;
        
        // Pattern to match the foreign table block.
        // A CREATE FOREIGN TABLE statement has nested parentheses (each column has its
        // own OPTIONS (...) and the table has a trailing OPTIONS (...)), so a paren-based
        // matcher fails for multi-column tables. The statement is reliably terminated by
        // the first ';' (column/option values never contain ';'), so consume up to it.
        // The optional surrounding quotes let this match both quoted and unquoted forms,
        // and replaceAll removes any duplicate definitions of the same table.
        String foreignTablePattern = "CREATE FOREIGN TABLE \"?" + Pattern.quote(normalizedName) + "\"?" +
                                    "\\s*\\([^;]*;";
        Pattern ftPattern = Pattern.compile(foreignTablePattern, Pattern.DOTALL | Pattern.CASE_INSENSITIVE);
        Matcher ftMatcher = ftPattern.matcher(modifiedContent);
        
        if (ftMatcher.find()) {
            modifiedContent = ftMatcher.replaceAll("");
        }
        
        // Pattern to match the view with extension suffix (e.g., tablename_XLSX)
        String viewPattern = "CREATE VIEW \"?" + Pattern.quote(normalizedName) + "_[A-Z]+\"?\\s+AS\\s+SELECT[^;]+;+";
        Pattern viewPatternCompiled = Pattern.compile(viewPattern, Pattern.DOTALL | Pattern.CASE_INSENSITIVE);
        Matcher viewMatcher = viewPatternCompiled.matcher(modifiedContent);
        
        if (viewMatcher.find()) {
            modifiedContent = viewMatcher.replaceAll("");
        }
        
        // Clean up extra blank lines
        modifiedContent = modifiedContent.replaceAll("\\n{3,}", "\n\n");
        
        return modifiedContent;
    }
    
    // Remove TXT/CSV view from VDB content
    private String removeTxtView(String vdbContent, String viewName) {
        String modifiedContent = vdbContent;
        
        // Pattern to match TXT/CSV views
        String upperName = viewName.replaceAll("([\\\\\\[\\](){}.*+?^$|])", "\\\\$1");
        String txtViewPattern = "CREATE VIEW \"?" + upperName + "\"?\\s*.*?AS\\s+SELECT.*?;+";
        Pattern txtViewPatternCompiled = Pattern.compile(txtViewPattern, Pattern.DOTALL | Pattern.CASE_INSENSITIVE);
        Matcher txtViewMatcher = txtViewPatternCompiled.matcher(modifiedContent);
        
        if (txtViewMatcher.find()) {
            modifiedContent = txtViewMatcher.replaceAll("");
        }
        
        // Clean up extra blank lines
        modifiedContent = modifiedContent.replaceAll("\\n{3,}", "\n\n");
        
        return modifiedContent;
    }
    
    /**
     * Invalidate Teiid result set cache for a specific table after file upload/replace.
     * This ensures queries return fresh data immediately after file updates.
     */
    private void invalidateTeiidCache(String tableName) {
        try {
            Admin admin = AdminFactory.getInstance().createAdmin(
                "localhost", 9990, "admin", "admin".toCharArray()
            );
            
            // Clear all result set cache (Teiid API doesn't support granular table-level clearing)
            admin.clearCache("QUERY_SERVICE_RESULT_SET_CACHE");
            
            System.out.println("[TeiidExcelImporter] Cache invalidated for table: " + tableName);
            admin.close();
            
        } catch (Exception e) {
            // Log error but don't fail the upload
            System.err.println("[TeiidExcelImporter] Failed to invalidate cache: " + e.getMessage());
            e.printStackTrace();
        }
    }
    
    /**
     * Find VDB file for a given organization ID.
     * Searches in the customer VDB folder for any file ending with -vdb.xml
     * 
     * @param orgId Organization ID
     * @return Full path to VDB file, or null if not found
     */
    private String findVDBFileForOrg(int orgId) {
        String vdbFolder = "/opt/wildfly/teiidfiles/customers/" + orgId + "/vdb/";
        File folder = new File(vdbFolder);
        
        System.out.println("[TeiidExcelImporterTest] Searching for org VDB in: " + vdbFolder);
        
        if (!folder.exists() || !folder.isDirectory()) {
            System.out.println("[TeiidExcelImporterTest] Org VDB folder does not exist: " + vdbFolder);
            return null;
        }
        
        // Find first VDB file (should only be one per organization)
        File[] vdbFiles = folder.listFiles(new FilenameFilter() {
            public boolean accept(File dir, String name) {
                return name.endsWith("-vdb.xml");
            }
        });
        
        if (vdbFiles != null && vdbFiles.length > 0) {
            String vdbPath = vdbFiles[0].getAbsolutePath();
            System.out.println("[TeiidExcelImporterTest] Found org VDB file: " + vdbPath);
            return vdbPath;
        }
        
        System.out.println("[TeiidExcelImporterTest] No org VDB file found in: " + vdbFolder);
        return null;
    }
    
    /**
     * Find VDB file for a given user within an organization.
     * Searches in the user-specific VDB folder for any file ending with -vdb.xml
     * This supports user-level VDB isolation.
     * 
     * @param orgId Organization ID
     * @param userId User ID
     * @return Full path to VDB file, or null if not found
     */
    private String findVDBFileForUser(int orgId, int userId) {
        String vdbFolder = "/opt/wildfly/teiidfiles/customers/" + orgId + "/" + userId + "/vdb/";
        File folder = new File(vdbFolder);
        
        System.out.println("[TeiidExcelImporterTest] Searching for user VDB in: " + vdbFolder);
        
        if (!folder.exists() || !folder.isDirectory()) {
            System.out.println("[TeiidExcelImporterTest] User VDB folder does not exist: " + vdbFolder);
            return null;
        }
        
        // Find first VDB file (should only be one per user)
        File[] vdbFiles = folder.listFiles(new FilenameFilter() {
            public boolean accept(File dir, String name) {
                return name.endsWith("-vdb.xml");
            }
        });
        
        if (vdbFiles != null && vdbFiles.length > 0) {
            String vdbPath = vdbFiles[0].getAbsolutePath();
            System.out.println("[TeiidExcelImporterTest] Found user VDB file: " + vdbPath);
            return vdbPath;
        }
        
        System.out.println("[TeiidExcelImporterTest] No user VDB file found in: " + vdbFolder);
        return null;
    }

    /**
     * Find VDB file for shared project within an organization.
     * Searches in the shared VDB folder for any file ending with -vdb.xml
     * This supports project-level shared VDB.
     * 
     * @param orgId Organization ID
     * @return Full path to VDB file, or null if not found
     */
    private String findVDBFileForShared(int orgId) {
        String vdbFolder = "/opt/wildfly/teiidfiles/customers/" + orgId + "/shared/vdb/";
        File folder = new File(vdbFolder);
        
        System.out.println("[TeiidExcelImporterTest] Searching for shared VDB in: " + vdbFolder);
        
        if (!folder.exists() || !folder.isDirectory()) {
            System.out.println("[TeiidExcelImporterTest] Shared VDB folder does not exist: " + vdbFolder);
            return null;
        }
        
        // Find first VDB file (should only be one per org)
        File[] vdbFiles = folder.listFiles(new FilenameFilter() {
            public boolean accept(File dir, String name) {
                return name.endsWith("-vdb.xml");
            }
        });
        
        if (vdbFiles != null && vdbFiles.length > 0) {
            String vdbPath = vdbFiles[0].getAbsolutePath();
            System.out.println("[TeiidExcelImporterTest] Found shared VDB file: " + vdbPath);
            return vdbPath;
        }
        
        System.out.println("[TeiidExcelImporterTest] No shared VDB file found in: " + vdbFolder);
        return null;
    }

    /**
     * Auto-provision a user VDB from template when it doesn't exist.
     * This allows file uploads to work even if the user hasn't accessed the project yet.
     * 
     * @param orgId Organization ID
     * @param userId User ID
     * @return Full path to the newly created VDB file, or null if provisioning failed
     */
    private String autoProvisionUserVDB(int orgId, int userId) {
        String vdbBasePath = "/opt/wildfly/teiidfiles";
        String customerFolder = vdbBasePath + "/customers/" + orgId + "/" + userId;
        String vdbFolder = customerFolder + "/vdb";
        String uploadsFolder = customerFolder + "/uploads";
        String templatePath = vdbBasePath + "/vdb_template/vdb_ template.xml";
        
        // Generate a random 7-digit VDB ID
        int vdbId = 1000000 + new java.util.Random().nextInt(9000000);
        String vdbFilePath = vdbFolder + "/" + vdbId + "-vdb.xml";
        
        System.out.println("[TeiidExcelImporterTest] Auto-provisioning user VDB: " + vdbFilePath);
        
        try {
            // 1. Create folders if they don't exist
            File customerDir = new File(customerFolder);
            if (!customerDir.exists()) {
                if (!customerDir.mkdirs()) {
                    System.err.println("[TeiidExcelImporterTest] Failed to create customer folder: " + customerFolder);
                    return null;
                }
                System.out.println("[TeiidExcelImporterTest] Created customer folder: " + customerFolder);
            }
            
            File vdbDir = new File(vdbFolder);
            if (!vdbDir.exists()) {
                if (!vdbDir.mkdirs()) {
                    System.err.println("[TeiidExcelImporterTest] Failed to create VDB folder: " + vdbFolder);
                    return null;
                }
                System.out.println("[TeiidExcelImporterTest] Created VDB folder: " + vdbFolder);
            }
            
            File uploadsDir = new File(uploadsFolder);
            if (!uploadsDir.exists()) {
                if (!uploadsDir.mkdirs()) {
                    System.err.println("[TeiidExcelImporterTest] Failed to create uploads folder: " + uploadsFolder);
                    return null;
                }
                System.out.println("[TeiidExcelImporterTest] Created uploads folder: " + uploadsFolder);
            }
            
            // 2. Read template VDB
            File templateFile = new File(templatePath);
            if (!templateFile.exists()) {
                System.err.println("[TeiidExcelImporterTest] Template VDB not found at: " + templatePath);
                return null;
            }
            
            String vdbXml = readFromFile(templatePath);
            if (vdbXml == null) {
                System.err.println("[TeiidExcelImporterTest] Failed to read template VDB");
                return null;
            }
            System.out.println("[TeiidExcelImporterTest] Template VDB loaded from: " + templatePath);
            
            // 3. Replace VDB name with generated ID
            vdbXml = vdbXml.replaceFirst("<vdb\\s+name=\"[^\"]+\"", "<vdb name=\"" + vdbId + "\"");
            System.out.println("[TeiidExcelImporterTest] VDB name replaced with: " + vdbId);
            
            // Update any hardcoded VDB name references
            vdbXml = vdbXml.replaceAll("'MyVDBTest'", "'" + vdbId + "'");
            vdbXml = vdbXml.replaceAll("'vdb_production'", "'" + vdbId + "'");
            
            // 4. Update file paths to use user-specific relative paths
            // The ParentDirectory comment should reflect the user's uploads folder
            String relativePathPrefix = orgId + "/" + userId + "/uploads/";
            vdbXml = vdbXml.replaceAll("ParentDirectory=/opt/wildfly/teiidfiles/customers[^)]*\\)", 
                                       "ParentDirectory=/opt/wildfly/teiidfiles/customers/" + orgId + "/" + userId + "/uploads)");
            System.out.println("[TeiidExcelImporterTest] File paths updated for user: " + relativePathPrefix);
            
            // 5. Write VDB file
            writeToFile(vdbFilePath, vdbXml);
            System.out.println("[TeiidExcelImporterTest] VDB file written to: " + vdbFilePath);
            
            // 6. Deploy VDB to Teiid
            String vdbDeploymentName = vdbId + "-vdb.xml";
            deployVDB(vdbFilePath, vdbDeploymentName);
            System.out.println("[TeiidExcelImporterTest] VDB deployed to Teiid: " + vdbDeploymentName);
            
            return vdbFilePath;
            
        } catch (Exception e) {
            System.err.println("[TeiidExcelImporterTest] Error auto-provisioning user VDB: " + e.getMessage());
            e.printStackTrace();
            return null;
        }
    }
}
