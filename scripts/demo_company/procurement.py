from __future__ import annotations

import datetime as dt


# ── Procurement ────────────────────────────────────────────────────────────
def _procurement(reg, dims, rng, months) -> None:
    sc = dims.scenarios
    proj, dep = "Procurement", "Procurement"

    reg.write_csv(
        "data/Procurement/procurement_supplier_master.csv",
        ["SupplierID", "SupplierName", "Commodity", "Country", "OnboardedDate",
         "RiskTier"], dims.suppliers, department=dep, project=proj,
        artifact_type="Master Data", tags=["procurement", "supplier", "master"],
        description="Supplier master.")

    pos = []
    for i in range(max(120, len(dims.parts))):
        part = rng.choice(dims.parts)
        m = rng.choice(months)
        qty = rng.randint(50, 2000)
        unit = part["StandardCostUSD"] * rng.uniform(0.95, 1.2)
        late = rng.random() < 0.18
        pos.append({"POID": f"PO-{100000 + i}", "SupplierID": part["PrimarySupplierID"],
                    "PartID": part["PartID"], "OrderDate": m.isoformat(),
                    "Qty": qty, "UnitCostUSD": round(unit, 2),
                    "ExtendedUSD": round(qty * unit, 2),
                    "PromiseDate": (m + dt.timedelta(days=rng.randint(14, 60))).isoformat(),
                    "Status": "Late" if late else rng.choice(["Received", "Received", "Open"])})
    reg.write_csv(
        "data/Procurement/procurement_purchase_orders.csv",
        ["POID", "SupplierID", "PartID", "OrderDate", "Qty", "UnitCostUSD",
         "ExtendedUSD", "PromiseDate", "Status"], pos, department=dep,
        project=proj, artifact_type="Operational Data",
        tags=["procurement", "purchase-orders"], description="Purchase orders.")

    risk = []
    for s in dims.suppliers:
        rt = s["RiskTier"]
        if s["SupplierID"] == sc.defect_supplier_id:
            rt = "High"
        risk.append({"SupplierID": s["SupplierID"], "SupplierName": s["SupplierName"],
                     "RiskTier": rt,
                     "FinancialRisk": rng.choice(["Low", "Medium", "High"]),
                     "GeographicRisk": rng.choice(["Low", "Medium", "High"]),
                     "SingleSource": rng.choice(["Y", "N", "N"]),
                     "MitigationStatus": rng.choice(["Planned", "In Progress", "None"])})
    reg.write_csv(
        "data/Procurement/procurement_supplier_risk_register.csv",
        ["SupplierID", "SupplierName", "RiskTier", "FinancialRisk",
         "GeographicRisk", "SingleSource", "MitigationStatus"], risk,
        department=dep, project=proj, artifact_type="Operational Data",
        tags=["procurement", "risk"], description="Supplier risk register.")

    sc_contr = [c for c in dims.contracts if c["ContractType"] == "Supplier"]
    reg.write_csv(
        "data/Procurement/procurement_supplier_contracts.csv",
        ["ContractID", "CounterParty", "Category", "ValueUSD", "StartDate",
         "EndDate", "Status"],
        [{k: c[k] for k in ["ContractID", "CounterParty", "Category", "ValueUSD",
                            "StartDate", "EndDate", "Status"]} for c in sc_contr],
        department=dep, project=proj, artifact_type="Operational Data",
        tags=["procurement", "contracts"], description="Supplier contracts.")

    price = []
    commodities = list(dict.fromkeys(p["Commodity"] for p in dims.parts))
    for m in months:
        for com in commodities:
            idx = rng.uniform(98, 108)
            if com == dims.parts[0]["Commodity"] and m >= dt.date(2025, 10, 1):
                idx += 2.5 * ((m.year - 2025) * 12 + m.month - 10)
            price.append({"Month": m.isoformat(), "Commodity": com,
                          "PriceIndex": round(idx, 2)})
    reg.write_csv(
        "data/Procurement/procurement_material_price_history.csv",
        ["Month", "Commodity", "PriceIndex"], price, department=dep, project=proj,
        artifact_type="Operational Data",
        tags=["procurement", "price-index", "monthly", "ai-scenario"],
        description="Commodity price index (planted inflation).")

    late = []
    for _i in range(60):
        s = rng.choice(dims.suppliers)
        late.append({"SupplierID": s["SupplierID"], "SupplierName": s["SupplierName"],
                     "POID": f"PO-{100000 + rng.randint(0, 119)}",
                     "PromiseDate": dt.date(2026, rng.randint(1, 6), rng.randint(1, 28)).isoformat(),
                     "DaysLate": rng.randint(1, 45),
                     "Impact": rng.choice(["Line Down", "Buffer", "None"])})
    reg.write_csv(
        "data/Procurement/procurement_late_delivery_log.csv",
        ["SupplierID", "SupplierName", "POID", "PromiseDate", "DaysLate", "Impact"],
        late, department=dep, project=proj, artifact_type="Operational Data",
        tags=["procurement", "late-delivery"], description="Late delivery log.")

    s2p = []
    for i in range(40):
        s2p.append({"ExceptionID": f"S2P-{i + 1:04d}",
                    "Type": rng.choice(["No PO", "Price Mismatch", "Qty Mismatch",
                                        "Duplicate Invoice"]),
                    "SupplierID": rng.choice([s["SupplierID"] for s in dims.suppliers]),
                    "AmountUSD": round(rng.uniform(500, 40000), 2),
                    "Status": rng.choice(["Open", "Resolved"])})
    reg.write_csv(
        "data/Procurement/procurement_source_to_pay_exceptions.csv",
        ["ExceptionID", "Type", "SupplierID", "AmountUSD", "Status"], s2p,
        department=dep, project=proj, artifact_type="Operational Data",
        tags=["procurement", "source-to-pay"], description="Source-to-pay exceptions.")


