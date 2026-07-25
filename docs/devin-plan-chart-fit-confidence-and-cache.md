# Devin plan: chart fit-confidence selection (DELIVERED) + cache auto-clear diagnosis

Repository: `lhoskins/tablescope-lh`

## ⚠️ Delivery model

The chart-selection fix is **already written and tested** on branch
**`claude/chart-fit-confidence`** (based on `devin/r-echarts-e2e-validation`).

**STRICT RULES — same as the previous handoff:**
1. **Do NOT rewrite, refactor, rename, or reformat the delivered changes.** Merge
   as-is. Resolve any conflict by preserving the delivered code and adapting the
   surrounding code.
2. Your job: **merge, run the full suites, deploy, clear caches, verify** — plus
   Part C (cache diagnosis) and Part D (suggestions check).
3. Suspected bug in delivered code → report it in the PR, don't silently change it.

---

## Part A — DELIVERED: chart selection now ranks by per-dataset fit

### Root cause of "Deeper analysis is nearly all heatmaps"

Selection ranked families by their **base score from the markdown**. Heatmap's
base is `0.80` and *any* table with 2 dimensions + 1 measure is **eligible** for
it — so heatmap won almost everywhere, regardless of whether the dimensions were
sensible (an id-like column with 300 distinct values still "qualified").

Base eligibility answers *"can this family draw this shape?"*. It never answered
*"is this family a good choice for THIS dataset?"*. That second question is what
your "template per chart with a confidence score" intuition asks for — and it is
what the delivered code adds.

### What changed (all tuning stays in the markdown)

1. **Markdown fit hints** (`chart_selection_best_practices.md`, both copies) —
   each family may now declare `min_rows`, `ideal_rows`, `ideal_dim_card`,
   `ideal_dim2_card`. Example (heatmap): `min_rows: 6`, `ideal_dim_card: 3-30`,
   `ideal_dim2_card: 3-30`. **Tuning selection is still a markdown edit.**
2. **`chart_catalog.fit_score()` / `fit_ranked()`** — the confidence model:
   - starts from the family's base score;
   - applies a **graded** penalty when the dataset falls outside a declared
     ideal range (a 400-category axis is penalised far harder than a 35-category
     one; floored at 0.15 so a bad fit is demoted, not erased);
   - **hard-excludes** a family below its `min_rows` (a boxplot needs a
     distribution, not 3 rows);
   - adds a **specificity bonus** so a family that consumes all the data's
     dimensions beats one that discards a dimension (a 2-dimension matrix is a
     heatmap, not a bar chart that throws a dimension away);
   - clamped to `1.0`. `fit_ranked()` returns every positive-fit family, best
     first — **[0] is the chart to display, [1:7] is the suggestion list**.
3. **`visualization_engine`** — ranking now blends the inline branch's
   *semantic* score (it knows part-of-whole, id-like labels, rate columns —
   things shape alone cannot reveal) with the catalog's *fit ratio*. This was
   deliberate: an early version let the catalog overwrite the inline score and
   it regressed part-of-whole data from pie to bar. Also:
   - promotes catalog-eligible families the inline branches never propose;
   - **unlocks 5 families that could never be selected before** — `histogram`,
     `waterfall`, `bubble`, `bump`, `calendar_heatmap` have no `ChartType` enum
     member and render via a parent + style, so they were silently skipped;
   - falls back to the **detail table** when no chart clears a weak-fit
     threshold (0.25) — "nothing fits" is now an honest answer instead of the
     least-bad chart.
4. **`home_intelligence` shape templates** iterate `fit_ranked(...) >= 0.5`
   instead of base-score eligibility, so a Deeper-analysis template only runs
   when its family genuinely fits the probed table.

### Verified behavior (all on the delivered branch)

| Dataset | Result |
|---|---|
| 8 regions × 12 products + revenue (true matrix) | **heatmap** 0.879 |
| 300 order-ids × 4 statuses (id-like) | **table** 0.182 — heatmap collapses to 0.132 |
| 4 segments summing to a whole | **pie/donut** 0.996 |
| 8 id-like suppliers | **bar/horizontal_bar** 0.918 |
| 12-month series | **line** 0.920 |
| 400 raw values | **boxplot** + **histogram** 0.750 |

Tests: `test_chart_catalog.py` **18/18**, `test_visualization_engine.py`
**23/23** (2 excluded — this container's numpy/pandas is broken, they import
`app.main`; re-run them in CI). `ruff` clean on all touched files.

---

## Part B — Devin: merge + verify

1. Merge `claude/chart-fit-confidence` into your integration branch.
2. Run the **full** suites (my container could not): platform-api
   `pytest`/`ruff`/`mypy`, ai-server `pytest`, web-ui `typecheck`/`test`/`build`.
   The two skipped tests (`test_ask_and_run_call_site_agrees_with_engine`,
   `test_home_call_site_agrees_with_engine`) must pass in CI.
3. Deploy (rebuild images), **clear insight caches**, regenerate.
4. Verify live: Deeper analysis is no longer heatmap-dominated; a distribution
   card offers boxplot/histogram; a genuine matrix still gets a heatmap.

---

## Part C — Cache "clears automatically" (diagnosis — confirm before fixing)

**Do not blind-fix this.** Confirm first.

The Business-Insight cache is not TTL-driven in practice (TTL is 24h). It is
invalidated by **KG version drift**: `business_insight_cache.get_fresh_result()`
returns `None` when `row.kg_version_id != active_version_id`.

Meanwhile `WorkerSettings.cron_jobs` runs **`evaluate_stale_graphs` every 15
minutes** (`:00/:15/:30/:45`), and that job does not merely mark drift — it
**queues a full KG rebuild** for every project it marks. A rebuild assigns a new
`active_version_id`, which invalidates that project's cached cards. If source
fingerprinting reports drift on a cycle where nothing meaningfully changed, this
thrashes: rebuild → cache invalidated → cards vanish until regeneration lands.
That matches "ran earlier and in a few hours there's no charts."

Confirm on the deployment:

```sql
-- How often is a new KG version being created per project?
SELECT project_id, count(*) AS versions_24h, max(created_at)
FROM knowledge_graph_versions
WHERE created_at > now() - interval '24 hours'
GROUP BY project_id ORDER BY versions_24h DESC;

-- Do cached rows exist but point at a superseded KG version?
SELECT b.project_id, b.updated_at, b.kg_version_id, g.active_version_id
FROM business_insight_results b
JOIN knowledge_graphs g ON g.project_id = b.project_id AND g.tenant_id = b.tenant_id;
```

- **Many versions per project per day** → drift detection is too sensitive; fix
  the fingerprint so an unchanged source does not produce a new version.
- **Few versions, rows still missing** → look at TTL / `ANALYSIS_VERSION` /
  regeneration failures instead.

**Recommended fix once confirmed:** make the cache **stale-while-revalidate** —
when the KG version drifts, serve the cached cards *and* enqueue a refresh,
rather than returning `None` and showing an empty page. Cards should never
disappear while a rebuild is in flight. (I did not implement this: it changes
worker-path semantics I cannot exercise in this container.)

---

## Part D — "No chart suggestions on Deeper analysis"

Server-side this now works: shape-template cards build candidates through
`_build_multi_chart` → `rank_visualizations`, and on the delivered branch the
melted rows produce a full ranked list (verified: heatmap-shaped rows → 6
candidates; sankey-shaped → 8). So after merging + cache clear, suggestions
should appear.

If they are still missing in the UI, the break is in the frontend hand-off —
check that `card.chartCandidates` is populated on shape cards in the API payload
(`home_intelligence` sets it from `card["chart"]["chartCandidates"]` for cards
with custom rows) and that the suggestion dialog reads it for that card type.
Report which side is empty rather than patching both.

## Definition of done

- Delivered branch merged unmodified; full suites green in CI.
- Deeper analysis shows a mix of families matched to data shape, not mostly
  heatmaps; nothing-fits cases show the table.
- Chart suggestions present on Deeper-analysis cards.
- Cache behavior diagnosed with the queries above, with a stated conclusion and
  (if confirmed) the stale-while-revalidate fix.
- Deployed, caches cleared, screenshots of: a heatmap card that is genuinely a
  matrix, a distribution card offering boxplot/histogram, and a suggestion modal
  on a Deeper-analysis card.
