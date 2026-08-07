package org.teiid.resource.adapter.remote.file;

import javax.resource.spi.InvalidPropertyException;

import org.teiid.resource.spi.BasicConnectionFactory;
import org.teiid.resource.spi.BasicManagedConnectionFactory;

public class RemoteFileManagedConnectionFactory extends BasicManagedConnectionFactory {

    private static final long serialVersionUID = 1L;

    private String parentDirectory;
    private String proxyBaseUrl;
    private String proxyApiKey;
    private boolean allowParentPaths = false;

    @Override
    public BasicConnectionFactory<RemoteFileConnectionImpl> createConnectionFactory() throws javax.resource.ResourceException {
        if (parentDirectory == null || parentDirectory.isEmpty()) {
            throw new InvalidPropertyException("ParentDirectory is required");
        }
        if (proxyBaseUrl == null || proxyBaseUrl.isEmpty()) {
            throw new InvalidPropertyException("ProxyBaseUrl is required");
        }
        return new BasicConnectionFactory<RemoteFileConnectionImpl>() {
            private static final long serialVersionUID = 1L;
            @Override
            public RemoteFileConnectionImpl getConnection() throws javax.resource.ResourceException {
                return new RemoteFileConnectionImpl(parentDirectory, allowParentPaths, proxyBaseUrl, proxyApiKey);
            }
        };
    }

    public String getParentDirectory() {
        return parentDirectory;
    }

    public void setParentDirectory(String parentDirectory) {
        this.parentDirectory = parentDirectory;
    }

    public String getProxyBaseUrl() {
        return proxyBaseUrl;
    }

    public void setProxyBaseUrl(String proxyBaseUrl) {
        this.proxyBaseUrl = proxyBaseUrl;
    }

    public String getProxyApiKey() {
        return proxyApiKey;
    }

    public void setProxyApiKey(String proxyApiKey) {
        this.proxyApiKey = proxyApiKey;
    }

    public Boolean isAllowParentPaths() {
        return allowParentPaths;
    }

    public void setAllowParentPaths(Boolean allowParentPaths) {
        this.allowParentPaths = allowParentPaths != null ? allowParentPaths : false;
    }

    @Override
    public int hashCode() {
        int result = 1;
        result = 31 * result + (allowParentPaths ? 1231 : 1237);
        result = 31 * result + (parentDirectory == null ? 0 : parentDirectory.hashCode());
        result = 31 * result + (proxyBaseUrl == null ? 0 : proxyBaseUrl.hashCode());
        result = 31 * result + (proxyApiKey == null ? 0 : proxyApiKey.hashCode());
        return result;
    }

    @Override
    public boolean equals(Object obj) {
        if (this == obj) return true;
        if (obj == null || getClass() != obj.getClass()) return false;
        RemoteFileManagedConnectionFactory other = (RemoteFileManagedConnectionFactory) obj;
        return allowParentPaths == other.allowParentPaths
                && checkEquals(parentDirectory, other.parentDirectory)
                && checkEquals(proxyBaseUrl, other.proxyBaseUrl)
                && checkEquals(proxyApiKey, other.proxyApiKey);
    }
}
