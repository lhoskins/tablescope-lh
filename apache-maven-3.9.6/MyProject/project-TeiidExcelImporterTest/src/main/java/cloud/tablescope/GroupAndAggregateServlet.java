package cloud.tablescope;

import java.io.*;
import javax.servlet.ServletException;
import javax.servlet.annotation.WebServlet;
import javax.servlet.http.*;
import com.google.gson.Gson;
import com.google.gson.JsonObject;
import com.google.gson.JsonArray;
import com.google.gson.JsonElement;

@WebServlet("/groupAggregate")
public class GroupAndAggregateServlet extends HttpServlet {

    private static final String CONFIG_PATH = "/opt/redash-8.0.0-7/apps/tsTest/src/GroupandAggregateConfig.json";

    @Override
    protected void doGet(HttpServletRequest req, HttpServletResponse res) throws ServletException, IOException {
        String action = req.getParameter("action");

        switch (action) {
            case "createGroupBy":
                handleCreateGroupBy(req, res);
                break;
            case "editGroupBy":
                handleEditGroupBy(req, res);
                break;
            case "deleteGroupBy":
                handleDeleteGroupBy(req, res);
                break;
            case "createAggregation":
                handleCreateAggregation(req, res);
                break;
            case "deleteAggregation":
                handleDeleteAggregation(req, res);
                break;
            default:
                res.setStatus(400);
                res.setContentType("application/json");
                res.getWriter().write("{\"error\": \"Invalid action\"}");
        }
    }

    private void handleCreateGroupBy(HttpServletRequest req, HttpServletResponse res) throws IOException {
        String sourceTable = req.getParameter("sourceTable");
        String sourceColumn = req.getParameter("sourceColumn");
        String groupBy = req.getParameter("groupBy");

        if (sourceTable == null || sourceColumn == null || groupBy == null) {
            res.setStatus(400);
            res.setContentType("application/json");
            res.getWriter().write("{\"error\": \"Missing required parameters\"}");
            return;
        }

        try {
            File file = new File(CONFIG_PATH);
            if (!file.exists()) {
                res.setStatus(500);
                res.setContentType("application/json");
                res.getWriter().write("{\"error\": \"GroupandAggregateConfig.json file not found\"}");
                return;
            }

            Gson gson = new Gson();
            JsonObject config = gson.fromJson(new FileReader(file), JsonObject.class);
            JsonArray drilldowns = config.getAsJsonArray("drilldowns");

            // Check if GroupBy already exists for this table
            for (JsonElement element : drilldowns) {
                JsonObject drilldown = element.getAsJsonObject();
                if (drilldown.has("groupBy") && drilldown.get("sourceTable").getAsString().equals(sourceTable)) {
                    res.setStatus(400);
                    res.setContentType("application/json");
                    res.getWriter().write("{\"error\": \"GroupBy already exists for this table\"}");
                    return;
                }
            }

            int newGroupNumber = getNextIncrement(drilldowns, "GroupBy");
            String newGroupName = "GroupBy_" + newGroupNumber;

            JsonObject newGroupBy = new JsonObject();
            newGroupBy.addProperty("name", newGroupName);
            newGroupBy.addProperty("sourceTable", sourceTable);
            newGroupBy.addProperty("sourceColumn", sourceColumn);
            newGroupBy.addProperty("groupBy", groupBy);

            drilldowns.add(newGroupBy);

            try (FileWriter writer = new FileWriter(CONFIG_PATH)) {
                gson.toJson(config, writer);
            }

            JsonObject responseJson = new JsonObject();
            responseJson.addProperty("message", "New groupBy added successfully.");
            res.setContentType("application/json");
            res.getWriter().write(gson.toJson(responseJson));

        } catch (IOException e) {
            e.printStackTrace();
            res.setStatus(500);
            res.setContentType("application/json");
            res.getWriter().write("{\"error\": \"Failed to update GroupandAggregateConfig.json\"}");
        }
    }

    private void handleEditGroupBy(HttpServletRequest req, HttpServletResponse res) throws IOException {
        String sourceTable = req.getParameter("sourceTable");
        String groupBy = req.getParameter("groupBy");

        if (sourceTable == null || groupBy == null) {
            res.setStatus(400);
            res.setContentType("application/json");
            res.getWriter().write("{\"error\": \"Missing required parameters\"}");
            return;
        }

        try {
            File file = new File(CONFIG_PATH);
            if (!file.exists()) {
                res.setStatus(500);
                res.setContentType("application/json");
                res.getWriter().write("{\"error\": \"GroupandAggregateConfig.json file not found\"}");
                return;
            }

            Gson gson = new Gson();
            JsonObject config = gson.fromJson(new FileReader(file), JsonObject.class);
            JsonArray drilldowns = config.getAsJsonArray("drilldowns");

            boolean groupUpdated = false;
            for (JsonElement element : drilldowns) {
                JsonObject drilldown = element.getAsJsonObject();
                if (drilldown.get("sourceTable").getAsString().equals(sourceTable) && drilldown.has("groupBy")) {
                    drilldown.addProperty("groupBy", groupBy);
                    groupUpdated = true;
                    break;
                }
            }

            if (!groupUpdated) {
                res.setStatus(404);
                res.setContentType("application/json");
                res.getWriter().write("{\"error\": \"GroupBy not found for this table\"}");
                return;
            }

            try (FileWriter writer = new FileWriter(CONFIG_PATH)) {
                gson.toJson(config, writer);
            }

            JsonObject responseJson = new JsonObject();
            responseJson.addProperty("message", "GroupBy updated successfully.");
            res.setContentType("application/json");
            res.getWriter().write(gson.toJson(responseJson));

        } catch (IOException e) {
            e.printStackTrace();
            res.setStatus(500);
            res.setContentType("application/json");
            res.getWriter().write("{\"error\": \"Failed to update GroupandAggregateConfig.json\"}");
        }
    }

    private void handleDeleteGroupBy(HttpServletRequest req, HttpServletResponse res) throws IOException {
        String sourceTable = req.getParameter("sourceTable");
        String sourceColumn = req.getParameter("sourceColumn");

        if (sourceTable == null || sourceColumn == null) {
            res.setStatus(400);
            res.setContentType("application/json");
            res.getWriter().write("{\"error\": \"Missing required parameters\"}");
            return;
        }

        try {
            File file = new File(CONFIG_PATH);
            if (!file.exists()) {
                res.setStatus(500);
                res.setContentType("application/json");
                res.getWriter().write("{\"error\": \"GroupandAggregateConfig.json file not found\"}");
                return;
            }

            Gson gson = new Gson();
            JsonObject config = gson.fromJson(new FileReader(file), JsonObject.class);
            JsonArray drilldowns = config.getAsJsonArray("drilldowns");

            boolean groupDeleted = false;
            for (int i = 0; i < drilldowns.size(); i++) {
                JsonObject drilldown = drilldowns.get(i).getAsJsonObject();
                if (drilldown.get("sourceTable").getAsString().equals(sourceTable) &&
                    drilldown.get("sourceColumn").getAsString().equals(sourceColumn) && drilldown.has("groupBy")) {
                    drilldowns.remove(i);
                    groupDeleted = true;
                    break;
                }
            }

            if (!groupDeleted) {
                res.setStatus(404);
                res.setContentType("application/json");
                res.getWriter().write("{\"error\": \"GroupBy not found for this table\"}");
                return;
            }

            try (FileWriter writer = new FileWriter(CONFIG_PATH)) {
                gson.toJson(config, writer);
            }

            JsonObject responseJson = new JsonObject();
            responseJson.addProperty("message", "GroupBy deleted successfully.");
            res.setContentType("application/json");
            res.getWriter().write(gson.toJson(responseJson));

        } catch (IOException e) {
            e.printStackTrace();
            res.setStatus(500);
            res.setContentType("application/json");
            res.getWriter().write("{\"error\": \"Failed to update GroupandAggregateConfig.json\"}");
        }
    }

private void handleCreateAggregation(HttpServletRequest req, HttpServletResponse res) throws IOException {
    String sourceTable = req.getParameter("sourceTable");
    String sourceColumn = req.getParameter("sourceColumn");
    String operation = req.getParameter("operation");
    String format = req.getParameter("format");
    String currency = req.getParameter("currency");
    String dataTypes = req.getParameter("dataTypes");

    if (sourceTable == null || sourceColumn == null || operation == null || format == null || currency == null || dataTypes == null) {
        res.setStatus(400);
        res.setContentType("application/json");
        res.getWriter().write("{\"error\": \"Missing required parameters\"}");
        return;
    }

    try {
        File file = new File(CONFIG_PATH);
        if (!file.exists()) {
            res.setStatus(500);
            res.setContentType("application/json");
            res.getWriter().write("{\"error\": \"GroupandAggregateConfig.json file not found\"}");
            return;
        }

        Gson gson = new Gson();
        JsonObject config = gson.fromJson(new FileReader(file), JsonObject.class);
        JsonArray drilldowns = config.getAsJsonArray("drilldowns");

        // Find the existing entry for the sourceTable and sourceColumn
        JsonObject existingEntry = null;
        for (JsonElement element : drilldowns) {
            JsonObject drilldown = element.getAsJsonObject();
            if (drilldown.get("sourceTable").getAsString().equals(sourceTable) &&
                drilldown.get("sourceColumn").getAsString().equals(sourceColumn)) {
                existingEntry = drilldown;
                break;
            }
        }

        // If an entry exists, remove it before adding the updated one
        if (existingEntry != null) {
            drilldowns.remove(existingEntry);
        }

        // Create the new aggregation entry
        JsonObject newAggregation = new JsonObject();
        newAggregation.addProperty("name", "AGG_" + getNextIncrement(drilldowns, "AGG"));  // Unique name for new aggregation
        newAggregation.addProperty("sourceTable", sourceTable);
        newAggregation.addProperty("sourceColumn", sourceColumn);

        JsonObject aggregateDetails = new JsonObject();
        aggregateDetails.addProperty("operation", operation);
        aggregateDetails.addProperty("format", format);
        aggregateDetails.addProperty("currency", currency);

        JsonObject aggregate = new JsonObject();
        aggregate.add(sourceColumn, aggregateDetails);
        newAggregation.add("aggregate", aggregate);

        // Add data type
        JsonObject dataTypeObj = new JsonObject();
        dataTypeObj.addProperty(sourceColumn, dataTypes);
        newAggregation.add("dataTypes", dataTypeObj);

        // Add the new aggregation object to the drilldowns array
        drilldowns.add(newAggregation);

        // Save the updated config back to the JSON file
        try (FileWriter writer = new FileWriter(CONFIG_PATH)) {
            gson.toJson(config, writer);
        }

        JsonObject responseJson = new JsonObject();
        responseJson.addProperty("message", "Aggregation updated successfully.");
        res.setContentType("application/json");
        res.getWriter().write(gson.toJson(responseJson));

    } catch (IOException e) {
        e.printStackTrace();
        res.setStatus(500);
        res.setContentType("application/json");
        res.getWriter().write("{\"error\": \"Failed to update GroupandAggregateConfig.json\"}");
    }
}

    private void handleDeleteAggregation(HttpServletRequest req, HttpServletResponse res) throws IOException {
        String sourceTable = req.getParameter("sourceTable");
        String sourceColumn = req.getParameter("sourceColumn");

        if (sourceTable == null || sourceColumn == null) {
            res.setStatus(400);
            res.setContentType("application/json");
            res.getWriter().write("{\"error\": \"Missing required parameters\"}");
            return;
        }

        try {
            File file = new File(CONFIG_PATH);
            if (!file.exists()) {
                res.setStatus(500);
                res.setContentType("application/json");
                res.getWriter().write("{\"error\": \"GroupandAggregateConfig.json file not found\"}");
                return;
            }

            Gson gson = new Gson();
            JsonObject config = gson.fromJson(new FileReader(file), JsonObject.class);
            JsonArray drilldowns = config.getAsJsonArray("drilldowns");

            boolean aggregationDeleted = false;
            for (int i = 0; i < drilldowns.size(); i++) {
                JsonObject drilldown = drilldowns.get(i).getAsJsonObject();
                if (drilldown.get("sourceTable").getAsString().equals(sourceTable) &&
                    drilldown.has("aggregate") && drilldown.get("aggregate").getAsJsonObject().has(sourceColumn)) {
                    // Remove the entire AGG object if it matches
                    drilldowns.remove(i);
                    aggregationDeleted = true;
                    break;
                }
            }

            if (!aggregationDeleted) {
                res.setStatus(404);
                res.setContentType("application/json");
                res.getWriter().write("{\"error\": \"Aggregation not found for this table and column\"}");
                return;
            }

            try (FileWriter writer = new FileWriter(CONFIG_PATH)) {
                gson.toJson(config, writer);
            }

            JsonObject responseJson = new JsonObject();
            responseJson.addProperty("message", "Aggregation deleted successfully.");
            res.setContentType("application/json");
            res.getWriter().write(gson.toJson(responseJson));

        } catch (IOException e) {
            e.printStackTrace();
            res.setStatus(500);
            res.setContentType("application/json");
            res.getWriter().write("{\"error\": \"Failed to update GroupandAggregateConfig.json\"}");
        }
    }

    // Helper method to get the next increment number for GroupBy or Aggregation names
    private int getNextIncrement(JsonArray drilldowns, String type) {
        int maxIncrement = 0;
        for (JsonElement element : drilldowns) {
            JsonObject drilldown = element.getAsJsonObject();
            if (drilldown.has("name") && drilldown.get("name").getAsString().startsWith(type)) {
                String[] parts = drilldown.get("name").getAsString().split("_");
                int increment = Integer.parseInt(parts[1]);
                maxIncrement = Math.max(maxIncrement, increment);
            }
        }
        return maxIncrement + 1;
    }
}
