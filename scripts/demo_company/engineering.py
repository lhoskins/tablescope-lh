from __future__ import annotations

import datetime as dt

from ._common import C


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


