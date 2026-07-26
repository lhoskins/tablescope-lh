# Devin: merge + deploy — insight, conversation & retrieval pipeline

Repository: `lhoskins/tablescope-lh`
**Branch to merge:** `claude/deep-analysis-business-value`
**Base:** `devin/r-echarts-e2e-validation` (deployed lineage; already has the
chart-fit work from PR #96)

**13 commits · 26 files · +4855 / −48 · all tests green** (§5)

---

## 1. Merge rules — read first

1. **Do not rewrite, refactor, rename or reformat the delivered files.** Merge
   as-is; resolve conflicts by preserving the delivered code and adapting the
   surrounding code.
2. Suspected bug → **report it in the PR description** with the exact change and
   reason. Do not silently change it.
3. Two platform tests could not run in the authoring container (its numpy/pandas
   is broken, so anything importing `app.main` was skipped):
   `test_ask_and_run_call_site_agrees_with_engine` and
   `test_home_call_site_agrees_with_engine`. **They must pass in CI.**

```bash
git fetch origin
git checkout -b devin/insight-conversation-integration origin/devin/r-echarts-e2e-validation
git merge origin/claude/deep-analysis-business-value
```

---

## 2. Commits

| Commit | What it does |
|---|---|
| `f1dcd38` | Identifier columns (`order_id`, SKU) are never chart dimensions |
| `fa9f7d7` | Method-driven Deeper analysis + materiality gate |
| `d604727` | Executive analyses: YoY, MoM, growth, actual-vs-target, co-movement, drivers |
| `dc0fed0` | Unified ask pipeline: shared chart-fit + R analytics + insight follow-ups |
| `ec9a497` | Chat renders the full ECharts vocabulary (3 frontend narrowings removed) |
| `eb0a0b9` | **Insight cards become retrievable — assistant stops inventing their SQL** |
| `e569cf8` | **Purpose-driven Deeper analysis: dissect the card, propose actions, demote MoM/YoY** |
| `bc0a958` | Wire card diagnostics into the insight run |
| `655640f` | Card strip + shareable `/business-insight/analysis/<id>` route |
| `9ddf5ef`, `8643495`, `0626398`, `d0482f2` | Handoff docs |

---

## 3. The five problems fixed

**A. Deeper analysis was not analysis.** `_shape_template_insights` probed tables
(`SELECT * LIMIT 50`) for any drawable column combination — zero calls to the
method engine, and it happily charted `order_id`. Now `_method_driven_insights`
plans governed *intents*, executes them R-first through the Analytical Method
Engine, and **suppresses any result that finds nothing** (materiality gate).

**B. Chat lost chart variety — twice.** The backend collapsed 26 families to five
(`_ASK_AND_RUN_SURFACE`, scatter→table), and the frontend collapsed again in
three places (`buildChart`'s pie/line/bar ternary, `VizType`, `ChartConfig`). All
four narrowings removed; chat now uses the same ranker as the cards.

**C. Chat had no analytics.** Neither ask path called the method engine, so a
chat answer had no R execution or provenance while a card on the same rows did.
`_attach_ask_analytics()` now runs it on both paths.

**D. The assistant invented insight SQL.** The ask paths received
knowledge-graph context only (documents/KPIs/tables) and **no path could look a
card up** — so "show me the query for *Material Costs vs Revenue Trend*"
produced a fabricated query. Cards store their real SQL; it is now retrievable.

**E. Deeper analysis answered a question nobody asked.** It ran month-over-month
and year-over-year on whatever had a date, because almost any dated measure
supports them — so every card got the same two comparisons and none of them said
what to *do*. Now each Risk / Trend / Opportunity card is **dissected**: where the
problem concentrates, when it shifted, how large it is, what explains it, where it
is heading — each step recording *why it was run*. Those findings ground
**proposed actions**. MoM/YoY is demoted to triggered evidence: it runs only when
the card shows change or threshold language, or a change-point / anomaly /
breach was actually detected (`should_compare_periods`).

---

## 4. Code path

### 4a. Chart selection — one ranker for every surface

```
chart_selection_best_practices.md          31 families, single source of truth
   └─ chart_catalog.fit_ranked()           per-dataset fit confidence
      └─ visualization_engine.rank_visualizations()
         ├─ business_dimensions()          ← drops identifier columns
         ├─ home_intelligence              → insight cards / deeper analysis
         └─ ask_pipeline                   → all three conversational surfaces
```

### 4b. Deeper analysis — governed methods, not shape probing

```
routes/home_intelligence.py::_run_for_project
  ├─ hi._card_diagnostic_insights()                  ← runs FIRST: dissect the cards
  │    card_diagnostics.card_family()                 risk / trend / opportunity
  │          → plan_card_diagnostics()                the ladder: localise → when →
  │                                                   quantify → explain → project
  │          → should_compare_periods()               MoM/YoY only on a trigger
  │          → analyze_methods()                      governed engine, R-first
  │          → extract_findings()                     envelope ⇒ the facts
  │          → propose_actions()                      facts ⇒ grounded next steps
  │          → plan_cross_references()                other tables/docs to check
  │          → suggested_followups()                  card-scoped questions
  │    card["diagnostics" | "proposedActions"
  │         | "crossReferences" | "suggestedQuestions"]
  ├─ hi._method_driven_insights()                    ← standalone method cards
  │    probe → deep_analysis.plan_deep_analyses()     which INTENTS the data supports
  │          → _deep_analysis_sql()                   per-intent projection
  │          → analyze_methods()                      governed engine, R-first
  │          → deep_analysis.assess_materiality()     no finding ⇒ NO CARD
  │          → card["analyticalMethod"]               R badge + Explain panel
  └─ hi._shape_template_insights()                   ← fallback only
```

### 4c. Conversation — retrieval first, then generation

```
AI Assistant · Business-Insight ask · Project-Insight ask
   └─ routes/ai_proxy.py::_ask_and_run_core          (all three flow here)
      ├─ _retrieve_stored_insight_query()            ← NEW, BEFORE generation
      │     is_query_request() && card resolves ⇒ return the STORED SQL
      ├─ _suggest_visualization() → ask_pipeline.resolve_presentation()
      │                              └─ rank_visualizations()   same ranker
      ├─ _attach_ask_analytics()  → analyze_methods()           R-first
      └─ _insight_card_context()  → response["insightContext"]  follow-up grounding
   frontend:
   conversation-turn → ResultChart → InsightChartBlock → WidgetRenderer → EChartsWidget
```

### 4d. Where the dissection surfaces — card strip + shareable route

```
intelligence-card.tsx
  └─ {!hideActions && <InsightAnalysisStrip card={card} />}
        renders NOTHING when card.diagnostics is empty
        shows: lead finding · top proposed action · "N diagnostic steps"
        → /business-insight/analysis/<insightId>

app/business-insight/analysis/[insightId]/page.tsx
  ├─ getIntelligenceSnapshot()   tenant-wide  — Business Insight cards
  └─ suggestInsights()           per-project  — Project Insight cards (fallback)
     sections: Proposed actions · How we got here (the ladder, with each step's
               rationale + chart + R method) · Check this against · Ask about this
```

Two constraints the shared card component imposes — **keep both**:

- **The strip is gated on `!hideActions`.** The same card renders on the public
  `/reports/<token>` page, where the reader has no session and the drill-down
  link would go nowhere.
- **The route resolves against both insight stores.** Business Insight cards live
  in `IntelligenceSnapshot` (tenant-wide); Project Insight cards live in
  `ProjectIntelligenceSnapshot` (per project, `suite="insights"`). The id in the
  URL does not say which produced the card, so the page tries the tenant snapshot
  and falls back to the project insights endpoint. Drop the fallback and every
  Project-Insight link dead-ends on "Analysis not available".

**Renderer note:** no renderer was added or retired. `recharts` is already gone
(zero imports, absent from `package.json`); `WidgetRenderer` is now a thin
**adapter** delegating to `EChartsWidget` with no chart library inside. **Keep
it** — it is the single `WidgetConfig → ECharts` mapping shared by dashboards,
cards, home pins and chat. `EChartsWidget` is the renderer; `WidgetRenderer` is
the adapter.

---

## 5. Files & verification

**New**
| File | Purpose | Tests |
|---|---|---|
| `app/services/deep_analysis.py` | intent planning, materiality gate, evidence presentation | 34 |
| `app/services/ask_pipeline.py` | shared conversational presentation + follow-up grounding | 14 |
| `app/services/insight_registry.py` | card retrieval by partial title, stored-SQL answers | 21 |
| `app/services/card_diagnostics.py` | the diagnostic ladder, MoM/YoY triggers, action proposals, cross-refs | 34 |
| `web-ui/.../home/insight-analysis-strip.tsx` | compact strip on the card | 6 |
| `web-ui/app/business-insight/analysis/[insightId]/page.tsx` | the shareable full analysis | — |
| `web-ui/.../ai-result-view.chartfamily.test.tsx` | locks the chart-family collapse shut | 4 |

**Modified:** `visualization_engine.py` (identifier detection),
`home_intelligence.py` (+ `routes/`), `routes/ai_proxy.py`,
`web-ui/lib/api/ai-actions.ts`, `web-ui/lib/api/conversational-analytics.ts`,
`web-ui/components/ai/ai-result-view.tsx`,
`web-ui/components/tablescope/conversation/conversation-turn.tsx`,
`web-ui/lib/api/home-intelligence.ts` (diagnostic/action/cross-ref types),
`web-ui/components/tablescope/home/intelligence-card.tsx` (strip mount).

| Suite | Result |
|---|---|
| `test_deep_analysis.py` | 34 / 34 |
| `test_card_diagnostics.py` | 34 / 34 |
| `test_insight_registry.py` | 21 / 21 |
| `test_ask_pipeline.py` | 14 / 14 |
| `test_chart_catalog.py` | 18 / 18 |
| `test_visualization_engine.py` | 27 / 27 |
| web-ui `vitest` | 248 / 248 (40 files) |
| `tsc` · `ruff` · `next lint` | clean |

CI:

```bash
cd platform-api && pytest -q && ruff check app tests && mypy app
cd ../ai-server/tablescope-ai-api && pytest -q
cd ../../web-ui && npm run typecheck && npm test -- --run && npm run build
```

---

## 6. Deploy

```bash
docker compose build web-ui platform-api        # both changed
docker compose up -d web-ui platform-api platform-api-worker r-analytics
```

Environment on **platform-api *and* platform-api-worker** (the worker generates
insights):

```
ANALYTICAL_METHOD_ENGINE_MODE=hybrid
R_ANALYTICS_ENABLED=true
R_ANALYTICS_FAILURE_MODE=python_fallback
```

Then **clear insight caches** so cards regenerate through the new path
(Clear-cache buttons, or `scripts/delete_insight_caches.py`).

> Card retrieval reads the Business-Insight cache. Clearing it empties the
> registry until cards regenerate — regenerate before testing §7 retrieval.

---

## 7. Verify live

**Deeper analysis**
- Cards are YoY / MoM / actual-vs-target / co-movement / contribution / anomaly /
  forecast — not shape-probe charts.
- **No card is keyed on an identifier column.**
- Cards show the **R Analytics badge**; Explain shows method, engine, n, caveats.
- A method that found nothing produces **no card** — correct, not a regression.

**Card dissection — the reported complaint**
- A Risk / Trend / Opportunity card carries a **Deeper-analysis strip**: one lead
  finding, one proposed action, `Full analysis →`.
- An **informational** card carries **no strip** — it was not dissected, and must
  not advertise an analysis.
- `Full analysis →` opens `/business-insight/analysis/<id>` and every step states
  **why it was run**, not just what it found.
- **Test the link from a Project Insight card too** — that is the path that needs
  the per-project fallback (§4d).
- The URL is shareable: paste it in another browser session (same tenant) and the
  analysis loads.
- **MoM/YoY no longer appears on every card.** A card with no change/threshold
  language and no detected change-point should show *no* period comparison; a
  trend card should show one, labelled with what triggered it.
- Open a shared **`/reports/<token>`** page and confirm **no strip** appears.

**Conversation — test all three surfaces**
- Two-measure question → **scatter** (was forced to a table).
- Two-dimension question → **heatmap**.
- bar / line / pie still render (same ECharts path); a table answer still tables.
- Chat bubble shows the **R Analytics badge** with method + n.

**Insight retrieval — the reported failure**
- `Please display query for Business Insight Title: Material Costs vs Revenue Trend`
  → returns the card's **stored** SQL verbatim, not a generated one.
- A **partial** title works: `show me the query for material costs`.
- An ambiguous fragment (e.g. `revenue` when two revenue cards exist) → the
  assistant **asks which**, rather than answering about one.
- A card with no stored SQL → says so; it must not invent one.
- `why did that happen?` still goes through normal generation (unchanged).

---

## 8. Follow-ups deliberately left to you

1. **"Ask about this card" wiring.** `_ask_and_run_core` already accepts
   `card_context`, and `ask_pipeline.build_insight_followup(question, card)` →
   `followup_prompt(...)` builds the grounded question. Send the card payload
   from the card's ask entry point. No new endpoint needed.
1b. **The analysis page's "Ask about this insight" chips** link to
   `/ai?q=<question>` — they pre-fill the assistant but do **not** yet pass the
   card as `card_context`, so the answer is not card-grounded. Wire them through
   the same `build_insight_followup` path as (1).
2. **Surface `analyticalMethod` / `insightContext` in the chat bubble's Explain
   area** so the R badge and card grounding are visible in conversation — the
   component already renders this shape for cards.

---

## 9. Known checks after deploy

**Materiality result keys.** The gates read keys defensively (`anomalies`,
`change_points`, `p_value`, `correlation`, `r_squared`, `relative_change` /
`percent_change`, …). The R implementations' actual key names were not visible
from the authoring container. If a gate reads keys the R methods do not emit,
that intent falls through to **material** — safe (you see cards, you do not lose
them), but unfiltered. Open one anomaly card and one driver/correlation card,
read the Explain panel's keys, and add any real names to the lookup lists in
`_MATERIALITY_RULES` (`deep_analysis.py`). One line per key.

**Diagnostic depth vs. run time.** Each dissected card now runs up to `max_steps`
governed methods on top of the card's own query, so an insight refresh does more
work than before. If a refresh times out, lower the cap where
`_card_diagnostic_insights()` calls `plan_card_diagnostics(...)` rather than
disabling the feature — the ladder is priority-ordered, so a smaller cap keeps
the most actionable steps (localise, then when) and drops the speculative tail.

**Retrieval scope.** `load_tenant_insight_cards()` reads cards for the caller's
tenant (optionally filtered by project). Confirm on a multi-project tenant that
a question resolves to the intended card, and report if project scoping should
be tightened.

---

## 10. Report back

Byte-identical confirmation (or exact deviations + reasons); CI totals per suite;
deploy + cache-clear confirmation; screenshots of a YoY card, an actual-vs-target
card, a co-movement (dual-axis) card, an anomaly card with its R badge, a scatter
chat answer, a heatmap chat answer, **a Risk card's Deeper-analysis strip and its
full-analysis route**, **the same route reached from a Project Insight card**,
and **the stored-SQL retrieval answering the "Material Costs vs Revenue Trend"
question**; plus any materiality key names you added.
