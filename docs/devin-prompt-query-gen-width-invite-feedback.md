# Devin plan: AI query SQL, Home grid width, invite redirect, insight feedback

Repository: `lhoskins/tablescope-lh`
Base branch: latest integrated branch containing
`feature/sprint-08-knowledge-graph-lifecycle` (NOT `main`). Note: the deployed
environment may be slightly AHEAD of the sprint-08 HEAD used to verify these
paths (`359367f`) — where a file/line differs, adapt to the current base.

Run web-ui `tsc` + lint + component tests and platform-api `pytest` + `ruff`
before finishing. Keep the PR focused on these four items.

---

## 1. "Generate Query with AI" produces invalid GROUP BY

Reported: asking "Generate Revenue by Month" produced SQL that failed:

```sql
SELECT PARSETIMESTAMP("Month", 'yyyy-MM-dd') AS "month",
       SUM(CAST("RevenueUSD" AS double)) AS total_revenue
FROM "monthly_review_metrics_CSV"
GROUP BY PARSETIMESTAMP(PARSETIMESTAMP("Month", 'yyyy-MM-dd'), 'M/d/yyyy'),
         SUM(CAST("RevenueUSD" AS double))
ORDER BY PARSETIMESTAMP("Month", 'yyyy-MM-dd')
```

Two independent defects in the GROUP BY:
- **Groups by an aggregate**: `SUM(CAST("RevenueUSD" AS double))` in GROUP BY is
  illegal SQL.
- **Double-wraps the period and uses a different mask than SELECT**:
  `PARSETIMESTAMP(PARSETIMESTAMP("Month",'yyyy-MM-dd'),'M/d/yyyy')` — Teiid
  requires each GROUP BY expression to repeat the SELECT expression verbatim;
  this differs from the SELECT's `PARSETIMESTAMP("Month",'yyyy-MM-dd')`.

Where it runs: the AI generate-query path — `POST /query/generate`
(`platform-api/app/routes/ai_proxy.py:888`) and
`POST /actions/generate-query-preview` (`ai_proxy.py:2956`). These already run
`normalize_teiid_timestamps`, `normalize_date_casts`, and
`collapse_bare_following_parens` from
`platform-api/app/services/teiid_sql.py`, but **none of those rebuilds the
GROUP BY** — they only fix mask/paren issues, so an aggregate-in-GROUP-BY and a
GROUP-BY-≠-SELECT slip through.

Do:
- **Add a deterministic GROUP BY repair** in `teiid_sql.py` (e.g.
  `rebuild_group_by_from_select(sql)`), applied on the generate/preview path
  after the existing normalizers. It must, for a single-table aggregate query:
  1. Parse the SELECT list; classify each item as aggregate
     (`SUM/AVG/MIN/MAX/COUNT(...)`) or non-aggregate.
  2. Set GROUP BY to **exactly the non-aggregate SELECT expressions**, verbatim
     (by the SELECT expression text, so it matches Teiid's requirement), dropping
     any aggregate term and any duplicate/extra wrapping. If there are no
     aggregates in the SELECT, remove the GROUP BY entirely.
  3. Leave ORDER BY as-is if it already references a SELECT alias or a
     non-aggregate expression; otherwise normalize it the same way.
  Use the existing top-level split helper (`_split_top_level`) so commas inside
  `PARSETIMESTAMP(...)`/`CAST(...)` are not mis-split.
- **Strengthen the ai-server generate-SQL prompt** (the single-table query
  generator in `ai-server/tablescope-ai-api/app/routers/ai.py` — the
  `/query/generate` or generate-sql handler, distinct from the intelligence
  plan handler) with two explicit rules: never place an aggregate
  (`SUM/AVG/COUNT/...`) in GROUP BY; GROUP BY must repeat the SELECT's
  non-aggregate expressions exactly and must never wrap `PARSETIMESTAMP` around
  a value that is already a timestamp. The deterministic repair is the
  guarantee; the prompt reduces how often repair is needed.
- Tests (`platform-api/tests/`): unit-test `rebuild_group_by_from_select` on the
  exact failing SQL above → expect
  `GROUP BY PARSETIMESTAMP("Month", 'yyyy-MM-dd')` and no aggregate in GROUP BY;
  plus cases with multiple non-aggregate columns, no aggregates (GROUP BY
  removed), and an already-correct query (unchanged).

## 2. Home pinned-widgets grid must extend to full width dynamically

The Home pinned-widgets grid (`web-ui/components/tablescope/home/home-pins-grid.tsx`)
uses `useContainerWidth` + `width={containerWidth}` and `getColsForWidth`, but is
constrained by the app shell's `max-w-content`
(`web-ui/components/tablescope/app-shell.tsx:70`,
`mx-auto w-full max-w-content px-5 py-6`). A recent change reverted the
full-width behavior.

Do:
- Let the Home pinned-widgets region (the pins grid and its "Refresh live
  widgets" row) use the **full available viewport width**, tracking the window
  **dynamically** on resize — not a fixed max. Scope this to the Home
  widgets area only: allow it to break out of the `max-w-content` container
  (e.g. a full-bleed wrapper around just the grid), or remove the max-width
  constraint for that region. Do NOT remove `max-w-content` globally — other
  screens depend on it for readable line lengths.
- Once uncapped, `useContainerWidth` reports the wider container and
  `getColsForWidth` re-flows to more columns automatically; verify the grid
  re-lays-out live as the browser window is resized (no page reload needed).
- Re-check after change: the grid fills to the right edge at wide viewports and
  reflows down to fewer columns at narrow ones.

## 3. Project-invite link must land on the tenant slug root

Reported: clicking the invite link does not go to the tenant URL; it should go
directly to the invited tenant slug, e.g.
`https://app.tablescope.cloud/simplicit`.

Root cause: `web-ui/app/[slug]/set-password/page.tsx` (around line 71) redirects
with `router.replace("/")` after the password is set and the token exchanged —
sending the user to the app root instead of their tenant workspace. The invite
link itself is built correctly as `{app_base_url}/{slug}/set-password`
(`platform-api/app/routes/tenants.py:669`), and the exchange returns
`result.tenant_slug`.

Do:
- Change the post-success redirect to the tenant slug root:
  `router.replace(\`/${result.tenant_slug}\`)` (fall back to the `tenantSlug`
  from the route params if `result.tenant_slug` is empty). This lands the user
  on `/{slug}` (the tenant workspace, `web-ui/app/[slug]/page.tsx`), i.e.
  `https://app.tablescope.cloud/simplicit`.
- Verify: accepting an invite for tenant `simplicit` ends on `/simplicit`, not
  `/`.

## 4. Insight feedback: not shown on the review list + button styling

### 4a. Agree/Disagree persists but does not appear on the Insight Review page

The feedback write path is per-user and works: the frontend calls
`PUT /api/insight-feedback/{insight_id}` (`web-ui/lib/api/insight-feedback.ts`),
and `insight_feedback.py`'s GET/PUT/batch all persist and read the current
user's own feedback (filtered `user_id == context.user_id`) — which is why the
card still shows it after a refresh.

The gap: **there is no tenant-wide / admin feedback-list endpoint.** Every route
in `platform-api/app/routes/insight_feedback.py` filters by
`user_id == context.user_id`, so an "Insight Review" page that is meant to show
feedback across users has no data source that returns other users' feedback. (On
the verified base, no "Insight Review" page exists in `web-ui` and the literal
label is absent — it may live on a branch newer than the sprint-08 HEAD; the
feedback feature originates on `feature/sprint-03-explainable-ai-feedback`.)

Do:
1. **Locate the Insight Review page** in the actual base branch (search
   `web-ui` for the review route/label; it may be ahead of `359367f`). Confirm
   which endpoint it currently calls.
2. **Add a tenant-wide admin list endpoint**, e.g.
   `GET /api/insight-feedback/review`, guarded by `require_role(Role.ADMIN)`,
   that lists ALL feedback rows for `context.tenant_id` (NO `user_id` filter),
   joined/annotated with the insight/card snapshot and the submitting user's
   display name for the review table. Support basic filters (sentiment, project,
   date) and pagination consistent with other list endpoints.
3. **Wire the Insight Review page** to that endpoint (not the per-user
   `/batch`). If the page today reads the per-user endpoint, that is the exact
   root cause — swap it.
4. Tests: an admin sees another user's feedback via the review endpoint; a
   non-admin is forbidden; tenant isolation holds; a newly upserted agree/
   disagree appears in the review list.

If the review page genuinely does not exist in the integrated base (orphaned
nav), report that and build a minimal admin review list backed by the new
endpoint rather than guessing at a prior design.

### 4b. Make Agree/Disagree match the other card buttons

On the insight card, the standalone **Agree**/**Disagree** controls are styled
differently from the other card actions (Investigate, Mark reviewed, Explain,
Action). Restyle Agree/Disagree to use the **same outlined button format** as
those actions. Target the card renderers:
- `web-ui/components/tablescope/project-insight/project-insight-screen.tsx`
  (`InsightCardItem`, ~line 894) — the Project Insight risk/trend/opportunity
  cards.
- `web-ui/components/tablescope/home/intelligence-card.tsx` — the Business
  Insight card, if it renders standalone Agree/Disagree the same way.
Reuse the exact button component/utility classes the other actions use so the
row is visually uniform (size, border, spacing, hover). Keep the
active/selected state (e.g. Agree chosen) legible, but the resting style must
match the sibling buttons. Do not change the feedback behavior — only the
styling.

## Definition of done

- web-ui: `tsc`, lint, component tests green; browser-verify each item —
  Generate Query with AI now returns runnable "Revenue by Month" SQL; the Home
  grid fills full width and reflows on resize; an invite lands on `/{slug}`;
  agree/disagree appears on the Insight Review page and the buttons match the
  other card actions.
- platform-api: `pytest` + `ruff` green, including the new
  `rebuild_group_by_from_select` tests and the review-endpoint tests.
- Final report: changed files; the exact GROUP BY repair behavior and where it's
  wired in the generate path; the Home width approach (scoped break-out vs
  container change); the one-line invite redirect change; the new review
  endpoint's route + auth + shape and which page was wired to it; the button
  component reused for Agree/Disagree; tests + browser checks run; anything on
  the base branch that differed from the verified paths above (especially the
  Insight Review page location).
