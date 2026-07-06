# Simplicit Demo Company — Synthetic Dataset

**Version:** 1.0  
**Data Through:** July 6, 2026  
**Seed:** 42 (fully reproducible)  
**Purpose:** Tablescope demo dataset — safe for all demo environments; no real PII or proprietary information

---

## Overview

Simplicit Demo Company is a fictional mid-size discrete manufacturer of precision metal components headquartered in Columbus, Ohio. The dataset provides a realistic, internally consistent set of operational, financial, and HR data spanning January 2023 through July 2026, along with policy documents, standard operating procedures, and executive review materials.

**Company facts:**
- ~320 employees across HQ, Plant A (Columbus), and Plant B (Dayton)
- Industries served: Aerospace, Automotive, Defense, Medical, Industrial
- Annual revenue approximately $45M (2026 revised forecast)
- Departments: Engineering, Finance, HR, IT, Manufacturing, Procurement, Quality, Sales, EHS, Executive

---

## How to Regenerate All CSVs

```bash
cd simplicit/
python generate.py
```

Requirements: Python 3.8+, standard library only (no pip dependencies). The script is fully deterministic with `random.seed(42)`.

---

## Directory Structure

```
simplicit/
  generate.py              # Dataset generator (seed=42)
  README.md                # This file
  data_dictionary.md       # Column-level documentation for all CSV files
  documents_dictionary.md  # Index of all document files
  data/
    hr/                    # Employees, headcount, turnover, compensation, training
    finance/               # GL, budget, actuals, forecast, capex
    sales/                 # Orders, customers, forecast, pipeline
    manufacturing/         # Production, OEE, inventory, work orders
    engineering/           # Projects, budgets, ECRs, BOM
    quality/               # NCRs, audits, supplier scorecards, inspections
    procurement/           # Purchase orders, suppliers, spend
    it/                    # Assets, tickets, software licenses
    ehs/                   # Incidents, training compliance, inspections
    executive/             # KPI monthly, risk register
  docs/
    policies/              # 15 company policies (POL-001 through POL-015)
    procedures/            # SOPs by department (2+ per dept, 9 depts)
      executive/ finance/ hr/ manufacturing/ engineering/
      sales/ quality/ it/ legal/ ehs/
    executive_reviews/
      monthly/             # Jan 2026 – Jul 2026 monthly executive reviews
      quarterly/           # Q1 and Q2 2026 comprehensive quarterly reviews
```

---

## Embedded Demo Patterns

The following analytical patterns are embedded in the data and designed to surface clearly in Tablescope demos:

### 1. Material Cost Variance (Finance)
`data/finance/gl_summary_monthly.csv` and `procurement/spend_by_category_monthly.csv`: Account 6100 (Direct Materials) and Raw Materials category run **8–12% over budget starting February 2026**. Upstream cause: titanium and steel price increases.

**Demo use:** Budget variance analysis, drill-down from P&L to cost category, finance-operations connection.

### 2. Line 2 Scrap Rate Trend (Manufacturing)
`data/manufacturing/production_weekly.csv` and `oee_weekly.csv`: Line 2 scrap rate increases from **~2.1% baseline to ~4.8% peak** over March–June 2026, reflecting a real quality degradation event (coolant contamination + tooling spec mismatch).

**Demo use:** Operational trend analysis, anomaly detection, cross-functional root cause (quality + manufacturing + engineering data).

### 3. Sales Forecast Slippage (Sales)
`data/sales/sales_forecast_monthly.csv` and `orders.csv`: Q2 2026 bookings run **~15% below plan** across product lines, with Automotive showing the deepest decline. Pipeline data remains healthy (coverage 3.1x).

**Demo use:** Sales pipeline vs. actuals comparison, leading/lagging indicator analysis, revenue forecasting.

### 4. Attrition Spike (HR)
`data/hr/employees.csv` and `turnover_monthly.csv`: Voluntary terminations elevated in **Q1 2026 (annualized rate ~15%) and again in June 2026 (annualized rate ~19%)**. Consistent with exit interview themes of compensation and competitor poaching documented in executive reviews.

**Demo use:** HR analytics, turnover trend detection, workforce risk identification.

### 5. Engineering Project Cost Overruns (Engineering)
`data/engineering/projects.csv` and `project_budget_monthly.csv`: Projects EPRJ-003 and EPRJ-007 show **20%+ cost overruns** by June 2026, with the budget monthly data showing escalating variance starting February 2026.

**Demo use:** Project portfolio management, budget variance drilling, resource allocation analysis.

---

## Cross-File Consistency

The dataset is internally consistent across these key linkages:
- `employees.csv` emp_ids are referenced in `training_completions.csv`
- `supplier_master.csv` supplier_ids appear in `purchase_orders.csv`, `bom.csv`, and `quality/supplier_scorecard.csv`
- `engineering/projects.csv` project_ids appear in `project_budget_monthly.csv` and `ecr_log.csv`
- `manufacturing/production_weekly.csv` line_ids and scrap trends align with `oee_weekly.csv` quality dimension
- `sales/orders.csv` customer_ids match `customers.csv`
- `executive/kpi_monthly.csv` reflects the same patterns as the underlying operational data

---

## Document Files

**Policies (docs/policies/):** 15 company policies covering code of conduct, information security, AI use, travel, remote work, anti-harassment, confidentiality, quality, EHS, procurement, records retention, change management, business continuity, and data privacy.

**Procedures (docs/procedures/):** 20 standard operating procedures across 10 departments, covering key operational processes such as month-end close, onboarding, production startup, design review, NCR handling, incident reporting, and contract review.

**Executive Reviews (docs/executive_reviews/):** 7 monthly reviews (Jan–Jul 2026) and 2 comprehensive quarterly reviews (Q1 and Q2 2026) that narrate the business story embedded in the data, including management analysis of each key pattern.

---

## Intended Use

This dataset is designed for Tablescope product demonstrations. It provides:
- Sufficient data volume (15,000+ CSV rows across 35 files) to demonstrate analytics on realistic datasets
- Rich document corpus (35+ Markdown files) for document Q&A and search demos
- Internally consistent narrative with embedded patterns that reward exploration
- No real PII, no proprietary technical data, no real company information
