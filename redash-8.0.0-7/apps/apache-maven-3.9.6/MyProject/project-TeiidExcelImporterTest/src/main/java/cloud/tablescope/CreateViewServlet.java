// CreateViewServlet.java
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


@WebServlet("/createview")
public class CreateViewServlet extends HttpServlet {

    protected void doPost(HttpServletRequest request, HttpServletResponse response)
            throws ServletException, IOException {
        response.setHeader("Access-Control-Allow-Origin", "*");
        response.setHeader("Access-Control-Allow-Methods", "POST, GET, OPTIONS, DELETE");
        response.setHeader("Access-Control-Allow-Headers", "Content-Type, Access-Control-Allow-Headers, Authorization, X-Requested-With");
        response.setContentType("application/json");
        PrintWriter out = response.getWriter();
        StringBuilder jsonResponse = new StringBuilder("{");

        String viewName = request.getParameter("viewName");
        String encodedSqlStatement = request.getParameter("sqlStatement");

        if (viewName == null || viewName.isEmpty()) {
            jsonResponse.append("\"error\": \"View name is required.\"}");
            out.println(jsonResponse.toString());
            return;
        }

        if (encodedSqlStatement == null || encodedSqlStatement.isEmpty()) {
            jsonResponse.append("\"error\": \"SQL statement is required.\"}");
            out.println(jsonResponse.toString());
            return;
        }

        String decodedSqlStatement = java.net.URLDecoder.decode(encodedSqlStatement, "UTF-8");
        String createViewStatement = "CREATE VIEW " + viewName + " AS " + decodedSqlStatement + ";";

        String vdbFilePath = "/opt/wildfly/teiidfiles/myvdbtest-vdb.xml";

        try {
            String vdbContent = readFromFile(vdbFilePath);
            if (vdbContent == null) {
                jsonResponse.append("\"error\": \"Failed to read VDB file. Check file permissions or existence.\"}");
                out.println(jsonResponse.toString());
                return;
            }

            if (!vdbContent.contains(createViewStatement)) {
                String modifiedContent = insertBefore(vdbContent, "-- Place new View above", createViewStatement + "\n");
                if (modifiedContent == null) {
                    jsonResponse.append("\"error\": \"Failed to modify VDB content.\"}");
                    out.println(jsonResponse.toString());
                    return;
                }
                writeToFile(vdbFilePath, modifiedContent);
            } else {
                jsonResponse.append("\"message\": \"View already exists in the VDB content.\"}");
                out.println(jsonResponse.toString());
                return;
            }

            deployVDB(vdbFilePath);
            jsonResponse.append("\"message\": \"View added and VDB deployed successfully.\"}");
        } catch (IOException e) {
            jsonResponse.append("\"error\": \"Failed to process file: ").append(e.getMessage()).append("\"}");
        } catch (Exception e) {
            jsonResponse.append("\"error\": \"An error occurred: ").append(e.getMessage()).append("\"}");
        }

        out.println(jsonResponse.toString());
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

    private String insertBefore(String originalContent, String searchText, String insertion) {
        if (originalContent == null || originalContent.isEmpty()) {
            return null;
        }

        if (searchText == null || searchText.isEmpty()) {
            return originalContent + "\n" + insertion;
        }

        int index = originalContent.indexOf(searchText);
        if (index != -1) {
            return originalContent.substring(0, index) + insertion + "\n" + searchText + "\n" + originalContent.substring(index + searchText.length());
        } else {
            return originalContent + "\n" + insertion;
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
