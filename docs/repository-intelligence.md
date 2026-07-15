# Repository Intelligence — Sprint 06

Sprint 06 adds a secure, extensible repository intelligence layer to Tablescope. It provides a reusable connector abstraction, a production-ready UNC/SMB connector, asynchronous background scanning, change detection, profiling, and audit visibility. Out-of-scope providers (SharePoint, OneDrive, Google Drive, S3, Azure Blob, Box, Dropbox) are reserved for future sprints.

## Architecture

### Backend

```text
Admin UI / Worker / Manual Request
  -> /api/repository-connectors
  -> Repository Service
  -> Secret Reference (ConnectorCredential + crypto.encrypt_secret/decrypt_secret)
  -> Connector Registry
  -> UNC Repository Connector (smbclient over asyncio.to_thread)
  -> Repository Scanner
       -> Distributed Lock + Heartbeat
       -> Connector.list_items(checkpoint)
       -> Change Detection / Incremental Upsert
       -> Profile Aggregation
       -> AI Governance Check (document_synthesis gate)
       -> Audit Events
```

### Frontend

```text
/admin/repositories
  -> Add/edit UNC form
  -> Connection test
  -> Scan now
  -> Scan history
  -> Profile stat cards
  -> Paginated item browser
```

## Components

### Backend modules

| Path | Responsibility |
|------|---------------|
| `app/connectors/repositories/base.py` | Abstract `RepositoryConnector` interface |
| `app/connectors/repositories/types.py` | `RepositoryItem`, `RepositoryPage`, `ConnectionTestResult`, `ConnectionCheck` |
| `app/connectors/repositories/registry.py` | Connector registration and discovery |
| `app/connectors/repositories/unc.py` | UNC/SMB connector implementation |
| `app/connectors/repositories/_path_utils.py` | UNC path normalization, joining, traversal guard |
| `app/services/repository_service.py` | CRUD, connection test orchestration for `/repository-connectors` |
| `app/services/repository_scanner.py` | Async background scanner, heartbeat, change detection |
| `app/services/repository_profiler.py` | Aggregate profile from scanned items (size, age, type, duplicates, extraction) |
| `app/services/repository_lock.py` | Distributed lock and heartbeat using Redis |
| `app/models/repository.py` | `RepositoryConnection`, `RepositoryScan`, `RepositoryItem`, `RepositoryProfile` |
| `app/models/connector_credential.py` | Reused secret storage for connector credentials |
| `app/routes/repository_connectors.py` | REST routes for `/repository-connectors` |
| `app/tasks/workflows.py` | `enqueue_scan_repository_connection` / `scan_repository_connection` worker task |
| `alembic/versions/0056_repository_intelligence.py` | Adds Sprint 06 tables, chained after `0055_ai_governance.py` |

### Frontend modules

| Path | Responsibility |
|------|---------------|
| `app/admin/repositories/page.tsx` | Connector list, UNC form, connection test, scan history, profile, item browser |
| `lib/api/repository-connectors.ts` | TypeScript API client for all `/api/repository-connectors` endpoints |
| `app/admin/layout.tsx` | Adds active-nav mapping for `/admin/repositories` |
| `components/tablescope/sidebar.tsx` | Adds Repositories admin nav item |
| `lib/ui/types.ts` | Adds `admin-repositories` to `NavKey` union |

## Security

- **No plaintext secrets.** Connector credentials are stored in `connector_credentials.secret_encrypted` using the existing `crypto.encrypt_secret`/`decrypt_secret` Fernet layer. APIs never return a secret.
- **Tenant isolation.** All routes and service methods use `tenant_id` from the request context. Users can only see connections from their tenant.
- **Role enforcement.** Routes require `tenant_admin`.
- **Path confinement.** UNC connector validates that the configured root path starts with `\\` and rejects traversal patterns (`..`, `/`, `*`, `?`) and leading drive letters or URI schemes.
- **No write access.** The connector is read-only (`smbclient.open_file("rb")`) and does not delete or modify source content.
- **SMB 1 disabled.** The UNC connector sets `ClientConfig(smb1=False, max_dialect=...)` and prefers SMB 3.x dialects.
- **Untrusted filenames.** Filenames and paths are treated as untrusted and sanitized in logs and error messages.
- **No client-supplied tenant IDs or roles.** The API ignores any tenant or role values sent by the client.

## API Reference

All routes are prefixed with `/api/repository-connectors` and require `tenant_admin`.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/types` | List registered connector types |
| GET | `/` | List connections for the tenant |
| POST | `/` | Create a connection |
| GET | `/{id}` | Get connection details (no secret) |
| PATCH | `/{id}` | Update connection with `expected_version` optimistic concurrency |
| DELETE | `/{id}` | Disable a connection |
| POST | `/test` | Test a connector config without saving |
| POST | `/{id}/test` | Test an existing stored connection |
| POST | `/{id}/scans` | Start a scan and enqueue the worker |
| GET | `/{id}/scans` | List scan history |
| GET | `/{id}/scans/{scan_id}` | Get scan details |
| GET | `/{id}/profile` | Get latest profile or build on demand |
| GET | `/{id}/items` | Paginated item browser with filters |

## Worker and scheduler

- **Worker technology:** `arq` backed by Redis, reusing the existing `WorkerSettings` in `app/tasks/workflows.py`.
- **New worker function:** `scan_repository_connection(ctx, tenant_id, connection_id, scan_id)`.
- **Scheduler technology:** The `scan_schedule` field on `RepositoryConnection` accepts a cron expression. A scheduled trigger will be added in a follow-up sprint; the current release exposes manual scans through the UI/API and worker task invocation.
- **Concurrency safety:** `RepositoryScanLock` uses Redis to ensure only one scan runs per connection at a time. `RepositoryScanHeartbeat` updates `heartbeat_at` while the scan is running.

## UNC connector

- **Library:** `smbclient` from `smbprotocol==1.16.1`.
- **Async strategy:** `asyncio.to_thread` so synchronous SMB calls do not block the worker event loop.
- **Connection lifecycle:** `open_file_session` creates an SMB session per share; the session is closed after each call.
- **Enumeration:** `listdir` and `stat` walk the configured share recursively in pages, respecting `page_size`.
- **Content streaming:** `read_item` opens files in binary mode and reads up to `limit_bytes`.
- **Change token:** Uses `st_ino` as ETag when available, then `content_hash`, then `modified_at`.

## Change detection

The scanner maintains a `RepositoryItem` per connection per `external_id` (unique `(connection_id, external_id)`).

On each scan:
- Existing items not seen are marked `is_deleted = True`.
- Existing items with a different ETag, content hash, or `source_modified_at` are treated as changed and their `last_changed_scan_id` is updated.
- New items get `first_seen_scan_id` set to the current scan.
- Scan counters (`added_count`, `changed_count`, `deleted_count`, `skipped_count`, `error_count`, `files_seen`, `directories_seen`, `bytes_seen`) are tracked per scan.

## Profile aggregation

`RepositoryProfiler.build_profile` computes an aggregate profile from the current item snapshot:

- `total_files`, `total_directories`, `total_size`
- Size buckets (`0 B`, `0 B - 1 KB`, ..., `> 1 GB`)
- Age buckets (`last_7_days`, `last_30_days`, `last_90_days`, `last_year`, `last_5_years`, `older`)
- MIME type counts
- Duplicate candidates by content hash
- Extraction status counts (`pending`, `completed`, `error`, `governance_blocked`, `unsupported`)

## Governance and audit

Each scan evaluates the `document_synthesis` AI governance gate once. If blocked, files receive `extraction_status = "governance_blocked"` and an `AIGovernanceAuditEvent` is emitted with `event_type = "repository.extraction_governance_blocked"`.

Additional audit events:
- `repository.scan.started`
- `repository.scan.succeeded`
- `repository.scan.partial`
- `repository.scan.failed`
- `repository.connection.tested`

## Migration

```bash
cd platform-api
alembic upgrade 0056
```

The migration `alembic/versions/0056_repository_intelligence.py` is chained after `0055_ai_governance.py` and creates `repository_connections`, `repository_scans`, `repository_items`, and `repository_profiles`.

## Tests

### Backend

```bash
cd platform-api
python -m compileall app
python -m pytest tests/test_repository_connectors.py
python -m pytest tests/test_unc_repository_connector.py
python -m pytest tests/test_repository_scanner.py
python -m pytest tests/test_repository_profiler.py
python -m pytest
python -m ruff check app tests
python -m mypy app
```

### Frontend

```bash
cd web-ui
npm run typecheck
npm run lint
npm test
npm run build
```

## Out of scope

- SharePoint, OneDrive, Google Drive, S3, Azure Blob, Box, Dropbox connectors.
- Source write-back, file deletion/modification.
- Real-time SMB event subscriptions.
- Full RAG/vector search, document chat, OCR expansion.
- Antivirus platform, DLP/classification engine, full ACL synchronization.
- Unrestricted local filesystem connector or cross-tenant repository sharing.
- Automatic cross-repository deduplication.
