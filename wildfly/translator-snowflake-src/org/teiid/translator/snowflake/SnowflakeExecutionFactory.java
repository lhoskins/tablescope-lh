package org.teiid.translator.snowflake;

import org.teiid.translator.Translator;
import org.teiid.translator.jdbc.JDBCExecutionFactory;

@Translator(name = "snowflake", description = "Snowflake JDBC translator")
public class SnowflakeExecutionFactory extends JDBCExecutionFactory {
    public SnowflakeExecutionFactory() {
    }
}
