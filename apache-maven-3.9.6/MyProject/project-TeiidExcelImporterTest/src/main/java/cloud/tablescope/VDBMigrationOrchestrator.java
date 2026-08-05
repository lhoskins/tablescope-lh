package cloud.tablescope;

import java.util.logging.Logger;
import org.json.JSONArray;
import org.json.JSONObject;

/**
 * Orchestrates migration of DDL between user and shared VDBs.
 */
public class VDBMigrationOrchestrator {

    private static final Logger LOGGER = Logger.getLogger(VDBMigrationOrchestrator.class.getName());

    public static class MigrationResult {
        public int tablesMigrated = 0;
        public int viewsMigrated = 0;
    }

    public static MigrationResult migrateToSharedVDB(String userVdbPath, String sharedVdbPath, JSONArray datasources)
            throws Exception {
        LOGGER.info("[VDB_MIGRATION] Starting migration to shared VDB");

        String userVdbContent = VDBXmlTextEditor.readVdbAsText(userVdbPath);
        String sharedVdbContent = VDBXmlTextEditor.readVdbAsText(sharedVdbPath);

        MigrationResult result = new MigrationResult();

        for (int i = 0; i < datasources.length(); i++) {
            JSONObject ds = datasources.getJSONObject(i);
            String foreignTableName = ds.getString("foreign_table_name");
            String privateFilePath = ds.getString("private_file_path");
            String sharedFilePath = ds.getString("shared_file_path");
            String fileType = ds.optString("file_type", VDBDDLExtractor.detectFileType(privateFilePath));

            LOGGER.info("[VDB_MIGRATION] Migrating: " + foreignTableName + " (type: " + fileType + ")");
            LOGGER.info("[VDB_MIGRATION] Path: " + privateFilePath + " -> " + sharedFilePath);

            VDBDDLExtractor.DDLResult ddlResult = VDBDDLExtractor.extractDDLFromText(userVdbContent, foreignTableName, fileType);

            if (ddlResult != null && ddlResult.ddl != null && !ddlResult.ddl.trim().isEmpty()) {
                LOGGER.info("[VDB_MIGRATION] Found " + ddlResult.type + " DDL, length: " + ddlResult.ddl.length());

                String updatedDDL = VDBXmlTextEditor.updateFilePaths(ddlResult.ddl, privateFilePath, sharedFilePath, ddlResult.type);

                sharedVdbContent = VDBXmlTextEditor.addDDLToVDBText(sharedVdbContent, updatedDDL, ddlResult.type);

                userVdbContent = VDBXmlTextEditor.removeDDLFromVDBText(userVdbContent, foreignTableName, ddlResult.type);

                if (VDBDDLExtractor.DDL_TYPE_FOREIGN_TABLE.equals(ddlResult.type)) {
                    result.tablesMigrated++;

                    String xlsxViewName = foreignTableName + "_XLSX";
                    String xlsxViewDDL = VDBDDLExtractor.extractViewDDLFromText(userVdbContent, xlsxViewName);
                    if (xlsxViewDDL != null && !xlsxViewDDL.trim().isEmpty()) {
                        LOGGER.info("[VDB_MIGRATION] Also migrating corresponding VIEW: " + xlsxViewName);
                        xlsxViewDDL = xlsxViewDDL.replace("FROM ExcelSourceModel." + foreignTableName, "FROM " + foreignTableName);
                        LOGGER.info("[VDB_MIGRATION] Updated VIEW to reference table directly: " + foreignTableName);
                        sharedVdbContent = VDBXmlTextEditor.addDDLToVDBText(sharedVdbContent, xlsxViewDDL, VDBDDLExtractor.DDL_TYPE_VIEW);
                        userVdbContent = VDBXmlTextEditor.removeDDLFromVDBText(userVdbContent, xlsxViewName, VDBDDLExtractor.DDL_TYPE_VIEW);
                        result.viewsMigrated++;
                    }
                } else {
                    result.viewsMigrated++;
                }
            } else {
                LOGGER.warning("[VDB_MIGRATION] WARNING: DDL not found for: " + foreignTableName);
            }
        }

        VDBXmlTextEditor.writeVdbAsText(userVdbPath, userVdbContent);
        VDBXmlTextEditor.writeVdbAsText(sharedVdbPath, sharedVdbContent);

        return result;
    }

    public static MigrationResult migrateToPrivateVDB(String userVdbPath, String sharedVdbPath, JSONArray datasources)
            throws Exception {
        LOGGER.info("[VDB_MIGRATION] Starting migration to private VDB");

        String userVdbContent = VDBXmlTextEditor.readVdbAsText(userVdbPath);
        String sharedVdbContent = VDBXmlTextEditor.readVdbAsText(sharedVdbPath);

        MigrationResult result = new MigrationResult();

        for (int i = 0; i < datasources.length(); i++) {
            JSONObject ds = datasources.getJSONObject(i);
            String foreignTableName = ds.getString("foreign_table_name");
            String privateFilePath = ds.getString("private_file_path");
            String sharedFilePath = ds.getString("shared_file_path");
            String fileType = ds.optString("file_type", VDBDDLExtractor.detectFileType(sharedFilePath));

            VDBDDLExtractor.DDLResult ddlResult = VDBDDLExtractor.extractDDLFromText(sharedVdbContent, foreignTableName, fileType);

            if (ddlResult != null && ddlResult.ddl != null && !ddlResult.ddl.trim().isEmpty()) {
                String updatedDDL = VDBXmlTextEditor.updateFilePaths(ddlResult.ddl, sharedFilePath, privateFilePath, ddlResult.type);

                userVdbContent = VDBXmlTextEditor.addDDLToVDBText(userVdbContent, updatedDDL, ddlResult.type);

                sharedVdbContent = VDBXmlTextEditor.removeDDLFromVDBText(sharedVdbContent, foreignTableName, ddlResult.type);

                if (VDBDDLExtractor.DDL_TYPE_FOREIGN_TABLE.equals(ddlResult.type)) {
                    result.tablesMigrated++;

                    String xlsxViewName = foreignTableName + "_XLSX";
                    String xlsxViewDDL = VDBDDLExtractor.extractViewDDLFromText(sharedVdbContent, xlsxViewName);
                    if (xlsxViewDDL != null && !xlsxViewDDL.trim().isEmpty()) {
                        LOGGER.info("[VDB_MIGRATION] Also migrating corresponding VIEW: " + xlsxViewName);
                        xlsxViewDDL = xlsxViewDDL.replace("FROM " + foreignTableName, "FROM ExcelSourceModel." + foreignTableName);
                        LOGGER.info("[VDB_MIGRATION] Updated VIEW to reference through ExcelSourceModel: " + foreignTableName);
                        userVdbContent = VDBXmlTextEditor.addDDLToVDBText(userVdbContent, xlsxViewDDL, VDBDDLExtractor.DDL_TYPE_VIEW);
                        sharedVdbContent = VDBXmlTextEditor.removeDDLFromVDBText(sharedVdbContent, xlsxViewName, VDBDDLExtractor.DDL_TYPE_VIEW);
                        result.viewsMigrated++;
                    }
                } else {
                    result.viewsMigrated++;
                }
            }
        }

        VDBXmlTextEditor.writeVdbAsText(userVdbPath, userVdbContent);
        VDBXmlTextEditor.writeVdbAsText(sharedVdbPath, sharedVdbContent);

        return result;
    }
}
