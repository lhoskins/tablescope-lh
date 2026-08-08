from __future__ import annotations

import datetime as dt


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


