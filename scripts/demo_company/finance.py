from __future__ import annotations

from ._common import C


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


