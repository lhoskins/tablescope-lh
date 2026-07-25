# MOVED — Deeper analysis: method-driven, executive-grade

**This plan now lives with the code it describes.**

➡️ **Branch:** `claude/deep-analysis-business-value`
➡️ **File:** `docs/devin-plan-deep-analysis-method-driven.md` *(on that branch)*

## Why it moved

This started as a design doc while the work was still a proposal. The work is
now **delivered, tested code**, so the handoff belongs beside it — Devin cannot
merge the code without also getting the instructions that govern it, and there
is a single source of truth instead of two drifting copies.

## What is on that branch (3 commits, based on `devin/r-echarts-e2e-validation`)

1. **Identifier columns are never chart dimensions** — no more Deeper-analysis
   cards keyed on `order_id` / SKU. Includes the guard that stops an
   *aggregated* result (8 suppliers in 8 rows) being misread as a key.
2. **Method-driven Deeper analysis** — a new pure, unit-tested
   `app/services/deep_analysis.py` that plans governed analytical *intents*,
   executes them through the Analytical Method Engine (R-first, governed,
   with provenance), and applies a **materiality gate** so a method that found
   nothing produces **no card**.
3. **Executive-grade analyses** — YoY, MoM, actual-vs-target, two KPIs moving
   along a shared timeline (dual-axis combo), rate of change, trend, drivers,
   contribution, anomalies, forecast.

Tests at time of delivery: `deep_analysis` 34/34, `chart_catalog` 18/18,
`visualization_engine` 27/27, `ruff` clean.

The answer to *"should we install more complex methods?"* — **no**: the catalog
already has 29 executable R methods and 23 resolvable intents; the old
Deeper-analysis path simply never called any of them.

See the branch copy for the strict merge rules, the deploy/verify steps, and the
one post-deploy check on materiality result keys.
