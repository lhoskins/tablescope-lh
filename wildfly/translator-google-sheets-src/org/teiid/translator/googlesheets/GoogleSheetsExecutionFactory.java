package org.teiid.translator.googlesheets;

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

@Translator(name = "google-sheets", description = "Google Sheets v4 translator")
public class GoogleSheetsExecutionFactory extends ExecutionFactory<Object, GoogleSheetsConnection> {

    private String refreshToken;
    private String clientId;
    private String clientSecret;
    private String spreadsheetId;

    public GoogleSheetsExecutionFactory() {
    }

    @TranslatorProperty(display = "Refresh Token", description = "Google OAuth2 refresh token", required = true, masked = true)
    public String getRefreshToken() { return refreshToken; }
    public void setRefreshToken(String refreshToken) { this.refreshToken = refreshToken; }

    @TranslatorProperty(display = "Client ID", description = "Google OAuth2 client ID", required = true)
    public String getClientId() { return clientId; }
    public void setClientId(String clientId) { this.clientId = clientId; }

    @TranslatorProperty(display = "Client Secret", description = "Google OAuth2 client secret", required = true, masked = true)
    public String getClientSecret() { return clientSecret; }
    public void setClientSecret(String clientSecret) { this.clientSecret = clientSecret; }

    @TranslatorProperty(display = "Spreadsheet ID", description = "Google Sheets spreadsheet ID", required = true)
    public String getSpreadsheetId() { return spreadsheetId; }
    public void setSpreadsheetId(String spreadsheetId) { this.spreadsheetId = spreadsheetId; }

    @Override
    public GoogleSheetsConnection getConnection(Object factory, ExecutionContext context) throws TranslatorException {
        return new GoogleSheetsConnection(refreshToken, clientId, clientSecret);
    }

    @Override
    public void closeConnection(GoogleSheetsConnection connection, Object factory) {
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
    public void getMetadata(MetadataFactory metadataFactory, GoogleSheetsConnection connection) throws TranslatorException {
        // Metadata is supplied by explicit DDL generated during source registration.
    }

    @Override
    public ResultSetExecution createResultSetExecution(QueryExpression command,
            ExecutionContext executionContext, RuntimeMetadata metadata, GoogleSheetsConnection connection)
            throws TranslatorException {
        if (!(command instanceof Select)) {
            throw new TranslatorException("Only SELECT statements are supported by the Google Sheets translator");
        }
        if (connection == null) {
            connection = getConnection(null, executionContext);
        }
        return new GoogleSheetsExecution((Select) command, executionContext, metadata, connection, spreadsheetId);
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
