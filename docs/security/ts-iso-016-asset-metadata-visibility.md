# TS-ISO-016: Asset Metadata Visibility — Standalone Implementation Plan

**Status:** Open — raw-content controls and partial derived-data filtering exist; implementation required

**Severity:** Medium

**Owner:** Platform / Knowledge Graph / AI / Search / Security

**Target branch:** `UX-design-03`

**Plan branch:** `codex/ts-iso-016-asset-metadata-visibility`

**Depends on:** Existing `ProjectAsset` visibility model and TS-ISO-005 vector-store authorization
**Related findings:** TS-ISO-004 (PostgreSQL RLS), TS-ISO-011 (cross-store deletion), TS-ISO-014 (service identity scoping)

## 1. Objective

Apply one authoritative asset-visibility decision to content, metadata, search, AI context, knowledge-graph derivatives, document families, activity, counts, previews, and every other representation of a project asset.

An ordinary project member who cannot read a private asset must not learn that asset's existence, filename, title, description, summary, tags, KPIs, owner, size, hash, processing status, error, graph relationships, family membership, preview, chunk, embedding, or derived aggregate. Direct access to a hidden asset must return the same not-found response as an unknown ID. Any approved tenant-administrator override must remain explicit, MFA-governed where required, audited, and consistent across every surface.

## 2. Current-state finding

The repository has useful object-level controls, but visibility is enforced at selected content paths rather than as a system-wide data policy:

| Area | Current behavior | Remaining gap |
|---|---|---|
| Asset content/preview | `project_assets._get_readable_asset()` combines project access with `_check_asset_read_access()` | This is the correct local behavior, but it is not reused by all asset routes and services |
| Asset list | `GET /projects/{project_id}/assets` returns every project asset as the full `ProjectAssetRead` model | A member can enumerate private titles, filenames, summaries, AI metadata, hashes, sizes, status, and errors |
| Asset detail | `GET /projects/{project_id}/assets/{asset_id}` checks tenant/project but not asset visibility | Knowing or guessing an ID reveals the private asset's complete metadata |
| AI profile | `GET .../{asset_id}/ai/profile` omits the asset read check | AI summary, metadata, and processing state remain visible |
| Asset mutations | Delete and AI-processing routes check project role but not ownership/private-object policy | An editor may modify or destroy another user's private asset |
| AI metadata API | Tag/KPI reads and mutations filter tenant/project/source identifiers but do not authorize the source object consistently | Tags, suggestions, KPIs, and mutations can reveal or cross the private-asset boundary |
| Project metadata/activity | Catalog and activity queries select all project assets and expose names, state, relationships, and actor-derived events | Hidden assets affect viewer-facing lists, timelines, counts, and relationships |
| Project aggregates | Document aggregation returns asset name, summary, owner, and project | A private asset is visible outside its direct asset route |
| AI context | Home/schema and workspace context load project assets without applying the object policy | A model can receive private titles, summaries, or metadata for an unauthorized viewer |
| AI permission context | Project documents are filtered shared-or-owned-private for vector claims | This is a strong foundation, but administrator semantics and graph-derived context must use the same central rule |
| Qdrant vector search | TS-ISO-005 requires tenant/project plus shared-or-owned-private payload filters | Legacy/missing labels fail closed correctly; visibility generation and synchronized reindexing are still needed |
| Lexical grounding | PostgreSQL FTS loads `ai_document_chunks` by tenant/project/query without joining document visibility and owner | Private chunk content may enter grounded evidence even when vector search is filtered |
| Knowledge graph | `knowledge_graph.visibility` filters private document and derived nodes for several graph views | Some loaders and consumers bypass it; missing/unknown sensitivity can default too broadly |
| Document families | Family member and relationship queries are not viewer-scoped, and document nodes can be written as `shared_project` regardless of source asset visibility | A private document's name, summary, family membership, and derived entities can leak |

### Root cause

Visibility is represented as a field on `ProjectAsset`, while readers independently decide whether and how to apply it. Strong checks were added to raw content, previews, graph views, and vector search, but metadata DTOs, direct SQL, aggregates, AI context builders, and derived records do not all depend on one query-time policy. The system therefore protects some bytes while revealing the same asset through another representation.

## 3. Scope and non-goals

This plan covers:

- authoritative read, write, manage, and administrative asset policy;
- viewer-filtered list/detail/profile, metadata, activity, counts, search, AI, graph, and family paths;
- visibility inheritance and lineage for chunks, documents, tags, KPIs, vectors, nodes, edges, families, summaries, and caches;
- visibility transitions, invalidation, reindexing, deletion, and background-worker revalidation;
- response-field minimization, enumeration resistance, audit, tests, rollout, and rollback.

This plan does not redesign project membership, invent a new access-group system, or weaken tenant isolation. If `access_group_id` is not backed by an authoritative active-membership policy at implementation time, group visibility must fail closed rather than be inferred. Storage relocation and durable cross-store erasure remain TS-ISO-011 responsibilities.

## 4. Visibility invariants

1. `ProjectAsset` is the authoritative source for an asset's tenant, project, owner, visibility, status, and visibility generation.
2. Content and metadata use the same object authorization decision; metadata is never considered less sensitive than content by default.
3. An ordinary user can read a private asset only when they are its canonical owner and an active authorized project member.
4. Any tenant-administrator override is explicit, current, audited, and applied consistently; no route-specific accidental override is allowed.
5. Hidden assets are removed at query time from lists, counts, activity, relationships, suggestions, AI context, search, and graph traversal.
6. Direct requests for hidden and nonexistent asset IDs return the same safe `404` response and comparable behavior.
7. Every derived record carries authoritative source lineage and inherits at least the strictest visibility of all source evidence.
8. A relationship or aggregate is visible only if every evidence item necessary to infer the hidden fact is visible to the viewer.
9. Missing, malformed, conflicting, or unknown visibility/owner/lineage data fails closed.
10. Shared-to-private changes stop new reads immediately before asynchronous search/vector/graph cleanup begins.
11. Background workers re-read current source policy and generation before processing and before publishing a derivative.
12. Caches, pagination totals, facets, timestamps, errors, and timing do not reintroduce hidden-asset existence disclosure.

## 5. Target design

### 5.1 Central asset access policy

Create one `AssetAccessPolicy` service used by routes, services, workers, and query builders. Its public operations should include equivalents of:

```text
readable_asset_predicate(viewer, project_id)
read_asset_or_404(asset_id, project_id, viewer)
require_asset_write(asset, viewer)
require_asset_manage(asset, viewer)
can_admin_override(viewer, action)
```

The read predicate is applied in SQL, not after loading every project asset:

```text
asset.tenant_id = viewer.tenant_id
AND asset.project_id = authorized project
AND viewer has current project access
AND (
  asset.visibility = 'shared_project'
  OR (asset.visibility = 'private' AND asset.owner_user_id = viewer.user_id)
  OR approved_admin_override(viewer)
)
```

Map current legacy labels through one canonical normalizer. Missing or unknown values match no allow branch. Do not silently map them to `shared_project`. If group visibility is implemented later, add an exact active-group-membership predicate and tests before enabling the label.

Policy methods must return a typed decision/reason for audit while public errors remain generic. Do not log filenames, titles, summaries, tags, query text, storage keys, graph labels, or content excerpts.

### 5.2 Read, write, and manage semantics

Define operations rather than reusing the read rule ambiguously:

| Operation | Ordinary owner | Other project member | Approved tenant admin |
|---|---:|---:|---:|
| Read shared asset | Yes | Yes | Yes |
| Read private asset | Yes | No | Explicit documented override only |
| Edit shared metadata | Existing editor/owner product policy | Existing editor product policy | Existing admin product policy |
| Edit private metadata | Owner with required project role | No | Explicit documented override only |
| Process/reindex private asset | Owner or authorized system job bound to asset | No | Explicit documented override only |
| Delete private asset | Owner under existing delete policy | No | Explicit documented override only |
| Change visibility | Owner with required role | No | Explicit documented override only |

The final administrator behavior must preserve the currently approved product policy or be changed through a separate security/product decision. It must not differ between content, metadata, AI, graph, search, and family surfaces. High-risk administrative reads or mutations should require the existing human MFA/step-up controls and immutable audit evidence.

### 5.3 Response minimization

Replace the full persistence model response with purpose-specific DTOs:

- viewer-safe list item;
- authorized detail;
- owner/admin operational detail;
- internal worker snapshot.

Do not expose `storage_location`, managed-secret references, internal AI errors, raw stack/error messages, object-store keys, or internal processing payloads through user APIs. Treat `file_hash` as a content fingerprint and return it only to an explicitly authorized product flow. Return owner identity, original filename, size, AI metadata, and processing details only where the UI actually requires them and the same asset policy permits them.

List queries must paginate after applying the visibility predicate. Totals, facets, sort positions, last-updated values, and empty-state behavior are computed from the viewer's authorized rows only.

### 5.4 Derived-data lineage and schema constraints

Add or standardize the following fields on asset-derived stores where absent:

```text
source_asset_id BIGINT NOT NULL
source_tenant_id BIGINT NOT NULL
source_project_id BIGINT NOT NULL
owner_user_id BIGINT NULL
visibility VARCHAR NOT NULL
visibility_generation INTEGER NOT NULL
source_version / processing_generation INTEGER NOT NULL
```

Add allowed-value checks, indexes supporting tenant/project/visibility/owner queries, and a rule that private records require a canonical owner. Migrate derived records from their authoritative `ProjectAsset`; quarantine or remove records whose source, owner, or visibility cannot be proven. Do not assign unknown legacy records to shared visibility.

For multi-source derivatives:

- node/card/summary sensitivity is the strictest contributing source;
- an edge is no more visible than either endpoint or its evidence;
- a family name, count, and relationship list is computed from the viewer-visible member set;
- a shared result cannot quote, name, summarize, count, or infer a hidden private source;
- provenance retains source asset IDs and generations so authorization can be recomputed.

Avoid duplicating policy logic in every schema. Persist denormalized visibility for search efficiency, but validate it against `ProjectAsset` on writes, changes, and sensitive reads.

### 5.5 API and product surfaces

Apply the central predicate/guard to:

- project asset list, detail, AI profile, content, preview, processing, visibility update, metadata update, and delete;
- tag/KPI suggestions and accepted values, including every accept/reject/remove mutation;
- project metadata catalogs, activity timelines, document lists, counts, facets, coverage, deltas, summaries, and recommendations;
- workspace active-document context and home/schema intelligence;
- AI permission responses, prompt context, citations, grounded passages, and saved AI outputs;
- document-family list/detail/member/relationship and graph endpoints;
- reference suggestions or task generation that use project asset type/title/content;
- export, notification, audit-display, and administrative surfaces discovered by the inventory.

Every source-type API must resolve the concrete source object before reading or mutating metadata. It may not authorize a caller using only caller-supplied `source_type`, `source_id`, and `project_id`. Suggestion IDs must be verified to belong to the same authorized source and project before state change.

### 5.6 Search, vector, and lexical grounding

Retain TS-ISO-005's Qdrant predicate:

```text
tenant_id = viewer tenant
AND project_id = authorized project
AND (visibility = shared_project OR owner_user_id = viewer user)
```

Extend vector payloads with source asset ID and visibility generation. On each query, require supported fields and reject missing/unknown labels. Reindex or delete legacy vectors; never add a compatibility branch that broadens results.

Change PostgreSQL lexical grounding to join `ai_document_chunks` to the authoritative `ai_documents`/`ProjectAsset` lineage and apply the same shared-or-owned-private predicate before ranking. Tenant/project-only chunk filtering is insufficient. Grounding citations and snippets must be built only from the filtered rows.

AI permission claims, vector filters, lexical filters, and saved prompt context must be generated from the same policy inputs. A model or AI service is not the viewer and must not receive a superset of the initiating user's assets.

### 5.7 Knowledge graph and document families

Make the current `knowledge_graph.visibility` policy consume the central asset rule or a shared typed policy snapshot rather than maintain a divergent vocabulary. Unknown/missing sensitivity and missing provenance fail closed.

- Filter raw stored nodes/edges before ranking or adding them to AI grounding context.
- Preserve private asset visibility when creating project document nodes; never hard-code `shared_project`.
- Propagate owner and visibility generation to chunks, document nodes, derived nodes, edges, cards, gaps, actions, traces, and family membership.
- Pass the viewer/policy scope into family member and relationship queries.
- Derive family counts and summaries only from visible members. A family with no visible evidence is absent, not an empty clue that hidden members exist.
- If an entity/KPI/tag is supported by both shared and private evidence, expose only the portion and relationships supported by visible evidence.

Stored structural graph loaders may read more data for an authorized background computation only inside a scoped worker, but no user-serving or AI-serving consumer may receive the unfiltered graph. Prefer early filtering to reduce accidental downstream exposure.

### 5.8 Visibility transitions and deletion

Add a monotonic `visibility_generation` to `ProjectAsset`. A visibility update must:

1. lock and authorize the asset;
2. validate the requested label and owner/group requirements;
3. update the authoritative row and increment its generation;
4. invalidate user-facing caches and mark old search/vector/graph/family derivatives unavailable in the same transaction or through a transactional outbox;
5. enqueue generation-bound recomputation/deletion;
6. publish replacement derivatives only if the source generation still matches.

For `shared_project` to `private`, deny non-owner reads immediately from the authoritative policy; stale derivatives with an old generation match no query. Asynchronous cleanup removes them afterward. For `private` to `shared_project`, do not expose old derivatives automatically; validate/rebuild them under the new generation before publication.

Deletion uses TS-ISO-011's manifest/tombstone workflow and the same source lineage to remove metadata, chunks, vectors, graph evidence, family membership, caches, previews, and object content. A soft-deleted/quarantined asset is not readable while cleanup runs.

### 5.9 Worker, cache, and event behavior

- Queue payloads contain asset ID, tenant/project, requested operation, and expected visibility/source generation, not trusted metadata snapshots.
- Workers load the authoritative asset under tenant/RLS scope and validate authorization/generation before processing and again before publishing.
- Cache keys include tenant, project, viewer or visibility class, policy version, and source generation.
- Shared caches may contain only shared data. Private responses use owner-specific cache partitions.
- Visibility change, ownership change, membership removal, project removal, tenant quarantine, and deletion invalidate affected caches/derived authorization.
- Notifications, event streams, websocket payloads, background progress, and error messages must not reveal a hidden asset to another member.

## 6. Implementation work breakdown

### Phase A — Inventory and central policy

1. Inventory every `ProjectAsset`, `ai_documents`, chunk, AI metadata, vector, graph, family, activity, aggregate, cache, and export reader/writer.
2. Document the approved administrator override and existing write/delete product policy.
3. Implement `AssetAccessPolicy`, canonical visibility vocabulary, SQL predicate, operation guards, and safe `404` behavior.
4. Replace route-local visibility decisions with the central service while preserving correctly authorized behavior.
5. Add static/query review checks for direct asset reads that lack an explicit policy scope.

### Phase B — Direct API and metadata closure

1. Filter project asset lists at query time and use viewer-safe DTOs.
2. Apply `read_asset_or_404` to detail and AI-profile routes.
3. Apply write/manage guards to processing, delete, metadata, and visibility mutations.
4. Resolve and authorize the real source object in every AI tag/KPI endpoint; validate suggestion/source consistency.
5. Filter metadata catalogs, activities, aggregate document lists, counts, facets, summaries, and UI queries.

### Phase C — AI and retrieval closure

1. Filter home/schema and workspace AI context through the viewer's policy.
2. Align AI permission claims and administrator behavior with the central decision.
3. Fix lexical FTS by joining document/source visibility and owner before ranking.
4. Add source asset ID and visibility generation to vector payloads; reindex or delete unprovable legacy points.
5. Ensure prompts, citations, saved outputs, traces, and retrieval telemetry contain only authorized evidence.

### Phase D — Knowledge graph and family closure

1. Centralize visibility/sensitivity normalization and make unknown lineage fail closed.
2. Propagate source owner, visibility, and generation through document processing and graph writes.
3. Filter stored graph nodes/edges before user and AI ranking/traversal.
4. Make family list/detail/member/relationship queries viewer-aware and recompute counts from visible evidence.
5. Backfill or quarantine legacy graph/family rows that cannot prove source visibility.

### Phase E — Lifecycle and enforcement

1. Add visibility-generation migration, derived-store lineage fields/checks/indexes, and transactional invalidation/outbox behavior.
2. Implement shared-to-private and private-to-shared generation-safe transitions.
3. Integrate membership/ownership changes and TS-ISO-011 deletion with cache/derivative invalidation.
4. Run two-owner, member, administrator, worker, race, and cross-store tests in report-only/canary mode.
5. Remove duplicate policy branches and enable CI enforcement after all known readers are migrated.

## 7. Expected file changes

| Area | Expected files |
|---|---|
| Authoritative model | `platform-api/app/models/project_asset.py`, related schemas/model exports, new Alembic revision |
| Central policy | new `platform-api/app/services/asset_access_policy.py`; project access and audit integration |
| Direct asset APIs | `platform-api/app/routes/project_assets.py`, asset response schemas, processing/upload helpers |
| AI metadata | `platform-api/app/routes/ai_asset_metadata.py`, AI asset metadata models/services |
| Project views | `projects_metadata.py`, `projects_aggregates.py`, summary/activity/document-list services |
| AI context | `ai_proxy_permissions.py`, `workspace_context.py`, `home_intelligence/schema_context.py`, prompt/citation builders |
| Retrieval | `ai_grounding.py`, `ai_documents`/chunk queries, document processing/indexing, AI-server vector payload/search code |
| Knowledge graph | `knowledge_graph/visibility.py`, graph collectors/loaders/writers, project graph routes/services |
| Families | document-family routes and `project_graph_service` family/member/relationship queries |
| Lifecycle | visibility/ownership update service, outbox/jobs, cache invalidation, TS-ISO-011 deletion integration |
| Tests/docs | route matrix, metadata leak, AI/search/vector/KG/family, transition race, admin, operations, and rollback coverage |

Exact paths and the Alembic revision must be confirmed against the repository head when implementation begins.

## 8. Data migration and backfill

1. Inventory every current visibility label and count records with missing owner, source, tenant, project, or lineage.
2. Normalize proven supported labels only. Quarantine missing/unknown/conflicting rows from user and AI serving.
3. Add `visibility_generation=1` to authoritative assets after validation.
4. Backfill `source_asset_id`, owner, visibility, and generation to `ai_documents`, chunks, AI metadata, graph, family, and searchable/vector records from the authoritative asset.
5. Delete or isolate orphaned derivatives whose source no longer exists; coordinate durable erasure with TS-ISO-011.
6. Rebuild shared and private vector/search indexes into generation-aware collections or payloads.
7. Compare viewer-specific counts and results before enforcement. Do not use an exposure-preserving fallback for unresolved legacy data.

The migration must be resumable, tenant-scoped, generation-safe, and observable. It must not hold a cross-tenant table lock for the full backfill. Record counts and safe IDs/reason codes, not filenames or customer metadata.

## 9. Test plan

### Direct asset and metadata tests

- Use at least two owners, one ordinary member, one removed member, and one approved administrator in the same project plus a second tenant/project.
- Verify list, detail, AI profile, content, preview, tags, KPIs, processing, visibility update, and delete against shared, own-private, and other-private assets.
- Hidden direct IDs return the same safe `404` as nonexistent IDs; no response header, field, timing class, or error reveals existence.
- List pagination, total, filters, facets, order, status counts, and last-updated values exclude hidden assets.
- Suggestion/tag/KPI mutation IDs cannot be replayed against another source, project, tenant, or owner.
- Viewer DTOs omit storage locations, object keys, internal errors, and unnecessary hashes/operational fields.

### Project and product-surface tests

- Metadata catalog, activity, aggregates, document lists, summaries, coverage, deltas, recommendations, tasks, exports, and notifications contain no hidden asset evidence.
- Workspace and home/schema contexts include shared plus caller-owned private assets only.
- Removed project membership takes effect on the next operation and invalidates cached context.
- Administrator override behavior is identical across content and metadata and emits the required audit event.

### Search, vector, and AI tests

- Qdrant, lexical FTS, hybrid ranking, prompt context, citations, and saved output include shared plus caller-owned private evidence only.
- Missing/unknown visibility, owner, source asset, or generation matches no result.
- A stale vector/chunk from a prior shared generation is hidden immediately after a shared-to-private change.
- AI service requests cannot broaden the initiating viewer's scope or retrieve another owner's private asset.
- Logs, traces, retrieval metrics, and error handling do not contain hidden titles, snippets, vector payloads, or query evidence.

### Knowledge graph and family tests

- Graph lists, node detail, traversal, cards, gaps, actions, traces, and AI-ranked nodes exclude hidden asset nodes and strictly derived relationships.
- Private document nodes retain private visibility and canonical owner during ingestion and reprocessing.
- Family membership, names, summaries, counts, relationships, entities, KPIs, and tags are computed from viewer-visible evidence.
- A family supported only by hidden assets is absent; mixed-evidence nodes expose only relationships supported by visible evidence.
- Unknown/missing sensitivity and provenance fail closed.

### Transition, race, cache, and worker tests

- Shared-to-private denial becomes effective before async cleanup; old-generation derivatives never match.
- Private-to-shared does not publish stale private derivatives before a validated rebuild.
- Concurrent processing, visibility change, ownership change, deletion, and membership removal cannot republish an obsolete generation.
- Workers reject cross-tenant and stale-generation jobs both before processing and before publication.
- Cache keys and invalidation prevent cross-user, cross-project, cross-tenant, and old-generation reuse.
- Delete/quarantine removes the asset immediately from serving and the TS-ISO-011 manifest eventually verifies every derivative/store.

## 10. Deployment sequence

1. Record the repository/image revisions, visibility-label inventory, orphan/unknown counts, all identified readers, and baseline viewer-specific results for two canary tenants.
2. Deploy the central policy, typed DTOs, audit decisions, schema constraints, lineage/generation fields, and query instrumentation without exposing quarantined legacy records.
3. Backfill authoritative and derived visibility in bounded tenant batches; reindex vector/lexical data and quarantine unresolved rows.
4. Migrate direct asset list/detail/profile/mutation and AI tag/KPI routes first; run the two-owner/member/admin matrix.
5. Migrate metadata catalogs, activity, aggregates, summaries, workspace, and home/schema AI context.
6. Migrate lexical grounding, AI permission/prompt/citation paths, and verify TS-ISO-005 vector filters with generation-aware payloads.
7. Migrate knowledge-graph and document-family loaders, writers, lists, relationships, counts, and AI ranking.
8. Enable generation-safe visibility transitions, worker double-checks, cache invalidation, and deletion integration.
9. Turn on CI/direct-query enforcement, remove duplicate policy logic, and exercise shared-to-private, private-to-shared, membership-removal, deletion, and rollback drills.

Deploy API and AI-server vector contract changes in the order required by TS-ISO-005 so an older consumer cannot interpret a new claim permissively. During every wave, deny or quarantine uncertain data rather than temporarily treating it as shared.

## 11. Rollback

- Roll back a reader only to a version that enforces an equivalent or stricter central policy and understands the current visibility generation.
- Keep schema, lineage, generation, quarantine, and audit data through application rollback.
- If a derived service cannot validate the new contract, disable that result source or feature; do not return unfiltered metadata, graph, lexical, or vector results.
- Never map unknown/missing visibility to shared, remove the owner predicate, serve stale prior-generation derivatives, or restore tenant/project-only lexical filtering.
- A shared-to-private transition and a deleted/quarantined asset remain restrictive through rollback.
- Rebuild derived data forward after a failure; do not re-publish an older index without proving its visibility and generation.

## 12. Acceptance criteria

- [ ] One central policy governs asset content, metadata, mutations, search, AI context, graph, family, aggregates, activity, counts, previews, and derivatives.
- [ ] An ordinary non-owner cannot learn a private asset's existence or any sensitive metadata through direct or indirect surfaces.
- [ ] Hidden and nonexistent direct asset IDs return the same safe response, and viewer-specific pagination/counts do not leak hidden rows.
- [ ] List/detail/profile and all tag/KPI reads/mutations resolve and authorize the concrete source asset.
- [ ] Lexical, vector, hybrid, prompt, citation, workspace, and home intelligence use the same shared-or-owned-private predicate.
- [ ] Every derivative has authoritative source lineage, owner, visibility, and generation; unknown or missing data fails closed.
- [ ] Knowledge graph and document families filter nodes, edges, evidence, relationships, summaries, and counts for the viewer.
- [ ] Shared-to-private changes deny immediately; private-to-shared publishes only a validated new generation.
- [ ] Workers, jobs, caches, membership changes, ownership changes, and TS-ISO-011 deletion cannot reintroduce stale visibility.
- [ ] Administrator override is explicit, consistent, appropriately MFA/audited, and covered by the complete route matrix.
- [ ] No sensitive asset metadata, content, storage location, vector payload, graph label, or query evidence appears in logs or unauthorized DTOs.
- [ ] Two-owner, member-removal, cross-tenant, transition-race, cache, search, AI, KG, family, and rollback tests pass in a production-like environment.

TS-ISO-016 must remain open until all direct and derived asset readers use the central policy, legacy visibility is either proven or quarantined, generation-safe transitions are deployed, and the full metadata/search/AI/knowledge-graph isolation matrix passes.
