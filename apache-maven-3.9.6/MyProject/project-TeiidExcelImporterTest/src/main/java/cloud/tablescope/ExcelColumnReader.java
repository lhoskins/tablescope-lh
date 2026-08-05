package cloud.tablescope;

import java.io.IOException;
import java.io.InputStream;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import javax.servlet.http.Part;
import org.apache.poi.hssf.usermodel.HSSFWorkbook;
import org.apache.poi.ss.usermodel.Cell;
import org.apache.poi.ss.usermodel.Row;
import org.apache.poi.ss.usermodel.Sheet;
import org.apache.poi.ss.usermodel.Workbook;
import org.apache.poi.xssf.usermodel.XSSFWorkbook;

/**
 * Reads and normalizes column names from Excel (.xls/.xlsx) uploads.
 */
public class ExcelColumnReader {

    public static List<String> getColumnNamesFromStream(InputStream inputStream, String fileName) throws IOException {
        List<String> columnNames = new ArrayList<>();
        Set<String> usedNames = new HashSet<>();
        Workbook workbook = null;
        try {
            System.out.println("[TeiidExcelImporterTest] getColumnNamesFromStream: Opening workbook for " + fileName);
            workbook = getWorkbook(inputStream, fileName);
            Sheet sheet = workbook.getSheetAt(0);
            System.out.println("[TeiidExcelImporterTest] getColumnNamesFromStream: Sheet name = " + sheet.getSheetName());

            Row headerRow = sheet.getRow(0);
            if (headerRow == null) {
                System.err.println("[TeiidExcelImporterTest] getColumnNamesFromStream: Header row is null!");
                return null;
            }
            int numColumns = headerRow.getLastCellNum();
            System.out.println("[TeiidExcelImporterTest] getColumnNamesFromStream: Found " + numColumns + " columns in header row (including empty trailing cells)");

            for (int i = 0; i < numColumns; i++) {
                Cell headerCell = headerRow.getCell(i);
                if (headerCell == null) {
                    System.out.println("[TeiidExcelImporterTest] getColumnNamesFromStream: Header cell " + i + " is null, stopping column scan");
                    break;
                }
                String cellValue = "";
                try {
                    cellValue = headerCell.getStringCellValue();
                } catch (Exception e) {
                    System.out.println("[TeiidExcelImporterTest] getColumnNamesFromStream: Cell " + i + " is not a string, trying numeric...");
                    try {
                        cellValue = String.valueOf((int) headerCell.getNumericCellValue());
                    } catch (Exception e2) {
                        System.err.println("[TeiidExcelImporterTest] getColumnNamesFromStream: Could not read cell " + i + " value: " + e2.getMessage());
                        break;
                    }
                }
                String columnName = cellValue.trim().replaceAll("\\s+", "_").replaceAll("[./:()]", "");
                if (columnName.isEmpty()) {
                    System.out.println("[TeiidExcelImporterTest] getColumnNamesFromStream: Column " + i + " has empty name, stopping column scan");
                    break;
                }
                if (Character.isDigit(columnName.charAt(0))) {
                    String originalName = columnName;
                    columnName = "Col_" + columnName;
                    System.out.println("[TeiidExcelImporterTest] getColumnNamesFromStream: Column " + i + " starts with digit, renamed '" + originalName + "' to '" + columnName + "'");
                }
                if (columnName.equalsIgnoreCase("Date")) {
                    columnName += "_";
                }
                String baseColumnName = columnName;
                int suffix = 1;
                while (usedNames.contains(columnName.toUpperCase())) {
                    columnName = baseColumnName + "_" + suffix;
                    suffix++;
                    System.out.println("[TeiidExcelImporterTest] getColumnNamesFromStream: Duplicate column name, renamed to '" + columnName + "'");
                }
                usedNames.add(columnName.toUpperCase());
                System.out.println("[TeiidExcelImporterTest] getColumnNamesFromStream: Column " + i + " = '" + columnName + "'");
                columnNames.add(columnName);
            }

            if (columnNames.isEmpty()) {
                System.err.println("[TeiidExcelImporterTest] getColumnNamesFromStream: No valid column names found!");
                return null;
            }

            System.out.println("[TeiidExcelImporterTest] getColumnNamesFromStream: Successfully extracted " + columnNames.size() + " column names");
        } catch (IOException e) {
            System.err.println("[TeiidExcelImporterTest] getColumnNamesFromStream: IOException - " + e.getMessage());
            throw new IOException("Failed to process column names: " + e.getMessage(), e);
        } finally {
            if (workbook != null) {
                workbook.close();
            }
        }
        return columnNames;
    }

    public static List<String> getColumnNames(Part filePart) throws IOException {
        List<String> columnNames = new ArrayList<>();
        Set<String> usedNames = new HashSet<>();
        Workbook workbook = null;
        try {
            String fileName = filePart.getSubmittedFileName();
            System.out.println("[TeiidExcelImporterTest] getColumnNames: Opening workbook for " + fileName);
            workbook = getWorkbook(filePart.getInputStream(), fileName);
            Sheet sheet = workbook.getSheetAt(0);
            System.out.println("[TeiidExcelImporterTest] getColumnNames: Sheet name = " + sheet.getSheetName());

            Row headerRow = sheet.getRow(0);
            if (headerRow == null) {
                System.err.println("[TeiidExcelImporterTest] getColumnNames: Header row is null!");
                return null;
            }
            int numColumns = headerRow.getLastCellNum();
            System.out.println("[TeiidExcelImporterTest] getColumnNames: Found " + numColumns + " columns in header row");

            for (int i = 0; i < numColumns; i++) {
                Cell headerCell = headerRow.getCell(i);
                if (headerCell == null) {
                    System.out.println("[TeiidExcelImporterTest] getColumnNames: Header cell " + i + " is null, stopping column scan");
                    break;
                }
                String cellValue = "";
                try {
                    cellValue = headerCell.getStringCellValue();
                } catch (Exception e) {
                    System.out.println("[TeiidExcelImporterTest] getColumnNames: Cell " + i + " is not a string, trying numeric...");
                    try {
                        cellValue = String.valueOf((int) headerCell.getNumericCellValue());
                    } catch (Exception e2) {
                        System.err.println("[TeiidExcelImporterTest] getColumnNames: Could not read cell " + i + " value: " + e2.getMessage());
                        break;
                    }
                }
                String columnName = cellValue.trim().replaceAll("\\s+", "_").replaceAll("[./:()]", "");
                if (columnName.isEmpty()) {
                    System.out.println("[TeiidExcelImporterTest] getColumnNames: Column " + i + " has empty name, stopping column scan");
                    break;
                }
                if (Character.isDigit(columnName.charAt(0))) {
                    String originalName = columnName;
                    columnName = "Col_" + columnName;
                    System.out.println("[TeiidExcelImporterTest] getColumnNames: Column " + i + " starts with digit, renamed '" + originalName + "' to '" + columnName + "'");
                }
                if (columnName.equalsIgnoreCase("Date")) {
                    columnName += "_";
                }
                String baseColumnName = columnName;
                int suffix = 1;
                while (usedNames.contains(columnName.toUpperCase())) {
                    columnName = baseColumnName + "_" + suffix;
                    suffix++;
                    System.out.println("[TeiidExcelImporterTest] getColumnNames: Duplicate column name, renamed to '" + columnName + "'");
                }
                usedNames.add(columnName.toUpperCase());
                System.out.println("[TeiidExcelImporterTest] getColumnNames: Column " + i + " = '" + columnName + "'");
                columnNames.add(columnName);
            }

            if (columnNames.isEmpty()) {
                System.err.println("[TeiidExcelImporterTest] getColumnNames: No valid column names found!");
                return null;
            }

            System.out.println("[TeiidExcelImporterTest] getColumnNames: Successfully extracted " + columnNames.size() + " column names");
        } catch (IOException e) {
            System.err.println("[TeiidExcelImporterTest] getColumnNames: IOException - " + e.getMessage());
            throw new IOException("Failed to process column names: " + e.getMessage(), e);
        } finally {
            if (workbook != null) {
                workbook.close();
            }
        }
        return columnNames;
    }

    public static Workbook getWorkbook(InputStream inputStream, String fileName) throws IOException {
        if (fileName.toLowerCase().endsWith(".xls")) {
            return new HSSFWorkbook(inputStream);
        } else if (fileName.toLowerCase().endsWith(".xlsx")) {
            return new XSSFWorkbook(inputStream);
        } else {
            throw new IllegalArgumentException("Invalid file format. Only XLS and XLSX files are supported.");
        }
    }
}
