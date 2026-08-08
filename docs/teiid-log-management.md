# Teiid / WildFly Log Management

**Date:** 2026-07-26  
**Scope:** `tablescope-teiid-1` container (`wildfly` service) and the `/opt/wildfly/standalone/log` directory.

---

## 1. What was validated

### VDB and customer data are in S3

The `tablescope-data-988823366090` bucket is the authoritative store for VDBs and customer uploads:

| Path pattern | Purpose |
|--------------|---------|
| `customers/{tenant_id}/{project_id}/vdb/{uuid}-vdb.xml` | Per-project VDB definition |
| `customers/{tenant_id}/shared/vdb/{uuid}-vdb.xml` | Tenant-wide shared VDB |
| `customers/{tenant_id}/{project_id}/uploads/{file}` | Uploaded source files (CSV/XLSX) |
| `{tenant_id}/{user_id}/avatar/{uuid}.png` | User avatars (top-level prefix) |

Counts observed at the time of review: **70 VDB XMLs** and **118 upload objects** under `customers/`.

Example objects:
- `customers/2/1/uploads/SalesJournalYTD.xlsx`
- `customers/2/1/vdb/6426044-vdb.xml`
- `customers/33/48/uploads/`
- `customers/33/shared/vdb/`

### `standalone` logs were not circular

The active WildFly config (`wildfly/standalone/configuration/standalone-teiid.xml`) used a `periodic-rotating-file-handler` named `FILE`:

- Rotated `server.log` once per day based on the `.yyyy-MM-dd` suffix.
- Appended continuously, so the current-day file could grow without a size cap.
- Had no `max-backup-index`, so rotated daily files accumulated until manually deleted.
- `audit.log` was written by the Elytron file-audit-log and was also unmanaged.

At review time the running container had:
- `server.log` = 836 KB / 5,186 lines
- root disk on the host = 86% full, 8.7 GB free

---

## 2. What changed

### 2.1 WildFly size-based rotation

`wildfly/standalone/configuration/standalone-teiid.xml` now uses a `size-rotating-file-handler`:

```xml
<size-rotating-file-handler name="FILE" autoflush="true">
    <formatter>
        <named-formatter name="PATTERN"/>
    </formatter>
    <file relative-to="jboss.server.log.dir" path="server.log"/>
    <rotate-size value="100m"/>
    <max-backup-index value="30"/>
    <append value="true"/>
</size-rotating-file-handler>
```

- Rotates `server.log` when it reaches **100 MB**.
- Keeps **30 backups** (`server.log.1` … `server.log.30`).
- Caps the `standalone/log` directory at roughly **3.1 GB** from the `FILE` handler.

### 2.2 Persistent log volume

`docker-compose.yml` mounts a named Docker volume so logs survive `teiid` container recreation:

```yaml
teid:
  volumes:
    - teiid_data:/opt/wildfly/teiidfiles/customers
    - teiid_logs:/opt/wildfly/standalone/log
```

```yaml
volumes:
  teiid_logs:
```

### 2.3 Logrotate sidecar for compression and daily retention

A dedicated `tablescope-teiid-logrotate` image runs `logrotate` hourly against the shared volume:

```yaml
teid-logrotate:
  build:
    context: ./wildfly/logrotate
  image: tablescope-teiid-logrotate:latest
  restart: unless-stopped
  volumes:
    - teiid_logs:/logs
```

`wildfly/logrotate/Dockerfile`:

```dockerfile
FROM alpine:3.20
RUN apk add --no-cache logrotate
COPY tablescope-teiid /etc/logrotate.d/tablescope-teiid
RUN chmod 644 /etc/logrotate.d/tablescope-teiid
CMD ["sh", "-c", "while true; do /usr/sbin/logrotate -s /tmp/logrotate.status /etc/logrotate.d/tablescope-teiid; sleep 3600; done"]
```

`wildfly/logrotate/tablescope-teiid`:

```
/logs/*.log {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
    dateext
    dateformat -%Y%m%d
}
```

- Compresses backups.
- Keeps **30 days** of logs.
- Uses `copytruncate` so WildFly does not need to be signaled or restarted on rotation.

### 2.4 Note on `audit.log`

The Elytron `file-audit-log` still writes `audit.log` unmanaged. Because `logrotate` matches `*.log`, the sidecar will also rotate and compress `audit.log` under the same policy.

---

## 3. Rollback

1. Revert `wildfly/standalone/configuration/standalone-teiid.xml` to the previous `periodic-rotating-file-handler`.
2. Remove `teiid_logs` from the `teiid` service volumes.
3. Remove the `teiid-logrotate` service.
4. Run `docker compose up -d` to recreate the `teiid` container without the log volume.

---

## 4. Operational notes

- Inspect live logs: `docker exec tablescope-teiid-1 tail -f /opt/wildfly/standalone/log/server.log`
- Copy a backup for offline analysis:
  `docker cp tablescope-teiid-1:/opt/wildfly/standalone/log/server.log.1 /tmp/`
- The `CONSOLE` handler still writes the same messages to the container stdout, so `docker logs tablescope-teiid-1` remains available for short-term troubleshooting.
