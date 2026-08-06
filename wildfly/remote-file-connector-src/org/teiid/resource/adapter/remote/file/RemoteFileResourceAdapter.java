package org.teiid.resource.adapter.remote.file;

import org.teiid.resource.spi.BasicResourceAdapter;

public class RemoteFileResourceAdapter extends BasicResourceAdapter {
    private static final long serialVersionUID = 1L;

    @Override
    public int hashCode() {
        return super.hashCode();
    }

    @Override
    public boolean equals(Object obj) {
        if (this == obj) {
            return true;
        }
        if (obj == null) {
            return false;
        }
        return getClass() == obj.getClass();
    }
}
