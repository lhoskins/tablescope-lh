from __future__ import annotations

import datetime as dt

from ._common import C, _seasonal


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


