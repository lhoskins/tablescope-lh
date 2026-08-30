package cloud.tablescope;

import java.io.File;
import java.io.FilenameFilter;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.Random;
import java.util.logging.Level;
import java.util.logging.Logger;

/**
 * Helper for locating VDB files and performing related filesystem operations.
 *
 * The base path is configurable per instance so that servlets can pass the value
 * loaded from environment/configuration while standalone callers can use the default.
 */
public class VDBFileLocator {

    private static final Logger LOGGER = Logger.getLogger(VDBFileLocator.class.getName());

    private final String vdbBasePath;

    public VDBFileLocator() {
        this("/opt/wildfly/teiidfiles");
    }

    public VDBFileLocator(String vdbBasePath) {
        this.vdbBasePath = vdbBasePath;
    }

    /**
     * Find VDB file (search in customer folders first, then base path).
     *
     * @param vdbId The VDB identifier
     * @return Full path to VDB file, or null if not found
     */
    public String findVDBFile(String vdbId) {
        String fileName = vdbId + "-vdb.xml";

        LOGGER.info("Searching for VDB file: " + fileName);

        File customersDir = new File(vdbBasePath + "/customers");
        if (customersDir.exists() && customersDir.isDirectory()) {
            File[] orgDirs = customersDir.listFiles();
            if (orgDirs != null) {
                for (File orgDir : orgDirs) {
                    if (orgDir.isDirectory()) {
                        String vdbPath = orgDir.getAbsolutePath() + "/vdb/" + fileName;
                        if (new File(vdbPath).exists()) {
                            LOGGER.info("Found VDB file in customer folder: " + vdbPath);
                            return vdbPath;
                        }
                    }
                }
            }
        }

        String basePath = vdbBasePath + "/" + fileName;
        if (new File(basePath).exists()) {
            LOGGER.info("Found VDB file in base path: " + basePath);
            return basePath;
        }

        LOGGER.info("VDB file not found: " + fileName);
        return null;
    }

    /**
     * Delete VDB file from customer folder or base path.
     *
     * @param vdbId The VDB identifier
     * @return true if file was deleted, false otherwise
     */
    public boolean deleteVDBFile(String vdbId) {
        String vdbPath = findVDBFile(vdbId);
        if (vdbPath != null) {
            File vdbFile = new File(vdbPath);
            boolean deleted = vdbFile.delete();
            if (deleted) {
                LOGGER.info("VDB file deleted successfully: " + vdbPath);
            } else {
                LOGGER.warning("Failed to delete VDB file: " + vdbPath);
            }
            return deleted;
        } else {
            LOGGER.warning("VDB file not found for deletion: " + vdbId + "-vdb.xml");
            return false;
        }
    }

    /**
     * Validate that a folder exists.
     */
    public boolean validateFolderExists(String folderPath) {
        File folder = new File(folderPath);
        return folder.exists() && folder.isDirectory();
    }

    /**
     * Create folder if it doesn't exist (including parent directories).
     *
     * @param folderPath Path to folder to create
     * @return true if folder exists or was created successfully, false otherwise
     */
    public boolean createFolderIfNotExists(String folderPath) {
        try {
            File folder = new File(folderPath);

            if (folder.exists() && folder.isDirectory()) {
                LOGGER.info("Folder already exists: " + folderPath);
                return true;
            }

            boolean created = folder.mkdirs();

            if (created) {
                LOGGER.info("Created folder: " + folderPath);
                return true;
            } else {
                LOGGER.warning("Failed to create folder: " + folderPath);
                return false;
            }

        } catch (Exception e) {
            LOGGER.log(Level.SEVERE, "Error creating folder: " + folderPath + " - " + e.getMessage(), e);
            return false;
        }
    }

    /**
     * Set folder permissions to 2777 (rwxrwsrwx) with setgid bit.
     */
    public void setFolderPermissions(String folderPath) {
        try {
            ProcessBuilder pb = new ProcessBuilder("chmod", "2777", folderPath);
            Process process = pb.start();
            int exitCode = process.waitFor();

            if (exitCode == 0) {
                LOGGER.info("Set folder permissions to 2777 (with setgid): " + folderPath);
            } else {
                LOGGER.warning("chmod command failed with exit code " + exitCode + " for: " + folderPath);
            }
        } catch (Exception e) {
            LOGGER.log(Level.WARNING, "Failed to set folder permissions for " + folderPath + ": " + e.getMessage(), e);
        }
    }

    /**
     * Read file content as string (UTF-8).
     */
    public String readFile(String filePath) throws IOException {
        LOGGER.info("Reading file: " + filePath);
        byte[] bytes = Files.readAllBytes(Paths.get(filePath));
        String content = new String(bytes, "UTF-8");
        LOGGER.info("File read successfully: " + filePath + " (" + bytes.length + " bytes)");
        return content;
    }

    /**
     * Write string content to file (UTF-8).
     */
    public void writeFile(String filePath, String content) throws IOException {
        LOGGER.info("Writing file: " + filePath + " (" + content.length() + " characters)");

        File file = new File(filePath);
        File parentDir = file.getParentFile();
        if (parentDir != null && !parentDir.exists()) {
            LOGGER.info("Creating parent directory: " + parentDir.getAbsolutePath());
            if (!parentDir.mkdirs()) {
                throw new IOException("Failed to create parent directory: " + parentDir.getAbsolutePath());
            }
        }

        Files.write(Paths.get(filePath), content.getBytes("UTF-8"));
        LOGGER.info("File written successfully: " + filePath);

        if (!file.exists()) {
            throw new IOException("File was not created: " + filePath);
        }
        LOGGER.info("File verified: " + filePath + " (" + file.length() + " bytes)");
    }

    /**
     * Find VDB file for a given organization ID.
     */
    public String findVDBFileForOrg(int orgId) {
        String vdbFolder = vdbBasePath + "/customers/" + orgId + "/vdb/";
        File folder = new File(vdbFolder);

        LOGGER.info("Searching for org VDB in: " + vdbFolder);

        if (!folder.exists() || !folder.isDirectory()) {
            LOGGER.info("Org VDB folder does not exist: " + vdbFolder);
            return null;
        }

        File[] vdbFiles = folder.listFiles(new FilenameFilter() {
            public boolean accept(File dir, String name) {
                return name.endsWith("-vdb.xml");
            }
        });

        if (vdbFiles != null && vdbFiles.length > 0) {
            String vdbPath = vdbFiles[0].getAbsolutePath();
            LOGGER.info("Found org VDB file: " + vdbPath);
            return vdbPath;
        }

        LOGGER.info("No org VDB file found in: " + vdbFolder);
        return null;
    }

    /**
     * Find VDB file for a given user within an organization.
     */
    public String findVDBFileForUser(int orgId, int userId) {
        String vdbFolder = vdbBasePath + "/customers/" + orgId + "/" + userId + "/vdb/";
        File folder = new File(vdbFolder);

        LOGGER.info("Searching for user VDB in: " + vdbFolder);

        if (!folder.exists() || !folder.isDirectory()) {
            LOGGER.info("User VDB folder does not exist: " + vdbFolder);
            return null;
        }

        File[] vdbFiles = folder.listFiles(new FilenameFilter() {
            public boolean accept(File dir, String name) {
                return name.endsWith("-vdb.xml");
            }
        });

        if (vdbFiles != null && vdbFiles.length > 0) {
            String vdbPath = vdbFiles[0].getAbsolutePath();
            LOGGER.info("Found user VDB file: " + vdbPath);
            return vdbPath;
        }

        LOGGER.info("No user VDB file found in: " + vdbFolder);
        return null;
    }

    /**
     * Find VDB file for shared project within an organization (legacy,
     * org-wide shared VDB -- one VDB shared by every project in the org).
     */
    public String findVDBFileForShared(int orgId) {
        return findVDBFileForShared(orgId, null);
    }

    /**
     * Find VDB file for a shared project. When {@code projectId} is
     * provided, each project gets its own shared VDB at
     * {@code /customers/{orgId}/shared/{projectId}/vdb/} so two shared
     * projects in the same org never resolve to the same VDB. When it is
     * null, falls back to the legacy org-wide shared path for backward
     * compatibility with VDBs provisioned before per-project scoping.
     */
    public String findVDBFileForShared(int orgId, Integer projectId) {
        String vdbFolder = projectId != null
            ? vdbBasePath + "/customers/" + orgId + "/shared/" + projectId + "/vdb/"
            : vdbBasePath + "/customers/" + orgId + "/shared/vdb/";
        File folder = new File(vdbFolder);

        LOGGER.info("Searching for shared VDB in: " + vdbFolder);

        if (!folder.exists() || !folder.isDirectory()) {
            LOGGER.info("Shared VDB folder does not exist: " + vdbFolder);
            return null;
        }

        File[] vdbFiles = folder.listFiles(new FilenameFilter() {
            public boolean accept(File dir, String name) {
                return name.endsWith("-vdb.xml");
            }
        });

        if (vdbFiles != null && vdbFiles.length > 0) {
            String vdbPath = vdbFiles[0].getAbsolutePath();
            LOGGER.info("Found shared VDB file: " + vdbPath);
            return vdbPath;
        }

        LOGGER.info("No shared VDB file found in: " + vdbFolder);
        return null;
    }

    /**
     * Find the user VDB path for migration operations.
     */
    public String findUserVDBPath(int orgId, int userId) {
        String vdbDir = vdbBasePath + "/customers/" + orgId + "/" + userId + "/vdb";
        File dir = new File(vdbDir);
        if (!dir.exists() || !dir.isDirectory()) return null;
        File[] vdbFiles = dir.listFiles((d, name) -> name.endsWith("-vdb.xml"));
        if (vdbFiles != null && vdbFiles.length > 0) {
            return vdbFiles[0].getAbsolutePath();
        }
        return null;
    }

    /**
     * Find the shared VDB path for migration operations.
     */
    public String findSharedVDBPath(int orgId) {
        String sharedVdbDir = vdbBasePath + "/customers/" + orgId + "/shared/vdb";
        File sharedDir = new File(sharedVdbDir);
        if (sharedDir.exists() && sharedDir.isDirectory()) {
            File[] vdbFiles = sharedDir.listFiles((d, name) -> name.endsWith("-vdb.xml"));
            if (vdbFiles != null && vdbFiles.length > 0) {
                LOGGER.info("Found shared VDB in shared/vdb directory: " + vdbFiles[0].getAbsolutePath());
                return vdbFiles[0].getAbsolutePath();
            }
        }

        String orgVdbDir = vdbBasePath + "/customers/" + orgId + "/vdb";
        File orgDir = new File(orgVdbDir);
        if (orgDir.exists() && orgDir.isDirectory()) {
            File[] vdbFiles = orgDir.listFiles((d, name) -> name.endsWith("-vdb.xml"));
            if (vdbFiles != null && vdbFiles.length > 0) {
                LOGGER.info("Found shared VDB in org vdb directory (legacy): " + vdbFiles[0].getAbsolutePath());
                return vdbFiles[0].getAbsolutePath();
            }
        }

        LOGGER.warning("No shared VDB found for org " + orgId);
        return null;
    }

    /**
     * Auto-provision a user VDB from template when it doesn't exist.
     */
    public String autoProvisionUserVDB(int orgId, int userId) {
        String customerFolder = vdbBasePath + "/customers/" + orgId + "/" + userId;
        String vdbFolder = customerFolder + "/vdb";
        String uploadsFolder = customerFolder + "/uploads";
        String templatePath = vdbBasePath + "/vdb_template/vdb_ template.xml";

        int vdbId = 1000000 + new Random().nextInt(9000000);
        String vdbFilePath = vdbFolder + "/" + vdbId + "-vdb.xml";

        LOGGER.info("Auto-provisioning user VDB: " + vdbFilePath);

        try {
            File customerDir = new File(customerFolder);
            if (!customerDir.exists()) {
                if (!customerDir.mkdirs()) {
                    System.err.println("[TeiidExcelImporterTest] Failed to create customer folder: " + customerFolder);
                    return null;
                }
                LOGGER.info("Created customer folder: " + customerFolder);
            }

            File vdbDir = new File(vdbFolder);
            if (!vdbDir.exists()) {
                if (!vdbDir.mkdirs()) {
                    System.err.println("[TeiidExcelImporterTest] Failed to create VDB folder: " + vdbFolder);
                    return null;
                }
                LOGGER.info("Created VDB folder: " + vdbFolder);
            }

            File uploadsDir = new File(uploadsFolder);
            if (!uploadsDir.exists()) {
                if (!uploadsDir.mkdirs()) {
                    System.err.println("[TeiidExcelImporterTest] Failed to create uploads folder: " + uploadsFolder);
                    return null;
                }
                LOGGER.info("Created uploads folder: " + uploadsFolder);
            }

            File templateFile = new File(templatePath);
            if (!templateFile.exists()) {
                System.err.println("[TeiidExcelImporterTest] Template VDB not found at: " + templatePath);
                return null;
            }

            String vdbXml = VDBXmlEditHelper.readFromFile(templatePath);
            if (vdbXml == null) {
                System.err.println("[TeiidExcelImporterTest] Failed to read template VDB");
                return null;
            }
            LOGGER.info("Template VDB loaded from: " + templatePath);

            vdbXml = vdbXml.replaceFirst("<vdb\\s+name=\"[^\"]+\"", "<vdb name=\"" + vdbId + "\"");
            LOGGER.info("VDB name replaced with: " + vdbId);

            vdbXml = vdbXml.replaceAll("'MyVDBTest'", "'" + vdbId + "'");
            vdbXml = vdbXml.replaceAll("'vdb_production'", "'" + vdbId + "'");

            String relativePathPrefix = orgId + "/" + userId + "/uploads/";
            vdbXml = vdbXml.replaceAll("ParentDirectory=/opt/wildfly/teiidfiles/customers[^)]*\\)",
                                       "ParentDirectory=/opt/wildfly/teiidfiles/customers/" + orgId + "/" + userId + "/uploads)");
            LOGGER.info("File paths updated for user: " + relativePathPrefix);

            VDBXmlEditHelper.writeToFile(vdbFilePath, vdbXml);
            LOGGER.info("VDB file written to: " + vdbFilePath);

            String vdbDeploymentName = vdbId + "-vdb.xml";
            new TeiidDeployHelper().deployVDB(vdbFilePath, vdbDeploymentName);
            LOGGER.info("VDB deployed to Teiid: " + vdbDeploymentName);

            return vdbFilePath;

        } catch (Exception e) {
            System.err.println("[TeiidExcelImporterTest] Error auto-provisioning user VDB: " + e.getMessage());
            e.printStackTrace();
            return null;
        }
    }
}
