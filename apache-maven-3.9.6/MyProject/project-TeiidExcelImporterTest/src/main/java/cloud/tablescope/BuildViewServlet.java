import java.io.BufferedReader;
import java.io.BufferedWriter;
import java.io.FileReader;
import java.io.FileWriter;
import java.io.FileInputStream;
import java.io.InputStream;
import java.io.IOException;
import java.io.PrintWriter;
import javax.servlet.ServletException;
import javax.servlet.annotation.MultipartConfig;
import javax.servlet.annotation.WebServlet;
import javax.servlet.http.HttpServlet;
import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpServletResponse;
import org.teiid.adminapi.Admin;
import org.teiid.adminapi.jboss.AdminFactory;

@WebServlet("/view")
@MultipartConfig
public class BuildViewServlet extends HttpServlet {

	protected void doPost(HttpServletRequest request, HttpServletResponse response)
			throws ServletException, IOException {
		response.setContentType("text/plain");
		PrintWriter out = response.getWriter();

		// Retrieve parameters from the frontend
		String viewName = request.getParameter("viewName");
		String sqlStatement = request.getParameter("sqlStatement");

		// Sanitize the viewName
		viewName = sanitizeViewName(viewName);



		// Check if parameters are null or empty
		if (viewName == null || viewName.isEmpty() || sqlStatement == null || sqlStatement.isEmpty()) {
			out.println("View name or SQL statement is missing.");
			return;
		}

		// Modify the SQL statement to remove characters after "_"
		//sqlStatement = modifySqlStatement(sqlStatement);

		String vdbFilePath = "/opt/wildfly/teiidfiles/myvdb-vdb.xml";

		try {
			// Check if the view already exists
			if (viewExists(vdbFilePath, viewName)) {
				out.println("View already exists. Aborting.");
				return;
			}

			// Check if the file can be read before proceeding
			String vdbContent = readFromFile(vdbFilePath);
			if (vdbContent == null) {
				out.println("Failed to read VDB file. Check file permissions or existence.");
				return;
			}

			String createViewStatement = "CREATE VIEW " + viewName + " AS " + sqlStatement + ";";

			// Update the VDB file with the new view
			String modifiedContent = updateVDB(vdbContent, createViewStatement);
			if (modifiedContent == null) {
				out.println("Failed to modify view");
				return;
			}

			writeToFile(vdbFilePath, modifiedContent);
			out.println("View added successfully!");

			// Deploy the modified VDB
			deployVDB(vdbFilePath);
			out.println("VDB deployed successfully!");
		} catch (IOException e) {
			out.println("Failed to update VDB or deploy VDB: " + e.getMessage());
		}
	}

/* 	private String modifySqlStatement(String sqlStatement) {
    // Replace "_XLSX" or "_XLS" with an empty string
    return sqlStatement.replaceAll("_XLSX|_XLS", "");
	} */

	private String sanitizeViewName(String viewName) {
		// Replace spaces with underscores
		String sanitizedName = viewName.replaceAll("\\s", "_");
		
		// Remove reserved characters
		sanitizedName = sanitizedName.replaceAll("[^a-zA-Z0-9_]", "");
		
		return sanitizedName;
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

    private void writeToFile(String filePath, String modifiedContent) throws IOException {
        if (filePath == null || filePath.isEmpty()) {
            throw new IllegalArgumentException("File path is null or empty.");
        }

        if (modifiedContent == null) {
            throw new IllegalArgumentException("Content is null.");
        }

        try (BufferedWriter writer = new BufferedWriter(new FileWriter(filePath))) {
            writer.write(modifiedContent);
        }
    }

    private boolean viewExists(String vdbFilePath, String viewName) throws IOException {
        try (BufferedReader reader = new BufferedReader(new FileReader(vdbFilePath))) {
            String line;
            while ((line = reader.readLine()) != null) {
                if (line.contains("CREATE VIEW " + viewName)) {
                    return true;
                }
            }
        }
        return false;
    }

	private String updateVDB(String originalContent, String createViewStatement) {
		String modifiedContent = insertBefore(originalContent, "-- Place new View above", createViewStatement);
		if (modifiedContent == null) {
			throw new IllegalArgumentException("Failed to modify VDB content with view definition.");
		}
		return modifiedContent;
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
