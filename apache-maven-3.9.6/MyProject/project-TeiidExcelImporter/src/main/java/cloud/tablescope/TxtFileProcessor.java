package cloud.tablescope;

import java.io.*;
import java.util.*;
import java.util.regex.*;
import java.util.stream.Collectors;

public class TxtFileProcessor {

    public List<String> getColumnNames(String filePath) throws IOException {
        List<String> columnNames = new ArrayList<>();
        try (BufferedReader reader = new BufferedReader(new FileReader(filePath))) {
            String headerLine = reader.readLine();
            if (headerLine == null) {
                return null; // No header row found in the file
            }
            String delimiter = getFileExtension(filePath).equals("csv") ? "," : "\t";
            String[] headers = headerLine.split(Pattern.quote(delimiter));
            for (String header : headers) {
                String columnName = header.trim().replaceAll("\\s+", "_").replaceAll("[./:()]", "");
                columnNames.add(columnName);
            }
        }
        return columnNames;
    }

    public String generateView(String fileName, List<String> columnNames) {
        String delimiter = getFileExtension(fileName).equals("csv") ? "," : "\t";
        String viewName = fileName.replaceAll("\\s+", "_").replaceAll("\\.", "_").toUpperCase();
        StringBuilder viewDefinition = new StringBuilder();
        viewDefinition.append("CREATE VIEW ").append(viewName).append(" (\n");
        for (String columnName : columnNames) {
            viewDefinition.append(columnName).append(" string(4000) OPTIONS(NAMEINSOURCE '").append(columnName).append("', UPDATABLE 'FALSE'),\n");
        }
        viewDefinition.deleteCharAt(viewDefinition.length() - 2); // Remove the last comma
        viewDefinition.append(") AS\n");
        viewDefinition.append("SELECT \n");
        viewDefinition.append(columnNames.stream().map(col -> "A." + col).collect(Collectors.joining(", ")));
        viewDefinition.append("\nFROM\n");
        viewDefinition.append("(EXEC CSVSourceModel.getTextFiles('").append(fileName).append("')) AS f,\n");
        viewDefinition.append("TEXTTABLE(f.file COLUMNS ");
        viewDefinition.append(columnNames.stream().map(col -> col + " string").collect(Collectors.joining(", ")));
        viewDefinition.append(" DELIMITER '").append(delimiter).append("' HEADER) AS A;");
        return viewDefinition.toString();
    }

    private String getFileExtension(String fileName) {
        int lastIndexOfDot = fileName.lastIndexOf('.');
        if (lastIndexOfDot == -1) {
            return "";
        }
        return fileName.substring(lastIndexOfDot + 1);
    }
}
