# Devin: merge + deploy — insight, conversation & retrieval pipeline

Repository: `lhoskins/tablescope-lh`
**Branch to merge:** `claude/deep-analysis-business-value`
**Base:** `devin/r-echarts-e2e-validation` (deployed lineage; already has the
chart-fit work from PR #96)

**20 commits · 49 files · +7990 / −78 · all tests green** (§5)

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
| `1c9131a` | **Analysis page evidence: real chart family, R's own anomaly markers, all rows, open ask box** |
| `5749e49` | **Drill-down answers instead of asking: 4→24 card coverage, ranked segments, executed cross-references** |
| `3a5f54c` | **Three reported defects: mid-session logout, uncorrectable 2FA code, lost place on back** |
| `dcbbbc9` | **Claim verification: the card's own narrative is put to a statistical test** |
| `<deploy>` | Deployment runbook; cache-clear script fixed to clear all three stores |
| `9ddf5ef`, `8643495`, `0626398`, `d0482f2`, `32c962a`, `d43446c`, `b5db428` | Handoff docs |

---

## 3. The eight problems fixed

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

**F. The drill-down asked questions instead of answering them.** Three separate
causes, all reported from one screenshot:

1. **Coverage.** `_card_diagnostic_insights` capped at `max_cards=4` and the call
   site never overrode it, so **at most four cards per run were ever dissected** —
   only 2 of 29 risk cards had a *Full analysis* link.
2. **The group-comparison chart was meaningless.** `compare_multiple_groups`
   projects **raw rows on purpose** (Welch's ANOVA needs the within-group spread),
   and the chart drew those same rows — plotting the first 25 of 948 *individual
   records*, so one work centre repeated down the axis with every bar the same
   height. It was never showing work centres at all.
3. **Cross-references were listed, not run.** "Does `mfg_labor_rates` show the
   same pattern?" is a question the system can answer itself.

Fixed respectively by a tunable card budget, `summarise_group_evidence()` (fold
to one ranked entry per group *for the chart only*), and `_run_cross_reference()`
(join the two sources on their shared period and run the governed correlation).

**G. Three defects reported from the deployed build.** Independent of the
insight work, and the first is the most serious thing in this branch:

1. **Sessions had no refresh path at all.** The JWT was minted for 60 minutes at
   login and **never renewed — no refresh endpoint existed anywhere**. The first
   request past the hour returned 401 and `api-client` cleared the token and
   redirected to login. Anyone working longer than an hour was logged out
   mid-task. Fixed with sliding renewal (§4g).
2. **A mistyped 2FA code could not be corrected.** `OtpInput`'s autoFocus effect
   was keyed on `digits.length`, so *every* deletion re-ran the mount effect,
   which calls `focus()` and resets the caret to the end. Deleting a wrong middle
   digit jumped to the end and the replacement landed there. The effect now runs
   once on mount.
3. **Back from Full analysis lost the reader's place.** The link went to
   `/business-insight`, remounting the feed with panels collapsed —
   `InsightPanel` holds open state locally, so browser history cannot restore it.
   The link now carries the insight id in the hash; the holding panel opens and
   the card scrolls into view.

**H. The card asserted causes it never tested.** A card reads "gross margin has
been declining …, **indicating rising material costs** and potential
profitability issues." The decline was measured; the clause after "indicating"
names a *different* measure in a *different* table and **nothing ever checked
it** — a hypothesis printed in the same voice as the finding, and the part most
likely to be acted on. `claim_verification` now extracts those clauses, locates
the measure each names anywhere in the project, and runs the governed trend
method over its history. Four verdicts: **confirmed** (with the magnitude, so
"rising" becomes "rose 18.4% over 2024-01 to 2026-01"), **not supported** (the
card's narrative is wrong — the most valuable outcome), **inconclusive** (moved,
but not significantly), **not testable** (no measure matches — said plainly).

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

### 4e. Evidence on the analysis page — chart, markers, rows, ask box

```
_card_diagnostic_insights()  attaches per step:
   presentation   deep_analysis.evidence_presentation(intent)   line/bar/scatter + layers
   markers        card_diagnostics.extract_markers(intent, env) R's OWN flagged indices
   roles          {x, y, y2} from the projection that ran
   result         the full evidence rows

lib/insights/diagnostic-chart.ts::buildDiagnosticChart()
   → honours `presentation`, keeps EVERY row in projection order, plots `roles`
   → options.markedIndices / markedChangePointIndex

EChartsWidget  explicit markedIndices WIN over the 2-sigma re-derivation
analysis page  "See all N observations" → EvidenceTable, flagged rows highlighted
               InsightAskBox → aiActionsApi.askAndRun(card_context with base_sql)
                  └─ _ask_and_run_core → ask_pipeline.build_insight_followup()
                                       → followup_prompt()  ← now includes the SQL
```

**Three things here are load-bearing — do not "simplify" them:**

- **`buildDiagnosticChart` is deliberately not `buildChart`.** The conversational
  builder ranks bars by magnitude and caps at 25 points. Correct for chat; applied
  to a 31-period series it reorders the timeline by value and drops six
  observations. That was the reported "scrambled dates" bug. Evidence keeps row
  order and every row.
- **`sortBy` on `WidgetConfig` is inert** — no renderer reads it. Row order is the
  only order. Do not "fix" ordering by setting `sortBy`.
- **Explicit `markedIndices` must keep winning over `showAnomalies`.** R's
  `detect_anomalies` fits an ETS model, so a flagged point can sit *inside* 2σ of
  the mean. Letting the heuristic run would mark a different point than the
  sentence above the chart names.

### 4f. Answering the drill-down — coverage, ranked segments, executed leads

```
_card_diagnostic_insights(max_cards=None, max_steps=5, max_cross_refs=3)
  ├─ _diagnostic_card_budget()        env INSIGHT_DIAGNOSTIC_CARD_BUDGET, default 24
  │                                   (was a hard-coded 4 — the coverage bug)
  ├─ per dissected card:
  │    plan_card_diagnostics() → _run_diagnostic() → analyze_methods()
  │    IF intent in GROUP_EVIDENCE_INTENTS and spec.group_by:
  │        summarise_group_evidence(RAW rows, group, measure)
  │           → one ranked entry per group, `marked` = clear leader or None
  │        describe_group_leader(...)  → finding NAMES the segment
  │        findings["top_segment"]     → propose_actions() gets a target
  │        presentation := bar, markers := {anomalyIndices:[marked]}
  └─ per other table in ctx.tables (bounded by max_cross_refs):
       _run_cross_reference()
         _cross_reference_sql()   aggregate BOTH tables on their own period,
                                  JOIN on period, ORDER BY period
         < 8 overlapping periods ⇒ skip (not evidence)
         analyze_methods(intent="relationship_numeric")
         assess_materiality()     immaterial ⇒ NO step
         _relationship_direction() "moves together" / "one rises as the other falls"
         ⇒ diagnostic{stage: corroborate, crossReference: <table>}
```

**Three things here are load-bearing — do not "simplify" them:**

- **The group-comparison SQL must keep returning RAW rows.** It looks like an
  obvious candidate for a `GROUP BY`, and that would break the analysis: Welch's
  ANOVA tests whether group *distributions* differ and needs the within-group
  spread. The aggregation belongs in `summarise_group_evidence()`, which shapes
  the **chart only** — the method still receives raw rows. Aggregating in SQL
  would leave one row per group and the test would have nothing to compare.
- **`marked` is `None` on a flat ranking, by design.** A leader is claimed only
  when it clears the runner-up by ≥10%. Always marking index 0 would point at
  noise and the finding would name a segment that is not actually the problem.
- **Immaterial cross-references must produce nothing.** An uncorrelated table is
  not evidence; emitting a "no relationship" step per table pair would bury the
  real findings.

**Wording constraint:** a cross-reference establishes *co-movement*, not
causation. The UI says "candidate cause or lever" deliberately. Do not
strengthen this to "causes" / "driven by" anywhere in the copy.

### 4g. Sliding session renewal — the auth change

```
AuthMiddleware.dispatch()
  decode_access_token(token)          unchanged: invalid ⇒ 401 SESSION_EXPIRED
  response = await call_next(request)
  renew_access_token(token)           None unless PAST HALFWAY through its life
    ├─ re-mints from the RAW claims   → `aal` (2FA level) survives
    ├─ `ses` = original session start → preserved across renewals
    └─ now - ses >= jwt_session_absolute_ttl_minutes ⇒ None (hard stop)
  response.headers["X-Session-Token"] = renewed
      ↑ must stay in CORS expose_headers (app/main.py) or the browser hides it

web-ui/lib/api-client.ts   request() · uploadFile() · streamRequest()
  response.headers.get("X-Session-Token") ⇒ storeToken(...)
```

**Four things here are load-bearing:**

- **Renewal must re-mint from the raw claims, not from a fixed field list.**
  `aal` records that the user cleared 2FA. Rebuilding the token from named
  fields would drop it and silently downgrade a verified session.
- **`ses` must be carried forward.** If each renewal reset it, the absolute cap
  would never fire and sessions would slide forever.
- **Tokens minted before this feature have no `ses`** and fall back to their
  `iat`, so existing sessions are capped rather than becoming immortal.
- **`X-Session-Token` must stay in `expose_headers`.** Drop it and the browser
  silently hides the header — every session then expires at the TTL exactly as
  before, with no error to point at the cause.

Renewal is deliberately *not* a refresh endpoint: it follows activity on the
requests already being made, so there is no extra round trip and no refresh
token to store. An **idle** session still expires on schedule.

### 4h. Claim verification — testing the narrative

```
_card_diagnostic_insights()
  └─ _verify_card_claims()                       ← runs BEFORE the ladder
       claim_verification.extract_claims(card)    summary/title/callout prose
         _CLAIM_PATTERNS   indicating · suggesting · driven by · due to ·
                           because of · reflecting · attributable to ·
                           resulting from
         _split_conjuncts()  "rising X and potential Y" ⇒ TWO claims
       match_measure(claim, every (table, column) in the project)
         └─ None ⇒ verdict "untestable" (stated, not dropped)
       SELECT period, AGG(measure) … GROUP BY period ORDER BY period
       analyze_methods(intent="detect_trend")     governed engine, R-first
       check_claim(...) + percent_change(rows)    ⇒ verdict + magnitude
  ⇒ diagnostic{stage: "verify", claimVerdict, claimMeasure, claimTable}
```

**Four things here are load-bearing:**

- **Coordinated clauses must stay split.** "rising material costs and potential
  profitability issues" is two assertions about two measures; checked as one, the
  blurred terms match *neither* column and the real claim goes untested.
- **A shared verb distributes, but never onto a hedged conjunct.** "rising X and
  Y" asserts both rise; giving "potential Y issues" a direction invents a claim
  the card never made — and could then report it *contradicted*.
- **Unit suffixes are excluded when matching** (`_UNIT_TOKENS`). `MaterialCostUSD`
  is the same measure as `MaterialCost`; counting `usd` against the match drops a
  correct column below threshold.
- **Matching stays conservative** (`min_score`). A confident verdict about the
  wrong column is worse than reporting that the claim could not be checked.

**Wording constraint:** a confirmed claim means the named measure moved the way
the card said, over the same window. It is co-movement, not proof of cause. Do
not restate a `supported` verdict as "caused by".

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
| `app/services/card_diagnostics.py` | ladder, MoM/YoY triggers, actions, markers, group evidence | 48 |
| `web-ui/.../home/insight-analysis-strip.tsx` | compact strip on the card | 6 |
| `web-ui/lib/insights/diagnostic-chart.ts` | evidence chart: intent's family, full series, method markers | 16 |
| `web-ui/.../home/insight-ask-box.tsx` | free-text ask grounded in the card's query | 5 |
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
| `test_card_diagnostics.py` | 48 / 48 |
| `test_claim_verification.py` | 24 / 24 |
| `test_jwt.py` (incl. 9 renewal / security-boundary tests) | full |
| `test_insight_registry.py` | 21 / 21 |
| `test_ask_pipeline.py` | 17 / 17 |
| `test_chart_catalog.py` | 18 / 18 |
| `test_visualization_engine.py` | 27 / 27 |
| web-ui `vitest` | 281 / 281 (43 files) |
| `tsc` · `ruff` · `next lint` | clean |

CI:

```bash
cd platform-api && pytest -q && ruff check app tests && mypy app
cd ../ai-server/tablescope-ai-api && pytest -q
cd ../../web-ui && npm run typecheck && npm test -- --run && npm run build
```

---

## 6. Deploy

**No database migration is required** — this branch changes no schema. Only
`platform-api` and `web-ui` changed; `r-analytics`, `teiid`, `nginx` and the
datastores are untouched and must not be rebuilt.

### 6.1 Configuration

Both new settings are already wired into `docker-compose.yml` with working
defaults, and `platform-api-worker` inherits them through the
`&platform_api_env` anchor — **the worker generates insights, so it needs them
too**. Deploy works with no `.env` change at all; set these only to override:

| Variable | Default | What it does |
|---|---|---|
| `INSIGHT_DIAGNOSTIC_CARD_BUDGET` | `24` | Cards dissected per run. Trades drill-down coverage against refresh time. |
| `JWT_SESSION_ABSOLUTE_TTL_MINUTES` | `720` | Ceiling on how long activity may extend one session. |

Confirm these are already correct for the R path (unchanged by this branch):

```
ANALYTICAL_METHOD_ENGINE_MODE=hybrid
R_ANALYTICS_ENABLED=true
R_ANALYTICS_FAILURE_MODE=python_fallback
```

> **If you add any further variable**, it must be listed in the `environment:`
> block of `docker-compose.yml` as well as `.env` — compose only forwards what
> it explicitly names. A variable set only in `.env` is silently ignored, which
> looks exactly like the feature not working.

### 6.2 Build and start

```bash
# Both changed images. r-analytics is NOT rebuilt.
docker compose build platform-api web-ui

# platform-api-worker runs the same image as platform-api, so it must be
# recreated too or it keeps serving the OLD insight code.
docker compose up -d platform-api platform-api-worker web-ui

docker compose ps          # all healthy before continuing
docker compose logs --tail=50 platform-api platform-api-worker
```

### 6.3 Smoke-check before clearing anything

Cheap checks that catch the two silent failure modes:

```bash
# 1. The renewed-session header must be visible to the browser. If
#    Access-Control-Expose-Headers is missing, sessions expire at the TTL
#    exactly as before, with no error anywhere to point at the cause.
curl -si -X OPTIONS https://<host>/api/ai/home-intelligence/snapshot \
  -H "Origin: https://<host>" -H "Access-Control-Request-Method: GET" \
  | grep -i "access-control-expose-headers"
#    expect: access-control-expose-headers: X-Session-Token

# 2. The worker picked up the new settings.
docker compose exec platform-api-worker env \
  | grep -E "INSIGHT_DIAGNOSTIC_CARD_BUDGET|ANALYTICAL_METHOD_ENGINE_MODE"
```

### 6.4 Clear insight caches, then regenerate

Cards are cached per user. Existing cards were produced by the old code and
carry **no** diagnostics, claim checks or cross-references, so nothing new
appears until they regenerate.

```bash
docker compose exec platform-api python scripts/delete_insight_caches.py
# expect all three counts, e.g.
# {'business_insight_results': N, 'intelligence_snapshots': N, 'project_intelligence_snapshots': N}
```

or use the **Clear cache** buttons on Business Insight / Project Insight.

> **This script was fixed in this branch and the fix matters.** It previously
> cleared only `BusinessInsightResult` and the `project_insight` suite — it never
> touched `IntelligenceSnapshot` (the tenant-wide snapshot the Business Insight
> feed *and* the full-analysis route actually read) nor the `insights` suite.
> Running the old version would leave both surfaces serving pre-deploy cards,
> which looks **exactly** like the new features not working. If you see no
> diagnostics after clearing, confirm you are running this branch's script and
> that all three counts came back non-zero.

Then **refresh Business Insight and wait for the run to finish.**

> **Order matters.** Card retrieval (§7) reads the Business-Insight cache, so
> between clearing and regenerating, "show me the query for …" has nothing to
> resolve against. Regenerate before testing retrieval.

> **Expect this run to take materially longer than before** — up to 24 cards are
> dissected instead of 4, each running several governed methods plus
> cross-reference correlations. **Time it and report the number** (§9). If it
> times out, lower `INSIGHT_DIAGNOSTIC_CARD_BUDGET` and re-run; do not disable
> the feature.

### 6.5 Rollback

No migration means rollback is just redeploying the previous images:

```bash
git checkout <previous-sha> && docker compose build platform-api web-ui
docker compose up -d platform-api platform-api-worker web-ui
docker compose exec platform-api python scripts/delete_insight_caches.py
```

Clear caches on the way back down too: cards generated by this branch carry
fields the old frontend ignores, but the stale cache would otherwise mask
whether the rollback took effect.

Sessions survive a rollback — a token issued with a `ses` claim still validates
against the old code, which simply ignores the extra claim.

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

**Analysis-page evidence — the reported follow-ups**
- An anomaly step renders as a **line in date order**, not a bar sorted by
  magnitude, and shows **all** observations (a 31-period series must show 31
  points, not 25).
- The flagged observation(s) carry a **red marker at the point the method
  named** — cross-check the marked period against the Explain panel's
  `anomalies` indices; they must agree.
- **"See all N observations"** expands the evidence table and the flagged rows
  are highlighted.
- The **ask box accepts free text**. Ask something the suggestions do not cover
  (e.g. "break this down by supplier and join the contract list") and confirm
  the generated SQL **builds on the card's query** rather than starting over.
- Suggested questions and cross-reference prompts **submit into the same box**
  (they no longer navigate away to `/ai?q=`).
- Title and summary show **bold text, not literal `**`**.

**Claim verification (§3H)**
- Open the *Rising Material Costs* card's full analysis. The **first** step is
  **Checking the card's claim**, quoting the claim and carrying a verdict chip.
- A confirmed claim **states the magnitude and window** ("rose 18.4% over
  2024-01 to 2026-01"), not just "rising".
- Confirm the tested measure (shown as `tested: <column> in <table>`) is the one
  the claim actually names. **Report any mismatch** — a wrong column produces a
  confident verdict about the wrong thing.
- A claim naming something the project has no measure for reads **Not testable**,
  not silence.
- If a claim comes back **Not supported**, that is a genuine finding: the card's
  narrative is wrong. Screenshot it.

**The three reported defects (§3G)**
- **Session:** sign in, then keep using the app past the token TTL. You must
  **not** be logged out. Confirm in devtools that responses carry
  `X-Session-Token` once past halfway, and that `tablescope.token` in
  localStorage changes. If the header is absent from the browser (but present
  server-side), `expose_headers` is missing — see §4g.
- **Session, 2FA:** do the same on a **2FA-verified** session and confirm you are
  not re-prompted for MFA after a renewal — that would mean `aal` was dropped.
- **Session, idle:** leave a tab idle past the TTL and confirm the next request
  *does* land on login. Renewal follows activity; idle sessions must still end.
- **2FA entry:** type a 6-digit code, click a **middle** cell, delete that digit
  and retype it. The corrected digit must land **where it was deleted**, not at
  the end.
- **Back navigation:** open a card's *Full analysis*, then *Back to this
  insight*. The panel holding that card must be **open** and the card scrolled
  into view (with a brief ring) — not the top of a collapsed feed.

**Coverage, segments and cross-references — the reported regressions**
- **Most Risk/Trend/Opportunity cards now carry a *Full analysis* link**, not 2
  of 29. If coverage is still thin, check the worker log for
  `card diagnostics failed` before assuming the budget.
- A **"Where X is concentrated"** step shows **one bar per group, ranked**, with
  **no repeated category labels**. Repeated labels means the raw-row path is back
  — see §4f.
- Its finding **names the segment** ("WC-007 leads at 42 per record, 320% above
  WC-001"), not just `p=0.000`, and the proposed action **targets that segment**
  instead of "Investigate before acting".
- On a genuinely even distribution, **no bar is marked** and the finding does not
  name a leader. That is correct.
- A **corroboration step** appears for at least one related table, badged
  `cross-checked · <table>`, stating **direction** (moves together / opposite).
- Tables that were cross-checked **do not also appear** under "Not yet checked".
- **Timing:** compare insight-refresh duration before/after. Report it — this
  change does materially more work per run.

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

> Items 1 and 1b from the previous revision of this doc are **done** — the
> card-grounded ask path is wired (`1c9131a`). Do not re-implement them.

1. **Surface `analyticalMethod` / `insightContext` in the chat bubble's Explain
   area** so the R badge and card grounding are visible in conversation — the
   component already renders this shape for cards.
2. **Knowledge-graph entities for insight cards.** Card retrieval is currently a
   title match over the cached cards (`insight_registry`). Promoting cards to KG
   entities would let the assistant reason over them relationally rather than by
   name. Design work, not a patch.
3. **The suggested-question chips are shortcuts, not the interface.** They sit
   below the free-text box now. The user's stated preference is that the system
   answers rather than asks; if the chips still read as the system asking, delete
   them — the ladder already carries the answered questions.

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

**Diagnostic depth vs. run time — the main operational risk of this merge.**
A run now dissects up to 24 cards (was 4), each executing up to 5 governed
methods plus up to 3 cross-reference correlations. That is roughly an order of
magnitude more analytical work per refresh. **Measure it and report the number.**
If refreshes time out, lower `INSIGHT_DIAGNOSTIC_CARD_BUDGET` first (the ladder
is priority-ordered, so a smaller `max_steps` keeps localise/when and drops the
speculative tail). Do not disable the feature to fix a timeout.

**Cross-reference period grain.** `_cross_reference_sql()` joins two tables on
their own period columns. Weekly-against-monthly sources will match on few or no
periods and correctly produce **nothing** rather than a bad correlation. If two
sources you *expect* to relate stay silent, mismatched grain is the first thing
to check — not a bug in the correlation. Report any pair where this bites; the
fix is a date-truncation in the projection, which needs to know your warehouse
dialect.

**Co-movement is not causation.** A corroboration step means two series moved
together over the overlapping periods. The copy says "candidate cause or lever"
on purpose. Do not strengthen it.

**Session renewal is the highest-risk change in this merge to get wrong.** It
touches authentication. The 9 tests in `test_jwt.py` cover the boundaries
(absolute cap enforced, legacy tokens capped, tampered and expired tokens never
renewed, `aal` and identity preserved) — **run them and report the totals**. If
anything about the sliding-session model is unacceptable for your security
posture, say so in the PR rather than weakening it silently; the alternative
(a real refresh-token flow) is a larger design change, not a tweak.

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

Also report, specifically:
- **how many cards now carry a *Full analysis* link** (was 2 of 29);
- a **screenshot of a ranked group chart** with the leading bar marked and the
  segment named in the finding;
- a **screenshot of a corroboration step** with its direction statement;
- **insight-refresh duration before and after** (§9), and the value of
  `INSIGHT_DIAGNOSTIC_CARD_BUDGET` you settled on;
- **confirmation that a session survives past the token TTL while active**, that
  a 2FA-verified session is not re-prompted after renewal, and that an **idle**
  session still expires;
- `test_jwt.py` totals.
