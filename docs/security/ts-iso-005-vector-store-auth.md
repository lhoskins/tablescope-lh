# TS-ISO-005: Vector-store authorization

## Status

Implemented as a fail-closed authorization contract between `platform-api`,
`ai-server`, and Qdrant. This change does not alter embedding generation,
ranking, result limits, or prompt behavior.

## Security design

Vector retrieval no longer treats a request `scope` string as authorization.
The only accepted retrieval scope is `authorized_project`, which means:

1. `platform-api` authorizes the user as project owner or active member.
2. `ai-server` calls the HMAC-authenticated `/api/ai/permissions` endpoint.
3. `platform-api` returns versioned `vector_access` claims derived from current
   database state.
4. `ai-server` validates that claim tenant, project, and principal exactly
   match the signed request envelope.
5. Qdrant receives mandatory tenant, project, and document-visibility filters.

The project-document predicate is:

- `tenant_id = authorized tenant`; and
- `project_id = authorized project`; and
- either `visibility = shared_project`; or
- a private visibility plus `owner_user_id = authorized principal`.

Unknown and missing visibility values match no branch. Legacy `personal` and
`private_project` labels remain owner-gated until those vectors are re-indexed.

Reference-library project-tier vectors now require both `tenant_id` and
`project_id`. Company-tier vectors require the tenant; industry-tier vectors
remain globally governed reference content.

## Lockout and compatibility controls

- Owners and active members retain shared-project retrieval.
- Each user retains retrieval of their own private documents.
- Removed/inactive members are denied by the live permission callback before
  Qdrant is queried.
- The permission response's project-document metadata is filtered with the
  same shared-or-owned-private rule.
- Existing vectors with an unsupported or missing visibility are deliberately
  hidden. Re-index them after correcting the source asset visibility; do not
  add a permissive compatibility fallback.
- Platform callers may still send the legacy UI value `project` to
  `platform-api`; it is never forwarded as authorization. The platform sends
  only `authorized_project` to `ai-server`.

## Deployment order

This is a coordinated contract change. Deploy in a short maintenance window:

1. Record the current `platform-api` and `ai-server` image digests.
2. Deploy **ai-server first**. During the brief interval before step 3, old
   platform calls using `project` fail closed with `422`; they cannot broaden
   retrieval.
3. Deploy `platform-api` immediately afterward. It emits
   `authorized_project` and returns `vector_access` claims.
4. Restart workers that import either service's request schemas.
5. Run the post-deploy checks below.

Do not deploy `platform-api` first: an old AI service does not understand the
new scope and could treat it as an unfiltered legacy branch.

## Post-deploy validation

1. Owner asks a document question and receives shared plus own-private content.
2. Active member asks the same question and receives shared plus their own
   private content, never the owner's private content.
3. Deactivate that member, then retry without waiting for token expiry; expect
   `403` and no vector search.
4. Send `scope=private_project`, `scope=tenant`, and a random scope directly to
   the AI schema; expect `422`.
5. Verify project-tier reference results never cross tenant even when numeric
   project IDs collide in a restored/test dataset.
6. Audit Qdrant payloads for missing or unsupported `visibility`; re-index
   affected project documents from their authoritative `ProjectAsset` rows.

## Rollback

Roll back both services together to their recorded image digests. Roll back
`platform-api` first, then `ai-server`, so the old platform never sends the new
scope to an old AI service. A rollback restores the old behavior and therefore
reopens TS-ISO-005; use only to restore service while preparing a corrected
forward deployment.

## Automated coverage

- active owner/member and removed-member permission tests;
- platform-minted claim contents;
- private document metadata exclusion;
- signed-envelope/claim mismatch rejection;
- forged private-owner claim rejection;
- unknown/legacy scope rejection;
- real in-memory Qdrant cross-user, cross-project, and missing-visibility tests;
- company/project reference tenant isolation.
