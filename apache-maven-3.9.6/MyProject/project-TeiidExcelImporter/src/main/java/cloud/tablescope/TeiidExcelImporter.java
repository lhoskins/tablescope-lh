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
public class TeiidExcelImporter extends HttpServlet {

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
        String uploadPath = "/opt/wildfly/teiidfiles/excelFiles";
        String archivePath = "/opt/wildfly/teiidfiles/excelFiles/archive";
        String vdbFilePath = "/opt/wildfly/teiidfiles/myvdb-vdb.xml";

        // File upload process
        String modifiedFileName = fileName.replaceAll("\\s+", "_");
        String filePath = uploadPath + "/" + modifiedFileName;
        try (InputStream inputStream = filePart.getInputStream();
             OutputStream outputStream = new FileOutputStream(new File(filePath))) {
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

        // Create archive file with date and timestamp
        String archiveFileName = generateArchiveFileName(fileName);
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

        try {
            if (fileName.toLowerCase().endsWith(".txt") || fileName.toLowerCase().endsWith(".csv")) {
                processTxtFile(filePath, fileName, vdbFilePath, jsonResponse);
            } else {
                processExcelFile(filePart, fileName, vdbFilePath, jsonResponse);
            }
        } catch (IOException e) {
            jsonResponse.append("\"error\": \"Failed to process file: ").append(e.getMessage()).append("\"}");
        } catch (Exception e) {
            jsonResponse.append("\"error\": \"An error occurred: ").append(e.getMessage()).append("\"}");
        }

        out.println(jsonResponse.toString());
    }

    private void processTxtFile(String filePath, String fileName, String vdbFilePath, StringBuilder jsonResponse) throws IOException {
        List<String> columnNames = txtFileProcessor.getColumnNames(filePath);
        if (columnNames == null) {
            jsonResponse.append("\"error\": \"Invalid column names in file.\"}");
            return;
        }

        String viewDefinition = txtFileProcessor.generateView(fileName, columnNames);

        // Check if the file can be read before proceeding
        String vdbContent = readFromFile(vdbFilePath);
        if (vdbContent == null) {
            jsonResponse.append("\"error\": \"Failed to read VDB file. Check file permissions or existence.\"}");
            return;
        }

        // Check if the view already exists
        String viewName = fileName.replaceAll("\\s+", "_").replaceAll("\\.", "_").toUpperCase();
        if (vdbContent.contains("CREATE VIEW " + viewName)) {
            jsonResponse.append("\"error\": \"View already exists. Aborting.\"}");
            return;
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

        // Deploy the modified VDB
        deployVDB(vdbFilePath);
        jsonResponse.append("\"data\": {\"fileName\": \"").append(fileName).append("\"}}");
    }

    private void processExcelFile(Part filePart, String fileName, String vdbFilePath, StringBuilder jsonResponse) throws IOException {
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

        StringBuilder foreignTableBlock = new StringBuilder();
        foreignTableBlock.append("CREATE FOREIGN TABLE ").append(fileNameWithoutExtension.replaceAll("\\s+", "_")).append("(\n");
        foreignTableBlock.append("\tROW_ID integer OPTIONS (SEARCHABLE 'All_Except_Like', \"teiid_excel:CELL_NUMBER\" 'ROW_ID'),\n");
        for (int i = 0; i < columnNames.size(); i++) {
            String columnName = columnNames.get(i);
            foreignTableBlock.append("\t").append(columnName.replaceAll("\\s+", "_")).append(" string OPTIONS (SEARCHABLE 'Unsearchable', \"teiid_excel:CELL_NUMBER\" '").append(i + 1).append("'),\n");
        }
        foreignTableBlock.append("\tCONSTRAINT PK0 PRIMARY KEY(ROW_ID)\n");
        foreignTableBlock.append(") OPTIONS (\"NAMEINSOURCE\" '").append(firstSheetName).append("', \"teiid_excel:FILE\" '").append(fileName.replaceAll("\\s+", "_")).append("', \"teiid_excel:FIRST_DATA_ROW_NUMBER\" '2');");

        // Check if the file can be read before proceeding
        String vdbContent = readFromFile(vdbFilePath);
        if (vdbContent == null) {
            jsonResponse.append("\"error\": \"Failed to read VDB file. Check file permissions or existence.\"}");
            return;
        }

        // Check if the foreign table already exists
        if (vdbContent.contains("CREATE FOREIGN TABLE " + fileNameWithoutExtension.replaceAll("\\s+", "_"))) {
            jsonResponse.append("\"error\": \"Foreign Table already exists. Aborting.\"}");
            return;
        }

        // Modify view name to include file extension with an underscore
        String viewName = fileNameWithoutExtension.replaceAll("\\s+", "_") + "_" + fileExtension.toUpperCase();
        String viewDefinition = "SELECT * FROM ExcelSourceModel." + fileNameWithoutExtension.replaceAll("\\s+", "_") + ";";
        String createViewStatement = "CREATE VIEW " + viewName + " AS " + viewDefinition + ";";

        // Ensure the insertion point string is preserved and duplicates are removed
        String modifiedContent = updateVDB(vdbFilePath, vdbContent, foreignTableBlock.toString(), createViewStatement);
        if (modifiedContent == null) {
            jsonResponse.append("\"error\": \"Failed to modify VDB content.\"}");
            return;
        }

        writeToFile(vdbFilePath, modifiedContent);
        jsonResponse.append("\"message\": \"Foreign Table and View added successfully.\",");

        // Deploy the modified VDB
        deployVDB(vdbFilePath);
        jsonResponse.append("\"message\": \"VDB deployed successfully.\",");
        jsonResponse.append("\"data\": {\"fileName\": \"").append(fileName).append("\"}}");
    }

    private List<String> getColumnNames(Part filePart) throws IOException {
        List<String> columnNames = new ArrayList<>();
        Workbook workbook = null;
        try {
            workbook = getWorkbook(filePart.getInputStream(), filePart.getSubmittedFileName());
            Sheet sheet = workbook.getSheetAt(0); // Assuming the first sheet is the one of interest

            Row headerRow = sheet.getRow(0);
            if (headerRow == null) {
                return null; // No header row found in the Excel sheet
            }
            int numColumns = headerRow.getLastCellNum();

            for (int i = 0; i < numColumns; i++) {
                Cell headerCell = headerRow.getCell(i);
                if (headerCell == null) {
                    return null; // Invalid Column Headers Found
                }
                String columnName = headerCell.getStringCellValue().trim().replaceAll("\\s+", "_")
                        .replaceAll("[./:()]", ""); // Removing . / : ( ) from column names
                if (columnName.equalsIgnoreCase("Date")) {
                    columnName += "_"; // Add an underscore if column name is exactly "Date"
                }
                columnNames.add(columnName);
            }
        } catch (IOException e) {
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

    private void deployVDB(String vdbFilePath) {
        try {
            Admin admin = AdminFactory.getInstance().createAdmin("64.52.108.62", 10000, "admin", "admin".toCharArray());
            try (InputStream inputStream = new FileInputStream(vdbFilePath)) {
                admin.deploy("myvdb-vdb.xml", inputStream);
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
}
