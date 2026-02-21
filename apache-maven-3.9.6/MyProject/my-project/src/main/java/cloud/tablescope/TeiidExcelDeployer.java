import java.io.IOException;
import java.io.PrintWriter;
import java.util.List;
import java.util.ArrayList;
import javax.servlet.ServletException;
import javax.servlet.annotation.MultipartConfig;
import javax.servlet.annotation.WebServlet;
import javax.servlet.http.HttpServlet;
import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpServletResponse;
import javax.servlet.http.Part;
import org.apache.poi.ss.usermodel.Cell;
import org.apache.poi.ss.usermodel.Row;
import org.apache.poi.ss.usermodel.Sheet;
import org.apache.poi.ss.usermodel.Workbook;
import org.apache.poi.xssf.usermodel.XSSFWorkbook;
import org.jboss.xnio.*;


@WebServlet("/uploadExcelFile")
@MultipartConfig
public class TeiidExcelDeployer extends HttpServlet {

    private static final long serialVersionUID = 1L;

    protected void doGet(HttpServletRequest request, HttpServletResponse response)
            throws ServletException, IOException {
        // Forward to doPost() method
        doPost(request, response);
    }

    protected void doPost(HttpServletRequest request, HttpServletResponse response)
            throws ServletException, IOException {

        // Explicitly check for required fields
        Part filePart = request.getPart("file"); // Retrieves <input type="file" name="file">
        if (filePart == null) {
            response.setStatus(HttpServletResponse.SC_BAD_REQUEST);
            response.getWriter().println("Error: Missing required field 'file' in the request.");
            return;
        }

        // Process uploaded Excel file
        List<List<String>> excelData = null;
        try ( // Use try-with-resources for automatic resource closing
              Workbook workbook = new XSSFWorkbook(filePart.getInputStream())) {

            // Read Excel data from the uploaded file
            excelData = readExcelData(workbook);

        } catch (Exception e) {
            // Log exception with more context
            System.err.println("Error processing Excel data: " + e.getMessage());
            response.setStatus(HttpServletResponse.SC_INTERNAL_SERVER_ERROR);
            response.getWriter().println("Error processing Excel data.");
            return;
        }


        // Check if Excel data was successfully extracted
        if (excelData == null) {
            response.setStatus(HttpServletResponse.SC_BAD_REQUEST);
            response.getWriter().println("Error: No Excel data found in the upload.");
            return;
        }

        // Write Excel data to the response
        response.setContentType("text/html");
        PrintWriter out = response.getWriter();
        out.println("<html><head><title>Excel Data</title></head><body>");
        out.println("<h1>Excel Data:</h1>");
        out.println("<table border=\"1\">");
        for (List<String> rowData : excelData) {
            out.println("<tr>");
            for (String cellData : rowData) {
                out.println("<td>" + cellData + "</td>");
            }
            out.println("</tr>");
        }
        out.println("</table>");
        out.println("</body></html>");

        // Delegate VDB schema and table deployment logic
        try {
            deployVDB(excelData);
        } catch (Exception e) {
            // Log exception with more context
            System.err.println("Error deploying VDB schema and table: " + e.getMessage());
            response.setStatus(HttpServletResponse.SC_INTERNAL_SERVER_ERROR);
            response.getWriter().println("Error deploying VDB schema and table.");
        }
    }

    private static List<List<String>> readExcelData(Workbook workbook) throws Exception {
        List<List<String>> data = new ArrayList<>();
        Sheet sheet = workbook.getSheetAt(0); // Assuming data is in the first sheet

        for (Row row : sheet) {
            List<String> rowData = new ArrayList<>();
            for (Cell cell : row) {
                rowData.add(cell.getStringCellValue());
            }
            data.add(rowData);
        }
        return data;
    }

    // Delegate methods for VDB deployment logic (implement these methods based on your Teiid version and requirements)
    private void deployVDB(List<List<String>> excelData) throws Exception {
        // Implementation of VDB deployment logic
    }
}
