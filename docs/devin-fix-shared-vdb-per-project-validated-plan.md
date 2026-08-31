# Devin: merge + deploy — per-project shared VDBs

**Repository:** `lhoskins/tablescope-lh`
**Branch to merge:** `fix-shared-vdb-per-project`
**Base:** `release/deploy-2026-08-07`

**3 commits · 15 files · +951 / −111 · 1 new Alembic migration · Java changes NOT compile-verified (§6)**

---

## 0. What this branch fixes

Shared projects were routing to the wrong VDB, and even when they hit the "right" one, that VDB never had real data in it. Root causes, all fixed here:

1. **`SharedVDB` was one row per *tenant*, not per *project*.** Two unrelated shared projects in the same tenant would resolve to the same VDB/folder.
2. **Queries to a shared project never actually reached any `SharedVDB`.** `query_sql_helpers.py::_resolve_vdb_database` (used by `/api/query/datasource`) routed straight to the project owner's *private* `UserVDB` instead — exposing the owner's own personal VDB to every project member, and never touching `SharedVDB` at all.
3. **Even a correctly-routed shared VDB was empty.** `share_project` copied files into a folder (`customer_folders.py`'s tenant-slug-keyed `shared/data`) that nothing else — not the Teiid VDB, not any read path — ever read from, then called the template-based `redeployVDB` servlet endpoint, which rewrites path prefixes but never reads a file's actual content. No real views were ever created for shared data.

This branch makes `SharedVDB` one-per-`(tenant_id, project_id)` (migration 0087), scopes the Java servlet layer's shared-VDB folder path to match, makes the two Python VDB-routing decision points agree (both now delegate to one canonical `VDBRoutingService.get_vdb_for_query`), and rewrites `share_project` to actually build real views via the same `/upload` servlet mechanism already proven for private uploads.

**Legacy redash was consulted for reference only and not migrated** — its `SharedVDB` was *also* one-per-organization, not per-project, so this is new work, not a restoration of prior behavior.

---

## 1. Merge rules — read first

1. **Do not rewrite, refactor, rename or reformat the delivered files.** Merge as-is; resolve conflicts by preserving the delivered code and adapting the surrounding code.
2. Suspected bug → **report it in the PR description**, don't silently change it.
3. **§4 (orphaned rows) and §5 (deleteVDB gap) are deliberate, scoped-out decisions, not oversights.** Don't "fix" them as part of this merge.
4. **§6 is a real gap, not boilerplate: the Java changes have not been compiled in this session.** Compile them for real before this ships — see §6 for exactly why and what to check.

```bash
git fetch origin
git checkout -b merge-fix-shared-vdb-per-project origin/release/deploy-2026-08-07
git merge origin/fix-shared-vdb-per-project
```

---

## 2. Commits

| Commit | What it does |
|---|---|
| `f7570825` | Schema (migration 0087 + `SharedVDB.project_id`) and Java servlet path-scoping (`VDBManagementServlet.createVDB`, `TeiidExcelImporterTest`'s `/upload`, `VDBFileLocator`, `VDBXmlBuilder`'s path-rewrite regex) |
| `e77d2590` | Reconciles `vdb_routing.py` and `query_sql_helpers.py` onto one canonical shared-project routing decision |
| `1e527be2` | `vdb_management.py`: project-scoped `create_shared_vdb` + new `upload_shared_file`; `project_sharing.py` rewritten to actually build real views via `/upload` instead of a dead file-copy + template-only redeploy |

---

## 3. Code path

```
Share a project
  routes/sharing.py::share_project
    └─ ProjectSharingService.share_project
         ├─ SharedVDB lookup: (tenant_id, project_id)          -- migration 0087
         │    miss ⇒ VDBManagementService.create_shared_vdb(org_id, project_id)
         │            └─ POST .../vdb-management/createVDB {vdb_type: shared, project_id}
         │               → VDBManagementServlet.createVDB: folder =
         │                 /customers/{orgId}/shared/{projectId}/  (was tenant-wide)
         ├─ per filename: read real bytes from the OWNER's actual uploads folder
         │    {customer_base_path}/{tenant_id}/{owner_id}/uploads/{filename}
         │    (same path finalize_tabular.py's private-upload flow writes to --
         │    NOT customer_folders.py's dead tenant-slug "shared/data" folder)
         └─ VDBManagementService.upload_shared_file(org_id, project_id, filename, content)
              └─ POST .../upload {vdb_type: shared, project_id, replace: true, file: <bytes>}
                 → TeiidExcelImporterTest.doPost: same real view-building path already
                   proven for private uploads (reads actual file content, builds a
                   genuine CREATE FOREIGN TABLE/view) -- vdb_type=shared + project_id
                   route it into /customers/{orgId}/shared/{projectId}/uploads/
                 → VDBFileLocator.findVDBFileForShared(orgId, projectId)
                 → VDBXmlBuilder.updateFilePaths: new sharedProjectPattern regex
                   recognizes the nested /shared/{projectId}/uploads path (checked
                   BEFORE the legacy org-wide sharedPattern)

Query a shared project
  routes/query.py::fetch_table_data           routes/query.py::query_datasource
    └─ VDBRoutingService.get_connection_info     └─ query_sql_helpers._resolve_vdb_database
         └─ get_vdb_for_query(project_id)              └─ delegates to
              is_shared ⇒ SharedVDB WHERE                  VDBRoutingService.get_vdb_for_query
                (tenant_id, project_id)                    (same method, same decision --
              no row ⇒ VDBNotConfiguredError                see e77d2590)
              (never falls back to owner's UserVDB)
```

**One canonical routing decision, not two.** Before `e77d2590`, `_resolve_vdb_database` had its own separate (and wrong) owner-VDB-fallback logic; now it delegates to `VDBRoutingService`, so `/api/query/fetch` and `/api/query/datasource` cannot resolve one project's query to two different VDBs.

---

## 4. Deliberately not backfilled: orphaned pre-migration `SharedVDB` rows

Migration 0087 adds `project_id` as **nullable** rather than backfilling it. Existing (pre-migration, per-tenant) `SharedVDB` rows are left with `project_id = NULL` and are simply orphaned — no code path looks them up anymore (every lookup is now `(tenant_id, project_id)`), and nothing deletes them either. This was an explicit choice, not an oversight: a fresh per-project `SharedVDB` gets created the next time each affected project is (re-)shared, and there was no reliable way to know from the old tenant-wide row alone which project(s) it was actually serving. If you want these cleaned up, that's a separate, deliberate follow-up — don't fold it into this merge.

---

## 5. Deliberately out of scope: `deleteVDB` still uses the tenant-wide shared path

`VDBManagementServlet.deleteVDB` has the identical hardcoded-shared-path pattern `createVDB` had before this branch, and was **not** updated to accept/use `project_id`. Deleting a project-scoped shared VDB through that endpoint today will look in the wrong (legacy, tenant-wide) folder. This is a known, explicitly scoped-out gap — flagged for a follow-up, not fixed here, since project deletion/un-sharing flows weren't part of this branch's task.

---

## 6. Java changes are NOT compile-verified — this is the real risk in this merge

`mvn compile` could not run in this session, in either mode:
- **Offline** (`mvn -q -o compile`): fails immediately — nothing was ever cached locally.
- **Online** (`mvn -q compile`): fails with `403 Forbidden` fetching `org.jboss.teiid:teiid-jdbc:pom:8.12.18.6_4-redhat-64-3` from `https://maven.repository.redhat.com/ga/` — that private Red Hat repo is unreachable from this sandbox.

Maven and JDK 21 themselves work fine here; it's purely the private repo that's unreachable. **Compile these for real before merging:**
- `apache-maven-3.9.6/MyProject/project-TeiidExcelImporterTest/src/main/java/cloud/tablescope/VDBFileLocator.java`
- `apache-maven-3.9.6/MyProject/project-TeiidExcelImporterTest/src/main/java/cloud/tablescope/VDBManagementServlet.java`
- `apache-maven-3.9.6/MyProject/project-TeiidExcelImporterTest/src/main/java/cloud/tablescope/VDBXmlBuilder.java`
- `apache-maven-3.9.6/MyProject/project-TeiidExcelImporterTest/src/main/java/cloud/tablescope/TeiidExcelImporterTest.java` (the most extensive change: 5 method signatures + call sites + 3 `relativeFilePath` branches all threaded with a new `Integer projectId` parameter)

```bash
cd apache-maven-3.9.6/MyProject/project-TeiidExcelImporterTest
mvn clean package
```
Then rebuild the WAR and confirm it's the one that ends up in `wildfly/standalone/deployments/TeiidExcelImporterTest.war` before deploying.

---

## 7. Verification

| Suite | Result |
|---|---|
| `platform-api` `ruff check app tests` | clean |
| `platform-api` `mypy app` | clean |
| Targeted VDB/sharing regression (10 files, incl. new `test_vdb_routing.py`, `test_project_sharing.py`, `test_vdb_management_shared_upload.py`) | **57 / 57 passed** |
| `platform-api` `pytest -q` (full suite) | **1649 passed, 7 failed, 4 skipped** (12m41s) — see below |
| Java `mvn compile` | **not run — blocked, see §6** |

New test files: `test_vdb_routing.py` (per-project `SharedVDB` routing, tenant isolation between two shared projects, no-VDB failure mode, private-project routing), `test_vdb_management_shared_upload.py` (`create_shared_vdb`'s `project_id` payload field, `upload_shared_file`'s multipart request shape and error handling), `test_project_sharing.py` (provisioning, `SharedVDB` reuse across re-shares, non-owner rejection, missing-file and path-traversal-filename rejection, and that `project.owner_id` is never touched by sharing).

All 7 full-suite failures are pre-existing and unrelated to this branch:
- **3** in `test_business_insight_phase1.py` — `redis.exceptions.ConnectionError: Error 111 connecting to localhost:6379`; no Redis reachable in this sandbox.
- **4** in `test_percent_change_summary.py` — a self-documented, pre-existing gap in that file's own `_fixed_today` fixture: it patches `date.today()` to `2026-06-30` but not `datetime.now(timezone.utc)`, which `build_percent_change_summary` uses directly for its `as_of` window. As real time drifts past the pinned date (now ~2 months, since this session's clock reads 2026-08-31), the "trailing 12 months" period-window math goes off by one. Confirmed unrelated: nothing on this branch touches `percent_change_summary.py`, date handling, or that module at all. Worth a follow-up (patch `datetime.now` in that fixture too, the way one test in that file already does locally), but out of scope here.

```bash
cd platform-api && pytest -q && ruff check app tests && mypy app
```

---

## 8. Deploy

**One new migration:** `0087_shared_vdb_per_project` — adds `shared_vdbs.project_id` (nullable FK to `projects.id`, `ondelete=CASCADE`), drops the old `uq_shared_vdbs_tenant` unique constraint, adds `uq_shared_vdbs_tenant_project` on `(tenant_id, project_id)`.

```bash
cd platform-api && alembic upgrade head
```

**The Teiid WAR must be rebuilt and redeployed** — see §6. This is not optional: without it, the Java side still has the old tenant-wide-only shared-path logic and `share_project`'s calls to `create_shared_vdb`/`upload_shared_file` with `project_id` will silently fall back to the legacy org-wide shared folder (the servlets treat an unrecognized/ignored `project_id` the same as absent), defeating the whole point of this branch without erroring.

```bash
docker compose build platform-api web-ui
docker compose up -d platform-api platform-api-worker web-ui wildfly   # name per your compose file
docker compose ps
```

### Rollback

```bash
cd platform-api && alembic downgrade -1
git checkout <previous-sha> -- wildfly/standalone/deployments/TeiidExcelImporterTest.war
docker compose build platform-api web-ui
docker compose up -d platform-api platform-api-worker web-ui wildfly
```
The downgrade's own comment flags it: it's only safe if no tenant has more than one `shared_vdbs` row by the time you roll back — true before this branch creates any new per-project rows, not guaranteed after. Check `SELECT tenant_id, COUNT(*) FROM shared_vdbs GROUP BY tenant_id HAVING COUNT(*) > 1` before downgrading; if any tenant has multiple rows, resolve that manually before running the migration downgrade.

---

## 9. Verify live

- **Share two different projects in the same tenant** (each with at least one file). Confirm they get two different `SharedVDB` rows (`SELECT * FROM shared_vdbs WHERE tenant_id = <t>` — two rows, two different `vdb_id`s, two different `project_id`s) and two different folders on disk (`/customers/{orgId}/shared/{project1}/` vs `/shared/{project2}/`).
- **Query a shared project as a non-owner member** (`/api/query/datasource` and `/api/query/fetch` both) — confirm real data comes back, not a 404, and confirm (via logs or a query against Teiid metadata) it's hitting the project's own `SharedVDB`, not the owner's `UserVDB`.
- **Confirm the shared VDB's views are real**, not placeholders: query an actual column from a shared file's view and get real values back, matching the source file.
- **Share a project with no files** — should provision cleanly (empty `copied_files`), no error.
- **A shared project with no `SharedVDB` row yet** (e.g. `is_shared=True` via the legacy member-count reconciliation heuristic, but never explicitly shared through this flow) should now **fail loudly** (404 / `VDBNotConfiguredError`) rather than silently falling back to any `UserVDB` — confirm this is the behavior you see, not a silent wrong-data return.

---

## 10. Report back

`mvn compile`/`package` output for all four Java files in §6 (or confirmation the WAR built and deployed cleanly); full `pytest` totals; migration 0087 applied cleanly with no errors; screenshots or query output demonstrating the two-shared-projects-two-VDBs isolation from §9; and explicit confirmation of the `SharedVDB`-with-no-row-yet failure mode (§9's last bullet) — that's the one place a silent regression would be worst (data crossing between an owner's private VDB and a shared project).
