package org.teiid.translator.databricks;

import org.teiid.translator.Translator;
import org.teiid.translator.hive.HiveExecutionFactory;

@Translator(name = "databricks", description = "Databricks Hive-compatible translator")
public class DatabricksExecutionFactory extends HiveExecutionFactory {
    public DatabricksExecutionFactory() {
    }
}
