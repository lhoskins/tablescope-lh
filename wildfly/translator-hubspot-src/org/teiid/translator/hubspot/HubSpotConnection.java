package org.teiid.translator.hubspot;

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
 * Thin HTTP client wrapper around the HubSpot CRM v3 Objects API.
 *
 * Pages through /crm/v3/objects/{object} using the "after" cursor and
 * exposes an Iterable<JsonObject> so the execution can stream records.
 */
public class HubSpotConnection {

    private final String baseUrl;
    private final String accessToken;
    private final int pageSize;

    public HubSpotConnection(String baseUrl, String accessToken, int pageSize) {
        if (baseUrl == null || baseUrl.isEmpty()) {
            this.baseUrl = "https://api.hubapi.com";
        } else {
            String url = baseUrl.trim();
            if (url.endsWith("/")) {
                url = url.substring(0, url.length() - 1);
            }
            this.baseUrl = url;
        }
        this.accessToken = accessToken;
        this.pageSize = pageSize <= 0 ? 100 : Math.min(pageSize, 100);
    }

    public Iterable<JsonObject> query(String table, String fields, int limit, int offset) throws TranslatorException {
        return new Iterable<JsonObject>() {
            @Override
            public Iterator<JsonObject> iterator() {
                return new HubSpotIterator(table, fields, limit, offset);
            }
        };
    }

    private class HubSpotIterator implements Iterator<JsonObject> {

        private final String table;
        private final String fields;
        private final int limit;
        private int returned;
        private String after;
        private JsonArray currentPage;
        private int pageIndex;

        HubSpotIterator(String table, String fields, int limit, int offset) {
            this.table = table;
            this.fields = fields;
            this.limit = limit;
            // HubSpot does not support numeric offset; the offset argument is
            // ignored.  Teiid is told supportsRowOffset=false so it only uses limit.
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
                StringBuilder url = new StringBuilder(baseUrl);
                url.append("/crm/v3/objects/").append(URLEncoder.encode(table, StandardCharsets.UTF_8.name()));
                String sep = "?";

                if (fields != null && !fields.isEmpty()) {
                    url.append(sep).append("properties=").append(URLEncoder.encode(fields, StandardCharsets.UTF_8.name()));
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

                url.append(sep).append("limit=").append(pageLimit);
                url.append("&archived=false");
                if (after != null && !after.isEmpty()) {
                    url.append("&after=").append(URLEncoder.encode(after, StandardCharsets.UTF_8.name()));
                }

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
                    throw new TranslatorException("HubSpot HTTP " + code + ": " + msg);
                }

                String body = read(conn.getInputStream());
                try (JsonReader reader = Json.createReader(new StringReader(body))) {
                    JsonObject resp = reader.readObject();
                    JsonArray result = resp.getJsonArray("results");
                    if (result == null) {
                        result = Json.createArrayBuilder().build();
                    }
                    currentPage = result;
                    JsonObject paging = resp.getJsonObject("paging");
                    if (paging != null) {
                        JsonObject next = paging.getJsonObject("next");
                        if (next != null) {
                            after = next.getString("after", null);
                        } else {
                            after = null;
                        }
                    } else {
                        after = null;
                    }
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
