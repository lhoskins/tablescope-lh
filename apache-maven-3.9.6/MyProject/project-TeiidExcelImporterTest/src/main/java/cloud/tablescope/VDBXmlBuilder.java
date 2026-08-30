package cloud.tablescope;

import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.logging.Level;
import java.util.logging.Logger;
import org.json.JSONArray;
import org.json.JSONObject;

/**
 * Static helpers for building and editing VDB XML strings.
 */
public class VDBXmlBuilder {

    private static final Logger LOGGER = Logger.getLogger(VDBXmlBuilder.class.getName());

    /**
     * Update file paths in VDB XML to use relative paths for multi-tenancy.
     *
     * @param vdbXml The VDB XML content
     * @param uploadsFolder The customer's uploads folder path
     * @return Updated VDB XML with relative paths
     */
    public static String updateFilePaths(String vdbXml, String uploadsFolder) {
        try {
            LOGGER.info("Converting file paths to relative format for: " + uploadsFolder);

            String updatedXml = vdbXml;

            Pattern userPattern = Pattern.compile("/customers/(\\d+)/(\\d+)/uploads");
            // Project-scoped shared path must be checked before the org-wide
            // sharedPattern below, since /shared/{projectId}/uploads would
            // otherwise fail to match sharedPattern's exact "/shared/uploads"
            // and fall through to the absolute-path fallback.
            Pattern sharedProjectPattern = Pattern.compile("/customers/(\\d+)/shared/(\\d+)/uploads");
            Pattern sharedPattern = Pattern.compile("/customers/(\\d+)/shared/uploads");
            Pattern orgPattern = Pattern.compile("/customers/(\\d+)/uploads");

            Matcher userMatcher = userPattern.matcher(uploadsFolder);
            Matcher sharedProjectMatcher = sharedProjectPattern.matcher(uploadsFolder);
            Matcher sharedMatcher = sharedPattern.matcher(uploadsFolder);
            Matcher orgMatcher = orgPattern.matcher(uploadsFolder);

            String relativePathPrefix;

            if (userMatcher.find()) {
                String orgId = userMatcher.group(1);
                String userId = userMatcher.group(2);
                relativePathPrefix = orgId + "/" + userId + "/uploads";
                LOGGER.info("Using user-level relative path prefix: " + relativePathPrefix + "/");
            } else if (sharedProjectMatcher.find()) {
                String orgId = sharedProjectMatcher.group(1);
                String projectId = sharedProjectMatcher.group(2);
                relativePathPrefix = orgId + "/shared/" + projectId + "/uploads";
                LOGGER.info("Using project-scoped shared relative path prefix: " + relativePathPrefix + "/");
            } else if (sharedMatcher.find()) {
                String orgId = sharedMatcher.group(1);
                relativePathPrefix = orgId + "/shared/uploads";
                LOGGER.info("Using shared relative path prefix: " + relativePathPrefix + "/");
            } else if (orgMatcher.find()) {
                String orgId = orgMatcher.group(1);
                relativePathPrefix = orgId + "/uploads";
                LOGGER.info("Using org-level relative path prefix: " + relativePathPrefix + "/");
            } else {
                LOGGER.warning("Could not extract path components from uploads_folder: " + uploadsFolder);
                LOGGER.info("Falling back to absolute paths");
                return updateFilePathsAbsolute(vdbXml, uploadsFolder);
            }

            String pattern1 = "LOCATION='file:///opt/wildfly/teiidfiles/(?:excelFilesTest|CSVFiles|customers/\\d+/uploads)/([^']+)'";
            String replacement1 = "LOCATION='file:///" + relativePathPrefix + "/$1'";
            updatedXml = updatedXml.replaceAll(pattern1, replacement1);

            String pattern1b = "LOCATION='file:///opt/wildfly/teiidfiles/([^']+)'";
            String replacement1b = "LOCATION='file:///" + relativePathPrefix + "/$1'";
            updatedXml = updatedXml.replaceAll(pattern1b, replacement1b);

            String pattern2 = "\"teiid_excel:FILE\"\\s+'/opt/wildfly/teiidfiles/(?:excelFilesTest|CSVFiles|customers/\\d+/uploads)/([^']+)'";
            String replacement2 = "\"teiid_excel:FILE\" '" + relativePathPrefix + "/$1'";
            updatedXml = updatedXml.replaceAll(pattern2, replacement2);

            String pattern2b = "\"teiid_excel:FILE\"\\s+'/opt/wildfly/teiidfiles/([^']+)'";
            String replacement2b = "\"teiid_excel:FILE\" '" + relativePathPrefix + "/$1'";
            updatedXml = updatedXml.replaceAll(pattern2b, replacement2b);

            updatedXml = updatedXml.replaceAll("\\s*<property name=\"ParentDirectory\" value=\"[^\"]*\"/>\\s*\\n?", "");
            updatedXml = updatedXml.replaceAll("\\s*<property name=\"importer\\.ParentDirectory\" value=\"[^\"]*\"/>\\s*\\n?", "");

            String pattern5 = "<property name=\"connection-url\" value=\"file:///opt/wildfly/teiidfiles/(?:excelFilesTest|CSVFiles|customers/\\d+/uploads)/([^\"]+)\"";
            String replacement5 = "<property name=\"connection-url\" value=\"file:///" + relativePathPrefix + "/$1\"";
            updatedXml = updatedXml.replaceAll(pattern5, replacement5);

            String pattern5b = "<property name=\"connection-url\" value=\"file:///opt/wildfly/teiidfiles/([^\"]+)\"";
            String replacement5b = "<property name=\"connection-url\" value=\"file:///" + relativePathPrefix + "/$1\"";
            updatedXml = updatedXml.replaceAll(pattern5b, replacement5b);

            String pattern6 = "LOCATION='/opt/wildfly/teiidfiles/(?:excelFilesTest|CSVFiles|customers/\\d+/uploads)/([^']+)'";
            String replacement6 = "LOCATION='" + relativePathPrefix + "/$1'";
            updatedXml = updatedXml.replaceAll(pattern6, replacement6);

            String pattern6b = "LOCATION='/opt/wildfly/teiidfiles/([^']+)'";
            String replacement6b = "LOCATION='" + relativePathPrefix + "/$1'";
            updatedXml = updatedXml.replaceAll(pattern6b, replacement6b);

            LOGGER.info("File paths converted to relative format successfully");

            return updatedXml;

        } catch (Exception e) {
            LOGGER.log(Level.SEVERE, "Error updating file paths: " + e.getMessage(), e);
            return vdbXml;
        }
    }

    /**
     * Fallback method: Update file paths using absolute paths (legacy behavior).
     */
    public static String updateFilePathsAbsolute(String vdbXml, String uploadsFolder) {
        try {
            LOGGER.info("Using absolute paths for customer folder: " + uploadsFolder);

            String updatedXml = vdbXml;

            String pattern1 = "LOCATION='file:///opt/wildfly/teiidfiles/([^']+)'";
            String replacement1 = "LOCATION='file://" + uploadsFolder + "/$1'";
            updatedXml = updatedXml.replaceAll(pattern1, replacement1);

            String pattern2 = "LOCATION='/opt/wildfly/teiidfiles/([^']+)'";
            String replacement2 = "LOCATION='" + uploadsFolder + "/$1'";
            updatedXml = updatedXml.replaceAll(pattern2, replacement2);

            String pattern3 = "<property name=\"ParentDirectory\" value=\"/opt/wildfly/teiidfiles\"";
            String replacement3 = "<property name=\"ParentDirectory\" value=\"" + uploadsFolder + "\"";
            updatedXml = updatedXml.replace(pattern3, replacement3);

            String pattern4 = "<property name=\"importer\\.ParentDirectory\" value=\"/opt/wildfly/teiidfiles\"";
            String replacement4 = "<property name=\"importer.ParentDirectory\" value=\"" + uploadsFolder + "\"";
            updatedXml = updatedXml.replace(pattern4, replacement4);

            String pattern5 = "<property name=\"connection-url\" value=\"file:///opt/wildfly/teiidfiles/([^\"]+)\"";
            String replacement5 = "<property name=\"connection-url\" value=\"file://" + uploadsFolder + "/$1\"";
            updatedXml = updatedXml.replaceAll(pattern5, replacement5);

            String pattern6 = "/opt/wildfly/teiidfiles/([^\\s<>\"']+)";
            String replacement6 = uploadsFolder + "/$1";
            updatedXml = updatedXml.replaceAll(pattern6, replacement6);

            LOGGER.info("File paths updated successfully using absolute paths");

            return updatedXml;

        } catch (Exception e) {
            LOGGER.log(Level.SEVERE, "Error updating file paths: " + e.getMessage(), e);
            return vdbXml;
        }
    }

    /**
     * Configure VDB credentials in VDB XML.
     */
    public static String configureVDBCredentials(String vdbXml, String username, String password) {
        return vdbXml;
    }

    /** Build a PHYSICAL model block with an explicit CREATE FOREIGN TABLE. */
    public static String buildServiceNowModelBlock(String modelName, String dsName, String translatorName,
                                                   String teiidTableName, String tableName, JSONArray columns) {
        StringBuilder cols = new StringBuilder();
        if (columns != null && columns.length() > 0) {
            for (int i = 0; i < columns.length(); i++) {
                JSONObject c = columns.getJSONObject(i);
                String name = c.getString("name");
                String type = c.optString("teiid_type", "string");
                String srcName = c.optString("name_in_source", name);
                String viewId = "\"" + name.replace("\"", "\"\"") + "\"";
                String nameInSourceLiteral = srcName.replace("'", "''");
                cols.append("\t").append(viewId).append(" ").append(type)
                    .append(" OPTIONS (NAMEINSOURCE '").append(nameInSourceLiteral).append("')");
                if (i < columns.length() - 1) cols.append(",");
                cols.append("\n");
            }
        } else {
            cols.append("\t\"__row__\" string\n");
        }

        StringBuilder sb = new StringBuilder();
        sb.append("\n");
        sb.append("  <model name=\"").append(modelName).append("\" type=\"PHYSICAL\" visible=\"false\">\n");
        sb.append("    <source name=\"").append(dsName).append("\" translator-name=\"").append(translatorName).append("\"/>\n");
        sb.append("    <metadata type=\"DDL\">\n");
        sb.append("      <![CDATA[\n");
        sb.append("CREATE FOREIGN TABLE ").append(teiidTableName).append(" (\n");
        sb.append(cols);
        sb.append(") OPTIONS (NAMEINSOURCE '").append(tableName.replace("'", "''")).append("');\n");
        sb.append("]]>\n");
        sb.append("    </metadata>\n");
        sb.append("  </model>\n");
        return sb.toString();
    }

    public static String buildServiceNowTranslatorBlock(String translatorName, String instanceUrl,
                                                        String username, String password) {
        return "\n  <translator name=\"" + translatorName + "\" type=\"servicenow\">\n" +
               "    <property name=\"instanceUrl\" value=\"" + xmlEncode(instanceUrl) + "\"/>\n" +
               "    <property name=\"username\" value=\"" + xmlEncode(username) + "\"/>\n" +
               "    <property name=\"password\" value=\"" + xmlEncode(password) + "\"/>\n" +
               "  </translator>\n";
    }

    public static String xmlEncode(String value) {
        if (value == null) return "";
        return value.replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;")
                    .replace("\"", "&quot;");
    }

    /** Build a PHYSICAL model block for a custom HTTP translator (HubSpot, QuickBooks). */
    public static String buildCustomHttpModelBlock(String modelName, String dsName, String translatorName,
                                                    String teiidTableName, String tableName, JSONArray columns) {
        StringBuilder cols = new StringBuilder();
        if (columns != null && columns.length() > 0) {
            for (int i = 0; i < columns.length(); i++) {
                JSONObject c = columns.getJSONObject(i);
                String name = c.getString("name");
                String type = c.optString("teiid_type", "string");
                String srcName = c.optString("name_in_source", name);
                String viewId = "\"" + name.replace("\"", "\"\"") + "\"";
                String nameInSourceLiteral = srcName.replace("'", "''");
                cols.append("\t").append(viewId).append(" ").append(type)
                    .append(" OPTIONS (NAMEINSOURCE '").append(nameInSourceLiteral).append("')");
                if (i < columns.length() - 1) cols.append(",");
                cols.append("\n");
            }
        } else {
            cols.append("\t\"__row__\" string\n");
        }

        StringBuilder sb = new StringBuilder();
        sb.append("\n");
        sb.append("  <model name=\"").append(modelName).append("\" type=\"PHYSICAL\" visible=\"false\">\n");
        sb.append("    <source name=\"").append(dsName).append("\" translator-name=\"").append(translatorName).append("\"/>\n");
        sb.append("    <metadata type=\"DDL\">\n");
        sb.append("      <![CDATA[\n");
        sb.append("CREATE FOREIGN TABLE ").append(teiidTableName).append(" (\n");
        sb.append(cols);
        sb.append(") OPTIONS (NAMEINSOURCE '").append(tableName.replace("'", "''")).append("');\n");
        sb.append("]]>\n");
        sb.append("    </metadata>\n");
        sb.append("  </model>\n");
        return sb.toString();
    }

    public static String buildCustomHttpTranslatorBlock(String translatorName, String translatorType,
                                                        Map<String, String> properties) {
        StringBuilder sb = new StringBuilder();
        sb.append("\n  <translator name=\"").append(translatorName).append("\" type=\"").append(translatorType).append("\">\n");
        for (Map.Entry<String, String> e : properties.entrySet()) {
            sb.append("    <property name=\"").append(xmlEncode(e.getKey())).append("\" value=\"")
              .append(xmlEncode(e.getValue() != null ? e.getValue() : "")).append("\"/>\n");
        }
        sb.append("  </translator>\n");
        return sb.toString();
    }

    /** Build a PHYSICAL model block for the native Teiid Salesforce translator. */
    public static String buildSalesforceModelBlock(String modelName, String dsName, String translatorName,
                                                   String jndiName, String teiidTableName,
                                                   String tableName, JSONArray columns) {
        StringBuilder cols = new StringBuilder();
        if (columns != null && columns.length() > 0) {
            for (int i = 0; i < columns.length(); i++) {
                JSONObject c = columns.getJSONObject(i);
                String name = c.getString("name");
                String type = c.optString("teiid_type", "string");
                String srcName = c.optString("name_in_source", name);
                String viewId = "\"" + name.replace("\"", "\"\"") + "\"";
                String nameInSourceLiteral = srcName.replace("'", "''");
                cols.append("\t").append(viewId).append(" ").append(type)
                    .append(" OPTIONS (NAMEINSOURCE '").append(nameInSourceLiteral).append("')");
                if (i < columns.length() - 1) cols.append(",");
                cols.append("\n");
            }
        } else {
            cols.append("\t\"__row__\" string\n");
        }

        StringBuilder sb = new StringBuilder();
        sb.append("\n");
        sb.append("  <model name=\"").append(modelName).append("\" type=\"PHYSICAL\" visible=\"false\">\n");
        sb.append("    <source name=\"").append(dsName).append("\" translator-name=\"").append(translatorName)
          .append("\" connection-jndi-name=\"").append(jndiName).append("\"/>\n");
        sb.append("    <metadata type=\"DDL\">\n");
        sb.append("      <![CDATA[\n");
        sb.append("CREATE FOREIGN TABLE ").append(teiidTableName).append(" (\n");
        sb.append(cols);
        sb.append(") OPTIONS (NAMEINSOURCE '").append(tableName.replace("'", "''")).append("');\n");
        sb.append("]]>\n");
        sb.append("    </metadata>\n");
        sb.append("  </model>\n");
        return sb.toString();
    }

    /** Build a PHYSICAL model block for a JDBC-backed source. */
    public static String buildPhysicalModelBlock(String modelName, String dsName, String translator,
                                                  String jndiName, String teiidTableName, String schemaName,
                                                  String tableName, JSONArray columns) {
        boolean backtick = translator != null && (
                translator.toLowerCase().startsWith("mysql")
                        || "hive".equalsIgnoreCase(translator)
                        || "databricks".equalsIgnoreCase(translator));
        char q = backtick ? '`' : '"';

        StringBuilder cols = new StringBuilder();
        if (columns != null && columns.length() > 0) {
            for (int i = 0; i < columns.length(); i++) {
                JSONObject c = columns.getJSONObject(i);
                String name = c.getString("name");
                String type = c.optString("teiid_type", "string");
                String srcName = c.optString("name_in_source", name);
                String viewId = "\"" + name.replace("\"", "\"\"") + "\"";
                String srcId = q + srcName.replace(String.valueOf(q), "" + q + q) + q;
                String nameInSourceLiteral = srcId.replace("'", "''");
                cols.append("\t").append(viewId).append(" ").append(type)
                    .append(" OPTIONS (NAMEINSOURCE '").append(nameInSourceLiteral).append("')");
                if (i < columns.length() - 1) cols.append(",");
                cols.append("\n");
            }
        } else {
            cols.append("\t\"__row__\" string\n");
        }

        String nameInSource;
        if (schemaName != null && !schemaName.isEmpty()) {
            nameInSource = q + schemaName + q + "." + q + tableName + q;
        } else {
            nameInSource = q + tableName + q;
        }

        StringBuilder sb = new StringBuilder();
        sb.append("\n");
        sb.append("  <model name=\"").append(modelName).append("\" type=\"PHYSICAL\" visible=\"false\">\n");
        sb.append("    <source name=\"").append(dsName).append("\" translator-name=\"").append(translator)
          .append("\" connection-jndi-name=\"").append(jndiName).append("\"/>\n");
        sb.append("    <metadata type=\"DDL\">\n");
        sb.append("      <![CDATA[\n");
        sb.append("CREATE FOREIGN TABLE ").append(teiidTableName).append(" (\n");
        sb.append(cols);
        sb.append(") OPTIONS (NAMEINSOURCE '").append(nameInSource).append("');\n");
        sb.append("]]>\n");
        sb.append("    </metadata>\n");
        sb.append("  </model>\n");
        return sb.toString();
    }

    /** Insert {@code insertion} immediately before the first occurrence of {@code anchor}. */
    public static String insertBefore(String content, String anchor, String insertion) {
        int idx = content.indexOf(anchor);
        if (idx < 0) {
            LOGGER.warning("Anchor not found for insertBefore: " + anchor);
            return content;
        }
        return content.substring(0, idx) + insertion + content.substring(idx);
    }

    /** Insert {@code insertion} immediately before the earliest of the given anchors. */
    public static String insertBeforeFirst(String content, String insertion, String... anchors) {
        int bestIdx = -1;
        String bestAnchor = null;
        for (String anchor : anchors) {
            int idx = content.indexOf(anchor);
            if (idx >= 0 && (bestIdx < 0 || idx < bestIdx)) {
                bestIdx = idx;
                bestAnchor = anchor;
            }
        }
        if (bestIdx < 0) {
            LOGGER.warning("No anchor found for insertBeforeFirst: " + String.join(", ", anchors));
            return content;
        }
        return content.substring(0, bestIdx) + insertion + content.substring(bestIdx);
    }

    /** Remove a <model name="..."> ... </model> block from VDB XML. */
    public static String removeModelBlock(String content, String modelName) {
        String start = "  <model name=\"" + modelName + "\"";
        int s = content.indexOf(start);
        if (s < 0) {
            start = "<model name=\"" + modelName + "\"";
            s = content.indexOf(start);
        }
        if (s < 0) return content;
        int e = content.indexOf("</model>", s);
        if (e < 0) return content;
        e += "</model>".length();
        while (e < content.length() && (content.charAt(e) == '\n' || content.charAt(e) == '\r')) e++;
        return content.substring(0, s) + content.substring(e);
    }

    /** Remove a <translator name="..."> ... </translator> block from VDB XML. */
    public static String removeTranslatorBlock(String content, String translatorName) {
        String start = "<translator name=\"" + translatorName + "\"";
        int s = content.indexOf(start);
        if (s < 0) return content;
        int e = content.indexOf("</translator>", s);
        if (e < 0) return content;
        e += "</translator>".length();
        while (e < content.length() && (content.charAt(e) == '\n' || content.charAt(e) == '\r')) e++;
        return content.substring(0, s) + content.substring(e);
    }

    /** Remove a CREATE VIEW ... ; statement from the virtual model DDL. */
    public static String removeViewStmt(String content, String viewName) {
        String prefix = "CREATE VIEW " + viewName + " AS SELECT * FROM ";
        int s = content.indexOf(prefix);
        if (s < 0) return content;
        int e = content.indexOf(";", s);
        if (e < 0) return content;
        e++;
        while (e < content.length() && (content.charAt(e) == '\n' || content.charAt(e) == '\r')) e++;
        return content.substring(0, s) + content.substring(e);
    }

    public static String newline() {
        return "\n";
    }
}
