package org.teiid.translator.googlesheets;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.io.UnsupportedEncodingException;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import javax.json.Json;
import javax.json.JsonArray;
import javax.json.JsonObject;
import javax.json.JsonReader;
import org.teiid.translator.TranslatorException;

public class GoogleSheetsConnection {

    private final String refreshToken;
    private final String clientId;
    private final String clientSecret;
    private volatile String accessToken;
    private volatile long expiresAt;

    public GoogleSheetsConnection(String refreshToken, String clientId, String clientSecret) {
        this.refreshToken = refreshToken;
        this.clientId = clientId;
        this.clientSecret = clientSecret;
    }

    public JsonArray fetchValues(String spreadsheetId, String range) throws TranslatorException {
        ensureAccessToken();
        String url = "https://sheets.googleapis.com/v4/spreadsheets/"
                + spreadsheetId
                + "/values/"
                + urlEncode(range)
                + "?valueRenderOption=UNFORMATTED_VALUE&dateTimeRenderOption=SERIAL_NUMBER&majorDimension=ROWS";
        HttpURLConnection conn = null;
        try {
            conn = (HttpURLConnection) new URL(url).openConnection();
            conn.setRequestProperty("Authorization", "Bearer " + accessToken);
            conn.setRequestProperty("Accept", "application/json");
            int code = conn.getResponseCode();
            if (code >= 400) {
                String body = readStream(conn.getErrorStream());
                throw new TranslatorException("Google Sheets API error " + code + ": " + body);
            }
            try (JsonReader reader = Json.createReader(conn.getInputStream())) {
                JsonObject obj = reader.readObject();
                JsonArray values = obj.getJsonArray("values");
                return values != null ? values : Json.createArrayBuilder().build();
            }
        } catch (TranslatorException e) {
            throw e;
        } catch (Exception e) {
            throw new TranslatorException(e, "Failed to fetch sheet values");
        } finally {
            if (conn != null) {
                conn.disconnect();
            }
        }
    }

    private void ensureAccessToken() throws TranslatorException {
        if (accessToken != null && System.currentTimeMillis() < expiresAt - 60000L) {
            return;
        }
        String payload = "client_id=" + urlEncode(clientId)
                + "&client_secret=" + urlEncode(clientSecret)
                + "&refresh_token=" + urlEncode(refreshToken)
                + "&grant_type=refresh_token";
        HttpURLConnection conn = null;
        try {
            conn = (HttpURLConnection) new URL("https://oauth2.googleapis.com/token").openConnection();
            conn.setRequestMethod("POST");
            conn.setDoOutput(true);
            conn.setRequestProperty("Content-Type", "application/x-www-form-urlencoded");
            try (OutputStream os = conn.getOutputStream()) {
                os.write(payload.getBytes(StandardCharsets.UTF_8));
            }
            int code = conn.getResponseCode();
            if (code >= 400) {
                String body = readStream(conn.getErrorStream());
                throw new TranslatorException("Google token refresh failed " + code + ": " + body);
            }
            try (JsonReader reader = Json.createReader(conn.getInputStream())) {
                JsonObject obj = reader.readObject();
                String token = obj.getString("access_token", null);
                if (token == null || token.isEmpty()) {
                    throw new TranslatorException("No access_token in refresh response");
                }
                this.accessToken = token;
                this.expiresAt = System.currentTimeMillis() + (obj.getInt("expires_in", 3600) * 1000L);
            }
        } catch (TranslatorException e) {
            throw e;
        } catch (Exception e) {
            throw new TranslatorException(e, "Failed to refresh Google access token");
        } finally {
            if (conn != null) {
                conn.disconnect();
            }
        }
    }

    private String urlEncode(String value) {
        try {
            return value == null ? "" : URLEncoder.encode(value, StandardCharsets.UTF_8.name());
        } catch (UnsupportedEncodingException e) {
            throw new RuntimeException(e);
        }
    }

    private String readStream(InputStream is) {
        if (is == null) {
            return "";
        }
        StringBuilder sb = new StringBuilder();
        try (BufferedReader br = new BufferedReader(new InputStreamReader(is, StandardCharsets.UTF_8))) {
            String line;
            while ((line = br.readLine()) != null) {
                sb.append(line).append('\n');
            }
        } catch (IOException e) {
            // ignore
        }
        return sb.toString();
    }
}
