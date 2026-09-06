# TS-ISO-010: Internal File Proxy Hardening — Standalone Implementation Plan

**Status:** Open — implementation required  
**Severity:** High  
**Owner:** Platform / Data Plane / Security  
**Target branch:** `UX-design-03`  
**Plan branch:** `codex/ts-iso-010-file-proxy-hardening`  
**Depends on:** Existing tenant data-plane identity and secret-management facilities  
**Related findings:** TS-ISO-001 (tenant scoping), TS-ISO-006 (SSRF), TS-ISO-012 (isolated storage boundary)

## 1. Objective

Harden `/internal/file-proxy` so a file can be fetched only by an authenticated TableScope workload that is authorized for the exact tenant, project, file source, and active VDB binding. Source IP is defense in depth, not an authorization decision.

The implementation must also preserve the existing safe URL-fetch and SMB controls, reject replayed requests, prevent identifier guessing, constrain the route at the network edge, and bound both downloaded and converted content.

## 2. Current-state finding

The current implementation has several controls, but the authorization boundary is incomplete:

| Area | Current behavior | Security gap |
|---|---|---|
| Route authentication | `/internal/file-proxy` is included in the generic anonymous path-prefix list | A caller does not need a user or workload identity |
| Caller validation | `_source_allowed()` accepts tenant Docker CIDRs, discovered Teiid networks, and operator-configured CIDRs | Network location is treated as authority; shared or misconfigured networks can cross tenant boundaries |
| Forwarded address | `_client_ip()` accepts the first `X-Forwarded-For` value | An untrusted caller can spoof the address unless the immediate proxy is authenticated and trusted |
| Source lookup | `FileSourceMeta` is loaded by numeric `data_source_id` | Sequential identifiers are discoverable and lookup is not tenant-scoped |
| Network connection | `NetworkFileConnection` is loaded by ID | The proxy route does not prove that the connection tenant equals the file-source and workload tenant |
| Project/VDB binding | The route does not validate the requesting workload's project or deployed VDB binding | A valid tenant-network caller can request unrelated sources |
| Teiid adapter | Supports an optional static `X-API-Key`, but deployed configuration uses only `ProxyBaseUrl` | No required signed request, timestamp, nonce, key rotation, or replay protection |
| URL retrieval | `safe_remote_fetch` already validates redirects, addresses, and size limits | These protections must remain mandatory and must not be bypassed in proxy refactoring |
| Conversion | The route buffers content and may return raw bytes after an Excel conversion failure | Converted output can exceed bounds; failure-open behavior can expose unintended content |

### Root cause

The proxy was designed as an internal network helper and accumulated security checks around network origin. In an isolated or VPN data plane, network origin cannot establish tenant, project, or source authorization. The route needs an application-layer workload identity and an object-level grant.

## 3. Security invariants

The implementation is complete only if all of these invariants hold:

1. Every proxy request has a verified, active workload identity.
2. A request is accepted only once and within a short clock-skew window.
3. The workload tenant equals the file-source tenant.
4. The file source is active, not archived, and bound to the requesting project/VDB where a project binding exists.
5. For network sources, the connection tenant equals both the workload and file-source tenant; the connection is enabled and not archived.
6. Numeric database IDs alone never authorize or locate a source at this boundary.
7. `X-Forwarded-For` is ignored unless the immediate socket peer is a configured trusted proxy.
8. Every URL redirect and resolved address is validated by the safe-fetch policy; metadata, loopback, link-local, and unapproved private addresses are rejected.
9. Downloaded, decompressed, parsed, and converted content each have enforced limits.
10. Authentication, replay-state, authorization, or dependency uncertainty fails closed.
11. The route is unreachable from the public ingress and is restricted to the expected data-plane workload path.
12. Logs and audit records do not contain credentials, signed headers, raw URLs, network paths, or file content.

## 4. Target design

### 4.1 Workload identity and signed request

Provision a distinct file-proxy workload identity for each tenant data plane. Store only identity metadata and a managed-secret reference in TableScope; deliver the secret to Teiid through the existing secret-injection mechanism. Do not place plaintext secrets in VDB XML, database rows, images, compose files, or logs.

The Teiid remote-file adapter must send these headers on every request:

- `X-Tablescope-Workload-Id`
- `X-Tablescope-Key-Id`
- `X-Tablescope-Timestamp`
- `X-Tablescope-Request-Id`
- `X-Tablescope-Signature`

Use HMAC-SHA-256 over a versioned canonical payload containing:

```text
version
HTTP method
canonical route
canonical sorted query string
SHA-256 request-body hash
workload ID
key ID
timestamp
request ID
```

Requirements:

- Generate request IDs with at least 128 bits of randomness.
- Permit at most 60 seconds of clock skew; make the value configurable with a secure upper bound.
- Compare signatures with a constant-time function.
- Store the request ID in Redis with an atomic `SET NX EX`; reject duplicates.
- Fail closed if the replay store is unavailable. This endpoint must not inherit any fail-open behavior used by lower-risk rate limiting.
- Support current and next key IDs during rotation, with explicit activation and expiry timestamps.
- Return one generic authentication response; never reveal whether the workload, key, timestamp, request ID, or signature was wrong.

### 4.2 Opaque source locator and grant binding

Add an opaque `proxy_locator_id` to `FileSourceMeta` and stop placing the numeric row ID in `remote://ds:<token>` VDB references.

Recommended schema changes:

```text
file_source_meta.proxy_locator_id UUID NOT NULL UNIQUE
file_source_meta.proxy_grant_version INTEGER NOT NULL DEFAULT 1
file_source_meta.proxy_locator_rotated_at TIMESTAMPTZ

file_proxy_workload
  id UUID PRIMARY KEY
  tenant_id UUID NOT NULL
  tenant_data_plane_id UUID NOT NULL
  workload_type VARCHAR NOT NULL
  key_id VARCHAR NOT NULL
  secret_ref VARCHAR NOT NULL
  active BOOLEAN NOT NULL
  not_before TIMESTAMPTZ
  expires_at TIMESTAMPTZ
  created_at / updated_at TIMESTAMPTZ
```

If one data plane can host multiple independently authorized VDBs, add a `file_proxy_grant` table binding `workload_id`, `file_source_meta_id`, `project_id`, deployed VDB identity, and `proxy_grant_version`. Otherwise, prove and document the equivalent binding from the authoritative VDB deployment records.

Generate locators with a cryptographically secure UUID or at least 128 random bits. Rotate the locator and increment the grant version when a source is archived, replaced, moved between projects, or has a material visibility/ownership change. Old locators must stop working immediately.

### 4.3 Authorization order

The proxy handler must perform checks in this order:

1. Verify signed workload identity and replay protection.
2. Resolve the active tenant and data-plane binding from the workload record.
3. Resolve `FileSourceMeta` using `proxy_locator_id`, workload `tenant_id`, and `archived = false` in the same query.
4. Validate the source's project and deployed VDB grant, including grant version.
5. Parse the source parameters using a typed schema; reject unknown source types or malformed parameters.
6. For `network_path`, load `NetworkFileConnection` with the connection ID, workload tenant, `enabled = true`, and `archived = false` in the same query. Explicitly verify all tenant IDs agree.
7. Perform the URL or SMB acquisition through the existing hardened service.
8. Apply content and conversion limits before returning a response.

Use a constant external `404` or `403` policy for missing and unauthorized locators so callers cannot enumerate cross-tenant metadata. Record the detailed internal reason only in a redacted security event.

### 4.4 Network and reverse-proxy boundary

- Remove `/internal/file-proxy` from `_ANONYMOUS_PATH_PREFIXES`.
- Register dedicated workload-auth middleware/dependencies for this exact route. Do not weaken the normal user-auth middleware globally.
- Add `TRUSTED_PROXY_CIDRS` specifically for known reverse proxies. Honor forwarding headers only when `request.client.host` is inside that set; otherwise use the socket peer and ignore forwarding headers.
- Reject malformed or multi-hop forwarding chains that do not match the configured proxy topology.
- Add an exact public-ingress denial for `/internal/file-proxy` in Nginx/ALB configuration.
- Restrict the application listener/security group/network policy so only the expected Teiid workload path can reach it.
- Remove `FILE_IMPORT_NETWORK_SOURCE_CIDRS` as an authorization bypass. During migration it may emit diagnostics, but it must not grant access once enforcement is enabled.
- Retain source-IP and expected-network checks only as secondary anomaly signals or a defense-in-depth denial.

### 4.5 URL, redirect, DNS, and content safety

Keep `safe_remote_fetch` as the single URL retrieval implementation. Extend it only where tests show a gap:

- Validate the scheme, canonical hostname, port, resolved IP, and domain allowlist before the initial connection and after every redirect.
- Resolve all A/AAAA results and reject the request if any result is disallowed.
- Prevent DNS rebinding by connecting to a validated address while preserving the correct Host header and TLS SNI/certificate validation; alternatively revalidate the actual connected peer address.
- Block cloud metadata endpoints, loopback, link-local, multicast, unspecified, and unapproved private ranges for IPv4 and IPv6.
- Permit private destinations only through an explicit tenant-scoped destination policy; never through a global caller-CIDR bypass.
- Keep strict redirect, connect, read, total-time, and downloaded-byte limits.
- Reject mismatched or misleading content lengths; count streamed bytes independently.

For Excel/CSV handling:

- Use a bounded spooled temporary file or streaming parser rather than keeping both input and output entirely in memory.
- Set independent limits for compressed bytes, expanded bytes, workbook sheets, rows, columns, cells, and converted CSV bytes.
- Abort when any limit is crossed.
- On conversion failure, return a safe error. Do not fall back to returning the original workbook bytes under a CSV content type.

### 4.6 Audit and observability

Emit a structured event for every allow and deny with:

- request ID and trace ID;
- workload, tenant, data-plane, project, VDB, and opaque source identifiers;
- grant version and key ID;
- decision and stable reason code;
- source type, byte counts, latency, and redirect count;
- socket-peer classification and whether a trusted forwarding header was used.

Hash or tokenize identifiers where operationally appropriate. Never log signatures, secret references, credentials, raw network paths, raw URLs, query strings containing locators, or file contents. Add alerts for repeated signature failures, replay attempts, cross-tenant mismatches, unusual volume, and blocked address classes.

## 5. Implementation work breakdown

### Phase A — Schema and configuration

1. Add an Alembic migration after the current migration head for the locator, grant version, workload identity, and optional explicit grant table.
2. Backfill an opaque locator for every active file source using application-generated secure values.
3. Add ORM models, uniqueness constraints, tenant/data-plane indexes, activation windows, and safe serialization.
4. Add validated configuration for trusted proxies, signature skew, replay TTL, enforcement mode, conversion limits, and tenant-scoped private destination policy.
5. Add startup validation that rejects production enforcement with missing replay storage, workload secrets, or public-route denial.

### Phase B — Authentication and authorization

1. Create `file_proxy_auth.py` with canonicalization, HMAC verification, key rotation, clock validation, atomic replay consumption, and redacted failure codes.
2. Refactor `internal_file_proxy.py` to accept only the opaque locator and signed workload headers.
3. Move tenant, project, VDB, source, and connection checks into a single authorization service with typed results.
4. Remove the route from the anonymous-prefix list and install the dedicated middleware/dependency.
5. Apply per-workload concurrency and request-rate limits without using them as a substitute for authentication.

### Phase C — Teiid adapter and provisioning

1. Extend the Java remote-file adapter to construct the canonical payload and signed headers.
2. Load workload ID, key ID, and secret from injected secret properties; redact them from `toString`, exceptions, and diagnostics.
3. Change VDB generation to emit the opaque source locator.
4. Update tenant data-plane provisioning to create/rotate the workload identity and inject its secret.
5. Update WildFly standalone configuration and deployment documentation; remove unused static `ProxyApiKey` behavior after migration.

### Phase D — Retrieval and response safety

1. Preserve all `safe_remote_fetch` checks and add connected-peer/DNS-rebinding tests.
2. Keep SMB access through `smb_gateway.py`; require the already-authorized tenant and connection object.
3. Introduce bounded spooling/streaming and explicit expanded-content and tabular conversion limits.
4. Replace raw-content conversion fallback with a fail-closed error.
5. Ensure temporary files are created in a private directory and deleted on success, error, cancellation, and process restart cleanup.

### Phase E — Edge policy and operations

1. Add the exact public-ingress denial.
2. Update security-group/network-policy rules for the Teiid-to-proxy path.
3. Add dashboards and alerts for the structured proxy events.
4. Add a key-rotation runbook, clock-skew monitoring, and emergency workload-revocation procedure.
5. Update the VPN network-repository operations guide to state that IP allowlisting is defense in depth only.

## 6. Expected file changes

| Area | Files |
|---|---|
| Route and middleware | `platform-api/app/routes/internal_file_proxy.py`, `platform-api/app/auth/middleware.py` |
| Auth service | new `platform-api/app/services/file_proxy_auth.py` and authorization helper |
| Fetch/SMB safety | `platform-api/app/services/safe_remote_fetch.py`, `platform-api/app/services/smb_gateway.py` |
| Configuration | `platform-api/app/config.py`, environment templates and deployment validation |
| Models/migration | `platform-api/app/models/file_source_meta.py`, `platform-api/app/models/network_file_connection.py`, new workload/grant model, new Alembic revision |
| VDB lifecycle | `platform-api/app/services/vdb_management.py` and the file-ingestion/VDB finalization path |
| Java adapter | `wildfly/remote-file-connector-src/.../RemoteVirtualFile.java`, `RemoteFileManagedConnectionFactory.java`, associated tests/build |
| Provisioning | tenant data-plane compose/provisioning and managed-secret integration |
| Edge controls | Nginx/application ingress and infrastructure security-group/network-policy definitions |
| Tests | new proxy security tests plus Java adapter and end-to-end data-plane tests |
| Documentation | VPN repository setup, secret rotation, troubleshooting, and rollback runbooks |

Paths must be confirmed against the repository at implementation time; the migration revision must be generated from the then-current Alembic head.

## 7. Test plan

### Unit and route tests

- Missing, malformed, wrong-key, wrong-workload, expired, future, and tampered signatures are rejected.
- Reusing a request ID is rejected, including concurrent replay attempts.
- Replay-store failure rejects the request.
- Canonical query ordering and encoding are identical in Python and Java implementations.
- A forged `X-Forwarded-For` from an untrusted socket does not affect the peer decision.
- A trusted proxy with a valid configured chain is handled correctly.
- A workload cannot fetch a source from another tenant or another project/VDB.
- A source cannot reference a network connection from another tenant.
- Archived/disabled sources and connections are rejected.
- Old locators and grant versions fail immediately after rotation.
- Numeric file-source IDs are not accepted.
- Errors do not disclose whether a locator exists.

### Retrieval safety tests

- Redirect to loopback, link-local, metadata, unapproved private, IPv6-local, or disallowed domain is rejected.
- DNS response changes and a connected peer outside the validated set are rejected.
- Redirect count, connect/read/total time, compressed size, expanded size, workbook, cell, and converted-output limits are enforced.
- Conversion failures do not return original bytes.
- SMB traversal, wildcard, host/share/root, signing, and encryption requirements remain enforced.

### Integration tests

- The built Java adapter and API agree on canonical signatures.
- A provisioned tenant data plane can fetch only its deployed, authorized source.
- Two tenants using overlapping Docker address ranges cannot fetch each other's sources.
- The public ingress cannot reach the route, while the intended internal path can.
- Key rotation supports the bounded overlap, then rejects the old key.
- Locator rotation updates/redeploys the VDB and revokes the previous locator.

## 8. Deployment and migration sequence

1. Merge the schema/auth changes behind `FILE_PROXY_AUTH_MODE=audit`; deploy the API migration and verify backfilled locators.
2. Provision workload identities and managed-secret references for a canary data plane.
3. Build and deploy the signed-request Java adapter and VDB locator changes to the canary.
4. Compare audit decisions with expected tenant/project/VDB bindings; investigate every mismatch.
5. Enable `enforce` for the canary and run the full integration suite, including replay, cross-tenant, public-ingress, and key-rotation tests.
6. Roll out the adapter and secret to all data planes, then enable enforcement tenant by tenant.
7. After all active workloads use signed requests, remove legacy numeric-ID and IP-only compatibility code, the global caller-CIDR bypass, and the optional static API-key path.
8. Verify metrics show no legacy requests for a full operating window before deleting legacy configuration.

Compatibility mode must be time-bounded and observable. It must never be enabled for the public ingress.

## 9. Rollback

- Before enforcement, roll back the canary adapter or disable that tenant's live remote-file source while correcting configuration.
- After enforcement, prefer disabling affected live sources or rolling forward. Do not restore public reachability, anonymous routing, numeric-ID authorization, or IP-only trust.
- Retain the prior workload key only for the defined rotation overlap; revoke it after rollback is complete.
- A database rollback must not remove locator/workload records while any deployed VDB references them.

## 10. Acceptance criteria

- [ ] The route is absent from the generic anonymous allowlist and denied at public ingress.
- [ ] Every successful request has a verified tenant-bound workload signature and a unique, consumed request ID.
- [ ] Tenant, project, VDB, source, grant version, and connection checks are enforced server-side.
- [ ] VDBs use opaque rotating locators; numeric IDs no longer work at the proxy boundary.
- [ ] Forwarding headers are trusted only from configured immediate proxies.
- [ ] URL/redirect/DNS/SMB protections pass adversarial tests.
- [ ] Download, expansion, parse, and conversion limits fail closed.
- [ ] Secrets and sensitive paths/URLs never appear in logs or configuration artifacts.
- [ ] Two-tenant tests prove that overlapping networks and guessed locators cannot cross the boundary.
- [ ] Key rotation, workload revocation, monitoring, deployment, and rollback runbooks are exercised.

TS-ISO-010 must remain open until enforcement is enabled for all supported data-plane modes and the production-like cross-tenant test evidence is attached to the finding.
