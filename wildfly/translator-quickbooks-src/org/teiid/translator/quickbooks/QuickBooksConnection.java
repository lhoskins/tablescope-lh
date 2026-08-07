package org.teiid.translator.quickbooks;

import java.io.IOException;
import java.io.InputStream;
import java.io.StringReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.Iterator;
import java.util.NoSuchElementException;

import javax.json.Json;
import javax.json.JsonArray;
import javax.json.JsonObject;
import javax.json.JsonReader;
import javax.json.JsonValue;

import org.teiid.translator.TranslatorException;

/**
 * Thin HTTP client wrapper around the QuickBooks Online Accounting API.
 *
 * Pages through the SQL-like query endpoint using STARTPOSITION / MAXRESULTS.
 */
public class QuickBooksConnection {

    private final String baseUrl;
    private final String realmId;
    private final String accessToken;
    private final int pageSize;

    public QuickBooksConnection(String baseUrl, String realmId, String accessToken, int pageSize) {
        if (baseUrl == null || baseUrl.isEmpty()) {
            this.baseUrl = "https://quickbooks.api.intuit.com";
        } else {
            String url = baseUrl.trim();
            if (url.endsWith("/")) {
                url = url.substring(0, url.length() - 1);
            }
            this.baseUrl = url;
        }
        this.realmId = realmId;
        this.accessToken = accessToken;
        this.pageSize = pageSize <= 0 ? 1000 : pageSize;
    }

    public Iterable<JsonObject> query(String table, String queryString, String fields, int limit, int offset) throws TranslatorException {
        return new Iterable<JsonObject>() {
            @Override
            public Iterator<JsonObject> iterator() {
                return new QuickBooksIterator(table, queryString, fields, limit, offset);
            }
        };
    }

    private class QuickBooksIterator implements Iterator<JsonObject> {

        private final String table;
        private final String queryString;
        private final String fields;
        private final int limit;
        private int offset;
        private int returned;
        private JsonArray currentPage;
        private int pageIndex;

        QuickBooksIterator(String table, String queryString, String fields, int limit, int offset) {
            this.table = table;
            this.queryString = queryString;
            this.fields = fields;
            this.limit = limit;
            // QuickBooks STARTPOSITION is 1-indexed; Teiid offset is 0-indexed.
            this.offset = offset;
            this.returned = 0;
        }

        @Override
        public boolean hasNext() {
            if (currentPage == null || pageIndex >= currentPage.size()) {
                if (limit > 0 && returned >= limit) {
                    return false;
                }
                try {
                    loadPage();
                } catch (TranslatorException e) {
                    throw new RuntimeException(e);
                }
            }
            return currentPage != null && pageIndex < currentPage.size();
        }

        @Override
        public JsonObject next() {
            if (!hasNext()) {
                throw new NoSuchElementException();
            }
            JsonObject row = currentPage.getJsonObject(pageIndex++);
            returned++;
            return row;
        }

        private void loadPage() throws TranslatorException {
            currentPage = null;
            pageIndex = 0;

            try {
                int pageLimit = pageSize;
                if (limit > 0) {
                    int remaining = limit - returned;
                    if (remaining <= 0) {
                        return;
                    }
                    pageLimit = Math.min(pageSize, remaining);
                }

                StringBuilder soql = new StringBuilder("SELECT ");
                if (fields != null && !fields.isEmpty()) {
                    soql.append(fields);
                } else {
                    soql.append("*");
                }
                soql.append(" FROM ").append(table);
                soql.append(" STARTPOSITION ").append(offset + 1);
                soql.append(" MAXRESULTS ").append(pageLimit);

                StringBuilder url = new StringBuilder(baseUrl);
                url.append("/v3/company/").append(URLEncoder.encode(realmId, StandardCharsets.UTF_8.name()));
                url.append("/query");
                String sep = "?";
                url.append(sep).append("minorversion=65");
                url.append("&query=").append(URLEncoder.encode(soql.toString(), StandardCharsets.UTF_8.name()));

                HttpURLConnection conn = (HttpURLConnection) new URL(url.toString()).openConnection();
                conn.setRequestMethod("GET");
                conn.setConnectTimeout(20000);
                conn.setReadTimeout(60000);
                conn.setRequestProperty("Authorization", "Bearer " + accessToken);
                conn.setRequestProperty("Accept", "application/json");

                int code = conn.getResponseCode();
                if (code >= 400) {
                    InputStream err = conn.getErrorStream();
                    String msg = err != null ? read(err) : "";
                    throw new TranslatorException("QuickBooks HTTP " + code + ": " + msg);
                }

                String body = read(conn.getInputStream());
                try (JsonReader reader = Json.createReader(new StringReader(body))) {
                    JsonObject resp = reader.readObject();
                    JsonObject queryResponse = resp.getJsonObject("QueryResponse");
                    if (queryResponse == null) {
                        currentPage = Json.createArrayBuilder().build();
                        return;
                    }
                    JsonArray result = queryResponse.getJsonArray(table);
                    if (result == null) {
                        result = Json.createArrayBuilder().build();
                    }
                    currentPage = result;
                    offset += result.size();
                }
            } catch (IOException e) {
                throw new TranslatorException(e);
            }
        }

        private String read(InputStream is) throws IOException {
            StringBuilder sb = new StringBuilder();
            byte[] buf = new byte[8192];
            int n;
            while ((n = is.read(buf)) > 0) {
                sb.append(new String(buf, 0, n, StandardCharsets.UTF_8));
            }
            return sb.toString();
        }
    }
}
