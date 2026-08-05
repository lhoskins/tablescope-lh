package org.teiid.translator.servicenow;

import java.io.IOException;
import java.io.InputStream;
import java.io.StringReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.Base64;
import java.util.Iterator;
import java.util.NoSuchElementException;

import javax.json.Json;
import javax.json.JsonArray;
import javax.json.JsonObject;
import javax.json.JsonReader;

import org.teiid.translator.TranslatorException;

/**
 * Thin HTTP client wrapper around the ServiceNow Table API.
 *
 * Pages through /api/now/table/{table} with sysparm_limit/sysparm_offset
 * and exposes an Iterable<JsonObject> so the execution can stream records.
 */
public class ServiceNowConnection {

    private final String instanceUrl;
    private final String username;
    private final String password;
    private final int pageSize;

    public ServiceNowConnection(String instanceUrl, String username, String password, int pageSize) {
        if (instanceUrl == null || instanceUrl.isEmpty()) {
            this.instanceUrl = null;
        } else {
            String url = instanceUrl.trim();
            if (url.endsWith("/")) {
                url = url.substring(0, url.length() - 1);
            }
            this.instanceUrl = url;
        }
        this.username = username;
        this.password = password;
        this.pageSize = pageSize <= 0 ? 200 : pageSize;
    }

    public Iterable<JsonObject> query(String table, String query, String fields, int limit, int offset) throws TranslatorException {
        return new Iterable<JsonObject>() {
            @Override
            public Iterator<JsonObject> iterator() {
                return new ServiceNowIterator(table, query, fields, limit, offset);
            }
        };
    }

    private class ServiceNowIterator implements Iterator<JsonObject> {

        private final String table;
        private final String query;
        private final String fields;
        private final int limit;
        private int offset;
        private int returned;
        private JsonArray currentPage;
        private int pageIndex;

        ServiceNowIterator(String table, String query, String fields, int limit, int offset) {
            this.table = table;
            this.query = query;
            this.fields = fields;
            this.limit = limit;
            this.offset = offset;
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

            if (instanceUrl == null) {
                throw new TranslatorException("ServiceNow instance URL is not configured");
            }

            try {
                StringBuilder url = new StringBuilder(instanceUrl);
                url.append("/api/now/table/").append(URLEncoder.encode(table, StandardCharsets.UTF_8.name()));
                String sep = "?";

                if (fields != null && !fields.isEmpty()) {
                    url.append(sep).append("sysparm_fields=").append(URLEncoder.encode(fields, StandardCharsets.UTF_8.name()));
                    sep = "&";
                }
                if (query != null && !query.isEmpty()) {
                    url.append(sep).append("sysparm_query=").append(URLEncoder.encode(query, StandardCharsets.UTF_8.name()));
                    sep = "&";
                }

                int pageLimit = pageSize;
                if (limit > 0) {
                    int remaining = limit - returned;
                    if (remaining <= 0) {
                        return;
                    }
                    pageLimit = Math.min(pageSize, remaining);
                }

                url.append(sep).append("sysparm_limit=").append(pageLimit);
                url.append("&sysparm_offset=").append(offset);
                url.append("&sysparm_display_value=false");
                url.append("&sysparm_exclude_reference_link=true");
                url.append("&sysparm_suppress_pagination_header=true");

                HttpURLConnection conn = (HttpURLConnection) new URL(url.toString()).openConnection();
                conn.setRequestMethod("GET");
                conn.setConnectTimeout(20000);
                conn.setReadTimeout(60000);
                String auth = username + ":" + password;
                conn.setRequestProperty("Authorization", "Basic " + Base64.getEncoder().encodeToString(auth.getBytes(StandardCharsets.UTF_8)));
                conn.setRequestProperty("Accept", "application/json");

                int code = conn.getResponseCode();
                if (code >= 400) {
                    InputStream err = conn.getErrorStream();
                    String msg = err != null ? read(err) : "";
                    throw new TranslatorException("ServiceNow HTTP " + code + ": " + msg);
                }

                String body = read(conn.getInputStream());
                try (JsonReader reader = Json.createReader(new StringReader(body))) {
                    JsonObject resp = reader.readObject();
                    JsonArray result = resp.getJsonArray("result");
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
