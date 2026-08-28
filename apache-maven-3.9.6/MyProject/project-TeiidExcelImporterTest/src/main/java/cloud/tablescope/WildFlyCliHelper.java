package cloud.tablescope;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.util.concurrent.TimeUnit;
import java.util.logging.Level;
import java.util.logging.Logger;

/**
 * Static helpers for running WildFly CLI commands and managing datasources.
 */
public class WildFlyCliHelper {

    private static final Logger LOGGER = Logger.getLogger(WildFlyCliHelper.class.getName());

    /** Map a db_type to the WildFly JDBC driver (template) name. */
    public static String driverNameFor(String dbType) {
        if ("postgresql".equalsIgnoreCase(dbType)) return "postgresql";
        if ("mysql".equalsIgnoreCase(dbType)) return "mysql";
        if ("sqlserver".equalsIgnoreCase(dbType)) return "sqlserver";
        if ("oracle".equalsIgnoreCase(dbType)) return "oracle";
        return dbType;
    }

    /** Create the WildFly JDBC datasource if it does not already exist. */
    public static void ensureDataSource(String dsName, String dbType,
                                         String jdbcUrl, String username, String password) throws Exception {
        if (dataSourceExists(dsName)) {
            LOGGER.info("Datasource already exists: " + dsName);
            return;
        }

        String driver = driverNameFor(dbType);
        String escUser = username == null ? "" : username.replace("\\", "\\\\").replace("\"", "\\\"");
        String escUrl = jdbcUrl == null ? "" : jdbcUrl.replace("\\", "\\\\").replace("\"", "\\\"");

        String passwordParam = "";
        if (password != null && !password.isEmpty()) {
            String escPass = password.replace("\\", "\\\\").replace("\"", "\\\"");
            passwordParam = ", password=\"" + escPass + "\"";
        }

        String command = "/subsystem=datasources/data-source=" + dsName + ":add("
                + "jndi-name=java:/" + dsName
                + ", driver-name=" + driver
                + ", connection-url=\"" + escUrl + "\""
                + ", user-name=\"" + escUser + "\""
                + passwordParam
                + ", enabled=true)";

        LOGGER.info("Creating datasource " + dsName + " with driver " + driver + " via CLI");
        String result = runCli(command);
        if (result == null || result.indexOf("\"outcome\" => \"success\"") < 0) {
            throw new Exception("CLI datasource creation failed: " + result);
        }
        LOGGER.info("Datasource created: " + dsName);
    }

    /** Return true if a WildFly data-source with this name already exists. */
    public static boolean dataSourceExists(String dsName) {
        try {
            String out = runCli("/subsystem=datasources:read-children-names(child-type=data-source)");
            return out != null && out.contains("\"" + dsName + "\"");
        } catch (Exception e) {
            LOGGER.log(Level.WARNING, "Could not list datasources: " + e.getMessage(), e);
            return false;
        }
    }

    /** Run a jboss-cli command against the local management interface (local auth). */
    public static String runCli(String command) throws Exception {
        String jbossHome = System.getProperty("jboss.home.dir", "/opt/wildfly");
        ProcessBuilder pb = new ProcessBuilder(
                jbossHome + "/bin/jboss-cli.sh",
                "--connect",
                "--controller=localhost:9990",
                "--command=" + command);
        pb.redirectErrorStream(true);
        Process p = pb.start();
        StringBuilder sb = new StringBuilder();
        try (BufferedReader reader = new BufferedReader(
                new InputStreamReader(p.getInputStream(), "UTF-8"))) {
            String line;
            while ((line = reader.readLine()) != null) {
                sb.append(line).append("\n");
            }
        }
        boolean finished = p.waitFor(60, TimeUnit.SECONDS);
        if (!finished) {
            p.destroyForcibly();
            throw new Exception("jboss-cli timed out");
        }
        return sb.toString();
    }

    /** Run a jboss-cli command and throw if the response reports failure. */
    public static String runCliChecked(String command) throws Exception {
        String out = runCli(command);
        if (out != null && out.contains("\"outcome\" => \"failed\"")) {
            throw new Exception("CLI command failed: " + command + "\n" + out);
        }
        return out;
    }

    public static boolean isSalesforceTranslator(String translator) {
        return translator != null && translator.toLowerCase().startsWith("salesforce");
    }

    public static String salesforceResourceAdapterName(String translator) {
        if (translator == null) return "salesforce";
        String t = translator.toLowerCase();
        if (t.contains("41")) return "salesforce-41";
        if (t.contains("34")) return "salesforce-34";
        return "salesforce";
    }

    public static String normalizeSalesforceSoapUrl(String url) {
        if (url == null || url.trim().isEmpty()) {
            return "https://login.salesforce.com/services/Soap/u/41.0";
        }
        String normalized = url.trim();
        if (normalized.endsWith("/")) {
            normalized = normalized.substring(0, normalized.length() - 1);
        }
        if (normalized.contains("/services/Soap/")) {
            return normalized;
        }
        if (normalized.contains("/services/")) {
            normalized = normalized.substring(0, normalized.indexOf("/services/"));
        }
        return normalized + "/services/Soap/u/41.0";
    }

    public static void ensureSalesforceConnectionFactory(String dsName, String translator,
                                                          String url, String username, String password) throws Exception {
        String ra = salesforceResourceAdapterName(translator);
        try {
            runCliChecked("/subsystem=resource-adapters/resource-adapter=" + ra
                    + "/connection-definitions=" + dsName + ":remove");
        } catch (Exception e) {
            LOGGER.log(Level.INFO, "Ignoring Salesforce connection factory removal for " + dsName + ": " + e.getMessage());
        }

        String addCmd = "/subsystem=resource-adapters/resource-adapter=" + ra
                + "/connection-definitions=" + dsName + ":add("
                + "jndi-name=\"java:/" + dsName + "\", "
                + "class-name=\"org.teiid.resource.adapter.salesforce.SalesForceManagedConnectionFactory\", "
                + "enabled=true, use-java-context=true)";
        runCliChecked(addCmd);

        runCliChecked("/subsystem=resource-adapters/resource-adapter=" + ra
                + "/connection-definitions=" + dsName + "/config-properties=URL:add(value=\"" + url + "\")");

        String escUser = username == null ? "" : username.replace("\\", "\\\\").replace("\"", "\\\"");
        runCliChecked("/subsystem=resource-adapters/resource-adapter=" + ra
                + "/connection-definitions=" + dsName + "/config-properties=username:add(value=\"" + escUser + "\")");

        String escPass = password == null ? "" : password.replace("\\", "\\\\").replace("\"", "\\\"");
        runCliChecked("/subsystem=resource-adapters/resource-adapter=" + ra
                + "/connection-definitions=" + dsName + "/config-properties=password:add(value=\"" + escPass + "\")");

        runCliChecked("/subsystem=resource-adapters/resource-adapter=" + ra + ":activate");
        LOGGER.info("Salesforce connection factory created/updated: " + dsName + " via RA " + ra);
    }

    public static void removeSalesforceConnectionFactory(String dsName, String translator) {
        try {
            String ra = salesforceResourceAdapterName(translator);
            runCliChecked("/subsystem=resource-adapters/resource-adapter=" + ra
                    + "/connection-definitions=" + dsName + ":remove");
            runCliChecked("/subsystem=resource-adapters/resource-adapter=" + ra + ":activate");
            LOGGER.info("Removed Salesforce connection factory: " + dsName);
        } catch (Exception e) {
            LOGGER.log(Level.WARNING, "Could not remove Salesforce connection factory " + dsName + ": " + e.getMessage(), e);
        }
    }

    /** Add or replace a Google Spreadsheet resource-adapter connection factory. */
    public static void ensureGoogleSpreadsheetConnectionFactory(String dsName, String spreadsheetId,
                                                                 String refreshToken, String clientId,
                                                                 String clientSecret, String apiVersion) throws Exception {
        // The google resource adapter is already declared in standalone-teiid.xml.
        try {
            runCliChecked("/subsystem=resource-adapters/resource-adapter=google/connection-definitions=" + dsName + ":remove");
        } catch (Exception e) {
            LOGGER.log(Level.INFO, "Ignoring Google spreadsheet connection factory removal for " + dsName + ": " + e.getMessage());
        }

        String addCmd = "/subsystem=resource-adapters/resource-adapter=google/connection-definitions=" + dsName + ":add("
                + "jndi-name=\"java:/" + dsName + "\", "
                + "class-name=\"org.teiid.resource.adapter.google.SpreadsheetManagedConnectionFactory\", "
                + "enabled=true, use-java-context=true)";
        runCliChecked(addCmd);

        String escSpreadsheetId = spreadsheetId == null ? "" : spreadsheetId.replace("\\", "\\\\").replace("\"", "\\\"");
        runCliChecked("/subsystem=resource-adapters/resource-adapter=google/connection-definitions=" + dsName
                + "/config-properties=SpreadsheetId:add(value=\"" + escSpreadsheetId + "\")");

        String escRefreshToken = refreshToken == null ? "" : refreshToken.replace("\\", "\\\\").replace("\"", "\\\"");
        runCliChecked("/subsystem=resource-adapters/resource-adapter=google/connection-definitions=" + dsName
                + "/config-properties=RefreshToken:add(value=\"" + escRefreshToken + "\")");

        String escClientId = clientId == null ? "" : clientId.replace("\\", "\\\\").replace("\"", "\\\"");
        runCliChecked("/subsystem=resource-adapters/resource-adapter=google/connection-definitions=" + dsName
                + "/config-properties=ClientId:add(value=\"" + escClientId + "\")");

        String escClientSecret = clientSecret == null ? "" : clientSecret.replace("\\", "\\\\").replace("\"", "\\\"");
        runCliChecked("/subsystem=resource-adapters/resource-adapter=google/connection-definitions=" + dsName
                + "/config-properties=ClientSecret:add(value=\"" + escClientSecret + "\")");

        String ver = (apiVersion == null || apiVersion.isEmpty()) ? "v4" : apiVersion;
        runCliChecked("/subsystem=resource-adapters/resource-adapter=google/connection-definitions=" + dsName
                + "/config-properties=ApiVersion:add(value=\"" + ver + "\")");

        runCliChecked("/subsystem=resource-adapters/resource-adapter=google/connection-definitions=" + dsName
                + "/config-properties=BatchSize:add(value=\"4096\")");

        runCliChecked("/subsystem=resource-adapters/resource-adapter=google:activate");
        LOGGER.info("Google spreadsheet connection factory created/updated: " + dsName);
    }

    public static void removeGoogleSpreadsheetConnectionFactory(String dsName) {
        try {
            runCliChecked("/subsystem=resource-adapters/resource-adapter=google/connection-definitions=" + dsName + ":remove");
            runCliChecked("/subsystem=resource-adapters/resource-adapter=google:activate");
            LOGGER.info("Removed Google spreadsheet connection factory: " + dsName);
        } catch (Exception e) {
            LOGGER.log(Level.WARNING, "Could not remove Google spreadsheet connection factory " + dsName + ": " + e.getMessage(), e);
        }
    }
}
