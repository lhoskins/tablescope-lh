package cloud.tablescope;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.logging.Level;
import java.util.logging.Logger;

/**
 * Text-based VDB XML editor used by VDB migration operations.
 *
 * Preserves CDATA sections, comments, and original formatting.
 */
public class VDBXmlTextEditor {

    private static final Logger LOGGER = Logger.getLogger(VDBXmlTextEditor.class.getName());

    public static String readVdbAsText(String vdbPath) throws Exception {
        return new String(Files.readAllBytes(Paths.get(vdbPath)), StandardCharsets.UTF_8);
    }

    public static void writeVdbAsText(String vdbPath, String content) throws Exception {
        String backupPath = vdbPath + ".backup_migration_" + System.currentTimeMillis();
        Files.copy(Paths.get(vdbPath), Paths.get(backupPath), StandardCopyOption.REPLACE_EXISTING);
        LOGGER.info("[VDB_MIGRATION] Created backup: " + backupPath);

        content = ensureCDATASections(content);

        Files.write(Paths.get(vdbPath), content.getBytes(StandardCharsets.UTF_8));
        LOGGER.info("[VDB_MIGRATION] Wrote VDB file: " + vdbPath);
    }

    public static String updateFilePaths(String ddl, String oldPath, String newPath, String ddlType) {
        String updatedDDL = ddl;

        if (VDBDDLExtractor.DDL_TYPE_VIEW.equals(ddlType)) {
            updatedDDL = updatedDDL.replace("getTextFiles('" + oldPath + "')", "getTextFiles('" + newPath + "')");
            String oldRel = extractRelativePath(oldPath);
            String newRel = extractRelativePath(newPath);
            if (oldRel != null && newRel != null && !oldRel.equals(newRel)) {
                updatedDDL = updatedDDL.replace("getTextFiles('" + oldRel + "')", "getTextFiles('" + newRel + "')");
            }
        } else {
            updatedDDL = updatedDDL.replace(oldPath, newPath);
            String oldRel = extractRelativePath(oldPath);
            String newRel = extractRelativePath(newPath);
            if (oldRel != null && newRel != null && !oldRel.equals(newRel)) {
                updatedDDL = updatedDDL.replace(oldRel, newRel);
            }
        }

        String oldFileName = new File(oldPath).getName();
        String newFileName = new File(newPath).getName();
        if (!oldFileName.equals(newFileName)) {
            updatedDDL = updatedDDL.replace(oldFileName, newFileName);
        }
        return updatedDDL;
    }

    public static String extractRelativePath(String fullPath) {
        if (fullPath == null) return null;
        int idx = fullPath.indexOf("customers/");
        if (idx != -1) return fullPath.substring(idx + "customers/".length());
        return fullPath;
    }

    public static String addDDLToVDBText(String vdbContent, String ddl, String ddlType) {
        String targetModel;
        String insertionComment;
        boolean insertBefore;

        if (VDBDDLExtractor.DDL_TYPE_VIEW.equals(ddlType)) {
            targetModel = "MyCompany";
            insertionComment = "-- Place new View above";
            insertBefore = true;
        } else {
            targetModel = "ExcelSourceModel";
            insertionComment = "-- Place Foreign Table Below";
            insertBefore = false;
        }

        String modelPattern = "<model[^>]*name=\"" + targetModel + "\"[^>]*>[\\s\\S]*?<metadata[^>]*type=\"DDL\"[^>]*>\\s*<!\\[CDATA\\[([\\s\\S]*?)\\]\\]>\\s*</metadata>";

        Pattern cdataPattern = Pattern.compile(modelPattern, Pattern.DOTALL);
        Matcher matcher = cdataPattern.matcher(vdbContent);

        if (matcher.find()) {
            String existingDDL = matcher.group(1);
            int metadataStart = vdbContent.indexOf("<metadata", matcher.start());
            int cdataStart = vdbContent.indexOf("<![CDATA[", metadataStart);
            int cdataEnd = vdbContent.indexOf("]]>", cdataStart);

            String newDDL;
            int commentIdx = existingDDL.indexOf(insertionComment);
            if (commentIdx != -1) {
                if (insertBefore) {
                    String ddlBefore = existingDDL.substring(0, commentIdx);
                    String ddlAfter = existingDDL.substring(commentIdx);
                    newDDL = ddlBefore + ddl + "\n\n" + ddlAfter;
                } else {
                    int lineEnd = existingDDL.indexOf('\n', commentIdx);
                    if (lineEnd == -1) lineEnd = existingDDL.length();
                    String ddlBefore = existingDDL.substring(0, lineEnd + 1);
                    String ddlAfter = existingDDL.substring(lineEnd + 1);
                    newDDL = ddlBefore + "\n" + ddl + ddlAfter;
                }
            } else {
                newDDL = existingDDL + "\n\n" + ddl;
            }

            LOGGER.info("[VDB_MIGRATION] Added " + ddlType + " to " + targetModel + " model " + (insertBefore ? "above" : "below") + " comment");

            String before = vdbContent.substring(0, cdataStart + "<![CDATA[".length());
            String after = vdbContent.substring(cdataEnd);
            return before + newDDL + after;
        }

        String noCdataModelPattern = "<model[^>]*name=\"" + targetModel + "\"[^>]*>[\\s\\S]*?<metadata[^>]*type=\"DDL\"[^>]*>([\\s\\S]*?)</metadata>";

        Pattern noCdataPattern = Pattern.compile(noCdataModelPattern, Pattern.DOTALL);
        Matcher noCdataMatcher = noCdataPattern.matcher(vdbContent);

        if (noCdataMatcher.find()) {
            String existingDDL = noCdataMatcher.group(1);

            if (existingDDL.trim().startsWith("<![CDATA[")) {
                LOGGER.warning("[VDB_MIGRATION] WARNING: Unexpected CDATA in fallback pattern, skipping");
                return vdbContent;
            }

            int metadataStart = vdbContent.indexOf("<metadata", noCdataMatcher.start());
            int metadataTagEnd = vdbContent.indexOf(">", metadataStart) + 1;
            int metadataEnd = vdbContent.indexOf("</metadata>", metadataStart);

            String newDDL;
            int commentIdx = existingDDL.indexOf(insertionComment);
            if (commentIdx != -1) {
                if (insertBefore) {
                    String ddlBefore = existingDDL.substring(0, commentIdx);
                    String ddlAfter = existingDDL.substring(commentIdx);
                    newDDL = ddlBefore + ddl + "\n\n" + ddlAfter;
                } else {
                    int lineEnd = existingDDL.indexOf('\n', commentIdx);
                    if (lineEnd == -1) lineEnd = existingDDL.length();
                    String ddlBefore = existingDDL.substring(0, lineEnd + 1);
                    String ddlAfter = existingDDL.substring(lineEnd + 1);
                    newDDL = ddlBefore + "\n" + ddl + ddlAfter;
                }
            } else {
                newDDL = existingDDL + "\n\n" + ddl;
            }

            LOGGER.info("[VDB_MIGRATION] Added " + ddlType + " to " + targetModel + " model and wrapped in CDATA");
            String before = vdbContent.substring(0, metadataTagEnd);
            String after = vdbContent.substring(metadataEnd);
            return before + "\n      <![CDATA[\n" + newDDL.trim() + "\n]]>\n    " + after;
        }

        LOGGER.warning("[VDB_MIGRATION] WARNING: Could not find metadata element to add " + ddlType + " to " + targetModel);
        return vdbContent;
    }

    public static String removeDDLFromVDBText(String vdbContent, String tableName, String ddlType) {
        String keyword = VDBDDLExtractor.DDL_TYPE_VIEW.equals(ddlType) ? "CREATE VIEW" : "CREATE FOREIGN TABLE";
        String searchPattern = keyword + " " + tableName;

        Pattern cdataPattern = Pattern.compile(
            "(<metadata[^>]*type=\"DDL\"[^>]*>\\s*<!\\[CDATA\\[)(.*?)(\\]\\]>\\s*</metadata>)",
            Pattern.DOTALL
        );
        Matcher matcher = cdataPattern.matcher(vdbContent);

        while (matcher.find()) {
            String existingDDL = matcher.group(2);
            if (existingDDL.contains(searchPattern)) {
                String before = matcher.group(1);
                String after = matcher.group(3);

                String block = VDBDDLExtractor.extractDDLBlock(existingDDL, tableName, keyword);
                if (block != null) {
                    String updatedDDL = existingDDL.replace(block, "");
                    updatedDDL = updatedDDL.replaceAll("\n{3,}", "\n\n");

                    LOGGER.info("[VDB_MIGRATION] Removed DDL from CDATA section");
                    return vdbContent.substring(0, matcher.start()) +
                           before + updatedDDL + after +
                           vdbContent.substring(matcher.end());
                }
            }
        }

        Pattern noCdataPattern = Pattern.compile(
            "(<metadata[^>]*type=\"DDL\"[^>]*>)([\\s\\S]*?)(</metadata>)",
            Pattern.DOTALL
        );
        Matcher noCdataMatcher = noCdataPattern.matcher(vdbContent);

        while (noCdataMatcher.find()) {
            String existingDDL = noCdataMatcher.group(2);
            if (existingDDL.trim().startsWith("<![CDATA[")) continue;

            if (existingDDL.contains(searchPattern)) {
                String before = noCdataMatcher.group(1);
                String after = noCdataMatcher.group(3);

                String block = VDBDDLExtractor.extractDDLBlock(existingDDL, tableName, keyword);
                if (block != null) {
                    String updatedDDL = existingDDL.replace(block, "");
                    updatedDDL = updatedDDL.replaceAll("\n{3,}", "\n\n");

                    LOGGER.info("[VDB_MIGRATION] Removed DDL and wrapped remaining in CDATA");
                    return vdbContent.substring(0, noCdataMatcher.start()) +
                           before + "\n      <![CDATA[\n" + updatedDDL.trim() + "\n]]>\n    " + after +
                           vdbContent.substring(noCdataMatcher.end());
                }
            }
        }

        LOGGER.warning("[VDB_MIGRATION] WARNING: Could not find DDL to remove for: " + tableName);
        return vdbContent;
    }

    public static String ensureCDATASections(String vdbContent) {
        Pattern noCdataPattern = Pattern.compile(
            "(<metadata[^>]*type=\"DDL\"[^>]*>)([\\s\\S]*?)(</metadata>)",
            Pattern.DOTALL
        );

        StringBuffer result = new StringBuffer();
        Matcher matcher = noCdataPattern.matcher(vdbContent);

        while (matcher.find()) {
            String before = matcher.group(1);
            String content = matcher.group(2);
            String after = matcher.group(3);

            String trimmedContent = content.trim();
            if (trimmedContent.startsWith("<![CDATA[") && trimmedContent.endsWith("]]>")) {
                matcher.appendReplacement(result, Matcher.quoteReplacement(matcher.group(0)));
            } else {
                String wrapped = before + "\n      <![CDATA[\n" + trimmedContent + "\n]]>\n    " + after;
                matcher.appendReplacement(result, Matcher.quoteReplacement(wrapped));
                LOGGER.info("[VDB_MIGRATION] Wrapped metadata content in CDATA");
            }
        }
        matcher.appendTail(result);

        return result.toString();
    }
}
