# Devin: merge + deploy instructions — insight & conversation pipeline

Repository: `lhoskins/tablescope-lh`
**Branch to merge:** `claude/deep-analysis-business-value`
**Base:** `devin/r-echarts-e2e-validation` (the deployed lineage; already contains
the merged chart-fit work from PR #96)

7 commits · 16 files · +2202 / −48 · **all tests green** (see §5)

---

## 1. Merge rules (read first)

1. **Do not rewrite, refactor, rename or reformat the delivered files.** Merge
   as-is. Resolve any conflict by preserving the delivered code and adapting the
   surrounding code.
2. Suspected bug in delivered code → **report it in the PR description** with the
   exact change and reason. Do not silently change it.
3. Two platform tests could not run in the authoring container (its
   numpy/pandas is broken, so anything importing `app.main` was skipped):
   `test_ask_and_run_call_site_agrees_with_engine` and
   `test_home_call_site_agrees_with_engine`. **They must pass in CI.**

```bash
git fetch origin
git checkout -b devin/insight-conversation-integration origin/devin/r-echarts-e2e-validation
git merge origin/claude/deep-analysis-business-value
```

---

## 2. What each commit does

| Commit | What it changes |
|---|---|
| `f1dcd38` | Identifier columns are never chart dimensions |
| `fa9f7d7` | Method-driven Deeper analysis + materiality gate |
| `d604727` | Executive analyses: YoY, MoM, growth, actual-vs-target, co-movement, drivers |
| `9ddf5ef` | Deeper-analysis handoff doc |
| `dc0fed0` | Unified ask pipeline: shared chart-fit + R analytics + insight follow-ups |
| `8643495` | Ask-pipeline handoff doc |
| `ec9a497` | Chat renders the full ECharts vocabulary (three frontend narrowings removed) |

---

## 3. The code path (end to end)

### 3a. Chart selection — one ranker, every surface

```
chart_selection_best_practices.md        ← single source of truth (31 families)
        │  parsed by
        ▼
services/chart_catalog.py                 fit_score() / fit_ranked()
        │  consumed by
        ▼
services/visualization_engine.py          rank_visualizations()
        │                                 ├─ business_dimensions()  ← NEW: drops
        │                                 │   identifier columns (order_id, sku)
        │                                 └─ _catalog_facts()       ← row counts +
        │                                     true cardinalities
        ├──────────────► home_intelligence  (insight cards, deeper analysis)
        └──────────────► ask_pipeline       (all three conversational surfaces)
```

### 3b. Deeper analysis — governed methods, not shape probing

```
routes/home_intelligence.py::_run_for_project
        │
        ├─ hi._method_driven_insights(...)            ← NEW, runs FIRST
        │      ├─ probe table (LIMIT 200)
        │      ├─ deep_analysis.plan_deep_analyses()  ← which INTENTS the data supports
        │      ├─ _deep_analysis_sql()                ← per-intent projection
        │      ├─ analyze_methods()                   ← governed engine, R-first
        │      ├─ deep_analysis.assess_materiality()  ← no finding ⇒ NO CARD
        │      └─ card["analyticalMethod"] = envelope ← R badge + Explain panel
        │
        └─ hi._shape_template_insights(...)           ← fallback only
```

### 3c. Conversation — same ranker, same renderer, plus R

```
AI Assistant / Business-Insight ask / Project-Insight ask
        │
        ▼
routes/ai_proxy.py::_ask_and_run_core            (every ask surface flows here)
        ├─ _suggest_visualization()  ──►  ask_pipeline.resolve_presentation()
        │                                  └─ rank_visualizations()  ← same ranker
        └─ _attach_ask_analytics()   ──►  analyze_methods()          ← R-first
                                           └─ response["analyticalMethod"]
        ▼  frontend
conversation-turn.tsx → ResultChart → InsightChartBlock → WidgetRenderer → EChartsWidget
```

**Renderer note (important):** no renderer was added or retired. `recharts` is
already gone (zero imports, absent from `package.json`), and `WidgetRenderer` is
now a thin **adapter** that delegates to `EChartsWidget` — it holds no chart
library. Keep it: it is the single `WidgetConfig → ECharts` mapping that
dashboards, cards, home pins and chat all share. `EChartsWidget` is the renderer;
`WidgetRenderer` is the adapter.

---

## 4. Files changed

**New**
- `platform-api/app/services/deep_analysis.py` — intent planning, materiality
  gate, evidence presentation (pure, no DB/LLM/pandas)
- `platform-api/app/services/ask_pipeline.py` — shared conversational
  presentation + insight follow-up grounding
- `platform-api/tests/test_deep_analysis.py` (34), `test_ask_pipeline.py` (14)
- `web-ui/components/ai/ai-result-view.chartfamily.test.tsx` (4)

**Modified**
- `platform-api/app/services/visualization_engine.py` — `is_identifier_column()`,
  `business_dimensions()`, wired into `_catalog_shape` / `_catalog_facts`
- `platform-api/app/services/home_intelligence.py` — `_method_driven_insights()`,
  `_deep_analysis_sql()`, `_distinct_years()`, `_target_measure()`
- `platform-api/app/routes/home_intelligence.py` — methods run before shape
  templates
- `platform-api/app/routes/ai_proxy.py` — `_suggest_visualization` delegates to
  the pipeline; dead `_ASK_AND_RUN_SURFACE` map removed; `_attach_ask_analytics()`
- `web-ui/lib/api/ai-actions.ts` — `VizType` widened to the full vocabulary
- `web-ui/lib/api/conversational-analytics.ts` — `ChartConfig.type` widened
- `web-ui/components/ai/ai-result-view.tsx` — the pie/line/bar collapse removed
- `web-ui/components/tablescope/conversation/conversation-turn.tsx` — passes
  `y2Field` / `metricField` / `topN` / `valueFormat`

---

## 5. Verification

Authoring container (platform tests run directly; two excluded per §1):

| Suite | Result |
|---|---|
| `test_deep_analysis.py` | 34 / 34 |
| `test_ask_pipeline.py` | 14 / 14 |
| `test_chart_catalog.py` | 18 / 18 |
| `test_visualization_engine.py` | 27 / 27 |
| web-ui `vitest` | 242 / 242 (39 files) |
| web-ui `tsc` | clean |
| `ruff` (platform-api) | clean |

Run in CI:

```bash
cd platform-api && pytest -q && ruff check app tests && mypy app
cd ../ai-server/tablescope-ai-api && pytest -q
cd ../../web-ui && npm run typecheck && npm test -- --run && npm run build
```

---

## 6. Deploy

```bash
docker compose build web-ui platform-api      # rebuild: frontend + backend both changed
docker compose up -d web-ui platform-api platform-api-worker r-analytics
```

Environment (platform-api **and** platform-api-worker — the worker generates
insights):

```
ANALYTICAL_METHOD_ENGINE_MODE=hybrid
R_ANALYTICS_ENABLED=true
R_ANALYTICS_FAILURE_MODE=python_fallback
```

Then **clear insight caches** so cards regenerate through the new path (the
Clear-cache buttons, or `scripts/delete_insight_caches.py`).

---

## 7. Verify on the live app

**Deeper analysis**
- Cards are YoY / MoM / actual-vs-target / co-movement / contribution / anomaly /
  forecast — not shape-probe charts.
- **No card is keyed on an identifier column** (`order_id`, SKU).
- Cards show the **R Analytics badge**; Explain shows method, engine, n, caveats.
- Statistically empty results produce **no card** — that is correct, not a
  regression.

**Conversation (test all three surfaces: AI Assistant, Business-Insight ask,
Project-Insight ask)**
- A two-measure question renders a **scatter** (previously forced to a table).
- A two-dimension question renders a **heatmap**.
- bar / line / pie still render correctly (same ECharts path).
- A data-table answer still renders as a table — nothing regressed.
- The chat bubble shows the **R Analytics badge** with method + n.

---

## 8. Two follow-ups deliberately left to you

1. **"Ask about this card" wiring.** `_ask_and_run_core` already accepts a
   `card_context` parameter, and `ask_pipeline.build_insight_followup(question,
   card)` → `followup_prompt(...)` produces the grounded question. Send the card
   payload from the insight card's ask entry point and pass the grounded prompt
   in. No new endpoint required.
2. **Surface `analyticalMethod` in the chat bubble's Explain area** so the R
   badge appears in conversation — the component already renders this shape for
   cards.

## 9. Known check after deploy

The materiality gates read result keys defensively (`anomalies`,
`change_points`, `p_value`, `correlation`, `r_squared`, `relative_change` /
`percent_change`, …). The R implementations' actual output key names were not
visible from the authoring container. **If a gate reads keys the R methods do not
emit, that intent falls through to "material"** — safe (you see cards, you do not
lose them), but unfiltered.

Open one anomaly card and one driver/correlation card, read the Explain panel's
result keys, and if they differ, add the real names to the lookup lists in
`_MATERIALITY_RULES` (`deep_analysis.py`). One line per key — report it in the
PR rather than restructuring the gate.

## 10. Report back

Byte-identical confirmation (or exact deviations + reasons); CI totals per suite;
deploy + cache-clear confirmation; screenshots of a YoY card, an actual-vs-target
card, a co-movement (dual-axis) card, an anomaly card with its R badge, a scatter
chat answer and a heatmap chat answer; plus any materiality key names you added.
