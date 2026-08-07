package org.teiid.translator.hubspot;

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
 * HubSpot CRM v3 Objects API without materialising data in Postgres.
 */
@Translator(name = "hubspot", description = "HubSpot CRM v3 API Translator")
public class HubSpotExecutionFactory extends ExecutionFactory<Object, HubSpotConnection> {

    private String instanceUrl = "https://api.hubapi.com";
    private String username;
    private String password;
    private int pageSize = 100;

    @TranslatorProperty(display = "Instance URL", description = "HubSpot API base URL, e.g. https://api.hubapi.com", required = false)
    public String getInstanceUrl() {
        return instanceUrl;
    }

    public void setInstanceUrl(String instanceUrl) {
        this.instanceUrl = instanceUrl;
    }

    @TranslatorProperty(display = "Username", description = "Unused for Private App token auth", required = false)
    public String getUsername() {
        return username;
    }

    public void setUsername(String username) {
        this.username = username;
    }

    @TranslatorProperty(display = "Access Token", description = "HubSpot Private App access token", required = true, masked = true)
    public String getPassword() {
        return password;
    }

    public void setPassword(String password) {
        this.password = password;
    }

    @TranslatorProperty(display = "Page Size", description = "Number of records requested per HubSpot API call (max 100)", advanced = true)
    public int getPageSize() {
        return pageSize;
    }

    public void setPageSize(int pageSize) {
        this.pageSize = pageSize;
    }

    @Override
    public HubSpotConnection getConnection(Object factory, ExecutionContext context) throws TranslatorException {
        return new HubSpotConnection(instanceUrl, password, pageSize);
    }

    @Override
    public void closeConnection(HubSpotConnection connection, Object factory) {
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
    public void getMetadata(MetadataFactory metadataFactory, HubSpotConnection connection) throws TranslatorException {
        // Metadata is supplied by explicit DDL generated during source registration.
    }

    @Override
    public ResultSetExecution createResultSetExecution(QueryExpression command, ExecutionContext executionContext, RuntimeMetadata metadata, HubSpotConnection connection) throws TranslatorException {
        if (!(command instanceof Select)) {
            throw new TranslatorException("Only SELECT statements are supported by the HubSpot translator");
        }
        if (connection == null) {
            connection = getConnection(null, executionContext);
        }
        return new HubSpotExecution((Select) command, connection, executionContext, metadata);
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
    public boolean supportsRowOffset() { return false; }

    @Override
    public boolean supportsInCriteria() { return false; }

    @Override
    public boolean supportsCompareCriteriaEquals() { return false; }

    @Override
    public boolean supportsCompareCriteriaOrdered() { return false; }

    @Override
    public boolean supportsLikeCriteria() { return false; }

    @Override
    public boolean supportsIsNullCriteria() { return false; }

    @Override
    public boolean supportsOrCriteria() { return false; }

    @Override
    public boolean supportsNotCriteria() { return false; }
}
