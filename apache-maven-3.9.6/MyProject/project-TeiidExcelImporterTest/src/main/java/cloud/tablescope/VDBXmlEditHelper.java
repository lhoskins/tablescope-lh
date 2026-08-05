package cloud.tablescope;

import java.io.BufferedReader;
import java.io.BufferedWriter;
import java.io.FileReader;
import java.io.FileWriter;
import java.io.IOException;
import java.util.Calendar;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.logging.Level;
import java.util.logging.Logger;

/**
 * Static helpers for editing VDB XML content during file uploads.
 */
public class VDBXmlEditHelper {

    private static final Logger LOGGER = Logger.getLogger(VDBXmlEditHelper.class.getName());

    public static String readFromFile(String filePath) throws IOException {
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

    public static void writeToFile(String filePath, String content) throws IOException {
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

    public static String updateVDB(String vdbFilePath, String vdbContent, String foreignTableBlock, String createViewStatement) throws IOException {
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

        if (!vdbContent.contains(foreignTableBlock)) {
            vdbContent = insertAfter(vdbContent, "-- Place Foreign Table Below", foreignTableBlock + "\n");
        }

        if (!vdbContent.contains(createViewStatement)) {
            vdbContent = insertBefore(vdbContent, "-- Place new View above", createViewStatement + "\n");
        }

        return vdbContent;
    }

    public static String insertBefore(String originalContent, String searchText, String insertion) {
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

    public static String insertAfter(String originalContent, String searchText, String insertion) {
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
            return originalContent + "\n" + insertion;
        }
    }

    public static String generateArchiveFileName(String fileName) {
        Calendar calendar = Calendar.getInstance();
        String timestamp = String.format("%tY%<tm%<td-%<tH%<tM%<tS", calendar);
        return fileName.replace(".", "-" + timestamp + ".");
    }

    public static String removeForeignTableAndView(String vdbContent, String normalizedName) {
        String modifiedContent = vdbContent;

        String foreignTablePattern = "CREATE FOREIGN TABLE \"?" + Pattern.quote(normalizedName) + "\"?" +
                                    "\\s*\\([^;]*;";
        Pattern ftPattern = Pattern.compile(foreignTablePattern, Pattern.DOTALL | Pattern.CASE_INSENSITIVE);
        Matcher ftMatcher = ftPattern.matcher(modifiedContent);

        if (ftMatcher.find()) {
            modifiedContent = ftMatcher.replaceAll("");
        }

        String viewPattern = "CREATE VIEW \"?" + Pattern.quote(normalizedName) + "_[A-Z]+\"?\\s+AS\\s+SELECT[^;]+;+";
        Pattern viewPatternCompiled = Pattern.compile(viewPattern, Pattern.DOTALL | Pattern.CASE_INSENSITIVE);
        Matcher viewMatcher = viewPatternCompiled.matcher(modifiedContent);

        if (viewMatcher.find()) {
            modifiedContent = viewMatcher.replaceAll("");
        }

        modifiedContent = modifiedContent.replaceAll("\\n{3,}", "\n\n");

        return modifiedContent;
    }

    public static String removeTxtView(String vdbContent, String viewName) {
        String modifiedContent = vdbContent;

        String upperName = viewName.replaceAll("([\\\\\\[\\](){}.*+?^$|])", "\\\\$1");
        String txtViewPattern = "CREATE VIEW \"?" + upperName + "\"?\\s*.*?AS\\s+SELECT.*?;+";
        Pattern txtViewPatternCompiled = Pattern.compile(txtViewPattern, Pattern.DOTALL | Pattern.CASE_INSENSITIVE);
        Matcher txtViewMatcher = txtViewPatternCompiled.matcher(modifiedContent);

        if (txtViewMatcher.find()) {
            modifiedContent = txtViewMatcher.replaceAll("");
        }

        modifiedContent = modifiedContent.replaceAll("\\n{3,}", "\n\n");

        return modifiedContent;
    }
}
