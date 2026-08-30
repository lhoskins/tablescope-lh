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

@WebServlet("/upload")
@MultipartConfig
public class TeiidExcelImporterTest extends HttpServlet {

    private TxtFileProcessor txtFileProcessor = new TxtFileProcessor();
    private VDBFileLocator vdbFileLocator = new VDBFileLocator();
    private TeiidDeployHelper deployHelper = new TeiidDeployHelper();

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

        // Scopes a "shared" VDB to one project instead of the whole org, so
        // two shared projects never resolve to the same VDB/folder. Null
        // (absent) falls back to the legacy org-wide shared VDB.
        String projectIdParam = request.getParameter("project_id");
        Integer projectId = (projectIdParam != null && !projectIdParam.isEmpty())
            ? Integer.valueOf(projectIdParam) : null;

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
                // Shared VDB, scoped per project when project_id is given
                // (falls back to the legacy org-wide shared folder otherwise).
                customerBase = projectId != null
                    ? "/opt/wildfly/teiidfiles/customers/" + orgId + "/shared/" + projectId
                    : "/opt/wildfly/teiidfiles/customers/" + orgId + "/shared";
                uploadPath = customerBase + "/uploads";
                archivePath = customerBase + "/uploads/archive";

                System.out.println("[TeiidExcelImporterTest] Using SHARED VDB for org " + orgId
                    + (projectId != null ? ", project " + projectId : " (org-wide, legacy)"));

                // Find shared VDB
                vdbFilePath = vdbFileLocator.findVDBFileForShared(orgId, projectId);

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
                vdbFilePath = vdbFileLocator.findVDBFileForUser(orgId, userId);

                if (vdbFilePath == null) {
                    // User VDB not found - auto-provision it from template
                    System.out.println("[TeiidExcelImporterTest] User VDB not found for org " + orgId + ", user " + userId + ". Auto-provisioning...");
                    vdbFilePath = vdbFileLocator.autoProvisionUserVDB(orgId, userId);

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
                vdbFilePath = vdbFileLocator.findVDBFileForOrg(orgId);
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
            String archiveFileName = VDBXmlEditHelper.generateArchiveFileName(fileName);
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
            String lowerFileName = fileName.toLowerCase();
            if (lowerFileName.endsWith(".txt") || lowerFileName.endsWith(".csv") || lowerFileName.endsWith(".tsv")) {
                processTxtFile(filePath, fileName, vdbFilePath, vdbDeploymentName, jsonResponse, shouldReplace, response, orgId, userId, vdbType, projectId);
            } else {
                // If file already exists, read from disk instead of upload stream
                if (targetFile.exists() && !shouldReplace) {
                    processExcelFileFromDisk(filePath, fileName, vdbFilePath, vdbDeploymentName, jsonResponse, shouldReplace, response, orgId, userId, vdbType, projectId);
                } else {
                    processExcelFile(filePart, fileName, vdbFilePath, vdbDeploymentName, jsonResponse, shouldReplace, response, orgId, userId, vdbType, projectId);
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

    private void processTxtFile(String filePath, String fileName, String vdbFilePath, String vdbDeploymentName, StringBuilder jsonResponse, boolean shouldReplace, HttpServletResponse response, int orgId, int userId, String vdbType, Integer projectId) throws IOException {
        System.out.println("[TeiidExcelImporterTest] Processing TXT/CSV file: " + filePath);
        System.out.println("[TeiidExcelImporterTest] VDB file path: " + vdbFilePath);
        System.out.println("[TeiidExcelImporterTest] VDB type: " + vdbType + ", orgId: " + orgId + ", userId: " + userId);

        // Verify the TXT/CSV file exists before processing
        File txtFile = new File(filePath);
        if (!txtFile.exists()) {
            System.err.println("[TeiidExcelImporterTest] ERROR: TXT/CSV file does not exist at: " + filePath);
            jsonResponse.append("\"error\": \"TXT/CSV file not found at: ").append(filePath).append("\"}");
            return;
        }
        if (!txtFile.canRead()) {
            System.err.println("[TeiidExcelImporterTest] ERROR: TXT/CSV file is not readable: " + filePath);
            jsonResponse.append("\"error\": \"TXT/CSV file is not readable: ").append(filePath).append("\"}");
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
            processTxtFileInternal(filePath, fileName, vdbFilePath, vdbDeploymentName, jsonResponse, shouldReplace, response, orgId, userId, vdbType, projectId);
        } catch (Exception e) {
            System.err.println("[TeiidExcelImporterTest] ERROR in processTxtFileInternal: " + e.getMessage());
            e.printStackTrace();
            jsonResponse.append("\"error\": \"Failed to process TXT/CSV file: ").append(e.getMessage()).append("\"}");
        } finally {
            VDBLockManager.releaseLock(vdbFilePath);
        }
    }

    private void processTxtFileInternal(String filePath, String fileName, String vdbFilePath, String vdbDeploymentName, StringBuilder jsonResponse, boolean shouldReplace, HttpServletResponse response, int orgId, int userId, String vdbType, Integer projectId) throws IOException {
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
                // Shared VDB, scoped per project when project_id is given:
                // {org_id}/shared/{project_id}/uploads/filename.csv.
                relativeFilePath = projectId != null
                    ? orgId + "/shared/" + projectId + "/uploads/" + fileName.replaceAll("\\s+", "_")
                    : orgId + "/shared/uploads/" + fileName.replaceAll("\\s+", "_");
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
            jsonResponse.append("\"error\": \"File not found at expected location: ").append(relativeFilePath).append(". Please check VDB type configuration.\"}");
            return;
        }
        if (!actualFile.canRead()) {
            System.err.println("[TeiidExcelImporterTest] ERROR: File exists but cannot be read: " + fullFilePath);
            jsonResponse.append("\"error\": \"File exists but cannot be read: ").append(relativeFilePath).append("\"}");
            return;
        }
        System.out.println("[TeiidExcelImporterTest] File validated successfully at: " + fullFilePath);

        String viewDefinition = txtFileProcessor.generateView(fileName, relativeFilePath, columnNames);

        // Check if the file can be read before proceeding
        String vdbContent = VDBXmlEditHelper.readFromFile(vdbFilePath);
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
            vdbContent = VDBXmlEditHelper.removeTxtView(vdbContent, viewName);
        }

        // Insert the view only once
        if (!vdbContent.contains(viewDefinition)) {
            String modifiedContent = VDBXmlEditHelper.insertBefore(vdbContent, "-- Place new View above", viewDefinition + "\n");
            if (modifiedContent == null) {
                jsonResponse.append("\"error\": \"Failed to modify VDB content.\"}");
                return;
            }
            VDBXmlEditHelper.writeToFile(vdbFilePath, modifiedContent);
        } else {
            jsonResponse.append("\"message\": \"View already exists in the VDB content.\"}");
        }

        // Invalidate Teiid cache BEFORE deploying VDB to ensure clean cache for new data
        // Use the same view name format with uppercase extension (e.g., sales_TXT)
        deployHelper.invalidateTeiidCache(viewName);

        // Deploy the modified VDB
        try {
            deployHelper.deployVDB(vdbFilePath, vdbDeploymentName);
        } catch (Exception e) {
            e.printStackTrace();
        }

        jsonResponse.append("\"status\": \"success\",");
        jsonResponse.append("\"message\": \"").append(shouldReplace ? "File replaced successfully." : "File uploaded successfully.").append("\",");
        jsonResponse.append("\"data\": {\"fileName\": \"").append(fileName).append("\"}}");
    }

    private void processExcelFileFromDisk(String filePath, String fileName, String vdbFilePath, String vdbDeploymentName, StringBuilder jsonResponse, boolean shouldReplace, HttpServletResponse response, int orgId, int userId, String vdbType, Integer projectId) throws IOException {
        System.out.println("[TeiidExcelImporterTest] Processing Excel file from disk: " + filePath);
        System.out.println("[TeiidExcelImporterTest] VDB file path: " + vdbFilePath);
        System.out.println("[TeiidExcelImporterTest] VDB type: " + vdbType + ", orgId: " + orgId + ", userId: " + userId);

        // Verify the Excel file exists before processing
        File excelFile = new File(filePath);
        if (!excelFile.exists()) {
            System.err.println("[TeiidExcelImporterTest] ERROR: Excel file does not exist at: " + filePath);
            jsonResponse.append("\"error\": \"Excel file not found at: ").append(filePath).append("\"}");
            return;
        }
        if (!excelFile.canRead()) {
            System.err.println("[TeiidExcelImporterTest] ERROR: Excel file is not readable: " + filePath);
            jsonResponse.append("\"error\": \"Excel file is not readable: ").append(filePath).append("\"}");
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
            processExcelFileFromDiskInternal(filePath, fileName, vdbFilePath, vdbDeploymentName, jsonResponse, shouldReplace, response, orgId, userId, vdbType, projectId);
        } catch (Exception e) {
            System.err.println("[TeiidExcelImporterTest] ERROR in processExcelFileFromDiskInternal: " + e.getMessage());
            e.printStackTrace();
            jsonResponse.append("\"error\": \"Failed to process Excel file: ").append(e.getMessage()).append("\"}");
        } finally {
            VDBLockManager.releaseLock(vdbFilePath);
        }
    }

    private void processExcelFileFromDiskInternal(String filePath, String fileName, String vdbFilePath, String vdbDeploymentName, StringBuilder jsonResponse, boolean shouldReplace, HttpServletResponse response, int orgId, int userId, String vdbType, Integer projectId) throws IOException {
        System.out.println("[TeiidExcelImporterTest] processExcelFileFromDiskInternal starting for: " + filePath);
        try (FileInputStream fis = new FileInputStream(filePath)) {
            System.out.println("[TeiidExcelImporterTest] File opened successfully, reading column names...");
            List<String> columnNames = ExcelColumnReader.getColumnNamesFromStream(fis, fileName);
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
                Workbook workbook = ExcelColumnReader.getWorkbook(fis2, fileName);
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

                // Build relative file path with org/user folder prefix for multi-tenancy
                String relativeFilePath;
                if (orgId > 0) {
                    if ("shared".equals(vdbType)) {
                        // Shared VDB, scoped per project when project_id is
                        // given: {org_id}/shared/{project_id}/uploads/filename.xlsx.
                        relativeFilePath = projectId != null
                            ? orgId + "/shared/" + projectId + "/uploads/" + fileName.replaceAll("\\s+", "_")
                            : orgId + "/shared/uploads/" + fileName.replaceAll("\\s+", "_");
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
                    jsonResponse.append("\"error\": \"File not found at expected location: ").append(relativeFilePath).append(". Please check VDB type configuration.\"}");
                    return;
                }
                if (!actualFile.canRead()) {
                    System.err.println("[TeiidExcelImporterTest] ERROR: File exists but cannot be read: " + fullFilePath);
                    jsonResponse.append("\"error\": \"File exists but cannot be read: ").append(relativeFilePath).append("\"}");
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
                String vdbContent = VDBXmlEditHelper.readFromFile(vdbFilePath);
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
                    vdbContent = VDBXmlEditHelper.removeForeignTableAndView(vdbContent, normalizedTableName);
                }

                // Create view
                String viewName = fileNameWithoutExtension.replaceAll("\\s+", "_") + "_" + fileExtension.toUpperCase();
                String columnsList = String.join(", ", columnNames);
                String viewDefinition = "SELECT " + columnsList + " FROM ExcelSourceModel.\"" + fileNameWithoutExtension.replaceAll("\\s+", "_") + "\"";
                String createViewStatement = "CREATE VIEW \"" + viewName + "\" AS " + viewDefinition + ";";

                // Update VDB
                String modifiedContent = VDBXmlEditHelper.updateVDB(vdbFilePath, vdbContent, foreignTableBlock.toString(), createViewStatement);
                if (modifiedContent == null) {
                    jsonResponse.append("\"error\": \"Failed to modify VDB content.\"}");
                    return;
                }

                VDBXmlEditHelper.writeToFile(vdbFilePath, modifiedContent);

                // Invalidate cache
                String normalizedFileName = fileName.replaceAll("\\s+", "_");
                String tableName = normalizedFileName.substring(0, normalizedFileName.lastIndexOf('.')).toUpperCase() + "_" +
                                  normalizedFileName.substring(normalizedFileName.lastIndexOf('.') + 1).toUpperCase();
                deployHelper.invalidateTeiidCache(tableName);

                // Deploy VDB
                try {
                    deployHelper.deployVDB(vdbFilePath, vdbDeploymentName);
                } catch (Exception e) {
                    e.printStackTrace();
                }

                jsonResponse.append("\"status\": \"success\",");
                jsonResponse.append("\"message\": \"").append(shouldReplace ? "File replaced successfully." : "File uploaded successfully.").append("\",");
                jsonResponse.append("\"data\": {\"fileName\": \"").append(fileName).append("\"}}");

                workbook.close();
            }
        }
    }

    private void processExcelFile(Part filePart, String fileName, String vdbFilePath, String vdbDeploymentName, StringBuilder jsonResponse, boolean shouldReplace, HttpServletResponse response, int orgId, int userId, String vdbType, Integer projectId) throws IOException {
        List<String> columnNames = ExcelColumnReader.getColumnNames(filePart);
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

        Workbook workbook = ExcelColumnReader.getWorkbook(filePart.getInputStream(), fileName);
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

        // Build relative file path with org/user folder prefix for multi-tenancy
        String relativeFilePath;
        if (orgId > 0) {
            if ("shared".equals(vdbType)) {
                // Shared VDB, scoped per project when project_id is given:
                // {org_id}/shared/{project_id}/uploads/filename.xlsx.
                relativeFilePath = projectId != null
                    ? orgId + "/shared/" + projectId + "/uploads/" + fileName.replaceAll("\\s+", "_")
                    : orgId + "/shared/uploads/" + fileName.replaceAll("\\s+", "_");
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
            jsonResponse.append("\"error\": \"File not found at expected location: ").append(relativeFilePath).append(". Please check VDB type configuration.\"}");
            workbook.close();
            return;
        }
        if (!actualFile.canRead()) {
            System.err.println("[TeiidExcelImporterTest] ERROR: File exists but cannot be read: " + fullFilePath);
            jsonResponse.append("\"error\": \"File exists but cannot be read: ").append(relativeFilePath).append("\"}");
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
        String vdbContent = VDBXmlEditHelper.readFromFile(vdbFilePath);
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
            vdbContent = VDBXmlEditHelper.removeForeignTableAndView(vdbContent, normalizedTableName);
        }

        // Modify view name to include file extension with an underscore
        String viewName = fileNameWithoutExtension.replaceAll("\\s+", "_") + "_" + fileExtension.toUpperCase();

        // Generate a comma-separated list of column names
        String columnsList = String.join(", ", columnNames);

        // Construct the view definition with explicit column names
        String viewDefinition = "SELECT " + columnsList + " FROM ExcelSourceModel.\"" + fileNameWithoutExtension.replaceAll("\\s+", "_") + "\"";
        String createViewStatement = "CREATE VIEW \"" + viewName + "\" AS " + viewDefinition + ";";

        // Ensure the insertion point string is preserved and duplicates are removed
        String modifiedContent = VDBXmlEditHelper.updateVDB(vdbFilePath, vdbContent, foreignTableBlock.toString(), createViewStatement);
        if (modifiedContent == null) {
            jsonResponse.append("\"error\": \"Failed to modify VDB content.\"}");
            return;
        }

        VDBXmlEditHelper.writeToFile(vdbFilePath, modifiedContent);

        // Invalidate Teiid cache BEFORE deploying VDB to ensure clean cache for new data
        String normalizedFileName = fileName.replaceAll("\\s+", "_");
        String tableName = normalizedFileName.substring(0, normalizedFileName.lastIndexOf('.')).toUpperCase() + "_" +
                          normalizedFileName.substring(normalizedFileName.lastIndexOf('.') + 1).toUpperCase();
        deployHelper.invalidateTeiidCache(tableName);

        // Deploy the modified VDB
        try {
            deployHelper.deployVDB(vdbFilePath, vdbDeploymentName);
        } catch (Exception e) {
            e.printStackTrace();
        }

        jsonResponse.append("\"status\": \"success\",");
        jsonResponse.append("\"message\": \"").append(shouldReplace ? "File replaced successfully." : "File uploaded successfully.").append("\",");
        jsonResponse.append("\"data\": {\"fileName\": \"").append(fileName).append("\"}}");
    }
}
