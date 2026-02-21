import com.fasterxml.jackson.databind.ObjectMapper;
import javax.servlet.ServletException;
import javax.servlet.annotation.WebServlet;
import javax.servlet.http.HttpServlet;
import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpServletResponse;
import java.io.BufferedReader;
import java.io.IOException;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.ResultSet;
import java.sql.Statement;
import java.util.HashMap;
import java.util.Map;
import java.util.List;
import java.util.ArrayList;
import com.google.gson.Gson;

@WebServlet("/buildSQL")
public class BuildSQLServlet extends HttpServlet {

    // JDBC connection parameters for PostgreSQL
    static final String JDBC_URL = "jdbc:postgresql://64.52.108.62:35442/myvdbtest";
    static final String USER = "test";
    static final String PASSWORD = "test";

  @Override
  protected void doPost(HttpServletRequest request, HttpServletResponse response) throws ServletException, IOException {
    response.setContentType("application/json");

    // Read the received JSON data
    BufferedReader reader = request.getReader();
    StringBuilder sb = new StringBuilder();
    String line;
    while ((line = reader.readLine()) != null) {
      sb.append(line);
    }

    // Parse the JSON data to extract the SQL statement
    Gson gson = new Gson();
    Map<String, String> requestData = gson.fromJson(sb.toString(), Map.class);
    String sqlStatement = requestData.get("sqlStatement");

    // Execute the SQL statement and retrieve results
    Map<String, Object> responseData = executeSQL(sqlStatement);

    // Send the response back to the client as JSON
    gson.toJson(responseData, response.getWriter()); // Use Gson for serialization
  }

private Map<String, Object> executeSQL(String sqlStatement) {
    Map<String, Object> resultMap = new HashMap<>();
    Connection connection = null;
    Statement statement = null;
    ResultSet resultSet = null;

    try {
        // Establish database connection
        connection = DriverManager.getConnection(JDBC_URL, USER, PASSWORD);
        statement = connection.createStatement();

        // Append LIMIT 10 to the SQL statement
        String limitedSqlStatement = sqlStatement + " LIMIT 10";

        // Execute the SQL statement
        resultSet = statement.executeQuery(limitedSqlStatement);

        // Prepare response data
        resultMap.put("connectionStatus", "success");

        // Extract column names and build result set as a list of maps
        if (resultSet.next()) {
            int columnCount = resultSet.getMetaData().getColumnCount();
            String[] columnNames = new String[columnCount];
            for (int i = 1; i <= columnCount; i++) {
                columnNames[i - 1] = resultSet.getMetaData().getColumnName(i);
            }

            List<Map<String, Object>> resultList = new ArrayList<>();
            do {
                Map<String, Object> rowMap = new HashMap<>();
                for (int i = 1; i <= columnCount; i++) {
                    rowMap.put(columnNames[i - 1], resultSet.getObject(i));
                }
                resultList.add(rowMap);
            } while (resultSet.next());
            resultMap.put("queryResults", resultList);
        } else {
            resultMap.put("queryResults", new ArrayList<>()); // Empty list for no results
        }
    } catch (Exception e) {
        resultMap.put("connectionStatus", "failed");
        resultMap.put("error", e.getMessage());
        e.printStackTrace();
    } finally {
        // Close resources
        if (resultSet != null) try { resultSet.close(); } catch (Exception e) {}
        if (statement != null) try { statement.close(); } catch (Exception e) {}
        if (connection != null) try { connection.close(); } catch (Exception e) {}
    }

    return resultMap;
}

}
