from __future__ import annotations

import datetime as dt


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


