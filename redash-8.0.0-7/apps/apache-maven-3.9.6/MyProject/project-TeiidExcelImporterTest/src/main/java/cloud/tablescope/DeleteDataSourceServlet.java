package cloud.tablescope;

import java.io.*;
import java.nio.file.*;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.regex.*;
import javax.servlet.ServletException;
import javax.servlet.annotation.WebServlet;
import javax.servlet.http.*;
import org.teiid.adminapi.Admin;
import org.teiid.adminapi.jboss.AdminFactory;

@WebServlet("/deleteDataSource")
public class DeleteDataSourceServlet extends HttpServlet {

    protected void doPost(HttpServletRequest request, HttpServletResponse response)
            throws ServletException, IOException {
        response.setHeader("Access-Control-Allow-Origin", "*");
        response.setHeader("Access-Control-Allow-Methods", "POST, GET, OPTIONS, DELETE");
        response.setHeader("Access-Control-Allow-Headers", "Content-Type, Access-Control-Allow-Headers, Authorization, X-Requested-With");
        response.setContentType("application/json");
        PrintWriter out = response.getWriter();
        StringBuilder jsonResponse = new StringBuilder("{");

        String dataSourceName = request.getParameter("dataSourceName");
        if (dataSourceName == null || dataSourceName.trim().isEmpty()) {
            jsonResponse.append("\"error\": \"Data source name is required.\"}");
            out.println(jsonResponse.toString());
            return;
        }

        String vdbFilePath = "/opt/wildfly/teiidfiles/myvdbtest-vdb.xml";
        
        try {
            String vdbContent = readFromFile(vdbFilePath);
            if (vdbContent == null) {
                jsonResponse.append("\"error\": \"Failed to read VDB file.\"}");
                out.println(jsonResponse.toString());
                return;
            }

            String normalizedName = dataSourceName.replaceAll("\\s+", "_");
            String modifiedContent = removeForeignTableAndView(vdbContent, normalizedName);
            
            int originalLength = vdbContent.length();
            int modifiedLength = modifiedContent.length();
            int removedChars = originalLength - modifiedLength;
            
            if (modifiedContent.equals(vdbContent)) {
                System.out.println("[DeleteDataSource] ⚠️ No changes made to VDB");
                jsonResponse.append("\"status\": \"no_match\",");
                jsonResponse.append("\"message\": \"No matching foreign table or view found for: ").append(dataSourceName).append("\"}");
            } else {
                System.out.println("[DeleteDataSource] VDB modified: removed " + removedChars + " characters");
                
                // Archive the file before updating VDB
                String archivedFile = archiveFile(normalizedName);
                if (archivedFile != null) {
                    System.out.println("[DeleteDataSource] ✓ File archived: " + archivedFile);
                }
                
                writeToFile(vdbFilePath, modifiedContent);
                System.out.println("[DeleteDataSource] ✓ VDB file updated");
                deployVDB(vdbFilePath);
                System.out.println("[DeleteDataSource] ✓ VDB deployed");
                
                jsonResponse.append("\"status\": \"success\",");
                jsonResponse.append("\"message\": \"Data source deleted and file archived successfully.\",");
                jsonResponse.append("\"dataSourceName\": \"").append(dataSourceName).append("\",");
                jsonResponse.append("\"archivedFile\": \"").append(archivedFile != null ? archivedFile : "none").append("\",");
                jsonResponse.append("\"removedCharacters\": ").append(removedChars).append("}");
            }
        } catch (Exception e) {
            jsonResponse.append("\"error\": \"Failed to delete data source: ").append(e.getMessage()).append("\"}");
        }

        out.println(jsonResponse.toString());
    }

    protected void doOptions(HttpServletRequest request, HttpServletResponse response)
            throws ServletException, IOException {
        response.setHeader("Access-Control-Allow-Origin", "*");
        response.setHeader("Access-Control-Allow-Methods", "POST, GET, OPTIONS, DELETE");
        response.setHeader("Access-Control-Allow-Headers", "Content-Type, Access-Control-Allow-Headers, Authorization, X-Requested-With");
        response.setStatus(HttpServletResponse.SC_OK);
    }

    private String removeForeignTableAndView(String vdbContent, String normalizedName) {
        String modifiedContent = vdbContent;
        
        System.out.println("========================================");
        System.out.println("[DeleteDataSource] Removing: " + normalizedName);
        
        // Strip extension suffix for foreign table name
        String foreignTableName = normalizedName.replaceAll("_[A-Z]+$", "");
        String viewName = normalizedName;
        
        System.out.println("[DeleteDataSource] Foreign table: " + foreignTableName);
        System.out.println("[DeleteDataSource] View: " + viewName);
        
        // SIMPLE REGEX: Match CREATE FOREIGN TABLE <name> ... up to the next CREATE or ]]>
        String ftPattern = "CREATE\\s+FOREIGN\\s+TABLE\\s+" + Pattern.quote(foreignTableName) + 
                          "\\s*\\(.*?\\)\\s*OPTIONS\\s*\\(.*?\\)\\s*;\\s*";
        Pattern ftCompiled = Pattern.compile(ftPattern, Pattern.DOTALL | Pattern.CASE_INSENSITIVE);
        Matcher ftMatcher = ftCompiled.matcher(modifiedContent);
        
        if (ftMatcher.find()) {
            modifiedContent = ftMatcher.replaceAll("");
            System.out.println("[DeleteDataSource] ✓ Removed foreign table: " + foreignTableName);
        }
        
        // Remove view with extension suffix (Excel)
        String viewPattern = "CREATE\\s+VIEW\\s+" + Pattern.quote(viewName) + 
                           "\\s+AS\\s+SELECT.*?;+\\s*";
        Pattern viewCompiled = Pattern.compile(viewPattern, Pattern.DOTALL | Pattern.CASE_INSENSITIVE);
        Matcher viewMatcher = viewCompiled.matcher(modifiedContent);
        
        if (viewMatcher.find()) {
            modifiedContent = viewMatcher.replaceAll("");
            System.out.println("[DeleteDataSource] ✓ Removed view: " + viewName);
        }
        
        // Remove CSV/TXT view (with TEXTTABLE)
        String csvPattern = "CREATE\\s+VIEW\\s+" + Pattern.quote(viewName.toUpperCase()) + 
                          "\\s*\\(.*?\\)\\s*AS\\s+SELECT.*?TEXTTABLE.*?;+\\s*";
        Pattern csvCompiled = Pattern.compile(csvPattern, Pattern.DOTALL | Pattern.CASE_INSENSITIVE);
        Matcher csvMatcher = csvCompiled.matcher(modifiedContent);
        
        if (csvMatcher.find()) {
            modifiedContent = csvMatcher.replaceAll("");
            System.out.println("[DeleteDataSource] ✓ Removed CSV/TXT view: " + viewName);
        }
        
        // Clean up extra blank lines
        modifiedContent = modifiedContent.replaceAll("\\n{3,}", "\n\n");
        
        System.out.println("========================================");
        return modifiedContent;
    }

    private String readFromFile(String filePath) throws IOException {
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
        try (BufferedWriter writer = new BufferedWriter(new FileWriter(filePath))) {
            writer.write(content);
        }
    }

    /**
     * Archives a file by moving it from the main directory to the archive folder
     * with a timestamp appended to the filename.
     * 
     * @param normalizedName The normalized data source name (e.g., "upload_users_CSV")
     * @return The archived filename, or null if file not found or archiving failed
     */
    private String archiveFile(String normalizedName) {
        String uploadPath = "/opt/wildfly/teiidfiles/excelFilesTest/";
        String archivePath = "/opt/wildfly/teiidfiles/excelFilesTest/archive/";
        
        // Extract the base name without extension suffix (e.g., "upload_users" from "upload_users_CSV")
        String baseName = normalizedName.replaceAll("_[A-Z]+$", "");
        
        // Try to find the file with case-insensitive search
        File uploadDir = new File(uploadPath);
        String[] possibleExtensions = {".xlsx", ".xls", ".csv", ".txt"};
        String fileName = null;
        String fileExtension = null;
        
        // List all files in directory and find matching file (case-insensitive)
        File[] files = uploadDir.listFiles();
        if (files != null) {
            for (File file : files) {
                if (file.isFile()) {
                    String currentFileName = file.getName();
                    // Check if filename matches (case-insensitive) with any extension
                    for (String ext : possibleExtensions) {
                        if (currentFileName.equalsIgnoreCase(baseName + ext)) {
                            fileName = currentFileName;
                            fileExtension = ext;
                            System.out.println("[DeleteDataSource] Found file: " + fileName);
                            break;
                        }
                    }
                    if (fileName != null) break;
                }
            }
        }
        
        if (fileName == null) {
            System.out.println("[DeleteDataSource] ⚠️ File not found for archiving: " + baseName);
            System.out.println("[DeleteDataSource] Searched in: " + uploadPath);
            return null;
        }
        
        try {
            // Generate archive filename with timestamp
            // Use the actual filename's base (without extension) to preserve original case
            String actualBaseName = fileName.substring(0, fileName.lastIndexOf('.'));
            SimpleDateFormat sdf = new SimpleDateFormat("yyyyMMdd-HHmmss");
            String timestamp = sdf.format(new Date());
            String archiveFileName = actualBaseName + "-" + timestamp + fileExtension;
            
            // Ensure archive directory exists
            File archiveDir = new File(archivePath);
            if (!archiveDir.exists()) {
                archiveDir.mkdirs();
            }
            
            // Move file to archive
            Path sourcePath = Paths.get(uploadPath + fileName);
            Path targetPath = Paths.get(archivePath + archiveFileName);
            Files.move(sourcePath, targetPath, StandardCopyOption.REPLACE_EXISTING);
            
            System.out.println("[DeleteDataSource] File moved: " + fileName + " → " + archiveFileName);
            return archiveFileName;
            
        } catch (IOException e) {
            System.err.println("[DeleteDataSource] Failed to archive file: " + e.getMessage());
            e.printStackTrace();
            return null;
        }
    }

    private void deployVDB(String vdbFilePath) {
        try {
            Admin admin = AdminFactory.getInstance().createAdmin("64.52.108.62", 10000, "admin", "admin".toCharArray());
            try (InputStream inputStream = new FileInputStream(vdbFilePath)) {
                admin.deploy("myvdbtest-vdb.xml", inputStream);
            }
        } catch (Exception e) {
            e.printStackTrace();
        }
    }
}
