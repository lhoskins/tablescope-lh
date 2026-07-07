"""Structured CSV dataset generators for the demo company.

Every table is derived from the shared :class:`Dimensions` so ids line up
across departments (referential integrity by construction).  Financial facts
are built from the same revenue / labor / material / scrap series that feed the
GL, so budget-vs-actual, forecast variance and the planted AI stories are
internally consistent rather than independent random noise.

All dates are rolled forward to the issue's window: monthly tables through
2026-07-01, weekly tables through 2026-07-06.
"""

from __future__ import annotations

import datetime as dt
import random

from . import config as C
from .dimensions import Dimensions
from .io_utils import Registry

# Department key → Tablescope project name (kept in sync with config).
_PROJECT = {d.key: d.project for d in C.DEPARTMENTS}


def _seasonal(month: int) -> float:
    """A mild seasonal multiplier (summer dip, year-end push)."""
    return 1.0 + 0.06 * [0, 1, 2, 1, 0, -1, -2, -2, 0, 1, 2, 3][month - 1] / 3.0


def generate_datasets(reg: Registry, dims: Dimensions) -> None:
    rng = random.Random(dims.spec.seed ^ 0x5F3759DF)
    months = C.month_starts(C.MONTHLY_START, C.MONTHLY_THROUGH)
    weeks = C.week_mondays(C.WEEKLY_START, C.WEEKLY_THROUGH)

    # Shared revenue series (program × month) — the spine of the financials.
    revenue = _sales(reg, dims, rng, months)
    material = _manufacturing(reg, dims, rng, months, weeks)
    labor = _engineering(reg, dims, rng, months)
    _finance(reg, dims, rng, months, revenue, material, labor)
    _hr(reg, dims, rng, months)
    _quality(reg, dims, rng, months, weeks)
    _procurement(reg, dims, rng, months)
    _it(reg, dims, rng, months)
    _ehs(reg, dims, rng, months)
    _legal(reg, dims, rng)
    _executive(reg, dims, rng, months, revenue)


# ── Sales ────────────────────────────────────────────────────────────────
def _sales(reg, dims, rng, months) -> dict:
    sc = dims.scenarios
    proj = "Sales"
    dep = "Sales"

    # Programs master.
    reg.write_csv(
        "data/Sales/sales_programs.csv",
        ["ProgramID", "ProgramName", "Customer", "ProgramType", "StartDate",
         "Status", "TargetMarginPct"],
        dims.programs, department=dep, project=proj, artifact_type="Master Data",
        tags=["sales", "programs", "master"],
        description="Program master: customer programs and target margins.",
    )

    # Revenue per program per month.
    base = {p["ProgramID"]: rng.uniform(180000, 900000) for p in dims.programs}
    growth = {p["ProgramID"]: rng.uniform(0.002, 0.012) for p in dims.programs}
    rev_rows = []
    revenue: dict[tuple[str, str], float] = {}
    for p in dims.programs:
        pid = p["ProgramID"]
        for i, m in enumerate(months):
            val = base[pid] * (1 + growth[pid]) ** i * _seasonal(m.month)
            val *= rng.uniform(0.94, 1.06)
            # Sales slippage scenario: the slipping customer dips in 2026 H1.
            if p["Customer"] == sc.slipping_customer and m >= dt.date(2026, 1, 1):
                val *= 0.82
            val = round(val, 2)
            revenue[(pid, C.fiscal_period(m))] = val
            rev_rows.append({
                "Month": m.isoformat(), "ProgramID": pid,
                "Customer": p["Customer"], "RevenueUSD": val,
                "Units": int(val / rng.uniform(800, 2500)),
            })
    reg.write_csv(
        "data/Sales/sales_revenue_monthly.csv",
        ["Month", "ProgramID", "Customer", "RevenueUSD", "Units"], rev_rows,
        department=dep, project=proj, artifact_type="Operational Data",
        tags=["sales", "revenue", "monthly"],
        description="Recognized revenue by program and month.",
        date_range=f"{months[0].isoformat()}..{months[-1].isoformat()}",
    )

    # Pipeline forecast (open opportunities, FY2026-FY2027).
    fmonths = C.month_starts(C.BUDGET_START, C.FORECAST_THROUGH)
    stages = ["Qualify", "Propose", "Negotiate", "Verbal", "Closed-Won", "Closed-Lost"]
    pipe = []
    opp = 0
    for p in dims.programs:
        for _ in range(rng.randint(3, 6)):
            opp += 1
            close = rng.choice(fmonths)
            stage = rng.choice(stages)
            amt = round(rng.uniform(50000, 1200000), 2)
            slip = p["Customer"] == sc.slipping_customer and rng.random() < 0.7
            pipe.append({
                "OpportunityID": f"OPP-{opp:04d}", "ProgramID": p["ProgramID"],
                "Customer": p["Customer"], "Stage": stage,
                "ExpectedCloseMonth": close.isoformat(), "AmountUSD": amt,
                "ProbabilityPct": {"Qualify": 20, "Propose": 40, "Negotiate": 60,
                                   "Verbal": 85, "Closed-Won": 100,
                                   "Closed-Lost": 0}[stage],
                "Slipped": "Y" if slip else "N",
            })
    reg.write_csv(
        "data/Sales/sales_pipeline_forecast.csv",
        ["OpportunityID", "ProgramID", "Customer", "Stage", "ExpectedCloseMonth",
         "AmountUSD", "ProbabilityPct", "Slipped"], pipe,
        department=dep, project=proj, artifact_type="Forecast",
        tags=["sales", "pipeline", "forecast", "ai-scenario"],
        description="Open pipeline with planted forecast-slippage scenario.",
    )

    # Bookings forecast + backlog (monthly).
    book, backlog = [], []
    run_backlog = rng.uniform(4_000_000, 8_000_000)
    for m in fmonths:
        bookings = round(sum(base.values()) * rng.uniform(0.9, 1.1), 2)
        rev_m = sum(revenue.get((p["ProgramID"], C.fiscal_period(m)), base[p["ProgramID"]])
                    for p in dims.programs)
        run_backlog = max(0.0, run_backlog + bookings - rev_m)
        book.append({"Month": m.isoformat(), "Scenario": "Plan",
                     "BookingsUSD": bookings,
                     "BookToBill": round(bookings / max(rev_m, 1), 2)})
        backlog.append({"Month": m.isoformat(), "BacklogUSD": round(run_backlog, 2),
                        "CoverageMonths": round(run_backlog / max(rev_m, 1), 1)})
    reg.write_csv(
        "data/Sales/sales_bookings_forecast.csv",
        ["Month", "Scenario", "BookingsUSD", "BookToBill"], book,
        department=dep, project=proj, artifact_type="Forecast",
        tags=["sales", "bookings", "forecast"],
        description="Bookings forecast and book-to-bill ratio.")
    reg.write_csv(
        "data/Sales/sales_backlog_monthly.csv",
        ["Month", "BacklogUSD", "CoverageMonths"], backlog,
        department=dep, project=proj, artifact_type="Operational Data",
        tags=["sales", "backlog", "monthly"],
        description="Order backlog and coverage months.")
    return revenue


# ── Manufacturing ─────────────────────────────────────────────────────────
def _manufacturing(reg, dims, rng, months, weeks) -> dict:
    sc = dims.scenarios
    proj, dep = "Manufacturing", "Manufacturing"

    reg.write_csv(
        "data/Manufacturing/mfg_work_centers.csv",
        ["WorkCenterID", "WorkCenterName", "SiteID", "Process", "Shifts"],
        dims.work_centers, department=dep, project=proj, artifact_type="Master Data",
        tags=["manufacturing", "work-centers", "master"],
        description="Work-center master.")

    reg.write_csv(
        "data/Manufacturing/mfg_parts.csv",
        ["PartID", "PartName", "Commodity", "ProgramID", "PrimarySupplierID",
         "StandardCostUSD", "UOM"], dims.parts,
        department=dep, project=proj, artifact_type="Master Data",
        tags=["manufacturing", "parts", "master"],
        description="Part master with standard costs.")

    rate_rows = []
    for wc in dims.work_centers:
        rate_rows.append({
            "WorkCenterID": wc["WorkCenterID"], "SiteID": wc["SiteID"],
            "LaborRateUSDPerHour": round(rng.uniform(38, 72), 2),
            "OvertimeMultiplier": 1.5,
            "EffectiveDate": "2026-01-01",
        })
    reg.write_csv(
        "data/Manufacturing/mfg_labor_rates.csv",
        ["WorkCenterID", "SiteID", "LaborRateUSDPerHour", "OvertimeMultiplier",
         "EffectiveDate"], rate_rows,
        department=dep, project=proj, artifact_type="Master Data",
        tags=["manufacturing", "labor-rates", "master"],
        description="Labor rates by work center.")

    # Weekly labor + scrap (scrap creep planted at scrap_work_center from 2026).
    labor_rows, scrap_rows = [], []
    for wc in dims.work_centers:
        base_hours = rng.uniform(280, 640)
        base_scrap = rng.uniform(1.2, 2.8)  # baseline scrap %
        for i, wk in enumerate(weeks):
            hours = round(base_hours * rng.uniform(0.9, 1.1), 1)
            ot = round(hours * rng.uniform(0.02, 0.12), 1)
            scrap_pct = base_scrap * rng.uniform(0.85, 1.15)
            if (wc["WorkCenterID"] == sc.scrap_work_center
                    and wk >= dt.date(2026, 1, 1)):
                # Creep: scrap rises steadily through H1 2026.
                weeks_in = (wk - dt.date(2026, 1, 1)).days / 7
                scrap_pct += 0.09 * weeks_in
            scrap_pct = round(scrap_pct, 2)
            produced = int(hours * rng.uniform(6, 14))
            scrapped = int(produced * scrap_pct / 100)
            labor_rows.append({
                "WeekStart": wk.isoformat(), "WorkCenterID": wc["WorkCenterID"],
                "SiteID": wc["SiteID"], "DirectHours": hours, "OvertimeHours": ot,
                "UnitsProduced": produced,
            })
            scrap_rows.append({
                "WeekStart": wk.isoformat(), "WorkCenterID": wc["WorkCenterID"],
                "SiteID": wc["SiteID"], "UnitsProduced": produced,
                "UnitsScrapped": scrapped, "ScrapPct": scrap_pct,
                "ScrapCostUSD": round(scrapped * rng.uniform(18, 60), 2),
            })
    reg.write_csv(
        "data/Manufacturing/mfg_labor_actuals_weekly.csv",
        ["WeekStart", "WorkCenterID", "SiteID", "DirectHours", "OvertimeHours",
         "UnitsProduced"], labor_rows,
        department=dep, project=proj, artifact_type="Operational Data",
        tags=["manufacturing", "labor", "weekly"],
        description="Weekly direct labor and output by work center.",
        date_range=f"{weeks[0].isoformat()}..{weeks[-1].isoformat()}")
    reg.write_csv(
        "data/Manufacturing/mfg_scrap_weekly.csv",
        ["WeekStart", "WorkCenterID", "SiteID", "UnitsProduced", "UnitsScrapped",
         "ScrapPct", "ScrapCostUSD"], scrap_rows,
        department=dep, project=proj, artifact_type="Operational Data",
        tags=["manufacturing", "scrap", "weekly", "ai-scenario"],
        description="Weekly scrap with planted scrap-creep scenario.",
        date_range=f"{weeks[0].isoformat()}..{weeks[-1].isoformat()}")

    # Monthly material actuals (material-cost inflation planted on one program).
    material: dict[str, float] = {}
    mat_rows = []
    for m in months:
        for p in dims.programs:
            qty = int(rng.uniform(400, 4000))
            unit = rng.uniform(20, 120)
            if (p["ProgramID"] == sc.material_cost_program
                    and m >= dt.date(2025, 10, 1)):
                unit *= 1.0 + 0.03 * ((m.year - 2025) * 12 + m.month - 10)
            cost = round(qty * unit, 2)
            material[C.fiscal_period(m)] = material.get(C.fiscal_period(m), 0) + cost
            mat_rows.append({
                "Month": m.isoformat(), "ProgramID": p["ProgramID"],
                "Commodity": rng.choice([pp["Commodity"] for pp in dims.parts[:5]]),
                "Quantity": qty, "UnitCostUSD": round(unit, 2),
                "MaterialCostUSD": cost,
            })
    reg.write_csv(
        "data/Manufacturing/mfg_material_actuals_monthly.csv",
        ["Month", "ProgramID", "Commodity", "Quantity", "UnitCostUSD",
         "MaterialCostUSD"], mat_rows,
        department=dep, project=proj, artifact_type="Operational Data",
        tags=["manufacturing", "material", "monthly", "ai-scenario"],
        description="Monthly material spend with planted cost-inflation scenario.",
        date_range=f"{months[0].isoformat()}..{months[-1].isoformat()}")

    # Production plan + capacity forecast + inventory forecast.
    fmonths = C.month_starts(C.BUDGET_START, C.FORECAST_THROUGH)
    plan, cap, inv = [], [], []
    for wc in dims.work_centers:
        for m in fmonths:
            planned = int(rng.uniform(1500, 5000))
            capacity = int(planned * rng.uniform(1.05, 1.4))
            plan.append({"Month": m.isoformat(), "WorkCenterID": wc["WorkCenterID"],
                         "SiteID": wc["SiteID"], "PlannedUnits": planned,
                         "Scenario": "Plan"})
            cap.append({"Month": m.isoformat(), "WorkCenterID": wc["WorkCenterID"],
                        "SiteID": wc["SiteID"], "CapacityUnits": capacity,
                        "PlannedUnits": planned,
                        "UtilizationPct": round(planned / capacity * 100, 1)})
    for p in dims.parts[:60]:
        inv.append({"PartID": p["PartID"], "ProgramID": p["ProgramID"],
                    "OnHandUnits": int(rng.uniform(0, 3000)),
                    "SafetyStock": int(rng.uniform(50, 500)),
                    "ForecastDemandUnits": int(rng.uniform(200, 4000)),
                    "ProjectedShortfall": rng.choice([0, 0, 0, 1])})
    reg.write_csv(
        "data/Manufacturing/mfg_production_plan_monthly.csv",
        ["Month", "WorkCenterID", "SiteID", "PlannedUnits", "Scenario"], plan,
        department=dep, project=proj, artifact_type="Forecast",
        tags=["manufacturing", "production-plan", "forecast"],
        description="Monthly production plan by work center.")
    reg.write_csv(
        "data/Manufacturing/mfg_capacity_forecast_monthly.csv",
        ["Month", "WorkCenterID", "SiteID", "CapacityUnits", "PlannedUnits",
         "UtilizationPct"], cap,
        department=dep, project=proj, artifact_type="Forecast",
        tags=["manufacturing", "capacity", "forecast"],
        description="Capacity vs plan utilization forecast.")
    reg.write_csv(
        "data/Manufacturing/mfg_inventory_forecast.csv",
        ["PartID", "ProgramID", "OnHandUnits", "SafetyStock",
         "ForecastDemandUnits", "ProjectedShortfall"], inv,
        department=dep, project=proj, artifact_type="Forecast",
        tags=["manufacturing", "inventory", "forecast"],
        description="Inventory position and projected shortfalls.")
    return material


# ── Engineering ────────────────────────────────────────────────────────────
def _engineering(reg, dims, rng, months) -> dict:
    sc = dims.scenarios
    proj, dep = "Engineering", "Engineering"

    labor: dict[str, float] = {}
    rows = []
    for e in dims.eng_projects:
        for m in months:
            hrs = rng.uniform(120, 900)
            rate = rng.uniform(85, 145)
            cost = hrs * rate
            if (e["ProjectID"] in sc.overrun_projects
                    and m >= dt.date(2025, 9, 1)):
                cost *= 1.35  # NRE overrun ramp
            cost = round(cost, 2)
            labor[C.fiscal_period(m)] = labor.get(C.fiscal_period(m), 0) + cost
            rows.append({"Month": m.isoformat(), "ProjectID": e["ProjectID"],
                         "ProgramID": e["ProgramID"], "LaborHours": round(hrs, 1),
                         "LaborRateUSD": round(rate, 2), "LaborCostUSD": cost})
    reg.write_csv(
        "data/Engineering/eng_labor_actuals_monthly.csv",
        ["Month", "ProjectID", "ProgramID", "LaborHours", "LaborRateUSD",
         "LaborCostUSD"], rows,
        department=dep, project=proj, artifact_type="Operational Data",
        tags=["engineering", "labor", "monthly"],
        description="Monthly engineering labor by project.",
        date_range=f"{months[0].isoformat()}..{months[-1].isoformat()}")

    # Project budget + forecast + NRE overrun watchlist.
    fmonths = C.month_starts(C.BUDGET_START, C.FORECAST_THROUGH)
    bud, fc, watch = [], [], []
    for e in dims.eng_projects:
        monthly_budget = e["BudgetUSD"] / 18
        for m in fmonths:
            forecast = monthly_budget * rng.uniform(0.95, 1.05)
            if e["ProjectID"] in sc.overrun_projects:
                forecast *= 1.3
            bud.append({"Month": m.isoformat(), "ProjectID": e["ProjectID"],
                        "ProgramID": e["ProgramID"], "Scenario": "Budget",
                        "BudgetUSD": round(monthly_budget, 2)})
            fc.append({"Month": m.isoformat(), "ProjectID": e["ProjectID"],
                       "ProgramID": e["ProgramID"], "Scenario": "Forecast",
                       "ForecastUSD": round(forecast, 2)})
        overrun = e["ProjectID"] in sc.overrun_projects
        eac = e["BudgetUSD"] * (1.28 if overrun else rng.uniform(0.9, 1.05))
        watch.append({
            "ProjectID": e["ProjectID"], "ProjectName": e["ProjectName"],
            "ProgramID": e["ProgramID"], "BudgetUSD": e["BudgetUSD"],
            "EAC_USD": round(eac, 2),
            "VarianceUSD": round(eac - e["BudgetUSD"], 2),
            "VariancePct": round((eac - e["BudgetUSD"]) / e["BudgetUSD"] * 100, 1),
            "Status": "Overrun" if overrun else "On Track",
        })
    reg.write_csv(
        "data/Engineering/eng_project_budget_monthly.csv",
        ["Month", "ProjectID", "ProgramID", "Scenario", "BudgetUSD"], bud,
        department=dep, project=proj, artifact_type="Budget",
        tags=["engineering", "budget", "monthly"],
        description="Monthly engineering project budget.")
    reg.write_csv(
        "data/Engineering/eng_project_forecast_monthly.csv",
        ["Month", "ProjectID", "ProgramID", "Scenario", "ForecastUSD"], fc,
        department=dep, project=proj, artifact_type="Forecast",
        tags=["engineering", "forecast", "monthly"],
        description="Monthly engineering project forecast.")
    reg.write_csv(
        "data/Engineering/eng_nre_overrun_watchlist.csv",
        ["ProjectID", "ProjectName", "ProgramID", "BudgetUSD", "EAC_USD",
         "VarianceUSD", "VariancePct", "Status"], watch,
        department=dep, project=proj, artifact_type="Operational Data",
        tags=["engineering", "nre", "overrun", "ai-scenario"],
        description="NRE overrun watchlist (planted overrun scenario).")
    return labor


# ── Finance ────────────────────────────────────────────────────────────────
def _finance(reg, dims, rng, months, revenue, material, labor) -> None:
    proj, dep = "Finance", "Finance"

    reg.write_csv(
        "data/Finance/fin_gl_chart_of_accounts.csv",
        ["AccountNumber", "AccountName", "AccountType", "Category"],
        dims.accounts, department=dep, project=proj, artifact_type="Master Data",
        tags=["finance", "gl", "chart-of-accounts", "master"],
        description="GL chart of accounts.")

    # Indirect rates (monthly), fringe/overhead/g&a.
    rate_rows = []
    for m in months:
        rate_rows.append({
            "Month": m.isoformat(),
            "FringePct": round(rng.uniform(28, 34), 2),
            "OverheadPct": round(rng.uniform(95, 125), 2),
            "GA_Pct": round(rng.uniform(12, 18), 2),
        })
    reg.write_csv(
        "data/Finance/fin_indirect_rates_monthly.csv",
        ["Month", "FringePct", "OverheadPct", "GA_Pct"], rate_rows,
        department=dep, project=proj, artifact_type="Operational Data",
        tags=["finance", "indirect-rates", "monthly"],
        description="Monthly fringe / overhead / G&A rates.",
        date_range=f"{months[0].isoformat()}..{months[-1].isoformat()}")

    # GL monthly derived from the shared series.
    gl_rows = []
    actual_by_acct_month: dict[tuple[str, str], float] = {}
    for m in months:
        fp = C.fiscal_period(m)
        rev = sum(revenue.get((p["ProgramID"], fp), 0) for p in dims.programs)
        mat = material.get(fp, rev * 0.32)
        eng = labor.get(fp, rev * 0.08)
        dl = rev * rng.uniform(0.13, 0.17)
        moh = rev * rng.uniform(0.09, 0.12)
        scrap = rev * rng.uniform(0.015, 0.03)
        lines = {
            "4000": round(rev * 0.9, 2), "4100": round(rev * 0.1, 2),
            "5000": round(mat, 2), "5100": round(dl, 2), "5200": round(moh, 2),
            "5300": round(scrap, 2), "6000": round(eng, 2),
            "6100": round(eng * 0.4, 2), "6200": round(rev * 0.05, 2),
            "6300": round(rev * 0.06, 2), "6400": round(rev * 0.02, 2),
            "6500": round(rev * 0.015, 2), "7000": round(rev * 0.03, 2),
        }
        for acct, amt in lines.items():
            actual_by_acct_month[(acct, fp)] = amt
            name = next(a["AccountName"] for a in dims.accounts if a["AccountNumber"] == acct)
            gl_rows.append({"Month": m.isoformat(), "AccountNumber": acct,
                            "AccountName": name, "AmountUSD": amt})
    reg.write_csv(
        "data/Finance/fin_gl_monthly.csv",
        ["Month", "AccountNumber", "AccountName", "AmountUSD"], gl_rows,
        department=dep, project=proj, artifact_type="Operational Data",
        tags=["finance", "gl", "monthly"],
        description="Monthly general ledger derived from operating series.",
        date_range=f"{months[0].isoformat()}..{months[-1].isoformat()}")

    # Budget + forecast + budget-vs-actual (FY2026+).
    fmonths = C.month_starts(C.BUDGET_START, C.FORECAST_THROUGH)
    budget, forecast, bva = [], [], []
    for m in fmonths:
        fp = C.fiscal_period(m)
        for a in dims.accounts:
            if a["AccountType"] == "Asset":
                continue
            acct = a["AccountNumber"]
            base = actual_by_acct_month.get((acct, "2026-01"),
                                            actual_by_acct_month.get((acct, "2025-12"), 100000))
            bud = round(base * rng.uniform(0.98, 1.05), 2)
            fcst = round(bud * rng.uniform(0.97, 1.08), 2)
            budget.append({"Month": m.isoformat(), "Scenario": "Budget",
                           "Version": "FY26-Plan", "AccountNumber": acct,
                           "AccountName": a["AccountName"], "BudgetUSD": bud})
            forecast.append({"Month": m.isoformat(), "Scenario": "Forecast",
                             "Version": "FY26-F2", "AccountNumber": acct,
                             "AccountName": a["AccountName"], "ForecastUSD": fcst})
            actual = actual_by_acct_month.get((acct, fp))
            if actual is not None:
                var = round(actual - bud, 2)
                bva.append({"Month": m.isoformat(), "AccountNumber": acct,
                            "AccountName": a["AccountName"], "BudgetUSD": bud,
                            "ActualUSD": actual, "VarianceUSD": var,
                            "VariancePct": round(var / bud * 100, 1) if bud else 0})
    reg.write_csv(
        "data/Finance/fin_budget_monthly.csv",
        ["Month", "Scenario", "Version", "AccountNumber", "AccountName",
         "BudgetUSD"], budget, department=dep, project=proj,
        artifact_type="Budget", tags=["finance", "budget", "fy2026"],
        description="FY2026+ budget by account and month.")
    reg.write_csv(
        "data/Finance/fin_forecast_monthly.csv",
        ["Month", "Scenario", "Version", "AccountNumber", "AccountName",
         "ForecastUSD"], forecast, department=dep, project=proj,
        artifact_type="Forecast", tags=["finance", "forecast", "rolling"],
        description="Rolling forecast by account and month.")
    reg.write_csv(
        "data/Finance/fin_budget_vs_actual_monthly.csv",
        ["Month", "AccountNumber", "AccountName", "BudgetUSD", "ActualUSD",
         "VarianceUSD", "VariancePct"], bva, department=dep, project=proj,
        artifact_type="Operational Data",
        tags=["finance", "budget-vs-actual", "monthly", "ai-scenario"],
        description="Budget vs actual with planted material-cost variance.")

    # Capex budget, cash-flow forecast, headcount budget.
    capex = []
    for i, s in enumerate(dims.sites):
        for cat in ["Machining Center", "Automation Cell", "Test Equipment",
                    "Facilities Upgrade"]:
            capex.append({"ProjectID": f"CAPX-{i + 1:02d}-{cat[:3].upper()}",
                          "SiteID": s["SiteID"], "Category": cat,
                          "BudgetUSD": rng.choice([150000, 350000, 700000, 1200000]),
                          "ApprovedUSD": rng.choice([0, 150000, 350000]),
                          "Status": rng.choice(["Approved", "Pending", "Deferred"]),
                          "FiscalYear": "FY2026"})
    reg.write_csv(
        "data/Finance/fin_capex_budget.csv",
        ["ProjectID", "SiteID", "Category", "BudgetUSD", "ApprovedUSD", "Status",
         "FiscalYear"], capex, department=dep, project=proj,
        artifact_type="Budget", tags=["finance", "capex", "budget"],
        description="Capital expenditure budget by site.")

    cash = []
    bal = rng.uniform(6_000_000, 12_000_000)
    for m in fmonths:
        infl = round(rng.uniform(3_000_000, 6_000_000), 2)
        outf = round(rng.uniform(2_500_000, 5_800_000), 2)
        bal += infl - outf
        cash.append({"Month": m.isoformat(), "Scenario": "Forecast",
                     "CashInflowUSD": infl, "CashOutflowUSD": outf,
                     "NetCashUSD": round(infl - outf, 2),
                     "EndingCashUSD": round(bal, 2)})
    reg.write_csv(
        "data/Finance/fin_cash_flow_forecast.csv",
        ["Month", "Scenario", "CashInflowUSD", "CashOutflowUSD", "NetCashUSD",
         "EndingCashUSD"], cash, department=dep, project=proj,
        artifact_type="Forecast", tags=["finance", "cash-flow", "forecast"],
        description="Monthly cash-flow forecast.")

    hc = []
    for d in dims.departments:
        cur = sum(1 for e in dims.employees
                  if e["DeptID"] == d["DeptID"] and e["Status"] == "Active")
        hc.append({"DeptID": d["DeptID"], "DeptName": d["DeptName"],
                   "CurrentHeadcount": cur,
                   "BudgetHeadcount": cur + rng.randint(0, 6),
                   "PlannedHiresFY26": rng.randint(0, 8), "FiscalYear": "FY2026"})
    reg.write_csv(
        "data/Finance/fin_headcount_budget.csv",
        ["DeptID", "DeptName", "CurrentHeadcount", "BudgetHeadcount",
         "PlannedHiresFY26", "FiscalYear"], hc, department=dep, project=proj,
        artifact_type="Budget", tags=["finance", "headcount", "budget"],
        description="Headcount budget by department.")


# ── HR ─────────────────────────────────────────────────────────────────────
def _hr(reg, dims, rng, months) -> None:
    sc = dims.scenarios
    proj, dep = "HR", "HR"

    reg.write_csv(
        "data/HR/hr_sites.csv",
        ["SiteID", "SiteName", "City", "State", "Country", "Region",
         "SquareFeet", "OpenedDate"], dims.sites,
        department=dep, project=proj, artifact_type="Master Data",
        tags=["hr", "sites", "master"], description="Site master.")
    reg.write_csv(
        "data/HR/hr_departments.csv",
        ["DeptID", "DeptName", "Function", "CostCenter"], dims.departments,
        department=dep, project=proj, artifact_type="Master Data",
        tags=["hr", "departments", "master"], description="Department master.")
    reg.write_csv(
        "data/HR/hr_employees.csv",
        ["EmployeeID", "FullName", "DeptID", "SiteID", "JobClass", "HireDate",
         "Status", "TerminationDate", "ManagerID", "AnnualSalaryUSD"],
        dims.employees, department=dep, project=proj, artifact_type="Master Data",
        tags=["hr", "employees", "master"],
        description="Employee master with hires, terminations and status.")

    # Headcount plan (monthly), open reqs, onboarding, training, reviews,
    # timekeeping exceptions, attrition risk, comp changes.
    hc_rows = []
    for m in months:
        for d in dims.departments:
            active = sum(1 for e in dims.employees if e["DeptID"] == d["DeptID"]
                         and e["Status"] == "Active")
            hc_rows.append({"Month": m.isoformat(), "DeptID": d["DeptID"],
                            "DeptName": d["DeptName"],
                            "Headcount": active + rng.randint(-2, 2),
                            "Plan": active + rng.randint(0, 4)})
    reg.write_csv(
        "data/HR/hr_headcount_plan.csv",
        ["Month", "DeptID", "DeptName", "Headcount", "Plan"], hc_rows,
        department=dep, project=proj, artifact_type="Operational Data",
        tags=["hr", "headcount", "monthly"], description="Monthly headcount vs plan.")

    reqs = []
    for i in range(max(8, dims.spec.profile.employees // 20)):
        d = rng.choice(dims.departments)
        reqs.append({"RequisitionID": f"REQ-{i + 1:04d}", "DeptID": d["DeptID"],
                     "JobClass": rng.choice(["CNC Machinist", "Design Engineer",
                                             "Buyer", "Quality Inspector"]),
                     "SiteID": rng.choice(dims.site_ids),
                     "OpenedDate": dt.date(2026, rng.randint(1, 7), rng.randint(1, 28)).isoformat(),
                     "DaysOpen": rng.randint(5, 140),
                     "Status": rng.choice(["Open", "Open", "Filled", "On Hold"])})
    reg.write_csv(
        "data/HR/hr_open_requisitions.csv",
        ["RequisitionID", "DeptID", "JobClass", "SiteID", "OpenedDate",
         "DaysOpen", "Status"], reqs, department=dep, project=proj,
        artifact_type="Operational Data", tags=["hr", "requisitions", "recruiting"],
        description="Open requisitions and days-open.")

    onb = []
    recent = [e for e in dims.employees
              if e["HireDate"] >= "2026-01-01"][:60]
    for e in recent:
        onb.append({"EmployeeID": e["EmployeeID"], "FullName": e["FullName"],
                    "DeptID": e["DeptID"], "StartDate": e["HireDate"],
                    "ITAccessGrantedDays": rng.randint(0, 21),
                    "TrainingComplete": rng.choice(["Y", "Y", "N"]),
                    "Status": rng.choice(["Complete", "In Progress"])})
    reg.write_csv(
        "data/HR/hr_onboarding_status.csv",
        ["EmployeeID", "FullName", "DeptID", "StartDate", "ITAccessGrantedDays",
         "TrainingComplete", "Status"], onb, department=dep, project=proj,
        artifact_type="Operational Data", tags=["hr", "onboarding", "ai-scenario"],
        description="Onboarding status (IT access delay ties to IT scenario).")

    train = []
    for e in dims.employees[:200]:
        for course in ["Safety Orientation", "Quality Basics", "Ethics"]:
            train.append({"EmployeeID": e["EmployeeID"], "Course": course,
                          "CompletedDate": dt.date(2026, rng.randint(1, 6), rng.randint(1, 28)).isoformat(),
                          "Status": rng.choice(["Complete", "Complete", "Overdue"])})
    reg.write_csv(
        "data/HR/hr_training_records.csv",
        ["EmployeeID", "Course", "CompletedDate", "Status"], train,
        department=dep, project=proj, artifact_type="Operational Data",
        tags=["hr", "training"], description="Training completion records.")

    revs = []
    for e in dims.employees[:250]:
        revs.append({"EmployeeID": e["EmployeeID"], "ReviewCycle": "2026",
                     "Rating": rng.choice([2, 3, 3, 3, 4, 4, 5]),
                     "PromotionReady": rng.choice(["Y", "N", "N"]),
                     "ReviewerID": e["ManagerID"]})
    reg.write_csv(
        "data/HR/hr_performance_reviews.csv",
        ["EmployeeID", "ReviewCycle", "Rating", "PromotionReady", "ReviewerID"],
        revs, department=dep, project=proj, artifact_type="Operational Data",
        tags=["hr", "performance"], description="Annual performance reviews.")

    tke = []
    for _ in range(120):
        e = rng.choice(dims.employees)
        tke.append({"EmployeeID": e["EmployeeID"], "SiteID": e["SiteID"],
                    "Week": rng.choice(["2026-06-01", "2026-06-08", "2026-06-15",
                                        "2026-06-22"]),
                    "ExceptionType": rng.choice(["Missing Punch", "Overtime",
                                                 "Unapproved Absence"]),
                    "Hours": round(rng.uniform(0.5, 12), 1)})
    reg.write_csv(
        "data/HR/hr_timekeeping_exceptions.csv",
        ["EmployeeID", "SiteID", "Week", "ExceptionType", "Hours"], tke,
        department=dep, project=proj, artifact_type="Operational Data",
        tags=["hr", "timekeeping"], description="Timekeeping exceptions.")

    # Attrition risk (spike planted on attrition_job_class at attrition_site).
    atr = []
    for e in dims.employees:
        risk = rng.uniform(0.05, 0.35)
        if (e["JobClass"] == sc.attrition_job_class
                and e["SiteID"] == sc.attrition_site):
            risk = rng.uniform(0.55, 0.9)
        atr.append({"EmployeeID": e["EmployeeID"], "DeptID": e["DeptID"],
                    "SiteID": e["SiteID"], "JobClass": e["JobClass"],
                    "AttritionRiskScore": round(risk, 2),
                    "RiskTier": "High" if risk > 0.5 else ("Medium" if risk > 0.25 else "Low")})
    reg.write_csv(
        "data/HR/hr_attrition_risk.csv",
        ["EmployeeID", "DeptID", "SiteID", "JobClass", "AttritionRiskScore",
         "RiskTier"], atr, department=dep, project=proj,
        artifact_type="Operational Data",
        tags=["hr", "attrition", "ai-scenario"],
        description="Attrition risk with planted spike scenario.")

    comp = []
    for e in dims.employees[:150]:
        comp.append({"EmployeeID": e["EmployeeID"],
                     "EffectiveDate": dt.date(2026, rng.randint(1, 7), 1).isoformat(),
                     "ChangeType": rng.choice(["Merit", "Promotion", "Market Adj"]),
                     "OldSalaryUSD": e["AnnualSalaryUSD"],
                     "NewSalaryUSD": int(e["AnnualSalaryUSD"] * rng.uniform(1.02, 1.12))})
    reg.write_csv(
        "data/HR/hr_compensation_changes.csv",
        ["EmployeeID", "EffectiveDate", "ChangeType", "OldSalaryUSD",
         "NewSalaryUSD"], comp, department=dep, project=proj,
        artifact_type="Operational Data", tags=["hr", "compensation"],
        description="Compensation change log.")


# ── Quality ────────────────────────────────────────────────────────────────
def _quality(reg, dims, rng, months, weeks) -> None:
    sc = dims.scenarios
    proj, dep = "Quality", "Quality"

    ncr = []
    for i in range(max(40, len(weeks))):
        wk = rng.choice(weeks)
        sup_defect = rng.random() < 0.4
        supplier = sc.defect_supplier_id if sup_defect and rng.random() < 0.6 else rng.choice([s["SupplierID"] for s in dims.suppliers])
        ncr.append({"NCRID": f"NCR-{i + 1:04d}", "Date": wk.isoformat(),
                    "SiteID": rng.choice(dims.site_ids),
                    "WorkCenterID": rng.choice([w["WorkCenterID"] for w in dims.work_centers]),
                    "PartID": rng.choice([p["PartID"] for p in dims.parts]),
                    "SupplierID": supplier if sup_defect else "",
                    "DefectType": rng.choice(["Dimensional", "Cosmetic", "Material",
                                              "Assembly", "Documentation"]),
                    "Qty": rng.randint(1, 60),
                    "Disposition": rng.choice(["Use As Is", "Rework", "Scrap",
                                               "Return to Supplier"])})
    reg.write_csv(
        "data/Quality/quality_nonconformance_log.csv",
        ["NCRID", "Date", "SiteID", "WorkCenterID", "PartID", "SupplierID",
         "DefectType", "Qty", "Disposition"], ncr, department=dep, project=proj,
        artifact_type="Operational Data", tags=["quality", "ncr", "ai-scenario"],
        description="Nonconformance log linked to suppliers/work centers.")

    capa = []
    for i in range(24):
        opened = dt.date(2026, rng.randint(1, 6), rng.randint(1, 28))
        capa.append({"CAPAID": f"CAPA-{i + 1:04d}", "OpenedDate": opened.isoformat(),
                     "SupplierID": sc.defect_supplier_id if i < 4 else rng.choice([s["SupplierID"] for s in dims.suppliers]),
                     "Category": rng.choice(["Supplier", "Process", "Design"]),
                     "Severity": rng.choice(["Low", "Medium", "High"]),
                     "Status": rng.choice(["Open", "Open", "In Progress", "Closed"]),
                     "DaysOpen": rng.randint(3, 120)})
    reg.write_csv(
        "data/Quality/quality_capa_log.csv",
        ["CAPAID", "OpenedDate", "SupplierID", "Category", "Severity", "Status",
         "DaysOpen"], capa, department=dep, project=proj,
        artifact_type="Operational Data", tags=["quality", "capa"],
        description="Corrective/preventive action log.")

    score = []
    for s in dims.suppliers:
        defect_ppm = rng.uniform(200, 1500)
        if s["SupplierID"] == sc.defect_supplier_id:
            defect_ppm = rng.uniform(3500, 6000)
        score.append({"SupplierID": s["SupplierID"], "SupplierName": s["SupplierName"],
                      "OnTimeDeliveryPct": round(rng.uniform(82, 99), 1),
                      "DefectPPM": round(defect_ppm, 0),
                      "QualityScore": round(max(0, 100 - defect_ppm / 80), 1),
                      "Rating": "At Risk" if defect_ppm > 3000 else "Approved"})
    reg.write_csv(
        "data/Quality/quality_supplier_scorecards.csv",
        ["SupplierID", "SupplierName", "OnTimeDeliveryPct", "DefectPPM",
         "QualityScore", "Rating"], score, department=dep, project=proj,
        artifact_type="Operational Data",
        tags=["quality", "supplier-scorecard", "ai-scenario"],
        description="Supplier scorecards (planted supplier defect trend).")

    aud = []
    for i in range(18):
        aud.append({"FindingID": f"QAF-{i + 1:03d}",
                    "AuditDate": dt.date(2026, rng.randint(1, 6), rng.randint(1, 28)).isoformat(),
                    "SiteID": rng.choice(dims.site_ids),
                    "Clause": rng.choice(["7.5 Documented Info", "8.5 Production",
                                          "8.7 Nonconforming", "9.2 Internal Audit"]),
                    "Severity": rng.choice(["Minor", "Minor", "Major"]),
                    "Status": rng.choice(["Open", "Closed", "Closed"])})
    reg.write_csv(
        "data/Quality/quality_audit_findings.csv",
        ["FindingID", "AuditDate", "SiteID", "Clause", "Severity", "Status"],
        aud, department=dep, project=proj, artifact_type="Operational Data",
        tags=["quality", "audit"], description="ISO 9001 audit findings.")

    fai = []
    for i in range(30):
        fai.append({"FAIID": f"FAI-{i + 1:04d}",
                    "PartID": rng.choice([p["PartID"] for p in dims.parts]),
                    "SupplierID": rng.choice([s["SupplierID"] for s in dims.suppliers]),
                    "Date": dt.date(2026, rng.randint(1, 6), rng.randint(1, 28)).isoformat(),
                    "Result": rng.choice(["Pass", "Pass", "Pass", "Fail"])})
    reg.write_csv(
        "data/Quality/quality_first_article_inspections.csv",
        ["FAIID", "PartID", "SupplierID", "Date", "Result"], fai,
        department=dep, project=proj, artifact_type="Operational Data",
        tags=["quality", "fai"], description="First article inspection results.")

    comp = []
    for i in range(22):
        comp.append({"ComplaintID": f"CMP-{i + 1:04d}",
                     "Date": dt.date(2026, rng.randint(1, 6), rng.randint(1, 28)).isoformat(),
                     "Customer": rng.choice([p["Customer"] for p in dims.programs]),
                     "ProgramID": rng.choice(dims.program_ids),
                     "Category": rng.choice(["Late", "Quality", "Documentation"]),
                     "Severity": rng.choice(["Low", "Medium", "High"]),
                     "Status": rng.choice(["Open", "Closed"])})
    reg.write_csv(
        "data/Quality/quality_customer_complaints.csv",
        ["ComplaintID", "Date", "Customer", "ProgramID", "Category", "Severity",
         "Status"], comp, department=dep, project=proj,
        artifact_type="Operational Data", tags=["quality", "complaints"],
        description="Customer complaints log.")

    trend = []
    for m in months:
        for s in dims.site_ids:
            ppm = rng.uniform(400, 1200)
            if s == sc.scrap_site and m >= dt.date(2026, 1, 1):
                ppm *= 1.6
            trend.append({"Month": m.isoformat(), "SiteID": s,
                          "DefectPPM": round(ppm, 0),
                          "FirstPassYieldPct": round(rng.uniform(92, 99), 1)})
    reg.write_csv(
        "data/Quality/quality_defect_trends_monthly.csv",
        ["Month", "SiteID", "DefectPPM", "FirstPassYieldPct"], trend,
        department=dep, project=proj, artifact_type="Operational Data",
        tags=["quality", "defect-trend", "monthly", "ai-scenario"],
        description="Monthly defect trends (tie to scrap site).",
        date_range=f"{months[0].isoformat()}..{months[-1].isoformat()}")


# ── Procurement ────────────────────────────────────────────────────────────
def _procurement(reg, dims, rng, months) -> None:
    sc = dims.scenarios
    proj, dep = "Procurement", "Procurement"

    reg.write_csv(
        "data/Procurement/procurement_supplier_master.csv",
        ["SupplierID", "SupplierName", "Commodity", "Country", "OnboardedDate",
         "RiskTier"], dims.suppliers, department=dep, project=proj,
        artifact_type="Master Data", tags=["procurement", "supplier", "master"],
        description="Supplier master.")

    pos = []
    for i in range(max(120, len(dims.parts))):
        part = rng.choice(dims.parts)
        m = rng.choice(months)
        qty = rng.randint(50, 2000)
        unit = part["StandardCostUSD"] * rng.uniform(0.95, 1.2)
        late = rng.random() < 0.18
        pos.append({"POID": f"PO-{100000 + i}", "SupplierID": part["PrimarySupplierID"],
                    "PartID": part["PartID"], "OrderDate": m.isoformat(),
                    "Qty": qty, "UnitCostUSD": round(unit, 2),
                    "ExtendedUSD": round(qty * unit, 2),
                    "PromiseDate": (m + dt.timedelta(days=rng.randint(14, 60))).isoformat(),
                    "Status": "Late" if late else rng.choice(["Received", "Received", "Open"])})
    reg.write_csv(
        "data/Procurement/procurement_purchase_orders.csv",
        ["POID", "SupplierID", "PartID", "OrderDate", "Qty", "UnitCostUSD",
         "ExtendedUSD", "PromiseDate", "Status"], pos, department=dep,
        project=proj, artifact_type="Operational Data",
        tags=["procurement", "purchase-orders"], description="Purchase orders.")

    risk = []
    for s in dims.suppliers:
        rt = s["RiskTier"]
        if s["SupplierID"] == sc.defect_supplier_id:
            rt = "High"
        risk.append({"SupplierID": s["SupplierID"], "SupplierName": s["SupplierName"],
                     "RiskTier": rt,
                     "FinancialRisk": rng.choice(["Low", "Medium", "High"]),
                     "GeographicRisk": rng.choice(["Low", "Medium", "High"]),
                     "SingleSource": rng.choice(["Y", "N", "N"]),
                     "MitigationStatus": rng.choice(["Planned", "In Progress", "None"])})
    reg.write_csv(
        "data/Procurement/procurement_supplier_risk_register.csv",
        ["SupplierID", "SupplierName", "RiskTier", "FinancialRisk",
         "GeographicRisk", "SingleSource", "MitigationStatus"], risk,
        department=dep, project=proj, artifact_type="Operational Data",
        tags=["procurement", "risk"], description="Supplier risk register.")

    sc_contr = [c for c in dims.contracts if c["ContractType"] == "Supplier"]
    reg.write_csv(
        "data/Procurement/procurement_supplier_contracts.csv",
        ["ContractID", "CounterParty", "Category", "ValueUSD", "StartDate",
         "EndDate", "Status"],
        [{k: c[k] for k in ["ContractID", "CounterParty", "Category", "ValueUSD",
                            "StartDate", "EndDate", "Status"]} for c in sc_contr],
        department=dep, project=proj, artifact_type="Operational Data",
        tags=["procurement", "contracts"], description="Supplier contracts.")

    price = []
    commodities = list(dict.fromkeys(p["Commodity"] for p in dims.parts))
    for m in months:
        for com in commodities:
            idx = rng.uniform(98, 108)
            if com == dims.parts[0]["Commodity"] and m >= dt.date(2025, 10, 1):
                idx += 2.5 * ((m.year - 2025) * 12 + m.month - 10)
            price.append({"Month": m.isoformat(), "Commodity": com,
                          "PriceIndex": round(idx, 2)})
    reg.write_csv(
        "data/Procurement/procurement_material_price_history.csv",
        ["Month", "Commodity", "PriceIndex"], price, department=dep, project=proj,
        artifact_type="Operational Data",
        tags=["procurement", "price-index", "monthly", "ai-scenario"],
        description="Commodity price index (planted inflation).")

    late = []
    for i in range(60):
        s = rng.choice(dims.suppliers)
        late.append({"SupplierID": s["SupplierID"], "SupplierName": s["SupplierName"],
                     "POID": f"PO-{100000 + rng.randint(0, 119)}",
                     "PromiseDate": dt.date(2026, rng.randint(1, 6), rng.randint(1, 28)).isoformat(),
                     "DaysLate": rng.randint(1, 45),
                     "Impact": rng.choice(["Line Down", "Buffer", "None"])})
    reg.write_csv(
        "data/Procurement/procurement_late_delivery_log.csv",
        ["SupplierID", "SupplierName", "POID", "PromiseDate", "DaysLate", "Impact"],
        late, department=dep, project=proj, artifact_type="Operational Data",
        tags=["procurement", "late-delivery"], description="Late delivery log.")

    s2p = []
    for i in range(40):
        s2p.append({"ExceptionID": f"S2P-{i + 1:04d}",
                    "Type": rng.choice(["No PO", "Price Mismatch", "Qty Mismatch",
                                        "Duplicate Invoice"]),
                    "SupplierID": rng.choice([s["SupplierID"] for s in dims.suppliers]),
                    "AmountUSD": round(rng.uniform(500, 40000), 2),
                    "Status": rng.choice(["Open", "Resolved"])})
    reg.write_csv(
        "data/Procurement/procurement_source_to_pay_exceptions.csv",
        ["ExceptionID", "Type", "SupplierID", "AmountUSD", "Status"], s2p,
        department=dep, project=proj, artifact_type="Operational Data",
        tags=["procurement", "source-to-pay"], description="Source-to-pay exceptions.")


# ── IT ─────────────────────────────────────────────────────────────────────
def _it(reg, dims, rng, months) -> None:
    proj, dep = "IT", "IT"

    assets = []
    for i in range(max(150, dims.spec.profile.employees)):
        assets.append({"AssetID": f"AST-{i + 1:05d}",
                       "Type": rng.choice(["Laptop", "Desktop", "Server", "Network",
                                           "Mobile", "License"]),
                       "SiteID": rng.choice(dims.site_ids),
                       "AssignedTo": rng.choice([e["EmployeeID"] for e in dims.employees]),
                       "PurchaseDate": dt.date(rng.randint(2021, 2026), rng.randint(1, 12), 1).isoformat(),
                       "Status": rng.choice(["Active", "Active", "Retired"])})
    reg.write_csv(
        "data/IT/it_assets.csv",
        ["AssetID", "Type", "SiteID", "AssignedTo", "PurchaseDate", "Status"],
        assets, department=dep, project=proj, artifact_type="Operational Data",
        tags=["it", "assets"], description="IT asset inventory.")

    inc = []
    for i in range(90):
        inc.append({"IncidentID": f"INC-{i + 1:05d}",
                    "OpenedDate": dt.date(2026, rng.randint(1, 6), rng.randint(1, 28)).isoformat(),
                    "Category": rng.choice(["Access", "Hardware", "Network",
                                            "Application", "Security"]),
                    "Priority": rng.choice(["P1", "P2", "P3", "P3", "P4"]),
                    "SiteID": rng.choice(dims.site_ids),
                    "ResolutionHours": round(rng.uniform(0.5, 72), 1),
                    "Status": rng.choice(["Resolved", "Resolved", "Open"])})
    reg.write_csv(
        "data/IT/it_incidents.csv",
        ["IncidentID", "OpenedDate", "Category", "Priority", "SiteID",
         "ResolutionHours", "Status"], inc, department=dep, project=proj,
        artifact_type="Operational Data", tags=["it", "incidents"],
        description="IT incident log.")

    chg = []
    for i in range(50):
        chg.append({"ChangeID": f"CHG-{i + 1:05d}",
                    "SubmittedDate": dt.date(2026, rng.randint(1, 6), rng.randint(1, 28)).isoformat(),
                    "System": rng.choice(["ERP", "MES", "PLM", "Network", "Email"]),
                    "RiskLevel": rng.choice(["Low", "Medium", "High"]),
                    "Status": rng.choice(["Approved", "Implemented", "Rejected"])})
    reg.write_csv(
        "data/IT/it_change_requests.csv",
        ["ChangeID", "SubmittedDate", "System", "RiskLevel", "Status"], chg,
        department=dep, project=proj, artifact_type="Operational Data",
        tags=["it", "change-management"], description="IT change requests.")

    # Access requests: onboarding bottleneck (long days-to-grant) planted.
    acc = []
    recent = [e for e in dims.employees if e["HireDate"] >= "2026-01-01"][:80]
    for i, e in enumerate(recent):
        days = rng.randint(1, 6)
        if i % 3 == 0:  # onboarding bottleneck cohort
            days = rng.randint(9, 24)
        acc.append({"RequestID": f"ACC-{i + 1:05d}", "EmployeeID": e["EmployeeID"],
                    "RequestedDate": e["HireDate"], "System": rng.choice(["ERP", "MES", "VPN", "Email"]),
                    "DaysToGrant": days,
                    "Status": rng.choice(["Granted", "Granted", "Pending"])})
    reg.write_csv(
        "data/IT/it_access_requests.csv",
        ["RequestID", "EmployeeID", "RequestedDate", "System", "DaysToGrant",
         "Status"], acc, department=dep, project=proj,
        artifact_type="Operational Data", tags=["it", "access", "ai-scenario"],
        description="Access requests (planted onboarding-delay bottleneck).")

    sec = []
    for i in range(30):
        sec.append({"FindingID": f"SEC-{i + 1:04d}",
                    "Date": dt.date(2026, rng.randint(1, 6), rng.randint(1, 28)).isoformat(),
                    "Severity": rng.choice(["Low", "Medium", "High", "Critical"]),
                    "Category": rng.choice(["Patch", "Config", "Phishing", "Access"]),
                    "Status": rng.choice(["Open", "Remediated"])})
    reg.write_csv(
        "data/IT/it_security_findings.csv",
        ["FindingID", "Date", "Severity", "Category", "Status"], sec,
        department=dep, project=proj, artifact_type="Operational Data",
        tags=["it", "security"], description="Security findings.")

    bak = []
    for i in range(40):
        bak.append({"JobID": f"BAK-{i + 1:04d}",
                    "System": rng.choice(["ERP", "MES", "PLM", "FileServer"]),
                    "Date": dt.date(2026, 6, rng.randint(1, 28)).isoformat(),
                    "Result": rng.choice(["Success", "Success", "Success", "Failed"]),
                    "DurationMin": rng.randint(15, 240)})
    reg.write_csv(
        "data/IT/it_backup_jobs.csv",
        ["JobID", "System", "Date", "Result", "DurationMin"], bak,
        department=dep, project=proj, artifact_type="Operational Data",
        tags=["it", "backup"], description="Backup job results.")

    saas = []
    for i in range(25):
        saas.append({"VendorID": f"SAAS-{i + 1:03d}",
                     "VendorName": rng.choice(["Atlassian", "Salesforce", "Slack",
                                               "Zoom", "Okta", "Workday", "SAP",
                                               "Datadog", "GitHub"]) + f" #{i}",
                     "Category": rng.choice(["Collaboration", "ERP", "Security",
                                             "Analytics"]),
                     "AnnualCostUSD": rng.choice([12000, 45000, 120000, 350000]),
                     "RenewalMonth": dt.date(rng.randint(2026, 2027), rng.randint(1, 12), 1).isoformat(),
                     "DataClassification": rng.choice(["Public", "Internal",
                                                       "Confidential"])})
    reg.write_csv(
        "data/IT/it_saas_vendor_register.csv",
        ["VendorID", "VendorName", "Category", "AnnualCostUSD", "RenewalMonth",
         "DataClassification"], saas, department=dep, project=proj,
        artifact_type="Operational Data", tags=["it", "saas"],
        description="SaaS vendor register.")

    avail = []
    for m in months:
        for sysname in ["ERP", "MES", "PLM", "Email", "Network"]:
            avail.append({"Month": m.isoformat(), "System": sysname,
                          "UptimePct": round(rng.uniform(98.5, 99.99), 2),
                          "IncidentCount": rng.randint(0, 6)})
    reg.write_csv(
        "data/IT/it_system_availability_monthly.csv",
        ["Month", "System", "UptimePct", "IncidentCount"], avail,
        department=dep, project=proj, artifact_type="Operational Data",
        tags=["it", "availability", "monthly"], description="System availability.",
        date_range=f"{months[0].isoformat()}..{months[-1].isoformat()}")


# ── EHS ────────────────────────────────────────────────────────────────────
def _ehs(reg, dims, rng, months) -> None:
    sc = dims.scenarios
    proj, dep = "EHS", "EHS"

    inc = []
    for i in range(60):
        site = sc.incident_site if rng.random() < 0.45 else rng.choice(dims.site_ids)
        inc.append({"IncidentID": f"EHS-{i + 1:04d}",
                    "Date": dt.date(2026, rng.randint(1, 6), rng.randint(1, 28)).isoformat(),
                    "SiteID": site,
                    "Type": rng.choice(["Near Miss", "First Aid", "Recordable",
                                        "Lost Time", "Property"]),
                    "BodyPart": rng.choice(["Hand", "Back", "Eye", "Foot", "N/A"]),
                    "DaysLost": rng.randint(0, 12),
                    "RootCause": rng.choice(["PPE", "Procedure", "Housekeeping",
                                             "Equipment"])})
    reg.write_csv(
        "data/EHS/ehs_incidents.csv",
        ["IncidentID", "Date", "SiteID", "Type", "BodyPart", "DaysLost",
         "RootCause"], inc, department=dep, project=proj,
        artifact_type="Operational Data", tags=["ehs", "incidents", "ai-scenario"],
        description="Safety incidents (planted facility concentration).")

    for name, cols, gen, tags, desc in [
        ("ehs_training_records", ["EmployeeID", "Course", "CompletedDate", "Status"],
         lambda: [{"EmployeeID": rng.choice([e["EmployeeID"] for e in dims.employees]),
                   "Course": rng.choice(["Lockout/Tagout", "Hazard Communication",
                                         "Forklift", "Fall Protection"]),
                   "CompletedDate": dt.date(2026, rng.randint(1, 6), rng.randint(1, 28)).isoformat(),
                   "Status": rng.choice(["Complete", "Complete", "Overdue"])} for _ in range(150)],
         ["ehs", "training"], "EHS training records."),
        ("ehs_audit_findings", ["FindingID", "Date", "SiteID", "Area", "Severity", "Status"],
         lambda: [{"FindingID": f"EHSA-{i + 1:03d}",
                   "Date": dt.date(2026, rng.randint(1, 6), rng.randint(1, 28)).isoformat(),
                   "SiteID": rng.choice(dims.site_ids),
                   "Area": rng.choice(["Machining", "Chemical Storage", "Dock",
                                       "Electrical"]),
                   "Severity": rng.choice(["Minor", "Major"]),
                   "Status": rng.choice(["Open", "Closed"])} for i in range(24)],
         ["ehs", "audit"], "EHS audit findings."),
        ("ehs_hazard_assessments", ["AssessmentID", "SiteID", "Process", "RiskScore", "Date"],
         lambda: [{"AssessmentID": f"HAZ-{i + 1:03d}", "SiteID": rng.choice(dims.site_ids),
                   "Process": rng.choice(["Welding", "Painting", "Machining"]),
                   "RiskScore": rng.randint(1, 25),
                   "Date": dt.date(2026, rng.randint(1, 6), 1).isoformat()} for i in range(20)],
         ["ehs", "hazard"], "Hazard assessments."),
        ("ehs_ppe_inspections", ["InspectionID", "SiteID", "PPEType", "PassPct", "Date"],
         lambda: [{"InspectionID": f"PPE-{i + 1:03d}", "SiteID": rng.choice(dims.site_ids),
                   "PPEType": rng.choice(["Eyewear", "Gloves", "Respirator", "Hearing"]),
                   "PassPct": round(rng.uniform(85, 100), 1),
                   "Date": dt.date(2026, rng.randint(1, 6), 1).isoformat()} for i in range(30)],
         ["ehs", "ppe"], "PPE inspections."),
        ("ehs_emergency_drill_log", ["DrillID", "SiteID", "Type", "Date", "EvacTimeMin", "Result"],
         lambda: [{"DrillID": f"DRL-{i + 1:03d}", "SiteID": rng.choice(dims.site_ids),
                   "Type": rng.choice(["Fire", "Tornado", "Chemical Spill"]),
                   "Date": dt.date(2026, rng.randint(1, 6), 1).isoformat(),
                   "EvacTimeMin": round(rng.uniform(2, 9), 1),
                   "Result": rng.choice(["Pass", "Pass", "Needs Improvement"])} for i in range(15)],
         ["ehs", "drill"], "Emergency drill log."),
        ("ehs_facilities_work_orders", ["WorkOrderID", "SiteID", "Category", "Priority", "Status", "OpenedDate"],
         lambda: [{"WorkOrderID": f"FWO-{i + 1:04d}", "SiteID": rng.choice(dims.site_ids),
                   "Category": rng.choice(["HVAC", "Electrical", "Plumbing", "Safety"]),
                   "Priority": rng.choice(["Low", "Medium", "High"]),
                   "Status": rng.choice(["Open", "Closed"]),
                   "OpenedDate": dt.date(2026, rng.randint(1, 6), rng.randint(1, 28)).isoformat()} for i in range(45)],
         ["ehs", "facilities"], "Facilities work orders."),
    ]:
        reg.write_csv(f"data/EHS/{name}.csv", cols, gen(), department=dep,
                      project=proj, artifact_type="Operational Data", tags=tags,
                      description=desc)


# ── Legal & Contracts ──────────────────────────────────────────────────────
def _legal(reg, dims, rng) -> None:
    proj, dep = "Legal & Contracts", "Legal_Contracts"

    reg.write_csv(
        "data/Legal_Contracts/contracts_master.csv",
        ["ContractID", "CounterParty", "ContractType", "Category", "ValueUSD",
         "StartDate", "EndDate", "Status"], dims.contracts, department=dep,
        project=proj, artifact_type="Master Data", tags=["legal", "contracts", "master"],
        description="Contracts master.")

    obl = []
    for c in dims.contracts:
        for _ in range(rng.randint(1, 3)):
            obl.append({"ContractID": c["ContractID"], "CounterParty": c["CounterParty"],
                        "ObligationType": rng.choice(["Delivery", "Payment", "Reporting",
                                                      "Renewal Notice", "Audit Right"]),
                        "DueDate": dt.date(2026, rng.randint(1, 12), rng.randint(1, 28)).isoformat(),
                        "Status": rng.choice(["Met", "Met", "Upcoming", "Overdue"])})
    reg.write_csv(
        "data/Legal_Contracts/contracts_obligations.csv",
        ["ContractID", "CounterParty", "ObligationType", "DueDate", "Status"],
        obl, department=dep, project=proj, artifact_type="Operational Data",
        tags=["legal", "obligations"], description="Contract obligations.")

    for name, cols, gen, tags, desc in [
        ("contracts_risk_register", ["ContractID", "RiskType", "Severity", "Likelihood", "Mitigation"],
         lambda: [{"ContractID": rng.choice([c["ContractID"] for c in dims.contracts]),
                   "RiskType": rng.choice(["Liability Cap", "IP", "Termination",
                                           "Indemnity", "Pricing"]),
                   "Severity": rng.choice(["Low", "Medium", "High"]),
                   "Likelihood": rng.choice(["Low", "Medium", "High"]),
                   "Mitigation": rng.choice(["Insurance", "Renegotiate", "Accept",
                                             "Escalate"])} for _ in range(30)],
         ["legal", "risk"], "Contract risk register."),
        ("contracts_review_log", ["ReviewID", "ContractID", "Reviewer", "ReviewDate", "Outcome"],
         lambda: [{"ReviewID": f"CRV-{i + 1:04d}",
                   "ContractID": rng.choice([c["ContractID"] for c in dims.contracts]),
                   "Reviewer": rng.choice([e["EmployeeID"] for e in dims.employees]),
                   "ReviewDate": dt.date(2026, rng.randint(1, 6), rng.randint(1, 28)).isoformat(),
                   "Outcome": rng.choice(["Approved", "Revisions", "Escalated"])} for i in range(40)],
         ["legal", "review"], "Contract review log."),
        ("contracts_nda_register", ["NDAID", "CounterParty", "SignedDate", "ExpiryDate", "Status"],
         lambda: [{"NDAID": f"NDA-{i + 1:04d}",
                   "CounterParty": rng.choice([c["CounterParty"] for c in dims.contracts]),
                   "SignedDate": dt.date(rng.randint(2024, 2026), rng.randint(1, 12), 1).isoformat(),
                   "ExpiryDate": dt.date(rng.randint(2027, 2029), rng.randint(1, 12), 1).isoformat(),
                   "Status": rng.choice(["Active", "Active", "Expired"])} for i in range(35)],
         ["legal", "nda"], "NDA register."),
        ("contracts_records_retention_index", ["RecordID", "RecordType", "RetentionYears", "Location", "DisposalDate"],
         lambda: [{"RecordID": f"REC-{i + 1:04d}",
                   "RecordType": rng.choice(["Contract", "Financial", "HR", "Quality",
                                             "EHS"]),
                   "RetentionYears": rng.choice([3, 5, 7, 10]),
                   "Location": rng.choice(["Vault", "Cloud", "Offsite"]),
                   "DisposalDate": dt.date(rng.randint(2027, 2035), 1, 1).isoformat()} for i in range(30)],
         ["legal", "retention"], "Records retention index."),
        ("contracts_claims_disputes_log", ["ClaimID", "CounterParty", "Type", "AmountUSD", "Status", "OpenedDate"],
         lambda: [{"ClaimID": f"CLM-{i + 1:04d}",
                   "CounterParty": rng.choice([c["CounterParty"] for c in dims.contracts]),
                   "Type": rng.choice(["Warranty", "Delivery", "Payment", "IP"]),
                   "AmountUSD": round(rng.uniform(5000, 500000), 2),
                   "Status": rng.choice(["Open", "Settled", "Closed"]),
                   "OpenedDate": dt.date(2026, rng.randint(1, 6), rng.randint(1, 28)).isoformat()} for i in range(18)],
         ["legal", "claims"], "Claims and disputes log."),
    ]:
        reg.write_csv(f"data/Legal_Contracts/{name}.csv", cols, gen(),
                      department=dep, project=proj, artifact_type="Operational Data",
                      tags=tags, description=desc)


# ── Executive ──────────────────────────────────────────────────────────────
def _executive(reg, dims, rng, months, revenue) -> None:
    sc = dims.scenarios
    proj, dep = "Executive", "Executive"

    kpi = []
    for m in months:
        rev = sum(revenue.get((p["ProgramID"], C.fiscal_period(m)), 0) for p in dims.programs)
        kpi.append({"Month": m.isoformat(), "RevenueUSD": round(rev, 2),
                    "GrossMarginPct": round(rng.uniform(24, 31), 1),
                    "OperatingMarginPct": round(rng.uniform(8, 14), 1),
                    "OnTimeDeliveryPct": round(rng.uniform(88, 97), 1),
                    "ScrapPct": round(rng.uniform(1.8, 3.6), 2),
                    "AttritionPct": round(rng.uniform(6, 15), 1)})
    reg.write_csv(
        "data/Executive/executive_kpi_scorecard_monthly.csv",
        ["Month", "RevenueUSD", "GrossMarginPct", "OperatingMarginPct",
         "OnTimeDeliveryPct", "ScrapPct", "AttritionPct"], kpi, department=dep,
        project=proj, artifact_type="Operational Data",
        tags=["executive", "kpi", "monthly"], description="Executive KPI scorecard.",
        date_range=f"{months[0].isoformat()}..{months[-1].isoformat()}")

    risks = [
        ("Rising material costs", "Finance", "High", sc.material_cost_program),
        ("Scrap creep at key line", "Manufacturing", "High", sc.scrap_work_center),
        ("NRE overrun", "Engineering", "High", ",".join(sc.overrun_projects)),
        ("Critical-role attrition", "HR", "Medium", sc.attrition_job_class),
        ("Supplier defect trend", "Quality", "High", sc.defect_supplier_name),
        ("Onboarding access delays", "IT", "Medium", ""),
        ("Facility incident trend", "EHS", "Medium", sc.incident_site),
        ("Sales forecast slippage", "Sales", "Medium", sc.slipping_customer),
        ("Contract renewal exposure", "Legal", "Low", ""),
        ("Cyber security posture", "IT", "Medium", ""),
    ]
    rr = []
    for i, (title, owner, sev, ref) in enumerate(risks):
        rr.append({"RiskID": f"RSK-{i + 1:03d}", "Title": title, "OwnerDept": owner,
                   "Severity": sev, "Likelihood": rng.choice(["Medium", "High"]),
                   "Category": rng.choice(["Operational", "Financial", "Strategic",
                                           "Compliance"]),
                   "ReferenceID": ref,
                   "Status": rng.choice(["Open", "Open", "Monitoring"]),
                   "ReviewDate": "2026-06-30"})
    reg.write_csv(
        "data/Executive/enterprise_risk_register.csv",
        ["RiskID", "Title", "OwnerDept", "Severity", "Likelihood", "Category",
         "ReferenceID", "Status", "ReviewDate"], rr, department=dep, project=proj,
        artifact_type="Operational Data", tags=["executive", "risk", "ai-scenario"],
        description="Enterprise risk register (ties to all planted scenarios).")

    # Action items — "Operational" category repeatedly overdue (planted).
    ai = []
    owners = [e["EmployeeID"] for e in dims.employees[:30]]
    for i in range(50):
        cat = rng.choice(["Operational", "Operational", "Financial", "Strategic",
                          "Compliance"])
        overdue = cat == "Operational" and rng.random() < 0.7
        due = dt.date(2026, rng.randint(1, 7), rng.randint(1, 28))
        ai.append({"ActionID": f"ACT-{i + 1:04d}",
                   "Description": rng.choice(["Contain scrap", "Requalify supplier",
                                              "Rebaseline NRE", "Backfill role",
                                              "Close audit finding", "Update forecast"]),
                   "Category": cat, "OwnerID": rng.choice(owners),
                   "DueDate": due.isoformat(),
                   "Status": "Overdue" if overdue else rng.choice(["Open", "Closed",
                                                                   "In Progress"])})
    reg.write_csv(
        "data/Executive/action_items.csv",
        ["ActionID", "Description", "Category", "OwnerID", "DueDate", "Status"],
        ai, department=dep, project=proj, artifact_type="Operational Data",
        tags=["executive", "action-items", "ai-scenario"],
        description="Action items (planted overdue-Operational trend).")

    dl = []
    for i in range(24):
        dl.append({"DecisionID": f"DEC-{i + 1:04d}",
                   "Date": dt.date(2026, rng.randint(1, 6), rng.randint(1, 28)).isoformat(),
                   "Topic": rng.choice(["Capex approval", "Pricing", "Hiring freeze",
                                        "Supplier switch", "Program go/no-go"]),
                   "Decision": rng.choice(["Approved", "Deferred", "Rejected"]),
                   "OwnerDept": rng.choice([d["DeptName"] for d in dims.departments])})
    reg.write_csv(
        "data/Executive/decision_log.csv",
        ["DecisionID", "Date", "Topic", "Decision", "OwnerDept"], dl,
        department=dep, project=proj, artifact_type="Operational Data",
        tags=["executive", "decisions"], description="Decision log.")

    mrm = []
    for m in months[-7:]:
        rev = sum(revenue.get((p["ProgramID"], C.fiscal_period(m)), 0) for p in dims.programs)
        mrm.append({"Month": m.isoformat(), "RevenueUSD": round(rev, 2),
                    "BudgetUSD": round(rev * rng.uniform(0.97, 1.03), 2),
                    "OpenActions": rng.randint(10, 30), "TopRisk": risks[0][0]})
    reg.write_csv(
        "data/Executive/monthly_review_metrics.csv",
        ["Month", "RevenueUSD", "BudgetUSD", "OpenActions", "TopRisk"], mrm,
        department=dep, project=proj, artifact_type="Operational Data",
        tags=["executive", "monthly-review"], description="Monthly review metrics.")

    qrm = []
    for q in ["2026-Q1", "2026-Q2"]:
        qrm.append({"Quarter": q, "RevenueUSD": round(rng.uniform(11e6, 15e6), 2),
                    "GrossMarginPct": round(rng.uniform(25, 30), 1),
                    "BookToBill": round(rng.uniform(0.95, 1.15), 2),
                    "TopRisk": risks[0][0]})
    reg.write_csv(
        "data/Executive/quarterly_review_metrics.csv",
        ["Quarter", "RevenueUSD", "GrossMarginPct", "BookToBill", "TopRisk"], qrm,
        department=dep, project=proj, artifact_type="Operational Data",
        tags=["executive", "quarterly-review"], description="Quarterly review metrics.")

    si = []
    for i, name in enumerate(["Operational Excellence", "Digital Manufacturing",
                              "Supplier Consolidation", "Talent Pipeline",
                              "Margin Expansion", "New Program Capture"]):
        si.append({"InitiativeID": f"INI-{i + 1:02d}", "Name": name,
                   "SponsorDept": rng.choice([d["DeptName"] for d in dims.departments]),
                   "Status": rng.choice(["On Track", "At Risk", "Behind"]),
                   "PctComplete": rng.randint(10, 95),
                   "TargetDate": dt.date(2026, rng.randint(8, 12), 1).isoformat()})
    reg.write_csv(
        "data/Executive/strategy_initiatives.csv",
        ["InitiativeID", "Name", "SponsorDept", "Status", "PctComplete",
         "TargetDate"], si, department=dep, project=proj,
        artifact_type="Operational Data", tags=["executive", "strategy"],
        description="Strategic initiatives.")
