package cloud.tablescope;

import java.io.File;
import java.io.FileInputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.logging.Level;
import java.util.logging.Logger;
import org.teiid.adminapi.Admin;
import org.teiid.adminapi.jboss.AdminFactory;

/**
 * Helper for deploying and managing VDBs on a Teiid/WildFly server.
 *
 * Admin credentials are provided via the constructor; host/port are supplied per call
 * so that callers (such as VDBManagementServlet) can use request-specific connection info.
 */
public class TeiidDeployHelper {

    private static final Logger LOGGER = Logger.getLogger(TeiidDeployHelper.class.getName());

    private final String teiidAdminUser;
    private final String teiidAdminPassword;

    /** Default helper using localhost:9990 and admin/admin credentials. */
    public TeiidDeployHelper() {
        this("admin", "admin");
    }

    public TeiidDeployHelper(String teiidAdminUser, String teiidAdminPassword) {
        this.teiidAdminUser = teiidAdminUser;
        this.teiidAdminPassword = teiidAdminPassword;
    }

    /** Deploy a VDB to Teiid without undeploying first. */
    public void deployVDB(String vdbFilePath, String vdbDeploymentName,
                           String teiidHost, int teiidPort) throws Exception {
        LOGGER.info("Connecting to Teiid management at " + teiidHost + ":" + teiidPort);

        Admin admin = AdminFactory.getInstance().createAdmin(
                teiidHost, teiidPort, teiidAdminUser, teiidAdminPassword.toCharArray());

        try (InputStream inputStream = new FileInputStream(vdbFilePath)) {
            admin.deploy(vdbDeploymentName, inputStream);
            LOGGER.info("VDB deployed to Teiid: " + vdbDeploymentName);
        } finally {
            admin.close();
        }
    }

    /** Convenience overload for localhost:9990. */
    public void deployVDB(String vdbFilePath, String vdbDeploymentName) throws Exception {
        deployVDB(vdbFilePath, vdbDeploymentName, "localhost", 9990);
    }

    /** Undeploy and then deploy a VDB. */
    public void redeployVDB(String vdbFilePath, String vdbDeploymentName,
                            String teiidHost, int teiidPort) throws Exception {
        LOGGER.info("Connecting to Teiid management at " + teiidHost + ":" + teiidPort);

        Admin admin = AdminFactory.getInstance().createAdmin(
                teiidHost, teiidPort, teiidAdminUser, teiidAdminPassword.toCharArray());

        try {
            try {
                admin.undeploy(vdbDeploymentName);
                LOGGER.info("VDB undeployed: " + vdbDeploymentName);
            } catch (Exception e) {
                LOGGER.info("Warning: Failed to undeploy VDB (may not be deployed): " + e.getMessage());
            }

            try (InputStream inputStream = new FileInputStream(vdbFilePath)) {
                admin.deploy(vdbDeploymentName, inputStream);
            }
            LOGGER.info("VDB redeployed successfully: " + vdbDeploymentName);
        } finally {
            admin.close();
        }
    }

    /** Convenience overload for localhost:9990. */
    public void redeployVDB(String vdbFilePath, String vdbDeploymentName) throws Exception {
        redeployVDB(vdbFilePath, vdbDeploymentName, "localhost", 9990);
    }

    /**
     * Deploy a VDB, then restore the original file content.
     *
     * Teiid's deploy() may modify the file on disk (stripping CDATA). This preserves it.
     */
    public void deployPreservingOriginal(String vdbPath) throws Exception {
        deployPreservingOriginal(vdbPath, "localhost", 9990);
    }

    public void deployPreservingOriginal(String vdbPath, String teiidHost, int teiidPort) throws Exception {
        String vdbFileName = new File(vdbPath).getName();
        LOGGER.info("Redeploying VDB: " + vdbFileName);

        String originalContent = new String(Files.readAllBytes(Paths.get(vdbPath)), StandardCharsets.UTF_8);

        deployVDB(vdbPath, vdbFileName, teiidHost, teiidPort);

        Files.write(Paths.get(vdbPath), originalContent.getBytes(StandardCharsets.UTF_8));
        LOGGER.info("Restored VDB file with CDATA preserved: " + vdbPath);
    }

    /**
     * Clear a Teiid cache. Logs failures rather than throwing, matching the original
     * invalidateTeiidCache behavior used during file uploads.
     */
    public void clearCache(String cacheName) {
        try {
            Admin admin = AdminFactory.getInstance().createAdmin(
                    "localhost", 9990, teiidAdminUser, teiidAdminPassword.toCharArray());
            try {
                admin.clearCache(cacheName);
                LOGGER.info("[TeiidExcelImporter] Cache invalidated: " + cacheName);
            } finally {
                admin.close();
            }
        } catch (Exception e) {
            System.err.println("[TeiidExcelImporter] Failed to invalidate cache: " + e.getMessage());
            e.printStackTrace();
        }
    }

    /** Invalidate a named cache (alias for clearCache). */
    public void invalidateTeiidCache(String cacheName) {
        clearCache(cacheName);
    }
}
