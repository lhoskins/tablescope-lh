package cloud.tablescope;

import java.io.*;
import javax.servlet.ServletException;
import javax.servlet.annotation.WebServlet;
import javax.servlet.http.*;
import com.google.gson.Gson;
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;

@WebServlet("/ColumnOrderHide")
public class ColumnOrderHideServlet extends HttpServlet {

    private static final String COLUMN_ORDER_HIDE_PATH = "/opt/redash-8.0.0-7/apps/tsTest/src/ColumnOrderHide.json";

    @Override
    protected void doGet(HttpServletRequest req, HttpServletResponse res) throws ServletException, IOException {
        String sourceTable = req.getParameter("sourceTable");
        String columns = req.getParameter("Columns");
        String hides = req.getParameter("Hide"); // New parameter for hide settings

        if (sourceTable == null || columns == null || hides == null) {
            res.setStatus(400);
            res.setContentType("application/json");
            res.getWriter().write("{\"error\": \"Missing required parameters: sourceTable, Columns, or Hide\"}");
            return;
        }

        // Split the columns and hides parameters into individual fields
        String[] columnFields = columns.split(",");
        String[] hideFlags = hides.split(",");

        if (columnFields.length != hideFlags.length) {
            res.setStatus(400);
            res.setContentType("application/json");
            res.getWriter().write("{\"error\": \"Mismatch between Columns and Hide parameters\"}");
            return;
        }

        // Initialize the Gson object
        Gson gson = new Gson();
        JsonObject columnOrderHideConfig;

        // Check if the file exists and read from it
        File file = new File(COLUMN_ORDER_HIDE_PATH);
        if (!file.exists()) {
            System.out.println("File not found, creating a new one: " + COLUMN_ORDER_HIDE_PATH);
            // If file doesn't exist, create a new JSON object structure
            columnOrderHideConfig = new JsonObject();
            columnOrderHideConfig.add("tables", new JsonArray());
        } else {
            // Try to read the file and parse the existing data
            try (FileReader reader = new FileReader(file)) {
                columnOrderHideConfig = gson.fromJson(reader, JsonObject.class);
                if (columnOrderHideConfig == null) {
                    // If the file is empty or corrupted, initialize a new object
                    columnOrderHideConfig = new JsonObject();
                    columnOrderHideConfig.add("tables", new JsonArray());
                }
            } catch (IOException e) {
                e.printStackTrace();
                res.setStatus(500);
                res.setContentType("application/json");
                res.getWriter().write("{\"error\": \"Failed to read ColumnOrderHide.json\"}");
                return;
            }
        }

        // Create a new JSON structure for the updated or new table's columns
        JsonObject updatedTable = new JsonObject();
        JsonArray columnsArray = new JsonArray();

        for (int i = 0; i < columnFields.length; i++) {
            JsonObject columnObject = new JsonObject();
            columnObject.addProperty("field", columnFields[i].trim());
            columnObject.addProperty("sourceTable", sourceTable);
            columnObject.addProperty("hide", Boolean.parseBoolean(hideFlags[i].trim())); // Add hide flag
            columnsArray.add(columnObject);
        }

        updatedTable.addProperty("sourceTable", sourceTable);
        updatedTable.add("columns", columnsArray);

        // Check if the sourceTable already exists and update it
        JsonArray tablesArray = columnOrderHideConfig.getAsJsonArray("tables");
        boolean tableExists = false;

        if (tablesArray != null) {
            for (int i = 0; i < tablesArray.size(); i++) {
                JsonObject table = tablesArray.get(i).getAsJsonObject();
                if (table.get("sourceTable").getAsString().equals(sourceTable)) {
                    tablesArray.set(i, updatedTable); // Overwrite the existing table's column order and hide settings
                    tableExists = true;
                    break;
                }
            }
        }

        // If the table doesn't exist, add it to the array
        if (!tableExists) {
            tablesArray.add(updatedTable);
        }

        // Write the updated JSON back to the file
        try (FileWriter writer = new FileWriter(COLUMN_ORDER_HIDE_PATH)) {
            gson.toJson(columnOrderHideConfig, writer);
        } catch (IOException e) {
            e.printStackTrace();
            res.setStatus(500);
            res.setContentType("application/json");
            res.getWriter().write("{\"error\": \"Failed to write to ColumnOrderHide.json\"}");
            return;
        }

        // Return success response
        JsonObject responseJson = new JsonObject();
        responseJson.addProperty("message", "Column order and visibility updated successfully.");
        res.setContentType("application/json");
        res.getWriter().write(gson.toJson(responseJson));
    }
}
