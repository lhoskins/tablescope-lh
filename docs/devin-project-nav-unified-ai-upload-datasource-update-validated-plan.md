# TableScope Devin-Ready Plan: Project Nav, Unified AI Upload, Drag-to-Update (Validated)

## Validation summary — read this before the source plan

Checked against `origin/devin/r-echarts-e2e-validation` (HEAD `a1969ff`).
Of the three issues, one is confirmed as described, one is **substantially
wrong in its framing** (not a false problem, but a false "this regressed,
go find the lost code" premise), and one is **already implemented** and
should not be rebuilt. Corrections below change scope materially — read
them before starting Sprint A.

### Issue 1 — Project resource navigation: confirmed exactly as described

`web-ui/components/tablescope/project/project-resource-tabs.tsx` renders
all five tabs with a leading Tabler icon and `text-ink-tertiary` for
inactive state:

```tsx
const tabs: Tab[] = [
  { label: "Overview", href: base, icon: IconLayoutGrid },
  { label: "Data Sources", href: `${base}/data-sources`, icon: IconDatabase },
  { label: "Tables", href: `${base}/queries`, icon: IconCode },
  { label: "Documents", href: `${base}/documents`, icon: IconFileText },
  { label: "Dashboards", href: `${base}/dashboards`, icon: IconLayoutDashboard },
];
...
<Icon size={16} stroke={1.8} />
{tab.label}
```
active: `text-brand-700`, inactive: `text-ink-tertiary` (this codebase's
lightest/most muted text token — confirms the plan's "too light" framing).
**This is the exact, sole component to edit** — implement Section 1 of the
source plan as written against this file. No other resource-nav component
exists (confirmed no duplicate).

### Issue 2 — "Unified AI-Assisted Upload": does not exist, was never lost

The source plan frames this as corrective/restorative and instructs a git
history search before rewriting. **That search was already run — do not
repeat it, and do not reframe this as a restoration.** `git log --all -S
'preferredAssetFamily'` and `-S 'asset_family'` across the entire repo
history return **zero results**. This vocabulary, and the classify-and-
route concept the plan describes, has never existed in this codebase.

What actually exists today is **two separate, disconnected upload UIs**,
neither of which classifies anything:

1. `web-ui/components/tablescope/data-source-builder/ai-upload-dropzone.tsx`
   — hard-coded to `accept=".csv,.xlsx,.xls"`; rejects everything else with
   `"unsupported type. Upload .csv, .xlsx or .xls."` (line 37). Always
   creates a Data Source. This is what Project Overview's Quick Actions and
   the plan both call "AI-Assisted Upload," but it has no document
   handling whatsoever.
2. `web-ui/components/documents/DocumentsTab.tsx` (rendered by the
   Documents page) — its own independent "+ Upload Documents" button,
   `accept=".pdf,.docx,.pptx,.txt,.md"`, posts directly to
   `/api/projects/{projectId}/assets/upload`. Always creates a Document.
   Has no CSV/XLSX handling and no relationship to the dropzone above.

And confirmed separately: `overview-screen.tsx`'s Quick Actions "Upload
document" entry does neither of these — it's a plain navigation:
```tsx
{
  label: "Upload document",
  icon: IconFileText,
  onClick: () => router.push(`/projects/${projectId}/documents`),
},
```
It just routes to the Documents page and relies on that page's own
uploader. There is no shared intake, no classifier, no capability
endpoint, and no intake state machine anywhere in the codebase.

**Correction to apply:** treat Sections 2–5 of the source plan (unified
intake, classification matrix, orchestration, UX) as **new
construction**, not restoration. Drop the plan's "find the overwritten
implementation" instructions for this piece specifically (there is
nothing to find) — keep them only for Issue 3 below, where they are
warranted. Everything else in Sections 2–5 (the classifier design, state
machine, capability endpoint, structured/unstructured pipeline split,
ambiguous-TXT/JSON/XML disambiguation UX) is sound target-state design and
should be implemented as written; it is simply larger, greenfield-ish
scope than "corrective" implies — size Sprint B/C accordingly, and don't
promise a quick fix.

One reuse opportunity the plan doesn't mention: the CSV/XLSX ingestion
pipeline behind `ai-upload-dropzone.tsx` and the structured-source-creation
API it calls already does schema inference, profiling, and VDB
publication (that's the whole existing Data Source Builder flow) — the new
unified intake's "structured pipeline" (Section 4) should call into that
*existing* pipeline rather than reimplement it. Confirm the exact upload
route it calls (`grep` for the fetch/`apiClient.upload` target in
`ai-upload-dropzone.tsx`) and reuse it as-is; only the *front door*
(classification + routing before that call) is new.

### Issue 3 — Drag-to-update: already implemented, do not rebuild

**This is the plan's biggest inaccuracy.** Drag-to-replace is live today
in `web-ui/components/tablescope/project/data-sources-screen.tsx`
(`git log --all -S 'onDrop' -- web-ui` surfaces its own commit,
`e035089 Items 1-10: drag-to-replace, ...` — the feature has real history
and is *not* missing from the deployed lineage):

```tsx
// data-sources-screen.tsx:76-113
const [dragOverKey, setDragOverKey] = useState<string | null>(null);
const [pendingReplace, setPendingReplace] = useState<{ source: DataSource; file: File } | null>(null);
...
const handleDrop = useCallback((source, files) => {
  setDragOverKey(null);
  if (!files || files.length === 0) return;
  setPendingReplace({ source, file: files[0] });
}, []);

const confirmReplace = useCallback(async () => {
  ...
  const res = await apiClient.upload<{ addedColumns?: string[] }>(
    `/api/upload/datasources/${encodeURIComponent(source.viewName)}/replace`,
    file,
  );
  ...
}, [pendingReplace, projectId, queryClient]);
```
Wired to table rows, gated to file-type sources only
(`isFile = !isDatabase(s) && !isSaas(s)`), highlights on drag-over, and
requires a `ConfirmDialog` confirmation before calling the backend — this
already satisfies "never replace production data immediately on drop" and
"stages... shows a preflight, requires confirmation."

The backend endpoint (`platform-api/app/routes/upload.py:549-694`,
`POST /datasources/{view_name}/replace`) also already exists and does real
work: same-filename check, column-superset check (rejects if any *existing*
column is missing from the new file, returns which new columns were
added), and an atomic re-import through the Teiid servlet with
`replace: true`.

**Correction to apply:** reframe Section 6 ("Restore drag-to-update") and
the "find the overwritten drag-to-update implementation" git-archaeology
instructions entirely — there is nothing lost to find, and Sprint D
("Restore safe drag-to-update... port or re-implement drag target") should
not exist as scoped. Replace it with the real, verified gaps:

1. **No accessible non-drag equivalent exists at all.** Confirmed by
   reading the full component: no button, menu item, or file-picker
   fallback anywhere in `data-sources-screen.tsx`. A keyboard-only or
   screen-reader user cannot update a data source's file today — full
   stop. This is the one place where the source plan's requirement
   ("Retain or add an `Update data source` action in the card's accessible
   action menu") is both accurate and genuinely unimplemented. Keep this
   requirement; it's real.
2. **The preflight only checks for missing columns, not type changes.**
   `upload.py:610-628`: `missing = existing_cols - incoming_cols` blocks
   only on column *removal*. A column that changes type between the old
   and new file (e.g. a numeric column starts containing text) is
   currently accepted silently — nothing in the endpoint compares
   `pg_type`/inferred type between old and new. The plan's "Rename/type
   change/removal: block activation until mappings or dependency issues
   are resolved" is a real, currently-missing safeguard.
3. **No dependency-impact preview.** The current confirm dialog shows only
   old/new filenames (verified: no row-count comparison, no affected
   tables/queries/dashboards list anywhere in the component or endpoint).
   The plan's richer "Preflight summary" (Section 7 of the source plan) is
   legitimate additive scope, not a restoration.
4. **No version history or rollback.** Confirmed: no `FileSourceVersion`-
   style model exists anywhere in `platform-api/app/models/`. `/replace`
   overwrites the Teiid view and updates `FileSourceMeta.column_types` in
   place; the previous file/version is not retained anywhere. Sections 8–9
   of the source plan (atomic update with archival, version history,
   rollback) describe real, unimplemented capability — implement as
   written, understanding this is new infrastructure built *around* the
   already-working replace call, not a fix to something broken.

**Practical sequencing implication:** since the core replace mechanism
already works end-to-end today, Devin can ship the accessible
non-drag-action fix (gap 1) and the type-change preflight check (gap 2) as
a fast, low-risk, standalone improvement before taking on the much larger
versioning/rollback/dependency-preview work (gaps 3–4). Consider splitting
those into two PRs against the same branch rather than one large one — the
source plan's single-PR "Definition of done" bundles a two-day fix with a
multi-sprint feature.

---

## Everything below is the original plan, preserved as validated

The scope, branch/merge strategy, Phase 0 discovery checklist, and
Sections 1, 4 (unstructured pipeline design), 5 (upload UX), 10–16
(security, API contracts, telemetry, tests, checklist, sequencing, feature
flags/rollback, PR deliverables, definition of done) from the source
document are accurate design targets and should be followed as written,
**except**:

- Drop every instruction to search git/PR history for a "prior drag-to-
  update implementation" (Section: "Find the overwritten drag-to-update
  implementation," and the corresponding item in Phase 0's discovery
  list, item 15). That search has been done; the feature is live on the
  current branch, not lost. Do not record "why it disappeared from the
  deployed lineage" in the PR — it never disappeared.
- Section "6. Restore drag-to-update on existing data sources" and
  Section "9. Version history and archival" — read these as "extend the
  existing mechanism" using the exact gaps 1–4 above as the acceptance
  bar, not as ground-up reconstruction.
- Sprint D ("Restore safe drag-to-update") in Section 15 — rename to
  "Harden existing drag-to-update" and re-scope to gaps 1–4.
- The PR-deliverables item "prior drag-to-update branch and commit
  disposition" and "explanation of why the earlier feature was overwritten
  or omitted" — remove; replace with "confirmation that the existing
  `data-sources-screen.tsx` drag-replace mechanism was extended, not
  replaced, with before/after diffs for gaps 1–4."
- Section 2 ("Create one unified AI-Assisted Upload intake") through
  Section 5 — implement as written, understood as new construction per
  the Issue 2 correction above (affects sizing/sequencing, not the design
  itself).

Everything else — the classifier design, macro/risky-format handling,
capability endpoint, intake state machine, structured/unstructured
pipeline steps, security/isolation requirements, API contract sketch,
telemetry, full test matrix (navigation/classifier/structured/document/
quick-action/drag-update-component/update-service/E2E), manual acceptance
checklist, implementation sequence (Sprints A–E, adjusted per above),
feature flags, deployment order, and rollback plan are unchanged from the
source document.

## Branch / PR

Branch: `devin/project-nav-unified-ai-upload-datasource-update`, based on
`origin/devin/r-echarts-e2e-validation` (HEAD `a1969ff` at validation
time). This doc is the only change on the branch; Devin implements per the
source plan plus the corrections above.
