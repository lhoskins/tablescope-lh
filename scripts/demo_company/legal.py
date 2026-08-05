from __future__ import annotations

import datetime as dt


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


