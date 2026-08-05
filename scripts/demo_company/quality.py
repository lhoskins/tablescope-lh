from __future__ import annotations

import datetime as dt


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


