# Devin: unified ask pipeline — one chart-fit process, R analytics, insight follow-ups (DELIVERED CODE)

Repository: `lhoskins/tablescope-lh`
Branch: **`claude/deep-analysis-business-value`** (this branch — the code is here)
Based on: `devin/r-echarts-e2e-validation`

## ⚠️ Delivery model

The code is **written and tested on this branch**. Your job is to **merge, run
the full suites in CI, deploy, clear caches, and verify** — not to rewrite it.

1. Do **not** rewrite, refactor, rename or reformat the delivered files. Merge
   as-is; resolve conflicts by preserving the delivered code.
2. Suspected bug → **report it in the PR**, do not silently change it.
3. Run in CI the tests this container could not (anything importing `app.main` —
   the container's numpy/pandas is broken).

---

## What was wrong

The AI Assistant, the Business-Insight ask box and the Project-Insight ask box
answer the same kind of question against the same data, but did not share a
pipeline. Verified in code:

1. **Chart variety was thrown away in chat.** `ask-and-run` asked the
   visualization engine for a chart and then collapsed it through
   `_ASK_AND_RUN_SURFACE` onto **five** families (kpi/table/line/bar/pie).
   `SCATTER` was mapped to `"table"`; heatmap, boxplot, sunburst, candlestick and
   the rest were **not in the map at all**, so they defaulted to a table — even
   though the ECharts renderer draws all of them. The chart-fit work only ever
   reached insight cards.
2. **`conversational_analytics` never imported the visualization engine.** It
   consumed whatever narrowed suggestion ask-and-run had already produced, so
   the project chat inherited the same five families.
3. **No analytics in chat.** Neither ask path called `analyze_methods` — a chat
   answer carried no R execution and no method envelope, while an insight card
   built from the same rows did.

## What is delivered

### `platform-api/app/services/ask_pipeline.py` (new, pure, unit-tested)

- **`resolve_presentation()`** delegates to the **same `rank_visualizations()`
  the insight cards use**. A question and a card about the same data now agree
  on the chart, and chat receives the ranked alternatives for its chart picker.
- **`chart_config()`** keeps chat's existing contract byte-compatible
  (`type` / `subtype` / `labelColumn` / `valueColumns` / `metricField` / `topN` /
  `valueFormat`) while letting the **full family vocabulary** through. **Table
  and KPI remain first-class answers** — the ability to return a data table in
  conversation is preserved, not weakened.
- **`build_insight_followup()` / `followup_prompt()`** ground a question in the
  insight card it was asked from: title, summary, source tables, and the
  governed method / engine / n / caveats, plus an explicit instruction not to
  change the subject. This is what makes "why did that happen?" or "break that
  down by region" dig into *that* finding rather than being answered against the
  whole project.

### Wiring in `app/routes/ai_proxy.py`

- `_suggest_visualization()` now delegates to the shared pipeline. **Legacy
  field names (`xField`, `yField`, `y2Field`, `chartStyle`) are still emitted**
  so existing clients keep working, with `candidates` added for the picker.
- The dead `_ASK_AND_RUN_SURFACE` narrowing map is **removed**.
- **`_attach_ask_analytics()`** runs the governed Analytical Method Engine over
  **both** ask paths — `_ask_and_run_core` (which every ask surface flows
  through) and `ai_generate_query_preview`. Because the catalog's 29 executable
  methods are all `execution_engine: r`, this gives chat **R-first execution with
  Python fallback**, and stamps `analyticalMethod` / `method_envelope` so the
  **R Analytics badge and Explain panel light up in conversation** exactly as on
  cards. Fail-closed: engine off, no rows, or any exception leaves the answer
  untouched.

## Tests (this container)

`ask_pipeline` **14/14**, `deep_analysis` **34/34**, `chart_catalog` **18/18**,
`visualization_engine` **27/27**, `ruff` clean.

Notable assertions: a two-measure result resolves to **scatter** (was forced to
`table`), a two-dimension matrix resolves to **heatmap**, candidates are diverse
rather than six of one family, and a Python-executed card is never described as
"executed in R".

---

## Devin: remaining wiring (small, and the reason to read this)

The backend now returns the richer chart plus `candidates` and
`analyticalMethod` on every ask response. Two front-end touches finish it:

1. **Chat renders the wider vocabulary.** Confirm the conversation renderer
   (`conversation-turn.tsx` / `AIQuestionResultModal.tsx` /
   `project-overview-chat.tsx`) passes `suggestedVisualization` through to the
   shared `WidgetRenderer` path rather than a local switch over line/bar/pie. If
   a local switch exists, route it through the same renderer the insight cards
   use so heatmap/scatter/boxplot answers actually draw.
2. **"Ask about this card."** Wire the insight card's ask entry point to send the
   card payload alongside the question, and call
   `ask_pipeline.build_insight_followup(question, card)` →
   `followup_prompt(...)` as the question passed into `_ask_and_run_core`. The
   core already accepts a `card_context` parameter, so this is a pass-through,
   not a new endpoint.

Also surface `analyticalMethod` in the chat bubble's Explain/details area so the
R badge appears in conversation (the component already renders this shape for
cards).

## Deploy & verify

1. Merge; full suites in CI (platform-api `pytest`/`ruff`/`mypy`, ai-server
   `pytest`, web-ui `typecheck`/`test`/`build`).
2. Rebuild images, deploy, clear insight caches.
3. Verify:
   - Ask a two-measure question in **each** of the three surfaces → a **scatter**
     renders (previously a table).
   - Ask a two-dimension question → a **heatmap** renders.
   - A chat answer shows the **R Analytics badge** with method + n in Explain.
   - A data-table answer still renders as a table (nothing regressed).
   - From an insight card, ask "break this down by …" → the answer stays on that
     card's metric.

## Report

Byte-identical confirmation (or exact deviations + reasons); CI totals per
suite; which front-end renderer changes were needed for item 1; how the card
payload is passed for item 2; screenshots of a scatter answer, a heatmap answer,
and a chat bubble showing the R Analytics badge.
