# Devin prompt: show R on Business Insight cards + route more insights to R + harden method-activation UI

Repository: `lhoskins/tablescope-lh`
Base branch: **`devin/r-catalog-activation-ui`** (PR #75 head — builds directly on
what is now deployed). Feature branch: `devin/r-insight-provenance-and-wiring`.
Re-verify PR #75's paths if it has merged. Do not deploy as part of the task.

Outcome: **a refreshed Business Insight both runs R and visibly shows it**, and
admins can reliably activate/deactivate methods from the UI.

Context (verified on the base branch, so you can trust the starting point):
- Execution provenance already lands correctly. `ExecutorRegistry.execute`
  stamps `executionEngine` (`"r"`/`"python"`) + `fallbackFrom`, and
  `result_envelope.build` reads `exec_result["executionEngine"]`
  (`result_envelope.py:68-70`). R-first + Python fallback is wired
  (`R_ANALYTICS_FAILURE_MODE`).
- The envelope **already reaches the Business Insight card** as
  `card["analyticalMethod"]` (`home_intelligence.py:3264`, only when
  `method_envelope.status == "ok"`).
- `web-ui/components/ai/method-envelope.tsx:43` already renders
  `Engine: {envelope.executionEngine}` — but only inside the Ask Anything
  `ResponsePresenter`, **not** on the insight cards.
- Business-insight method routing is gated by a 2-entry table:
  `_CATEGORY_INTENT_HINTS = {"trend": "detect_trend", "relationship": "relationship_numeric"}`
  (`home_intelligence.py:2680`). Nothing routes to the Set B time-series methods.
- The activation UI **exists and is wired** (sidebar link `sidebar.tsx:204`;
  toggle + `implementation_available` guard in
  `web-ui/app/admin/analytical-methods/page.tsx`; API
  `POST /api/ai/methods/{id}/activate|deactivate` in
  `routes/analytical_methods.py` + `catalog_admin.py`, with cache invalidation).

---

## Workstream 1 — Show R on the insight cards (provenance badge + Analysis details)

The data is already on the card; this is mostly frontend. Do **not** infer R from
config — key strictly off `card.analyticalMethod.executionEngine === "r"`.

`web-ui/components/tablescope/home/intelligence-card.tsx` (Business Insight / Home):
- When `card.analyticalMethod?.executionEngine === "r"`, render a compact
  **R Analytics** badge on/adjacent to the existing **Explain** action (a small
  pill in the same action group; do not replace "Explain"). Tooltip/aria: "This
  insight includes analysis executed with R." Light/dark safe; must not collide
  with severity/feedback/governance badges.
- **Never** show the badge for `executionEngine === "python"`, a fallback result
  (`fallbackFrom === "r"` → engine is python → no badge), missing
  `analyticalMethod`, or a non-`ok` status.
- Add an **Analysis details** section inside the Explain surface (collapsed by
  default) showing only truthful fields from `analyticalMethod`: Engine (R /
  Python), Method (name + id), Status, Quality, Warnings/caveats/assumptions
  (bounded), and a **Fallback** disclosure when `fallbackFrom === "r"` ("R
  unavailable; computed via Python fallback"). Reuse the existing
  `MethodEnvelopeBlock`/`method-envelope.tsx` rendering where practical rather
  than duplicating the vocabulary.

`web-ui/components/tablescope/project-insight/project-insight-screen.tsx`
(`InsightCardItem`): wire the **same** badge/details helper, but note Project
Insights carry no `analyticalMethod` today (the service does not run the engine),
so the badge simply never shows and Analysis details shows the legacy
"provenance not available" state. Do not fabricate provenance.

Persistence: confirm `card.analyticalMethod` is included in the persisted
`business_insight_results` snapshot (not just the live response) so the badge
survives refresh/pin. The cache was cleared (migration `0067`) so refreshed cards
rebuild with it; verify a pinned/reloaded card keeps the badge.

Extract a shared helper (`getInsightEngineDisplay(analyticalMethod)` +
`RAnalyticsBadge`) so both card types use one vocabulary.

## Workstream 2 — Route more Business Insights to R (intent wiring)

Today only `trend` and `relationship` analyses select a method (hence run R).
Make the common business-insight categories route to executable methods,
including the new Set B time-series methods.

In `home_intelligence.py`:
- **Enumerate the actual categories** produced by insight generation (grep the
  analysis/category taxonomy this file emits) and expand `_CATEGORY_INTENT_HINTS`
  so each maps to the best available intent — e.g. group-comparison categories →
  `compare_two_groups`/`compare_multiple_groups`; period/change categories →
  `compare_periods`; forecast/outlook → `forecast_time_series`; anomaly/outlier →
  `detect_anomalies`; driver/contribution → `contribution_to_change`;
  descriptive → `describe_numeric`. Only map a category to an intent that has an
  active executable method and whose `resolve_roles` accepts the data shape.
- **Strengthen `infer_intent`** (`analytical_method_engine/intent.py`) for the
  phrasing that drives Set B — "month over month / MoM / YoY / rate of change" →
  `compare_periods`; "what should we expect / forecast / next quarter" →
  `forecast_time_series`; "unusual / spike / anomaly" → `detect_anomalies`; "when
  did it change" → `detect_change_point`. This helps even when the category hint
  is absent.
- Keep the engine **fail-closed per item** (the existing
  `_attach_method_envelopes` guard): if no method fits, attach no envelope and
  still render the card (regression guard for the earlier 6→0 incidents). Do not
  force a method where the data shape does not support the intent.

Net effect: trend/relationship **and** period/forecast/anomaly/group business
insights execute R (Set A with Python fallback; Set B R-only), and Workstream 1
surfaces the badge on them.

## Workstream 3 — Verify and harden the method-activation UI

The activation UI is present on the base branch — **verify it end-to-end on the
deployment first** (sidebar "Analytical Methods" → toggle activate/deactivate on
an implemented method → the method becomes selectable). Then harden:

1. **Persistence across redeploy/reseed.** The seeder is idempotent-by-version
   and creates methods once, so UI activations on the active version persist
   across reboots. But a **catalog version bump** seeds a new version from
   defaults and would drop prior UI activations. Add carry-forward: when
   activating a new version, copy `is_executable`/`status` overrides from the
   previous active version for methods still present (or document the limitation
   explicitly and surface it in the admin UI). Do not silently lose activations.
2. **R-availability robustness.** `catalog_admin.available_r_methods()` queries
   the R service; if that call momentarily fails it must not flip every R
   method's `implementation_available` to false and disable their toggles. Cache
   the last good list and/or treat an unreachable R service as "unknown" rather
   than "unavailable" (don't hard-disable). Keep the activation guard itself
   strict at write time (still reject activating a truly unimplemented method).
3. **Clarity.** When a toggle is disabled, the tooltip must say why ("No Python or
   R implementation for this method"). Make explicit (docs/PR notes) that
   activating a reference-tail method requires implementing it first — the UI
   cannot conjure an executor.
4. Keep it `ADMIN`-gated with audit logging (already present); confirm a
   deactivated method is no longer selected (registry cache invalidated).

## ECharts rollout — split out

The ECharts-default work (dashboards + insight cards + Pin/Add-to-Dashboard, and
retiring recharts) is now a **separate** Devin prompt:
`docs/devin-prompt-echarts-default-rollout.md`. Keep this PR focused on R
provenance, intent wiring, and activation-UI hardening. The badge work here reads
`analyticalMethod.executionEngine` and is renderer-agnostic, so the two PRs are
independent.

---

## Tests

Backend:
- Intent wiring: a business-insight analysis in each newly-mapped category selects
  the expected method; unsupported data shapes still yield no envelope and the
  card still renders.
- Provenance: an R-executed analysis yields `analyticalMethod.executionEngine ==
  "r"`; a Python-fallback yields `"python"` + `fallbackFrom == "r"`; both
  serialize onto the card and into the snapshot.
- Activation: activate/deactivate persists on the active version and survives a
  simulated reboot; version-bump carry-forward keeps prior activations;
  R-service-unreachable does not mass-disable toggles; non-admin → 403;
  activating an unimplemented method → rejected.

Frontend (`intelligence-card`, `project-insight-screen`, admin page):
- R provenance → R Analytics badge on Explain; python/fallback/missing → no
  badge; Explain reveals Analysis details with engine/method/warnings/fallback;
  legacy cards show the unavailable state only after Explain.
- Admin: engine badges + activate/deactivate toggle; disabled-with-tooltip when
  no implementation; toggle updates the row without reload.
- Existing feedback/review/governance/pinning/Save-to-Dashboard behavior intact.

Repo-standard: `pytest -q`, `ruff`, `mypy app`; web-ui `typecheck`,
`test -- --run`, `build`. Known Teiid-name-resolution failures are environmental
— show they also fail on base.

## Definition of done

- Refreshing a Business Insight that maps to an R method **runs R** and the card
  **shows the R Analytics badge**, with Analysis details behind Explain.
- Python/fallback results are labeled Python (no R badge) and disclose the
  fallback; missing/legacy provenance shows nothing misleading.
- Project Insight cards use the same contract and correctly show no badge (no
  engine execution there yet) — documented as a known limitation.
- Admins can activate/deactivate any implemented method from the UI; activations
  are guarded, audited, persist across reboots, and carry forward on version
  bump; the R-availability check degrades gracefully.
- `R_ANALYTICS_ENABLED=false` remains byte-for-byte today's behavior.
- (ECharts-default rollout is tracked separately in
  `docs/devin-prompt-echarts-default-rollout.md`.)

## PR summary must include

Base/branch; the expanded `_CATEGORY_INTENT_HINTS` map + `infer_intent`
additions; the badge/Analysis-details components and where they read
`analyticalMethod.executionEngine`; the activation-persistence/carry-forward
change and the R-availability hardening; before/after screenshots of a Business
Insight card (R badge + Analysis details open) and a Python/fallback card (no
badge + fallback disclosure); the admin methods page showing engine badges and a
working toggle; test results; and confirmation that R-off behavior is unchanged.
```
