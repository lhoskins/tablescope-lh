# Devin prompt: integrate + deploy all R/ECharts work so it actually shows

Repository: `lhoskins/tablescope-lh`

**The code already exists.** Both feature prompts were implemented on two
**sibling** branches (each based on PR #75 `devin/r-catalog-activation-ui`, but
neither contains the other). Nothing is visible in the app because they are
**unmerged and undeployed**. This task is to **integrate both branches, deploy,
and verify end-to-end** — do not re-implement.

## Branches to combine

| Branch | What it implements (verified) |
|---|---|
| `devin/r-catalog-activation-ui` (PR #75, the base) | R catalog v1.1 (29 executable R methods), R-first/Python-fallback registry, admin activation API/UI. **Already deployed.** |
| `devin/r-insight-provenance-and-wiring` | R Analytics badge (`insight-engine-badge.tsx`) + Analysis details on cards, `_CATEGORY_INTENT_HINTS`/`intent.py` wiring so more Business Insights run R, activation-UI hardening (16 files). |
| `devin/echarts-default-rollout` | ECharts as sole renderer (`WidgetRenderer` gutted of recharts, `EChartsWidget` +1105), recharts removed from `package.json`, `SimpleLineChart.tsx` deleted, authoring via `chartRegistry`/`WidgetConfigPanel`, and data-shape-driven insight viz (`visualization_engine.py`). |

The two feature branches are siblings and **conflict on 3 files**:
`web-ui/components/dashboard/EChartsWidget.tsx`,
`platform-api/app/services/analytical_method_engine/catalog_admin.py`,
`platform-api/scripts/seed_analytical_catalog.py`.

## Step 1 — Integration branch

1. Branch `devin/r-echarts-integration` from **`devin/r-catalog-activation-ui`**
   (PR #75 head; if #75 has merged to an integration line, use that and confirm
   it still contains the v1.1 catalog + activation work).
2. Merge `devin/r-insight-provenance-and-wiring`, then
   `devin/echarts-default-rollout` (or vice-versa). Resolve the 3 conflicts by
   **keeping both intents**:
   - `EChartsWidget.tsx` — take the ECharts-rollout renderer as the base (the
     full renderer) and re-apply the provenance branch's additions on top (engine
     badge / method-envelope hooks). Neither set of changes may be dropped.
   - `catalog_admin.py` and `seed_analytical_catalog.py` — union the changes
     (activation-hardening from the provenance branch + any seed/version edits
     from the ECharts branch). Keep both.
3. `npm run typecheck && npm test -- --run && npm run build` (web-ui) and
   `pytest -q && ruff check && mypy app` (platform-api) must pass on the merged
   result. Fix merge fallout, not scope.

## Step 2 — Completeness check (against the two source prompts)

Confirm the merged branch delivers, and finish anything a merge dropped:
- R Analytics badge renders on a Business Insight card when
  `analyticalMethod.executionEngine === "r"`; Analysis details behind Explain;
  Python/fallback shows no badge.
- More Business Insight categories route to R (not just trend/relationship);
  `infer_intent` handles period/forecast/anomaly phrasing.
- ECharts is the **only** renderer: repo-wide `grep -r "recharts"` returns zero;
  `recharts` absent from `package.json`; `SimpleLineChart.tsx` gone.
- Insight charts are **data-shape-driven** (not capped to `WidgetType`) —
  `visualization_engine.py` emits the richer vocabulary (heatmap/box/treemap/
  sankey/bubble where the data warrants).
- Authoring (`WidgetConfigPanel` + `ChartOptionsPanel` + `chartRegistry`) drives
  ECharts styles/options; Pin-to-Home and Add-to-Dashboard persist ECharts.
- Admin activation UI still works (activate/deactivate round-trip).

## Step 3 — Deploy so it SHOWS (this is the part that's been missing)

On the app host, from the integration branch:

1. **Rebuild web-ui — do not just restart.** ECharts mode is build-inlined and
   recharts was removed, so a stale image renders nothing new:
   `docker compose build web-ui`.
2. **Environment** (platform-api **and** platform-api-worker — the worker
   generates insights and inherits `*platform_api_env`; confirm the deploy `.env`
   doesn't override):
   `ANALYTICAL_METHOD_ENGINE_MODE=hybrid`, `R_ANALYTICS_ENABLED=true`,
   `R_ANALYTICS_FAILURE_MODE=python_fallback`.
3. **Catalog:** confirm the active catalog version is **v1.1 with 29 executable
   R methods** (`SELECT version,status FROM method_catalog_versions …` +
   the active-version R-method count). If not active, run the seed/activation so
   insight generation actually selects R methods.
4. **Clear insight caches so cards rebuild R-first + ECharts:** truncate/delete
   `business_insight_results` and the project-insight snapshots (the existing
   `scripts/delete_insight_caches.py` / migration `0067` path).
5. **Restart:** `docker compose up -d web-ui platform-api platform-api-worker
   r-analytics` (after the web-ui rebuild).

## Step 4 — End-to-end verification (map each promised change to a visible check)

- **R runs on insights:** refresh a Business Insight; its API payload shows
  `analyticalMethod.executionEngine === "r"`; the card shows the **R Analytics**
  badge on Explain; Analysis details lists engine/method/warnings.
- **ECharts everywhere:** on a dashboard, an insight card, a Home pin, an Ask
  Anything answer, and a Generate-Query preview — the chart is an ECharts canvas
  (`document.querySelectorAll('[_echarts_instance_]').length >= 1`); a network
  request loads an ECharts chunk; **no `.recharts-wrapper` anywhere**.
- **Data-shape charts:** an insight whose data is a matrix/distribution/flow
  renders heatmap/box/sankey (not forced into bar/line).
- **Authoring:** open a widget editor; changing chart type and a style option
  visibly changes the ECharts render; save persists it.
- **Pin/Add:** Pin to Home and Add to Dashboard produce ECharts widgets that
  reload as ECharts.
- **Activation UI:** deactivate then re-activate an R method; the button
  round-trips.

## Step 5 — Land it (stop stranding the work)

After verification, **merge `devin/r-echarts-integration` into the deployed
lineage** (open the PR and merge it) so these changes are the new base — do not
leave them on an unmerged branch. This is why nothing showed until now: the work
kept living on sibling branches ahead of what was deployed.

## Report

Branches merged + conflict resolutions; anything a merge dropped and how it was
restored; the deploy commands run (rebuild/env/seed/cache-clear/restart); the
end-to-end verification results with screenshots (R badge on a card, an ECharts
canvas on a dashboard and an insight card, a data-shape chart like a heatmap, the
authoring panel); and confirmation that the integration branch is merged into the
deployed lineage.
