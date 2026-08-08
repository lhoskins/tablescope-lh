package org.teiid.translator.servicenow;

import org.teiid.language.QueryExpression;
import org.teiid.language.Select;
import org.teiid.metadata.MetadataFactory;
import org.teiid.metadata.RuntimeMetadata;
import org.teiid.translator.ExecutionContext;
import org.teiid.translator.ExecutionFactory;
import org.teiid.translator.ResultSetExecution;
import org.teiid.translator.Translator;
import org.teiid.translator.TranslatorException;
import org.teiid.translator.TranslatorProperty;

/**
 * Teiid translator that executes SQL queries directly against the
 * ServiceNow Table API without materialising data in Postgres.
 */
@Translator(name = "servicenow", description = "ServiceNow Table API Translator")
public class ServiceNowExecutionFactory extends ExecutionFactory<Object, ServiceNowConnection> {

    private String instanceUrl;
    private String username;
    private String password;
    private int pageSize = 200;

    @TranslatorProperty(display = "Instance URL", description = "ServiceNow instance URL, e.g. https://mycompany.service-now.com", required = true)
    public String getInstanceUrl() {
        return instanceUrl;
    }

    public void setInstanceUrl(String instanceUrl) {
        this.instanceUrl = instanceUrl;
    }

    @TranslatorProperty(display = "Username", description = "ServiceNow API user", required = true)
    public String getUsername() {
        return username;
    }

    public void setUsername(String username) {
        this.username = username;
    }

    @TranslatorProperty(display = "Password", description = "ServiceNow API password", required = true, masked = true)
    public String getPassword() {
        return password;
    }

    public void setPassword(String password) {
        this.password = password;
    }

    @TranslatorProperty(display = "Page Size", description = "Number of records requested per ServiceNow API call", advanced = true)
    public int getPageSize() {
        return pageSize;
    }

    public void setPageSize(int pageSize) {
        this.pageSize = pageSize;
    }

    @Override
    public ServiceNowConnection getConnection(Object factory, ExecutionContext context) throws TranslatorException {
        return new ServiceNowConnection(instanceUrl, username, password, pageSize);
    }

    @Override
    public void closeConnection(ServiceNowConnection connection, Object factory) {
        // stateless HTTP client; nothing to close
    }

    @Override
    public boolean isSourceRequired() {
        return false;
    }

    @Override
    public boolean isSourceRequiredForMetadata() {
        return false;
    }

    @Override
    public void getMetadata(MetadataFactory metadataFactory, ServiceNowConnection connection) throws TranslatorException {
        // Metadata is supplied by explicit DDL generated during source registration.
    }

    @Override
    public ResultSetExecution createResultSetExecution(QueryExpression command, ExecutionContext executionContext, RuntimeMetadata metadata, ServiceNowConnection connection) throws TranslatorException {
        if (!(command instanceof Select)) {
            throw new TranslatorException("Only SELECT statements are supported by the ServiceNow translator");
        }
        // When no JCA source is required, Teiid passes a null connection; build one
        // from the translator properties configured in the VDB.
        if (connection == null) {
            connection = getConnection(null, executionContext);
        }
        return new ServiceNowExecution((Select) command, connection, executionContext, metadata);
    }

    // Capabilities: keep the surface narrow so Teiid compensates in memory.
    @Override
    public boolean supportsSelectDistinct() { return false; }

    @Override
    public boolean supportsGroupBy() { return false; }

    @Override
    public boolean supportsHaving() { return false; }

    @Override
    public boolean supportsAggregatesSum() { return false; }

    @Override
    public boolean supportsAggregatesAvg() { return false; }

    @Override
    public boolean supportsAggregatesMin() { return false; }

    @Override
    public boolean supportsAggregatesMax() { return false; }

    @Override
    public boolean supportsAggregatesCount() { return false; }

    @Override
    public boolean supportsAggregatesCountStar() { return false; }

    @Override
    public boolean supportsAggregatesDistinct() { return false; }

    @Override
    public boolean supportsOrderBy() { return false; }

    @Override
    public boolean supportsOrderByUnrelated() { return false; }

    @Override
    public boolean supportsInnerJoins() { return false; }

    @Override
    public boolean supportsOuterJoins() { return false; }

    @Override
    public boolean supportsFullOuterJoins() { return false; }

    @Override
    public boolean supportsSelfJoins() { return false; }

    @Override
    public boolean supportsRowLimit() { return true; }

    @Override
    public boolean supportsRowOffset() { return true; }

    @Override
    public boolean supportsInCriteria() { return true; }

    @Override
    public boolean supportsCompareCriteriaEquals() { return true; }

    @Override
    public boolean supportsCompareCriteriaOrdered() { return true; }

    @Override
    public boolean supportsLikeCriteria() { return true; }

    @Override
    public boolean supportsIsNullCriteria() { return true; }

    @Override
    public boolean supportsOrCriteria() { return true; }

    @Override
    public boolean supportsNotCriteria() { return true; }
}
