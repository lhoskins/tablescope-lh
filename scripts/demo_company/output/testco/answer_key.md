# TestCo Demo Company — Answer Key (Planted Scenarios)

These are the AI-discoverable stories seeded into the data and documents. Each is internally consistent across departments so Tablescope can demonstrate cross-department analytics and document intelligence.

## 1. Finance — material-cost budget variance
- Program **PGM-003** shows rising material cost from 2025-10 onward.
- Data: `data/Manufacturing/mfg_material_actuals_monthly.csv`, `data/Finance/fin_budget_vs_actual_monthly.csv`, `data/Procurement/procurement_material_price_history.csv`.
- Docs: `FIN-001`, `FIN-003`.

## 2. Manufacturing — scrap creep
- Work center **WC-002** at site **SITE-01** shows scrap % climbing through H1 2026.
- Data: `data/Manufacturing/mfg_scrap_weekly.csv`, `data/Quality/quality_defect_trends_monthly.csv`.
- Docs: `MFG-001`.

## 3. Engineering — NRE overrun
- Projects **EPRJ-003, EPRJ-007** (programs PGM-003, PGM-007) exceed budget ~28%.
- Data: `data/Engineering/eng_nre_overrun_watchlist.csv`, `data/Engineering/eng_labor_actuals_monthly.csv`.
- Docs: `ENG-001`.

## 4. HR — attrition spike
- **CNC Machinist** at site **SITE-01** shows high attrition risk.
- Data: `data/HR/hr_attrition_risk.csv`.
- Docs: `HR-001`, `HR-002`.

## 5. Quality — supplier defect trend
- Supplier **Apex Metalworks** (SUP-001) has elevated defect PPM, linked to manufacturing scrap.
- Data: `data/Quality/quality_supplier_scorecards.csv`, `data/Quality/quality_nonconformance_log.csv`.
- Docs: `QA-002`.

## 6. IT — onboarding access delay
- A cohort of new hires has long access-grant times.
- Data: `data/IT/it_access_requests.csv`, `data/HR/hr_onboarding_status.csv`.
- Docs: `IT-002`, `HR-004`.

## 7. EHS — facility incident trend
- Incidents concentrate at site **SITE-01**.
- Data: `data/EHS/ehs_incidents.csv`.
- Docs: `EHS-001`, `EHS-002`.

## 8. Sales — forecast slippage
- Customer **Meridian Motors** opportunities slip; revenue dips in H1 2026.
- Data: `data/Sales/sales_pipeline_forecast.csv`, `data/Sales/sales_revenue_monthly.csv`.
- Docs: `SAL-002`.

## 9. Executive — overdue action items
- Action items in the **Operational** category are repeatedly overdue.
- Data: `data/Executive/action_items.csv`, `data/Executive/enterprise_risk_register.csv`.
- Docs: `EXEC-001`.
