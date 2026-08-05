package cloud.tablescope;

import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.logging.Logger;

/**
 * Extracts DDL blocks from VDB XML text.
 */
public class VDBDDLExtractor {

    private static final Logger LOGGER = Logger.getLogger(VDBDDLExtractor.class.getName());

    public static final String DDL_TYPE_FOREIGN_TABLE = "FOREIGN_TABLE";
    public static final String DDL_TYPE_VIEW = "VIEW";

    public static class DDLResult {
        public String ddl;
        public String type;

        public DDLResult(String ddl, String type) {
            this.ddl = ddl;
            this.type = type;
        }
    }

    public static String detectFileType(String filePath) {
        if (filePath == null) return "excel";
        String lowerPath = filePath.toLowerCase();
        if (lowerPath.endsWith(".csv") || lowerPath.endsWith(".txt")) {
            return "csv_txt";
        }
        return "excel";
    }

    public static DDLResult extractDDLFromText(String vdbContent, String tableName, String fileType) {
        if ("csv_txt".equals(fileType)) {
            String viewDDL = extractViewDDLFromText(vdbContent, tableName);
            if (viewDDL != null) return new DDLResult(viewDDL, DDL_TYPE_VIEW);
            String tableDDL = extractForeignTableDDLFromText(vdbContent, tableName);
            if (tableDDL != null) return new DDLResult(tableDDL, DDL_TYPE_FOREIGN_TABLE);
        } else {
            String tableDDL = extractForeignTableDDLFromText(vdbContent, tableName);
            if (tableDDL != null) return new DDLResult(tableDDL, DDL_TYPE_FOREIGN_TABLE);
            String viewDDL = extractViewDDLFromText(vdbContent, tableName);
            if (viewDDL != null) return new DDLResult(viewDDL, DDL_TYPE_VIEW);
        }
        return null;
    }

    public static String extractForeignTableDDLFromText(String vdbContent, String tableName) {
        String searchPattern = "CREATE FOREIGN TABLE " + tableName;

        Pattern cdataPattern = Pattern.compile("<!\\[CDATA\\[(.*?)\\]\\]>", Pattern.DOTALL);
        Matcher cdataMatcher = cdataPattern.matcher(vdbContent);

        while (cdataMatcher.find()) {
            String ddlContent = cdataMatcher.group(1);
            if (ddlContent.contains(searchPattern)) {
                LOGGER.info("[VDB_MIGRATION] Found FOREIGN TABLE in CDATA section");
                return extractDDLBlock(ddlContent, tableName, "CREATE FOREIGN TABLE");
            }
        }

        if (vdbContent.contains(searchPattern)) {
            Pattern metaPattern = Pattern.compile("<metadata[^>]*type=\"DDL\"[^>]*>([\\s\\S]*?)</metadata>", Pattern.DOTALL);
            Matcher metaMatcher = metaPattern.matcher(vdbContent);
            while (metaMatcher.find()) {
                String ddlContent = metaMatcher.group(1);
                if (ddlContent.trim().startsWith("<![CDATA[")) continue;

                if (ddlContent.contains(searchPattern)) {
                    LOGGER.info("[VDB_MIGRATION] Found FOREIGN TABLE in plain metadata (no CDATA)");
                    return extractDDLBlock(ddlContent, tableName, "CREATE FOREIGN TABLE");
                }
            }
        }

        return null;
    }

    public static String extractViewDDLFromText(String vdbContent, String tableName) {
        String searchPattern = "CREATE VIEW " + tableName;

        Pattern cdataPattern = Pattern.compile("<!\\[CDATA\\[(.*?)\\]\\]>", Pattern.DOTALL);
        Matcher cdataMatcher = cdataPattern.matcher(vdbContent);

        while (cdataMatcher.find()) {
            String ddlContent = cdataMatcher.group(1);
            if (ddlContent.contains(searchPattern)) {
                LOGGER.info("[VDB_MIGRATION] Found VIEW in CDATA section");
                return extractDDLBlock(ddlContent, tableName, "CREATE VIEW");
            }
        }

        if (vdbContent.contains(searchPattern)) {
            Pattern metaPattern = Pattern.compile("<metadata[^>]*type=\"DDL\"[^>]*>([\\s\\S]*?)</metadata>", Pattern.DOTALL);
            Matcher metaMatcher = metaPattern.matcher(vdbContent);
            while (metaMatcher.find()) {
                String ddlContent = metaMatcher.group(1);
                if (ddlContent.trim().startsWith("<![CDATA[")) continue;

                if (ddlContent.contains(searchPattern)) {
                    LOGGER.info("[VDB_MIGRATION] Found VIEW in plain metadata (no CDATA)");
                    return extractDDLBlock(ddlContent, tableName, "CREATE VIEW");
                }
            }
        }

        return null;
    }

    public static String extractDDLBlock(String fullDDL, String tableName, String createKeyword) {
        String startPattern = createKeyword + " " + tableName;
        int startIndex = fullDDL.indexOf(startPattern);
        if (startIndex == -1) return null;

        int endIndex = fullDDL.length();
        int nextFT = fullDDL.indexOf("CREATE FOREIGN TABLE", startIndex + startPattern.length());
        int nextView = fullDDL.indexOf("CREATE VIEW", startIndex + startPattern.length());
        int nextComment = fullDDL.indexOf("-- Place new", startIndex + startPattern.length());

        if (nextFT != -1 && nextFT < endIndex) endIndex = nextFT;
        if (nextView != -1 && nextView < endIndex) endIndex = nextView;
        if (nextComment != -1 && nextComment < endIndex) endIndex = nextComment;

        return fullDDL.substring(startIndex, endIndex).trim();
    }
}
