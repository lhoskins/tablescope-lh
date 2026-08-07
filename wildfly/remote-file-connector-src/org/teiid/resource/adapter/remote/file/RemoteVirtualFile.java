package org.teiid.resource.adapter.remote.file;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;

import org.teiid.file.VirtualFile;

public class RemoteVirtualFile implements VirtualFile {

    private final String path;
    private final String token;
    private final String proxyBaseUrl;
    private final String proxyApiKey;

    public RemoteVirtualFile(String path, String token, String proxyBaseUrl, String proxyApiKey) {
        this.path = path;
        this.token = token;
        this.proxyBaseUrl = proxyBaseUrl;
        this.proxyApiKey = proxyApiKey;
    }

    @Override
    public String getName() {
        return path;
    }

    @Override
    public boolean isDirectory() {
        return false;
    }

    @Override
    public String getPath() {
        return path;
    }

    @Override
    public long getLastModified() {
        return 0L;
    }

    @Override
    public long getCreationTime() {
        return 0L;
    }

    @Override
    public long getSize() {
        return -1L;
    }

    @Override
    public InputStream openInputStream(boolean lock) throws IOException {
        if (proxyBaseUrl == null || proxyBaseUrl.isEmpty()) {
            throw new IOException("Remote file proxy base URL is not configured");
        }
        String sep = proxyBaseUrl.contains("?") ? "&" : "?";
        URL url = new URL(proxyBaseUrl + sep + "data_source_id=" + URLEncoder.encode(token, StandardCharsets.UTF_8));
        HttpURLConnection conn = (HttpURLConnection) url.openConnection();
        conn.setRequestMethod("GET");
        conn.setConnectTimeout(30000);
        conn.setReadTimeout(120000);
        if (proxyApiKey != null && !proxyApiKey.isEmpty()) {
            conn.setRequestProperty("X-API-Key", proxyApiKey);
        }
        int code = conn.getResponseCode();
        if (code >= 400) {
            String msg = "";
            try (InputStream err = conn.getErrorStream()) {
                if (err != null) {
                    msg = new String(err.readAllBytes(), StandardCharsets.UTF_8);
                }
            } catch (Exception ignore) {
            }
            throw new IOException("Remote file proxy returned " + code + ": " + msg);
        }
        return conn.getInputStream();
    }

    @Override
    public OutputStream openOutputStream(boolean lock) throws IOException {
        throw new IOException("Remote files are read-only");
    }
}
