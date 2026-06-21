package cloud.tablescope;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import java.io.File;
import java.io.FileWriter;
import java.io.IOException;
import java.nio.file.Files;
import java.util.Arrays;
import java.util.List;

import org.junit.Test;

/**
 * Regression tests for reserved-word column handling. Reserved words must be
 * preserved as logical column names and handled via quoting in the generated
 * DDL/SQL, never renamed (e.g. no "Date" -> "Date_").
 */
public class TxtFileProcessorTest {

    private static final List<String> RESERVED_FIELDS =
            Arrays.asList("Date", "Order", "Group", "Select");

    private File writeCsv(String header) throws IOException {
        File f = File.createTempFile("reserved", ".csv");
        try (FileWriter w = new FileWriter(f)) {
            w.write(header + "\n");
            w.write("a,b,c,d\n");
        }
        return f;
    }

    @Test
    public void reservedFieldNamesArePreservedNotRenamed() throws IOException {
        File csv = writeCsv("Date,Order,Group,Select");
        try {
            TxtFileProcessor p = new TxtFileProcessor();
            List<String> columns = p.getColumnNames(csv.getAbsolutePath());
            // Logical names are unchanged: no Date_ / Order_ etc.
            assertEquals(RESERVED_FIELDS, columns);
        } finally {
            Files.deleteIfExists(csv.toPath());
        }
    }

    @Test
    public void generatedDdlQuotesReservedFields() throws IOException {
        File csv = writeCsv("Date,Order,Group,Select");
        try {
            TxtFileProcessor p = new TxtFileProcessor();
            List<String> columns = p.getColumnNames(csv.getAbsolutePath());
            String ddl = p.generateView("reserved.csv", columns);

            // No manual renaming leaked into the DDL.
            assertFalse("DDL must not rename Date to Date_", ddl.contains("Date_"));

            for (String field : RESERVED_FIELDS) {
                // CREATE VIEW column-definition list quotes the reserved word.
                assertTrue(
                        "view column should be quoted: " + field,
                        ddl.contains("\"" + field + "\" string(4000)"));
                // NAMEINSOURCE preserves the original column name.
                assertTrue(
                        "NAMEINSOURCE should preserve: " + field,
                        ddl.contains("NAMEINSOURCE '" + field + "'"));
                // TEXTTABLE clause quotes the reserved word too.
                assertTrue(
                        "TEXTTABLE should quote: " + field,
                        ddl.contains("\"" + field + "\" string"));
            }
        } finally {
            Files.deleteIfExists(csv.toPath());
        }
    }
}
