from __future__ import annotations

import datetime as dt

from ._common import C


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
        for _i, wk in enumerate(weeks):
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


