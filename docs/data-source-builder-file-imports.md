# Data Source Builder file imports (URL and UNC/SMB)

The Data Source Builder acquires files three ways — local upload, an approved
HTTPS URL, and an approved UNC/SMB network path — and then runs the *same*
profiling, AI analysis, Teiid registration, metadata, and project-assignment
pipeline for all three. A URL or network path is **provenance for an immutable
snapshot**, not a live connection: nothing re-reads the source later.

## Architecture

| Concern | Where it lives |
| --- | --- |
| Acquisition (HTTP fetch, SMB read) | `platform-api` only — never the browser, never the AI server |
| Credentials | `network_file_connections.secret_encrypted` (Fernet), decrypted only inside `smb_gateway` |
| Staged bytes | tenant-scoped quarantine on disk, `FILE_IMPORT_QUARANTINE_PATH/<tenant>/<user>/<job>` |
| Job state | `file_import_jobs` table (survives API restarts) |
| Provenance | redacted locator + sha256 + etag on `file_source_meta` |

Key modules:

- `app/services/safe_remote_fetch.py` — the only sanctioned way to fetch a
  user-supplied URL server-side. `reference_library_bulk` uses it too.
- `app/services/smb_gateway.py` — path resolution (pure, testable) plus the
  SMB2/SMB3 read.
- `app/services/file_validation.py` — extension + MIME + magic-byte agreement,
  archive/executable refusal, OOXML decompression-bomb guards.
- `app/services/malware_scan.py` — ClamAV `INSTREAM` client and failure policy.
- `app/services/file_ingestion.py` — staging, profiling, and finalization
  shared by every acquisition method.

## Configuration

| Variable | Default | Notes |
| --- | --- | --- |
| `FILE_IMPORT_URL_ENABLED` | `true` | Disables the URL card when off. |
| `FILE_IMPORT_NETWORK_ENABLED` | `false` | Requires approved connections + host allowlist. |
| `FILE_IMPORT_MAX_BYTES` | `104857600` | Enforced early (Content-Length) and while streaming. |
| `FILE_IMPORT_QUARANTINE_PATH` | `/opt/tablescope/quarantine` | Must be writable by the API and worker. |
| `FILE_IMPORT_ALLOWED_URL_DOMAINS` | empty | Comma-separated host suffixes; empty means any *public* host. |
| `FILE_IMPORT_ALLOWED_SMB_HOSTS` | empty | Comma-separated hosts. **Empty blocks all SMB reads.** |
| `FILE_IMPORT_ALLOW_HTTP` | `false` | Leave off; HTTPS-only is the contract. |
| `FILE_IMPORT_JOB_TTL_SECONDS` | `86400` | Abandoned jobs expire and their bytes are deleted. |
| `FILE_IMPORT_MALWARE_SCAN_ENABLED` | `false` | See below — must be `true` in production. |
| `FILE_IMPORT_MALWARE_SCAN_HOST` / `_PORT` | `clamav` / `3310` | clamd TCP endpoint. |
| `FILE_IMPORT_MALWARE_SCAN_FAIL_OPEN` | `false` | Keep `false`; `true` is a break-glass setting. |

## Malware scanning (Phase 1 infrastructure)

Scanning is new infrastructure, not a toggle over an existing capability.
Standing it up means all of:

1. **Run the scanner.** `docker compose --profile clamav up -d clamav` starts a
   private clamd with no published ports; only the API and worker reach it.
2. **Keep signatures current.** The image's `freshclam` updates on a timer. In
   an air-gapped install, mirror the CVD/CLD files and mount them read-write
   over `/var/lib/clamav`; a signature set older than ~7 days should raise an
   operational alert.
3. **Set the failure mode.** With scanning enabled and clamd unreachable, an
   import fails closed with `SCANNER_UNAVAILABLE` (HTTP 503). Setting
   `FILE_IMPORT_MALWARE_SCAN_FAIL_OPEN=true` downgrades that to a logged
   warning and is only for a scanner outage that would otherwise block work.
4. **Watch capacity.** Every byte of every import is streamed through clamd;
   size the scanner alongside `FILE_IMPORT_MAX_BYTES` and expected volume.

An infected file blocks the import (`SECURITY_BLOCKED`), deletes the staged
copy, and logs the signature name with the job and tenant id.

**Exit criterion:** URL and network import must not be enabled in an
environment where `FILE_IMPORT_MALWARE_SCAN_ENABLED` is `false`.

## URL import controls

HTTPS only; URL user-info rejected; DNS resolved up front with every resulting
address checked against private, loopback, link-local, multicast, reserved,
CGNAT, and cloud-metadata ranges (IPv4 and IPv6); the connection pinned to the
vetted address so a re-resolution cannot rebind the name to an internal target;
every redirect hop revalidated the same way with a hop cap of 5; early
`Content-Length` rejection plus a hard streaming byte cap; bounded
connect/read/total timeouts; capped global concurrency and per-host rate
limiting; no retry of permanent or security failures.

Query strings and fragments can carry signed credentials, so only
`scheme://host/path` is ever logged, stored, or shown to the user.

## Network (UNC/SMB) import controls

Users cannot type an arbitrary server. An admin registers a
**network file connection** (host, share, approved root path, read-only
service account) under `/api/network-file-connections`, the host must also be
in `FILE_IMPORT_ALLOWED_SMB_HOSTS`, and the entered path must match that
connection and stay inside its approved root. Traversal segments, wildcards,
alternate separators, device paths (`\\.\`, `\\?\`), and administrative shares
(`C$`, `ADMIN$`, `IPC$`, …) are refused. Connections default to requiring
signing and encryption; `smbprotocol` speaks SMB 2.0.2+ only, so SMB1 and
NTLMv1 are not reachable. Credentials are never passed on a command line,
never mounted, never returned by an API, and never sent to the browser or the
AI server.

Grant the service account **read-only** access to the approved root, and open
egress from the API/worker to port 445 on the approved hosts only.

## API surface

```
POST   /api/data-sources/imports/local          multipart upload
POST   /api/data-sources/imports/url            { url, project_id? }
POST   /api/data-sources/imports/network/test   { connection_id, path? }
POST   /api/data-sources/imports/network        { connection_id, path, project_id? }
GET    /api/data-sources/imports/capabilities   what the builder may offer
GET    /api/data-sources/imports/{job_id}       safe status + preview
DELETE /api/data-sources/imports/{job_id}       cancel + purge quarantine
POST   /api/data-sources/upload/finalize        { import_job_id | upload_session_id, … }
```

`/api/data-sources/upload/analyze` still works and now returns both
`import_job_id` and the legacy `upload_session_id` alias, so existing clients
keep working while they migrate.
