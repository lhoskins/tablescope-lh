from __future__ import annotations

import datetime as dt


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


