import java.io.BufferedReader;
import java.io.BufferedWriter;
import java.io.FileReader;
import java.io.FileWriter;
import java.io.IOException;
import javax.servlet.ServletException;
import javax.servlet.annotation.MultipartConfig;
import javax.servlet.annotation.WebServlet;
import javax.servlet.http.HttpServlet;
import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpServletResponse;

@WebServlet("/update-vdb")
@MultipartConfig
public class VDBUpdater extends HttpServlet {

    protected void doPost(HttpServletRequest request, HttpServletResponse response)
            throws ServletException, IOException {
        String vdbFilePath = "/opt/wildfly/teiidfiles/myvdb-vdb.xml";
        String foreignTableBlock = "CREATE FOREIGN TABLE Sheet1 (\n" +
                "      ROW_ID integer OPTIONS (SEARCHABLE 'All_Except_Like', \"teiid_excel:CELL_NUMBER\" 'ROW_ID'),\n" +
                "      ACCOUNT_ID string OPTIONS (SEARCHABLE 'Unsearchable', \"teiid_excel:CELL_NUMBER\" '1'),\n" +
                "      PRODUCT_TYPE string OPTIONS (SEARCHABLE 'Unsearchable', \"teiid_excel:CELL_NUMBER\" '2'),\n" +
                "      PRODUCT_VALUE string OPTIONS (SEARCHABLE 'Unsearchable', \"teiid_excel:CELL_NUMBER\" '3'),\n" +
                "      Ephraim string OPTIONS (SEARCHABLE 'Unsearchable', \"teiid_excel:CELL_NUMBER\" '4'),\n" +
                "      CONSTRAINT PK0 PRIMARY KEY(ROW_ID)\n" +
                "    ) OPTIONS (\"teiid_excel:FILE\" 'COGSDate.XLS', \"teiid_excel:FIRST_DATA_ROW_NUMBER\" '12');";

        try {
            updateVDB(vdbFilePath, foreignTableBlock);
            response.getWriter().write("Foreign Table block added successfully!");
        } catch (IOException e) {
            e.printStackTrace();
            response.getWriter().write("Failed to update VDB: " + e.getMessage());
        }
    }

    private void updateVDB(String vdbFilePath, String foreignTableBlock) throws IOException {
        String originalContent = readFromFile(vdbFilePath);
        String modifiedContent = insertAfter(originalContent, "SET NAMESPACE 'http://www.teiid.org/translator/excel/2014' AS teiid_excel;", foreignTableBlock);
        writeToFile(vdbFilePath, modifiedContent);
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

    private String insertAfter(String originalContent, String searchText, String insertion) {
        int index = originalContent.indexOf(searchText);
        if (index != -1) {
            return originalContent.substring(0, index + searchText.length()) + "\n" + insertion + "\n" + originalContent.substring(index + searchText.length());
        } else {
            // If search text is not found, append the insertion at the end
            return originalContent + "\n" + insertion;
        }
    }
}
