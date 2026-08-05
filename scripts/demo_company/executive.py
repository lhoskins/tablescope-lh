from __future__ import annotations

import datetime as dt

from ._common import C


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
