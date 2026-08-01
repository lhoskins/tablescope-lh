# TableScope Devin-Ready Plan: Data Source Builder URL and UNC/SMB File Imports (Validated)

## Validation summary

Checked against `origin/devin/r-echarts-e2e-validation` (HEAD `a1969ff`).
Like the 2FA plan validated earlier in this engagement, this one is
**unusually accurate** — every specific file/behavior claim in "Current
implementation findings" checks out exactly. This is a validated,
lightly-corrected, file/line-grounded version. The objective, architecture,
data model, phased delivery, and acceptance criteria are preserved
unchanged; corrections below add precision and close a couple of gaps the
source plan didn't have visibility into.

### Confirmed exactly as claimed

- `web-ui/app/data-source-builder/page.tsx` renders `DataSourceBuilderWorkspace`.
- `workspace.tsx` renders `<AiUploadDropzone />` immediately above
  `<ConnectedDatabases />` (confirmed both import lines and render order).
- `ai-upload-dropzone.tsx` confirmed exactly: `MAX_BYTES = 100 * 1024 *
  1024`; `ALLOWED = ["csv", "xlsx", "xls"]`; calls `analyzeFile(file)`;
  builds a `SessionSource` with `fileMetadata.uploadSessionId:
  preview.upload_session_id`; the file input is
  `accept=".csv,.xlsx,.xls"`.
- `platform-api/app/routes/file_analysis.py:30`:
  `_upload_sessions: dict[str, dict[str, Any]] = {}` — confirmed
  module-level, process-local, in-memory. `/upload/finalize`
  (`file_analysis.py:175`) pops from it via `req.upload_session_id`
  (line 188). Router prefix is `/data-sources`
  (`APIRouter(prefix="/data-sources", ...)`, `file_analysis.py:26`), so
  the full path is exactly `/api/data-sources/upload/finalize` as the
  plan states.
- `platform-api/app/services/crypto.py`: `encrypt_secret`/`decrypt_secret`
  exist exactly as described, backed by Fernet, reading
  `settings.tablescope_secret_key`. **The plan's caution is validated by
  the module's own docstring**, which explicitly warns: "values encrypted
  with a derived key become unreadable if the JWT secret changes, so
  production should always set an explicit key." Reuse this module
  as-is — no changes needed to it.
- `web-ui/lib/stores/data-source-builder-store.ts` already has
  `sourceType` and `isFileUpload` fields on `SessionSource`, confirming it
  already distinguishes file/database/SaaS sources as claimed.
- All nine files/paths listed in "Expected files to inspect or change"
  exist (verified each individually — none hallucinated).
- RBAC role vocabulary matches the real `Role` enum
  (`platform-api/app/auth/rbac.py:17-24`:
  `ROOT_ADMIN, TENANT_ADMIN, ADMIN, DB_ADMIN, EDITOR, VIEWER`) — the
  plan's "Tenant Admin/DB Admin" and "Root/super users" phrasing maps
  cleanly onto `Role.TENANT_ADMIN`/`Role.DB_ADMIN` and `Role.ROOT_ADMIN`.
- No competing work exists: `git branch -a` has no branch touching
  SMB/UNC/network-file-connection/URL-import code, and no branch (checked
  every remote branch, not just `devin/*`) has staked a competing
  migration revision number.

### Amendment 1 — the reference_library_bulk.py SSRF gap is worse than "not fully sufficient," and it's live in production today

The plan correctly identifies that the existing Reference Library URL
fetcher needs hardening, but undersells the severity. Read in full,
`platform-api/app/services/reference_library_bulk.py:87-91`:

```python
def _is_valid_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except ValueError:
        return False
```

This is the **entire** validation this feature applies to a user-supplied
URL before fetching it. There is no DNS resolution check, no private/
loopback/link-local/reserved/cloud-metadata IP blocking, no redirect-
target revalidation, no DNS-rebinding defense, and plain `http://` is
accepted (contradicting this plan's own "HTTPS only by default"
requirement for the *new* fetcher). Today, any authorized Industry-tier
bulk-import user can put `http://169.254.169.254/latest/meta-data/`,
`http://localhost:5432`, or an internal service hostname directly in a
CSV `source_url` column and the batch importer (`run_batch`,
`reference_library_bulk.py:204`) will fetch it with zero blocking.

**This means Section 7.3's closing instruction — "Apply the hardened
fetcher to Reference Library URL imports as well so the older path does
not remain an SSRF exception" — is not an optional cleanup step, it's
closing a live vulnerability that exists independently of whether this
plan ships.** If this plan is phased (per Section 15) and Phase 1 doesn't
happen soon, consider raising the Reference Library fetcher hardening as
its own fast-follow security fix rather than waiting for the full Data
Source Builder feature to land — the fix (swap `_is_valid_url` and the
raw `client.stream("GET", url)` call for the new hardened fetcher) is a
small, isolated change once the fetcher exists, and there's no reason to
leave a confirmed-unprotected SSRF path live for the multi-phase duration
of this plan.

### Amendment 2 — malware scanning is genuinely new infrastructure, not a config toggle

Confirmed: zero existing malware/virus-scanning capability anywhere in
`platform-api/app/` (no ClamAV client, no scanning service, no
`FILE_IMPORT_MALWARE_SCAN_ENABLED`-shaped flag of any kind exists today).
Section 11 lists this as one bullet among many environment variables,
which understates it — standing up ClamAV (or an equivalent) with a
maintained signature feed, a scanning client library, a failure-mode
policy (block vs. quarantine-and-alert on scanner-unavailable), and an
operational runbook is real infrastructure work with its own testing and
deployment surface, comparable in weight to the SMB gateway itself.
Recommendation: treat "malware scanning implemented and enforced" as an
explicit, separately-tracked line item within Phase 1 (Section 15 already
lists Phase 1 as including "security tests and deployment controls" —
make malware-scanner readiness one of Phase 1's named exit criteria, not
an assumed-available dependency Phase 2/3 can build on top of).

### Amendment 3 — concrete migration revision, verified clean

Section 6's "Determine the next migration revision with alembic heads; do
not assume a fixed revision number" is good practice and should stay in
the plan verbatim (re-verify at merge time — this is a fast-moving repo).
At validation time: single head, confirmed via
`alembic/versions/0078_project_action_deleted_at.py` — **the next
revision is `0079`**, and no branch anywhere in the remote (checked all
153, not just `devin/*`) currently claims `0079`, `0080`, or `0081`. Safe
to proceed; still re-run `alembic heads` immediately before opening the
PR per the source plan's own instruction, in case something else lands
first.

### One thing to double-check that this validation could not confirm

The plan cites "PR #113 merge commit `25ae89d31d13236c0454a721bf056972a3c7cadc`"
as part of the deployed lineage. This session's git history inspection
didn't independently verify that specific SHA against PR #113 (no GitHub
API access was exercised for this validation pass) — Devin's own
"Confirm the exact production deployment SHA before coding" step (already
required by Section 2) will naturally re-verify this; no action needed
beyond following that existing instruction, just noting it wasn't
re-checked here so it isn't reported as independently confirmed.

---

## Everything below is the original plan, preserved as validated

Sections 1 (Objective), 2 (Repository and branch instructions — with
Amendment 3's concrete `0079` filled in), 4 (Product behavior and scope),
5 (Target architecture), 6 (Data model and migration), 7 (Backend
implementation, with Amendments 1–2 folded in as noted), 8 (API contract),
9 (Frontend implementation), 10 (RBAC, tenant isolation, auditing), 11
(Configuration and deployment, with Amendment 2's scoping note), 12
(Expected files to inspect or change), 13 (Testing requirements), 14
(Validation commands), 15 (Phased delivery, with the Amendment 1
fast-follow recommendation optionally pulled forward), 16 (Acceptance
criteria), 17 (Production smoke test), 18 (Rollback), and 19 (Devin
completion report) are all accurate as written and should be implemented
exactly as specified in the source document. No corrections apply to
these sections beyond the three amendments above.

## Branch / PR

Branch: `devin/data-source-builder-url-unc-imports`, based on
`origin/devin/r-echarts-e2e-validation` (HEAD `a1969ff` at validation
time — rebase onto the current head before opening the PR, per the source
plan's own instruction). This doc is the only change on the branch; Devin
implements per the source plan plus the three amendments above.
