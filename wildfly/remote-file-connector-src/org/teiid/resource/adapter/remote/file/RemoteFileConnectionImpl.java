package org.teiid.resource.adapter.remote.file;

import java.io.InputStream;

import org.teiid.file.JavaVirtualFileConnection;
import org.teiid.file.VirtualFile;
import org.teiid.resource.spi.ResourceConnection;
import org.teiid.translator.TranslatorException;

public class RemoteFileConnectionImpl extends JavaVirtualFileConnection implements ResourceConnection {

    private static final String REMOTE_PREFIX = "remote://";

    private final String proxyBaseUrl;
    private final String proxyApiKey;

    public RemoteFileConnectionImpl(String parentDirectory, boolean allowParentPaths,
                                    String proxyBaseUrl, String proxyApiKey) {
        super(parentDirectory);
        this.proxyBaseUrl = proxyBaseUrl;
        this.proxyApiKey = proxyApiKey;
    }

    @Override
    public VirtualFile[] getFiles(String pattern) throws TranslatorException {
        if (pattern != null && pattern.startsWith(REMOTE_PREFIX)) {
            String token = pattern.substring(REMOTE_PREFIX.length());
            // Allow a "ds:" namespace prefix so the VDB pattern remote://ds:{id}
            // is resolved to the platform FileSourceMeta primary key.
            if (token.startsWith("ds:")) {
                token = token.substring(3);
            }
            return new VirtualFile[] { new RemoteVirtualFile(pattern, token, proxyBaseUrl, proxyApiKey) };
        }
        // Remote file connections are read-only and only understand remote:// patterns.
        throw new TranslatorException("Remote file connection cannot resolve local pattern: " + pattern);
    }

    @Override
    public void add(InputStream is, String path) throws TranslatorException {
        throw new TranslatorException("Remote file connection is read-only");
    }

    @Override
    public boolean remove(String path) throws TranslatorException {
        throw new TranslatorException("Remote file connection is read-only");
    }

    @Override
    public boolean areFilesUsableAfterClose() {
        // Each query re-fetches the remote stream, so files are usable after close.
        return true;
    }
}
