package cloud.tablescope;

import java.io.*;
import javax.servlet.ServletException;
import javax.servlet.annotation.WebServlet;
import javax.servlet.http.*;
import com.google.gson.Gson;
import com.google.gson.JsonObject;
import com.google.gson.JsonArray;

@WebServlet("/createScope")
public class CreateScopeServlet extends HttpServlet {

    private static final String DRILLDOWN_CONFIG_PATH = "/opt/redash-8.0.0-7/apps/tsTest/src/drilldownConfig.json";

    @Override
    protected void doGet(HttpServletRequest req, HttpServletResponse res) throws ServletException, IOException {
        String action = req.getParameter("action");

        if ("getScope".equals(action)) {
            handleGetScope(req, res);
        } else if ("deleteScope".equals(action)) {
            handleDeleteScope(req, res);
        } else {
            // Standard scope creation logic for GET requests
            String sourceTable = req.getParameter("sourceTable");
            String sourceColumn = req.getParameter("sourceColumn");
            String targetTable = req.getParameter("targetTable");
            String targetColumn = req.getParameter("targetColumn");

            if (sourceTable == null || sourceColumn == null || targetTable == null || targetColumn == null) {
                res.setStatus(400);
                res.setContentType("application/json");
                res.getWriter().write("{\"error\": \"Missing required parameters\"}");
                return;
            }

            processCreateScope(sourceTable, sourceColumn, targetTable, targetColumn, res);
        }
    }

    @Override
    protected void doPost(HttpServletRequest req, HttpServletResponse res) throws ServletException, IOException {
        req.setCharacterEncoding("UTF-8");
        String contentType = req.getContentType();
        String action = req.getParameter("action");

        if ("updateScope".equals(action)) {
            handleUpdateScope(req, res);
        } else {
            // Handle creation for POST requests
            String sourceTable = null;
            String sourceColumn = null;
            String targetTable = null;
            String targetColumn = null;

            if ("application/json".equals(contentType)) {
                // Parse JSON data from request body
                BufferedReader reader = req.getReader();
                Gson gson = new Gson();
                JsonObject jsonRequest = gson.fromJson(reader, JsonObject.class);

                sourceTable = jsonRequest.get("sourceTable").getAsString();
                sourceColumn = jsonRequest.get("sourceColumn").getAsString();
                targetTable = jsonRequest.get("targetTable").getAsString();
                targetColumn = jsonRequest.get("targetColumn").getAsString();
            } else {
                // Handle form-urlencoded request (e.g., from cURL)
                sourceTable = req.getParameter("sourceTable");
                sourceColumn = req.getParameter("sourceColumn");
                targetTable = req.getParameter("targetTable");
                targetColumn = req.getParameter("targetColumn");
            }

            if (sourceTable == null || sourceColumn == null || targetTable == null || targetColumn == null) {
                res.setStatus(400);
                res.setContentType("application/json");
                res.getWriter().write("{\"error\": \"Missing required parameters\"}");
                return;
            }

            processCreateScope(sourceTable, sourceColumn, targetTable, targetColumn, res);
        }
    }

    // Method to handle the creation of a new scope and updating drilldownConfig.json
    private void processCreateScope(String sourceTable, String sourceColumn, String targetTable, String targetColumn, HttpServletResponse res) throws IOException {
        try {
            File file = new File(DRILLDOWN_CONFIG_PATH);
            if (!file.exists()) {
                res.setStatus(500);
                res.setContentType("application/json");
                res.getWriter().write("{\"error\": \"drilldownConfig.json file not found\"}");
                return;
            }

            Gson gson = new Gson();
            JsonObject drilldownConfig = gson.fromJson(new FileReader(file), JsonObject.class);
            JsonArray drilldowns = drilldownConfig.getAsJsonArray("drilldowns");

            int newScopeNumber = drilldowns.size() + 1;
            String newScopeName = "Scope_" + newScopeNumber;

            JsonObject newDrilldown = new JsonObject();
            newDrilldown.addProperty("name", newScopeName);
            newDrilldown.addProperty("sourceTable", sourceTable);
            newDrilldown.addProperty("sourceColumn", sourceColumn);
            newDrilldown.addProperty("targetTable", targetTable);
            newDrilldown.addProperty("targetColumn", targetColumn);

            drilldowns.add(newDrilldown);

            try (FileWriter writer = new FileWriter(DRILLDOWN_CONFIG_PATH)) {
                gson.toJson(drilldownConfig, writer);
            }

            JsonObject responseJson = new JsonObject();
            responseJson.addProperty("message", "New drilldown added successfully.");
            JsonObject responseData = new JsonObject();
            responseData.addProperty("name", newScopeName);
            responseData.addProperty("sourceTable", sourceTable);
            responseData.addProperty("sourceColumn", sourceColumn);
            responseData.addProperty("targetTable", targetTable);
            responseData.addProperty("targetColumn", targetColumn);
            responseJson.add("data", responseData);

            res.setContentType("application/json");
            res.getWriter().write(gson.toJson(responseJson));

        } catch (IOException e) {
            e.printStackTrace();
            res.setStatus(500);
            res.setContentType("application/json");
            res.getWriter().write("{\"error\": \"Failed to update drilldownConfig.json\"}");
        }
    }

    // Method to handle fetching an existing scope
    private void handleGetScope(HttpServletRequest req, HttpServletResponse res) throws IOException {
        String sourceTable = req.getParameter("sourceTable");
        String sourceColumn = req.getParameter("sourceColumn");

        if (sourceTable == null || sourceColumn == null) {
            res.setStatus(400);
            res.setContentType("application/json");
            res.getWriter().write("{\"error\": \"Missing required parameters\"}");
            return;
        }

        try {
            File file = new File(DRILLDOWN_CONFIG_PATH);
            if (!file.exists()) {
                res.setStatus(500);
                res.setContentType("application/json");
                res.getWriter().write("{\"error\": \"drilldownConfig.json file not found\"}");
                return;
            }

            Gson gson = new Gson();
            JsonObject drilldownConfig = gson.fromJson(new FileReader(file), JsonObject.class);
            JsonArray drilldowns = drilldownConfig.getAsJsonArray("drilldowns");

            JsonObject foundScope = null;
            for (int i = 0; i < drilldowns.size(); i++) {
                JsonObject drilldown = drilldowns.get(i).getAsJsonObject();
                if (drilldown.get("sourceTable").getAsString().equals(sourceTable) &&
                    drilldown.get("sourceColumn").getAsString().equals(sourceColumn)) {
                    foundScope = drilldown;
                    break;
                }
            }

            if (foundScope == null) {
                res.setStatus(404);
                res.setContentType("application/json");
                res.getWriter().write("{\"error\": \"Scope not found\"}");
                return;
            }

            res.setContentType("application/json");
            res.getWriter().write(gson.toJson(foundScope));

        } catch (IOException e) {
            e.printStackTrace();
            res.setStatus(500);
            res.setContentType("application/json");
            res.getWriter().write("{\"error\": \"Failed to read drilldownConfig.json\"}");
        }
    }

    // Method to handle updating an existing scope
    private void handleUpdateScope(HttpServletRequest req, HttpServletResponse res) throws IOException {
        BufferedReader reader = req.getReader();
        Gson gson = new Gson();
        JsonObject jsonRequest = gson.fromJson(reader, JsonObject.class);

        String sourceTable = jsonRequest.get("sourceTable").getAsString();
        String sourceColumn = jsonRequest.get("sourceColumn").getAsString();
        String targetTable = jsonRequest.get("targetTable").getAsString();
        String targetColumn = jsonRequest.get("targetColumn").getAsString();

        if (sourceTable == null || sourceColumn == null || targetTable == null || targetColumn == null) {
            res.setStatus(400);
            res.setContentType("application/json");
            res.getWriter().write("{\"error\": \"Missing required parameters\"}");
            return;
        }

        try {
            File file = new File(DRILLDOWN_CONFIG_PATH);
            if (!file.exists()) {
                res.setStatus(500);
                res.setContentType("application/json");
                res.getWriter().write("{\"error\": \"drilldownConfig.json file not found\"}");
                return;
            }

            JsonObject drilldownConfig = gson.fromJson(new FileReader(file), JsonObject.class);
            JsonArray drilldowns = drilldownConfig.getAsJsonArray("drilldowns");

            boolean scopeUpdated = false;
            for (int i = 0; i < drilldowns.size(); i++) {
                JsonObject drilldown = drilldowns.get(i).getAsJsonObject();
                if (drilldown.get("sourceTable").getAsString().equals(sourceTable) &&
                    drilldown.get("sourceColumn").getAsString().equals(sourceColumn)) {
                    drilldown.addProperty("targetTable", targetTable);
                    drilldown.addProperty("targetColumn", targetColumn);
                    scopeUpdated = true;
                    break;
                }
            }

            if (!scopeUpdated) {
                res.setStatus(404);
                res.setContentType("application/json");
                res.getWriter().write("{\"error\": \"Scope not found\"}");
                return;
            }

            try (FileWriter writer = new FileWriter(DRILLDOWN_CONFIG_PATH)) {
                gson.toJson(drilldownConfig, writer);
            }

            JsonObject responseJson = new JsonObject();
            responseJson.addProperty("message", "Scope updated successfully.");
            res.setContentType("application/json");
            res.getWriter().write(gson.toJson(responseJson));

        } catch (IOException e) {
            e.printStackTrace();
            res.setStatus(500);
            res.setContentType("application/json");
            res.getWriter().write("{\"error\": \"Failed to update drilldownConfig.json\"}");
        }
    }

    // Method to handle deleting a scope
    private void handleDeleteScope(HttpServletRequest req, HttpServletResponse res) throws IOException {
        String sourceTable = req.getParameter("sourceTable");
        String sourceColumn = req.getParameter("sourceColumn");

        if (sourceTable == null || sourceColumn == null) {
            res.setStatus(400);
            res.setContentType("application/json");
            res.getWriter().write("{\"error\": \"Missing required parameters\"}");
            return;
        }

        try {
            File file = new File(DRILLDOWN_CONFIG_PATH);
            if (!file.exists()) {
                res.setStatus(500);
                res.setContentType("application/json");
                res.getWriter().write("{\"error\": \"drilldownConfig.json file not found\"}");
                return;
            }

            Gson gson = new Gson();
            JsonObject drilldownConfig = gson.fromJson(new FileReader(file), JsonObject.class);
            JsonArray drilldowns = drilldownConfig.getAsJsonArray("drilldowns");

            boolean scopeDeleted = false;
            for (int i = 0; i < drilldowns.size(); i++) {
                JsonObject drilldown = drilldowns.get(i).getAsJsonObject();
                if (drilldown.get("sourceTable").getAsString().equals(sourceTable) &&
                    drilldown.get("sourceColumn").getAsString().equals(sourceColumn)) {
                    drilldowns.remove(i);
                    scopeDeleted = true;
                    break;
                }
            }

            if (!scopeDeleted) {
                res.setStatus(404);
                res.setContentType("application/json");
                res.getWriter().write("{\"error\": \"Scope not found\"}");
                return;
            }

            try (FileWriter writer = new FileWriter(DRILLDOWN_CONFIG_PATH)) {
                gson.toJson(drilldownConfig, writer);
            }

            JsonObject responseJson = new JsonObject();
            responseJson.addProperty("message", "Scope deleted successfully.");
            res.setContentType("application/json");
            res.getWriter().write(gson.toJson(responseJson));

        } catch (IOException e) {
            e.printStackTrace();
            res.setStatus(500);
            res.setContentType("application/json");
            res.getWriter().write("{\"error\": \"Failed to update drilldownConfig.json\"}");
        }
    }
}
