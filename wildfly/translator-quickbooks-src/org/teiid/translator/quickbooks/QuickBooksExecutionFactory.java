package org.teiid.translator.quickbooks;

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
 * QuickBooks Online Accounting API without materialising data in Postgres.
 */
@Translator(name = "quickbooks", description = "QuickBooks Online Accounting API Translator")
public class QuickBooksExecutionFactory extends ExecutionFactory<Object, QuickBooksConnection> {

    private String instanceUrl = "https://quickbooks.api.intuit.com";
    private String realmId;
    private String username;
    private String password;
    private int pageSize = 1000;

    @TranslatorProperty(display = "Base URL", description = "QuickBooks API base URL, e.g. https://quickbooks.api.intuit.com", required = false)
    public String getInstanceUrl() {
        return instanceUrl;
    }

    public void setInstanceUrl(String instanceUrl) {
        this.instanceUrl = instanceUrl;
    }

    @TranslatorProperty(display = "Realm / Company ID", description = "QuickBooks company (realm) id", required = true)
    public String getRealmId() {
        return realmId;
    }

    public void setRealmId(String realmId) {
        this.realmId = realmId;
    }

    @TranslatorProperty(display = "Username", description = "Unused for OAuth2 bearer token auth", required = false)
    public String getUsername() {
        return username;
    }

    public void setUsername(String username) {
        this.username = username;
    }

    @TranslatorProperty(display = "Access Token", description = "QuickBooks OAuth2 access token", required = true, masked = true)
    public String getPassword() {
        return password;
    }

    public void setPassword(String password) {
        this.password = password;
    }

    @TranslatorProperty(display = "Page Size", description = "Number of records requested per QuickBooks query (max 1000)", advanced = true)
    public int getPageSize() {
        return pageSize;
    }

    public void setPageSize(int pageSize) {
        this.pageSize = pageSize;
    }

    @Override
    public QuickBooksConnection getConnection(Object factory, ExecutionContext context) throws TranslatorException {
        return new QuickBooksConnection(instanceUrl, realmId, password, pageSize);
    }

    @Override
    public void closeConnection(QuickBooksConnection connection, Object factory) {
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
    public void getMetadata(MetadataFactory metadataFactory, QuickBooksConnection connection) throws TranslatorException {
        // Metadata is supplied by explicit DDL generated during source registration.
    }

    @Override
    public ResultSetExecution createResultSetExecution(QueryExpression command, ExecutionContext executionContext, RuntimeMetadata metadata, QuickBooksConnection connection) throws TranslatorException {
        if (!(command instanceof Select)) {
            throw new TranslatorException("Only SELECT statements are supported by the QuickBooks translator");
        }
        if (connection == null) {
            connection = getConnection(null, executionContext);
        }
        return new QuickBooksExecution((Select) command, connection, executionContext, metadata);
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
