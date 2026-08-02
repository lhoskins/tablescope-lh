# Devin-Ready Plan: Refresh Existing Demo Data Sources (Same-Name "Overwrite")

## Direct answer to the question asked

**No — not as the importer is currently written.** Re-running
`install_demo_company.py --all` (or `--sample`) against a demo tenant that
already has this data loaded will **skip** every CSV, not overwrite it,
because filenames are unchanged by the two-year-window change
(`devin/demo-company-two-year-window`) — only the row contents/date ranges
changed. The regenerated data would never actually reach the tenant.

The good news: `platform-api` already has the exact mechanism the question
assumes exists — `POST /api/upload/datasources/{view_name}/replace`
(`platform-api/app/routes/upload.py:549-694`). The importer script just never
calls it. This plan wires it up.

## Root cause

`DemoImporter._upload_csv` (`scripts/demo_company/importer.py:336-354`):

```python
def _upload_csv(self, a: dict, pid: int, path: Path, filename: str) -> None:
    view = compute_view_name(filename)
    if view in self._datasource_views:
        self.report.skipped += 1
        self._log(f"  = skip (exists): {a['path']}")
        return
    ...
    self.c.post_multipart(
        "/api/upload",
        fields={"project_id": str(pid), "vdb_type": "user"},
        file_field="file", filename=filename,
        file_bytes=path.read_bytes(), content_type="text/csv")
```

`_load_existing()` (`importer.py:196-215`) pre-populates
`self._datasource_views` from `GET /api/upload/datasources?include_archived=true`
before the run starts. Every artifact's `compute_view_name()` — which
mirrors the backend's own derivation exactly (docstring: "for idempotency")
— is checked against that set. This design is intentional and correct for
the importer's stated purpose ("Idempotent: skips artifacts that already
exist," `importer.py:6`) when running `--sample` then `--all` in sequence
against a *fresh* tenant. It becomes the wrong behavior the moment the goal
is "replace what's already there with regenerated data," because it always
takes the skip branch and never reaches an upload call at all.

`platform-api/app/routes/upload.py:549-694` (`replace_file_source`) is a
separate, already-implemented endpoint for exactly this case: same view
name, new file content, requires the incoming file's columns to be a
superset of the existing ones (new columns allowed), re-imports through the
Teiid servlet with `replace: "true"` (overwrites the existing view/foreign
table in place), and preserves the `FileSourceMeta` row — so the data
source's project association and any saved queries built against the view
name keep working unchanged. The importer has no code path that calls it.

## Scope: CSV data sources only

Verified `documents.py` (125 generated business documents: policies,
procedures, executive reviews) has **zero** references to
`MONTHLY_START`/`WEEKLY_START`/`MONTHLY_THROUGH`/`WEEKLY_THROUGH` — their
content is independent of the calendar window entirely. Only
`dictionaries.py`'s generated data-dictionary README references
`MONTHLY_THROUGH`/`WEEKLY_THROUGH`, and the two-year-window change did not
touch those (both stayed fixed at `2026-07-01`/`2026-07-06`; only the
*start* of each window moved). So on a tenant that already has this demo
data loaded, documents and Company Library assets are still byte-identical
to what's already there — the existing skip-if-exists behavior for
`_upload_doc`/`_upload_library` is correct as-is and must not be changed.
This plan only touches `_upload_csv`.

## Fix

Make the "already exists" case opt-in-replaceable rather than always-skip,
gated behind a new CLI flag so the default idempotent-skip behavior (relied
on for the `--sample` → `--all` two-step flow) is unchanged unless the
operator explicitly asks for a refresh.

**1. `scripts/demo_company/importer.py`** — add a `replaced` counter to
`Report`, thread a `refresh` flag through `DemoImporter.__init__`, and
branch `_upload_csv` on it:

```diff
 @dataclass
 class Report:
     projects_created: int = 0
     projects_existing: int = 0
     created: int = 0
+    replaced: int = 0
     skipped: int = 0
     failed: int = 0
     failures: list[str] = field(default_factory=list)

     def summary(self) -> str:
         lines = [
             "── Demo Company Import Report ──",
             f"Projects: {self.projects_created} created, {self.projects_existing} existing",
-            f"Artifacts: {self.created} uploaded, {self.skipped} skipped, {self.failed} failed",
+            f"Artifacts: {self.created} uploaded, {self.replaced} replaced, "
+            f"{self.skipped} skipped, {self.failed} failed",
         ]
```

```diff
 class DemoImporter:
     def __init__(self, client: ApiClient, manifest: dict, root: Path, *,
                  dry_run: bool = False, sample: bool = False,
-                 shared: bool = True, verbose: bool = True) -> None:
+                 shared: bool = True, verbose: bool = True,
+                 refresh: bool = False) -> None:
         self.c = client
         self.m = manifest
         self.root = root
         self.dry_run = dry_run
         self.sample = sample
         self.shared = shared
         self.verbose = verbose
+        self.refresh = refresh
         self.report = Report()
```

```diff
     def _upload_csv(self, a: dict, pid: int, path: Path, filename: str) -> None:
         view = compute_view_name(filename)
-        if view in self._datasource_views:
+        exists = view in self._datasource_views
+        if exists and not self.refresh:
             self.report.skipped += 1
             self._log(f"  = skip (exists): {a['path']}")
             return
         if self.dry_run:
+            verb = "replace" if exists else "upload"
             self.report.created += 1
-            self._log(f"  + would upload CSV → {a['destination_project']}: {a['path']}")
+            self._log(f"  + would {verb} CSV → {a['destination_project']}: {a['path']}")
             return
+        if exists:
+            self.c.post_multipart(
+                f"/api/upload/datasources/{view}/replace",
+                fields={}, file_field="file", filename=filename,
+                file_bytes=path.read_bytes(), content_type="text/csv")
+            self.report.replaced += 1
+            self._log(f"  ~ replaced CSV → {a['destination_project']}: {a['path']}")
+            return
         self.c.post_multipart(
             "/api/upload",
             fields={"project_id": str(pid), "vdb_type": "user"},
             file_field="file", filename=filename,
             file_bytes=path.read_bytes(), content_type="text/csv")
         self._datasource_views.add(view)
         self.report.created += 1
         self._log(f"  + uploaded CSV → {a['destination_project']}: {a['path']}"
                   " (data source + query + AI)")
```

`ApiClient.post_multipart` already accepts an empty `fields` dict (it just
iterates `fields.items()`, which is a no-op) — no client changes needed
beyond the call site above.

**2. `scripts/install_demo_company.py`** — new flag, threaded through:

```diff
     mode.add_argument("--all", action="store_true",
                       help="Upload everything.")
+    mode.add_argument("--refresh-existing", action="store_true",
+                      help="Replace already-uploaded CSV data sources with "
+                           "freshly generated data instead of skipping them "
+                           "(same file name; the new file's columns must be "
+                           "a superset of what's already loaded). Documents "
+                           "and Company Library assets are never affected — "
+                           "their content doesn't depend on the calendar "
+                           "window, so re-uploading them is unnecessary.")
```

```diff
     importer = DemoImporter(client, manifest, out_root, sample=args.sample,
-                            shared=not args.no_shared, verbose=verbose)
+                            shared=not args.no_shared, verbose=verbose,
+                            refresh=args.refresh_existing)
```

(Also thread `refresh=args.refresh_existing` into the `--dry-run` branch's
`DemoImporter(...)` construction a few lines above, so `--dry-run
--refresh-existing` correctly previews "replace" instead of "skip.")

## Known limitation to flag, not silently fix

`replace_file_source` swaps the underlying Teiid view/foreign table data in
place but does not re-trigger AI processing (embeddings, saved-query
suggestions, insight cards) — those were generated against the old data and
won't automatically refresh just because the rows changed underneath them.
Confirmed by reading the full endpoint (`upload.py:549-694`): it ends at
`session.commit()` on `FileSourceMeta.column_types`, no call into any AI
reprocessing path. Whether that matters depends on how the demo site
actually uses AI-derived content (Business Insight cards, home-page
narratives) — flag this to the user rather than silently handling it, since
the right fix (re-trigger AI processing per data source? per project?) is a
platform-api question outside this script's scope, and guessing at it here
risks either doing nothing when something was needed or triggering
expensive reprocessing nobody asked for.

## Tests

`scripts/demo_company/importer.py` currently has **zero** test coverage —
`scripts/tests/test_demo_company.py` only exercises the generators
(`generate_datasets`, `build_dimensions`, `generate_documents`), never
`DemoImporter`. Add `scripts/tests/test_demo_importer.py` with a fake
`ApiClient` (subclass overriding `get`/`post_json`/`put_json`/`post_multipart`
to record calls and return canned responses, no real HTTP) covering:

- `refresh=False` (default): an artifact whose view is already in
  `_datasource_views` is skipped — `post_multipart` is never called for it,
  `report.skipped == 1`, `report.replaced == 0`.
- `refresh=True`: same setup — `post_multipart` is called once, against
  `/api/upload/datasources/{view}/replace`, not `/api/upload`;
  `report.replaced == 1`, `report.skipped == 0`.
- `refresh=True` with an artifact whose view is *not* already loaded: falls
  through to the normal create path (`/api/upload`), `report.created == 1`
  — confirms `refresh` only changes behavior for artifacts that already
  exist, never turns a fresh install into something else.
- `refresh=True` + `dry_run=True`: log line says "would replace", not
  "would upload"; no `post_multipart` call at all (dry-run contract
  preserved).
- Documents/library artifacts are unaffected by `refresh=True` — still skip
  on existing filename/title, confirming the flag is scoped to
  `_upload_csv` only as designed.

## Rollout (the actual "regenerate the live demo site" step)

Once merged, the two-year-window data (already regenerated and verified on
`devin/demo-company-two-year-window`) reaches an existing demo tenant via:

```
python scripts/install_demo_company.py --all \
    --api-url <demo-site-url> --email <owner-email> --refresh-existing
```

If the target is genuinely a brand-new/empty tenant (no prior demo data
loaded at all — matching "setting a new demo site" from the original ask),
`--refresh-existing` is a no-op: `_load_existing()` finds nothing, every
CSV takes the normal create path regardless of the flag. It's only load-time
API access this doc doesn't have (no `--api-url`/credentials in this
environment) — that step still needs to be run by whoever holds those, with
`--dry-run` first recommended to review the create/replace/skip plan before
committing to it.

## Branch / PR

Branch: `devin/demo-company-refresh-existing-datasources`, based on
`devin/demo-company-two-year-window` (which itself is based on Devin's
`devin/1783400583-demo-company-installer`, not yet merged into
`devin/r-echarts-e2e-validation`). This doc is the only change on the
branch; Devin implements the importer/CLI diff and the new test file.
