# TableScope Devin-Ready Implementation Plan

## AI Operational Dashboard Designer: Promote, Generalize Beyond ITSM, and Retire the Legacy Widget Frontend

**Status:** Ready for implementation
**Recommended branch:** `devin/operational-designer-universal-rollout`
**Base branch:** `devin/servicenow-itsm-dashboards-v2` at `296b954e` (merge of PR #191). Confirmed as a strict superset of the current production branch — `git log origin/devin/servicenow-itsm-dashboards-v2..origin/release/deploy-2026-08-07` returns nothing, so this branch already contains everything live plus 46 additional commits. Re-fetch and confirm before starting; more may have landed since.
**Repository:** `lhoskins/tablescope-lh`
**Supersedes:** the two "AI Operational Dashboard Designer: Devin deployment runbook" documents submitted alongside this plan. Those runbooks describe Phase 1 below accurately (see section 0) but do not address the two scope changes requested since they were written: making this the universal default for all dashboards, and removing the legacy widget frontend.

---

## 0. Validation notes

Checked the submitted runbooks against the actual repository (branch `devin/servicenow-itsm-dashboards-v2` at `296b954e`), and against the two new requirements stated alongside them: apply this style as the default for **all** new dashboards (not just ITSM), and remove the legacy dashboard frontend. A note on sourcing: the ChatGPT conversation links provided alongside the runbooks (`chatgpt.com/s/...`) are not reachable from this environment — `chatgpt.com` is blocked by network egress policy here. Everything below is validated directly against the repository and the two runbook documents, not against those threads; if they contain requirements not captured in the runbooks, they need to be pasted in directly.

### 0.1 The runbook's claims about what's already built are accurate

- `POST /api/ai/actions/dashboard-designer/review` and `.../apply` are real (`platform-api/app/routes/ai_proxy_dashboard_designer.py:278,482`), correctly wired through `ai_proxy.py`'s `/ai` router.
- `/ai/dashboard/suggest-multi` is a real, pre-existing route (`ai-server/tablescope-ai-api/app/routers/ai_dashboard.py:269`), genuinely reused via `platform-api/app/routes/ai_proxy_dashboard_suggest.py:89` — not new work.
- All four named test files exist and pass: `pytest tests/test_ai_dashboard_designer.py tests/test_ai_dashboard_pipeline.py tests/test_operational_insight_dashboards.py` → **20 passed** (4 + 15 + 1). One caveat: `test_ai_dashboard_pipeline.py`'s 15 tests exercise pre-existing widget-judge/correction helpers (`_map_widget_visual`, judge drops, `build_join_metadata`) that the designer route reuses — they document that reuse, not new PR #191 behavior, so don't read "15 passed" as designer-specific coverage.
- The longer runbook's acceptance checks 1-16 are accurate descriptions of what PR #191 actually built (review/apply flow, fully/partially/not_supported gating, Edit dashboard / Add insight / Modify with AI, no Add Widget button on operational dashboards). Use that runbook's acceptance checklist as-is for Phase 1 below; it does not need rewriting.

### 0.2 A second, older template system exists and must not be confused with this one

A separate "template binding" framework predates PR #191 (`platform-api/app/models/dashboard_template.py`, `app/routes/dashboard_templates.py`, `app/services/dashboard_templates/{compiler,registry}.py`, `web-ui/components/tablescope/project/dashboard-templates/`). It is genuinely generic — its registry (`registry.py`) already defines real metric manifests for `servicenow-kpi-board`, `servicenow-itsm-operations`, `finance-performance` (revenue, expense, gross margin), `manufacturing-operations`, `sales-performance` (revenue, pipeline, win rate), and `hr-workforce-insights`, each tagged with a `category` field on the frontend's `DashboardTemplateDefinition`.

It is **not** the mechanism to build on for "AI evaluates every requested metric, user never configures anything," and should not be revived or extended for that purpose:

- Creating a dashboard through it requires an admin to manually approve a field mapping first — `web-ui/components/tablescope/project/dashboard-templates/instantiate.ts` blocks `Create` on `!binding?.validation.valid || !mappingApproved`. That is exactly the manual configuration step this initiative is removing.
- It's explicitly walled off from ITSM, the one domain the new Designer already covers: `instantiate.ts:166-168` throws `"This ServiceNow template is already available in the current project."` when a template has `itsmPreset` set.
- It calls old endpoints (`/api/ai/actions/suggest-dashboards`, `/api/ai/actions/save-dashboard-suggestion`), never `/dashboard-designer/review|apply`.

Its value is data, not mechanism: the `_MANIFESTS` dict in `registry.py` is a ready-made, already-reasoned-about source of per-domain metric vocabulary for finance/manufacturing/sales/hr — reuse those definitions as input to generalizing the new Designer (section 2 below), then retire the manual-mapping UI/routes once the new Designer covers the same ground (section 4).

### 0.3 The new Designer is currently hardcoded to ITSM, confirmed at the exact point that matters

`ai_proxy_dashboard_designer.py`'s `_CONCEPT_FIELDS` dict (lines 68-91) is the vocabulary the AI review step matches a user's described metrics against — every entry is ITSM-specific: `"resolution time"`, `"SLA performance"`, `"backlog state"`, `"assignment group"`, keyed to column-name heuristics like `slamet`, `assignmentgroup`, `resolvedat`. Separately, `_ai_prompt()` (line 266) unconditionally injects `"Use the Tablescope ServiceNow Operational Insight presentation."` into every generation call, regardless of what the user described. Neither is gated by project type, industry, or any per-tenant signal — a Finance or Manufacturing project hitting this route today would either get nothing recognized in `_CONCEPT_FIELDS` (falling through to `not_supported` for anything domain-specific) or a dashboard whose narrative framing was written for incidents and SLA breaches. This is the concrete, single place "adapted to other business areas" has to change.

### 0.4 Legacy and Operational Insight dashboards share one table; removing the frontend without migrating data breaks existing dashboards

There is no separate table or `dashboard_type` column. `platform-api/app/models/dashboard.py` has one `dashboards` table with a `config: Mapped[dict]` JSON blob; a dashboard is "operational" purely because `config.presentation == "operational_insight"` (set by `operational_insight_config()` in `app/services/operational_insight_dashboards.py`). The frontend reads the same flag: `web-ui/components/dashboard/DashboardViewer.tsx:84` — `const operational = dashboard.config?.presentation === "operational_insight"` — and branches the header button at line 615 (`{operational ? "Add insight" : "Add Widget"}`) and the body between the new renderer and `<WidgetConfigPanel>`.

A migration script already exists for converting old dashboards to the new shape — `platform-api/scripts/migrate_operational_insight_dashboards.py` — but it defaults to exactly two tenant slugs (`["simplicit", "scaitis"]`, line 64) unless called with an explicit list, and defaults to dry-run unless `--apply` is passed. **Removing `WidgetConfigPanel`/the legacy branch from `DashboardViewer.tsx` before this script has been run with `--apply` across every tenant leaves any unmigrated dashboard with no renderer at all** — its `config.presentation` is not `"operational_insight"`, and the branch that used to handle that case would be gone. Section 4 sequences this correctly; do not remove the legacy branch first.

One more note on cleanup scope: `web-ui/components/dashboard/CreateDashboardWizard.tsx` is confirmed dead code today — zero imports anywhere in `web-ui` outside its own file. It can be deleted immediately, independent of the phased plan below, with no coordination required.

---

## 1. Objective

Make the AI-guided, no-manual-configuration Operational Insight dashboard (ServiceNow-style: cards, skinny bars, Operational Brief, Best Improvement Opportunities) the single way every dashboard in TableScope is created and edited, across every business area, and remove the legacy widget-configuration frontend once it is safe to do so.

This is staged into three phases because the three parts have different readiness today: the ITSM version is built and tested now; generalizing it is unbuilt; removing legacy safely requires a completed data migration that hasn't run tenant-wide. Collapsing these into one deployment would either delay shipping the part that's ready, or remove the legacy renderer while dashboards still depend on it.

## 2. Phase 1 — Promote what's already built (ready now)

PR #191 is merged, tested (20/20 passing), and already a superset of production. This phase is deployment, not development:

1. Follow the shorter runbook's release sequence as written (`docker compose build platform-api web-ui`, rolling restart, no new migrations required beyond what PR #191 already carries).
2. Run the longer runbook's 20-point acceptance checklist as written — it is accurate (section 0.1).
3. Fast-forward `release/deploy-2026-08-07` to `devin/servicenow-itsm-dashboards-v2`'s tip rather than cherry-picking, since it's a confirmed superset.
4. Delete `web-ui/components/dashboard/CreateDashboardWizard.tsx` in this same pass — it's dead code today regardless of the phases below (section 0.4).

Outcome after this phase: every **ITSM** project gets the described experience. Finance/Manufacturing/Sales/HR/other projects are unaffected — they still see the legacy widget builder, because `_CONCEPT_FIELDS` and the ServiceNow-only prompt (section 0.3) mean the Designer would either reject their metrics or mislabel the result. Do not enable the Designer as the only path for non-ITSM projects until Phase 2 lands.

## 3. Phase 2 — Generalize the Designer beyond ITSM

Goal: the same `/dashboard-designer/review` → `/apply` flow, with the same no-manual-config guarantee, produces a correctly-labeled dashboard for any business area with matching data — not just ITSM.

1. Replace the single hardcoded `_CONCEPT_FIELDS` dict with a per-domain lookup. Seed it from the existing template registry's `_MANIFESTS` (`app/services/dashboard_templates/registry.py`) — the finance (`revenue`, `expense`, `gross_margin`), manufacturing (`oee`, `downtime`), sales (`revenue`, `pipeline`, `win_rate`), and hr manifests are already-reasoned-about starting vocabulary; convert each metric definition into the same `(aliases, column-heuristics)` shape `_CONCEPT_FIELDS` already uses for ITSM, rather than inventing a new shape.
2. Determine which domain applies to a given review request. Do not ask the user to pick a "business area" as a new manual step — that would reintroduce configuration. Prefer: infer from the project's existing data (table/column names already present in the project, the same kind of signal `_CONCEPT_FIELDS`'s column heuristics already use) or from an existing per-project classification if one exists; fall back to a general/unbranded concept set if no domain matches confidently rather than forcing an ITSM label onto unrelated data.
3. Make `_ai_prompt()`'s presentation-style injection (currently the unconditional ServiceNow-Operational-Insight line, `ai_proxy_dashboard_designer.py:266`) domain-aware: keep the same visual system (cards, skinny bars, Operational Brief, Best Improvement Opportunities — the plan's own non-negotiable "Same ServiceNow Style" requirement) but let the narrative vocabulary match the domain (e.g. "SLA breach" only for ITSM; "gross margin trend" for finance) instead of always saying "ServiceNow."
4. Extend `fully_supported` / `partially_supported` / `not_supported` grading (already correct for ITSM per Phase 1 testing) to run against whichever domain's concept set was selected in step 2, with the same missing-field callout behavior the runbook's acceptance check 4 already validates for ITSM.
5. Test with the same rigor as PR #191: a `test_ai_dashboard_designer_multi_domain.py`-style suite exercising finance and manufacturing test fixtures through `review`/`apply`, alongside the existing ITSM suite (don't replace it, extend it).

## 4. Phase 3 — Complete the migration, then remove the legacy frontend

Only after Phase 2 ships and has run for at least one full validation cycle against non-ITSM tenants:

1. Enumerate every tenant with dashboards, not just the two defaults baked into `migrate_operational_insight_dashboards.py` (section 0.4) — run it with an explicit full tenant-slug list, dry-run first, review the diff, then `--apply`.
2. Verify with a query, not an assumption: after `--apply`, confirm zero dashboards remain where `config.presentation != "operational_insight"` across every tenant.
3. Only then remove the legacy branch from `DashboardViewer.tsx` (the `operational` ternary at lines 84/615 and the `<WidgetConfigPanel>` render path), and delete `WidgetConfigPanel.tsx` and its now-unreferenced supporting files.
4. Retire the older template-binding framework's manual-mapping UI and its two old endpoints (section 0.2) — `dashboard_templates.py`'s routes, `TemplateBindingEditor`, `instantiate.ts`'s manual-approval path — since Phase 2 now covers the same domains without the manual step it required. Keep the `registry.py` manifests only as long as Phase 2's migration (step 1 of this section) needs them as a data source; they can be deleted once that data has been folded into the Designer's per-domain concept sets.
5. Add a hard server-side guard, not just a removed UI path: reject any new dashboard write whose `config.presentation` isn't `"operational_insight"` (or a future domain-tagged equivalent), so a stale client or direct API call can't recreate a legacy-shaped dashboard after the frontend is gone.

Do not perform step 3 before steps 1-2 are confirmed complete — this is the exact risk described in section 0.4.

## 5. Acceptance criteria

**Phase 1** — the longer runbook's existing 20-point checklist, unchanged (section 0.1).

**Phase 2**
- [ ] A Finance project's described dashboard, evaluated with real Finance data present, returns `fully_supported` with finance-labeled metrics (not ITSM vocabulary, not `not_supported` for data that genuinely exists).
- [ ] A Manufacturing project behaves the same way for OEE/downtime-shaped data.
- [ ] A project whose data matches no known domain still gets an honest `not_supported`/general result rather than a forced ITSM or wrong-domain label.
- [ ] The visual system (cards, skinny bars, Operational Brief, Best Improvement Opportunities) is identical across domains; only the narrative vocabulary changes.
- [ ] No new manual configuration step was added to select a domain.

**Phase 3**
- [ ] Zero dashboards across all tenants have `config.presentation != "operational_insight"` before the legacy branch is removed.
- [ ] `DashboardViewer.tsx` and `WidgetConfigPanel.tsx` no longer contain a reachable non-operational render path.
- [ ] A direct API write attempting to create a legacy-shaped dashboard is rejected server-side.
- [ ] The old template-binding manual-mapping UI and its two endpoints are removed or return a clear deprecation response, not a silent 404.

## 6. Rollback

- Phase 1: deploy the previous `platform-api`/`web-ui` SHA, as the original runbook already specifies. No schema rollback needed.
- Phase 2: disable domain-generalization behind a flag (e.g. `DASHBOARD_DESIGNER_MULTI_DOMAIN_ENABLED`) and fall back to ITSM-only `_CONCEPT_FIELDS`; this does not affect Phase 1's shipped behavior.
- Phase 3: do not roll back by restoring `WidgetConfigPanel` once dashboards have been migrated and the server-side guard (section 4 step 5) is live — restoring the UI without restoring pre-migration `config.presentation` values would desync the two. If Phase 3 must be reversed, restore from the pre-`--apply` dashboard snapshot instead.

---

## Devin Completion Instructions

1. Confirm `devin/servicenow-itsm-dashboards-v2` is still the correct current base (re-fetch; more may have landed since `296b954e`).
2. Ship Phase 1 first, independently — it is complete, tested, and blocked on nothing. Promote it to `release/deploy-2026-08-07` and re-deploy the same way as the two most recently shipped PRs before starting Phase 2.
3. Phase 2 and Phase 3 are separate PRs, in that order, on top of Phase 1's promoted tip. Do not combine them — Phase 3's frontend removal is unsafe until Phase 3's own migration step has been verified complete, and that verification needs Phase 2's domain coverage to already be live so non-ITSM tenants have somewhere to land.
4. For each phase, report actual evidence (test output, migration diff/apply counts, screenshots per domain) the same way PR #191's own testing did — not a description of what should work.
