# Devin-ready plan: append 24-month data to the live simplicit tenant (append-only, no regeneration)

## Context

The simplicit tenant (tenant 31, owner leonard.hoskins@gmail.com / user 46) was
recreated with 81 CSV files via the demo company installer, but the live data
never actually got the 24-month calendar-window fix (`2544060` on
`devin/demo-company-two-year-window`) — the CSVs on disk today
(`/opt/wildfly/teiidfiles/customers/31/46/uploads/`) are the OLD generation
(30 months monthly / 18 months weekly, e.g. `sales_revenue_monthly.csv` runs
2024-01 → 2026-07, `mfg_scrap_weekly.csv` runs 2025-01 → 2026-07), not the
24-month window. This was confirmed directly from the live files, not
inferred.

**Do not fix this by regenerating.** `scripts/install_demo_company.py
--refresh-existing` calls the generator fresh, and the generator (
`scripts/demo_company/datasets.py`) uses one shared sequential RNG stream
across all 81 files, with each value computed as roughly
`base * growth**month_index * seasonal * noise`. Shifting the calendar window
shifts every `month_index` and therefore every downstream RNG draw —
regenerating would silently change **every historical value in every file**,
not just append new ones. That's confirmed by reading the generator source,
not assumed.

**What this plan does instead:** the 81 live files were pulled down and
inspected directly. Of the 81, only 14 have a genuine monthly/weekly grid that
currently stops short of today (2026-08-02) — these are exactly the files
that feed the percent-change trend cards. (9 more files are forecast/budget
tables that already extend to 2027-12 and don't need touching; the rest are
master data or event logs with no periodic cadence.) For each of the 14, every
existing row was verified byte-identical to what's live — nothing was
regenerated — and new trailing periods were appended, each value projected
from that entity's own last 6–12 real observations (linear trend fit +
residual-matched noise), so any scenario already visible in the data (the
slipping customer, the WC-002 scrap creep, the material cost inflation on one
program) continues naturally instead of resetting. New coverage:

- Monthly files: through **2026-08-01** (1 new month; last live data point
  was already through 2026-07, so July is not touched).
- Weekly files (`mfg_labor_actuals_weekly.csv`, `mfg_scrap_weekly.csv`):
  through **2026-07-27** (3 new weeks; last live point was 2026-07-06).

## Files changed (14)

| File | Rows added | New coverage |
|---|---|---|
| `sales_revenue_monthly.csv` | +9 | 2026-08-01 (9 programs) |
| `mfg_material_actuals_monthly.csv` | +9 | 2026-08-01 |
| `eng_labor_actuals_monthly.csv` | +12 | 2026-08-01 |
| `fin_gl_monthly.csv` | +13 | 2026-08-01 (13 GL accounts, derived from the 3 rows above using the exact fixed fractions in `datasets.py::_finance`) |
| `fin_budget_vs_actual_monthly.csv` | +13 | 2026-08-01 (derived from the new GL month; budget reuses each account's stable historical anchor) |
| `hr_headcount_plan.csv` | +11 | 2026-08-01 (11 departments) |
| `quality_defect_trends_monthly.csv` | +4 | 2026-08-01 (4 sites) |
| `procurement_material_price_history.csv` | +10 | 2026-08-01 (10 commodities) |
| `it_system_availability_monthly.csv` | +5 | 2026-08-01 (5 systems) |
| `fin_indirect_rates_monthly.csv` | +1 | 2026-08-01 |
| `executive_kpi_scorecard_monthly.csv` | +1 | 2026-08-01 (RevenueUSD = new sales total; ties out) |
| `monthly_review_metrics.csv` | rolling, still 7 rows | drops 2026-01, adds 2026-08 (this file is a rolling last-7-months view per the generator's own `months[-7:]` logic) |
| `mfg_labor_actuals_weekly.csv` | +36 | 2026-07-13/20/27 (12 work centers × 3 weeks) |
| `mfg_scrap_weekly.csv` | +36 | 2026-07-13/20/27 |

All 14 files are staged at `docs/simplicit-refresh-2026-08-02/files/` in this
branch. Every byte of every pre-existing row was diffed against the live tar
dump and confirmed identical (the only difference in the live files is CRLF
line endings, which the uploader already normalizes on ingest — same thing
noted in the earlier root-cause writeup).

The other 67 live files are untouched — do not re-upload them.

## Steps

1. **Merge in the tenant-slot TTL fix first.** `platform-api/app/services/home_intel_queue.py::acquire_tenant_slot`
   on `origin/claude/validate-enhance-logic-r2fyy1` (commit `86510cc`) fixes a
   real bug: the Redis TTL on a tenant's concurrency-slot counter used to be
   refreshed on every *rejected* acquire attempt too, so once a slot leaked
   (e.g. a worker crashed mid-analysis) it could never expire — every retry
   from the jobs it was blocking re-armed the TTL forever. This is exactly
   what was observed live during the last simplicit refresh attempt (a stuck
   run retrying 50+ times with the slot never clearing). Cherry-pick or merge
   that one commit before running step 3, or at minimum manually check/clear
   `home-intel:tenant-slots:31` in Redis before triggering the refresh so a
   leftover leaked slot from a prior failed attempt doesn't block this run.

2. **Confirm Teiid is healthy** before running anything — a prior attempt
   failed because the shared `tablescope-teiid-1` container was overloaded
   (connection pool exhaustion across 72 VDBs). Don't proceed until PG
   connections to Teiid are succeeding normally.

3. **Run the targeted replace script** — not the generic installer:
   ```
   python scripts/refresh_simplicit_2026_08.py \
       --api-url https://app.tablescope.cloud \
       --email leonard.hoskins@gmail.com
   ```
   This script (staged at `scripts/refresh_simplicit_2026_08.py`, stdlib-only,
   no dependency on the demo_company package so it runs regardless of which
   branch is checked out) calls `POST /api/upload/datasources/{view}/replace`
   for exactly the 14 files above, reading their bytes from
   `docs/simplicit-refresh-2026-08-02/files/`. It does **not** touch the
   other 67 data sources and does **not** call the generator.

   If any file fails with a 409 filename-mismatch or column-compatibility
   error, stop and report which file — that would mean the live file's
   current name/columns have drifted from what was captured in the tar dump
   this plan was built from, and the mapping needs to be re-verified rather
   than forced through.

4. **Verify the replace actually happened**, independent of Teiid being
   responsive (this check is pure filesystem I/O and doesn't depend on query
   capability):
   ```
   ls -la /opt/wildfly/teiidfiles/customers/31/46/uploads/archive/ | tail -20
   ```
   You should see 14 freshly timestamped archive entries (the servlet writes
   one on every successful replace, before any Teiid deploy step). Then
   directly check one file's new tail:
   ```
   tail -3 /opt/wildfly/teiidfiles/customers/31/46/uploads/sales_revenue_monthly.csv
   ```
   Should show 9 new `2026-08-01` rows (one per program), not stop at
   `2026-07-01`.

5. **Reprocess AI content** for the affected projects (same two calls
   `--refresh-existing` makes) — Sales, Manufacturing, Engineering, Finance,
   HR, Quality, Procurement, IT, Executive (the 9 departments touched by
   these 14 files; EHS and Legal/Contracts are unaffected):
   ```
   POST /api/projects/{pid}/graph/refresh      # for each of the 9 projects
   GET  /api/home-intelligence/stream?cross_project=true
   ```

6. **Acceptance check** — this is the actual thing Leonard asked to see:
   pull up the percent-change / trend summary for a card built on one of
   these 14 sources (e.g. sales revenue, GL, or scrap trend) and confirm the
   date range spans **2024-08/09 → 2026-08**, i.e. ~24 months, not a
   6-month window. If cards still show only ~6 months after this refresh,
   that confirms the earlier "6 months instead of 24" symptom is NOT a
   data-availability problem (the data now genuinely has 24 months) but
   something in how the AI plan/query construction windows the trend —
   that would need to be investigated separately as its own issue, now that
   the data-side variable is eliminated.

## What NOT to do

- Do not run `scripts/install_demo_company.py --all --refresh-existing`
  against tenant 31. That regenerates all 81 files from scratch and will
  silently change historical values that are already live and may be in use.
- Do not hand-copy files directly onto
  `/opt/wildfly/teiidfiles/customers/31/46/uploads/` bypassing the
  `/replace` API. That skips the VDB view rebuild and Teiid cache
  invalidation the servlet does on a genuine replace (`TeiidExcelImporterTest.java`,
  `processTxtFileInternal`) and can leave Teiid serving a stale schema.
