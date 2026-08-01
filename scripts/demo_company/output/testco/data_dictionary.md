# TestCo Demo Company — Data Dictionary

Auto-generated from the produced CSV files.

## EHS

### `data/EHS/ehs_audit_findings.csv`
- **Type:** Operational Data
- **Rows:** 24
- **Description:** EHS audit findings.
- **Columns:** FindingID, Date, SiteID, Area, Severity, Status
- **Tags:** ehs, audit

### `data/EHS/ehs_emergency_drill_log.csv`
- **Type:** Operational Data
- **Rows:** 15
- **Description:** Emergency drill log.
- **Columns:** DrillID, SiteID, Type, Date, EvacTimeMin, Result
- **Tags:** ehs, drill

### `data/EHS/ehs_facilities_work_orders.csv`
- **Type:** Operational Data
- **Rows:** 45
- **Description:** Facilities work orders.
- **Columns:** WorkOrderID, SiteID, Category, Priority, Status, OpenedDate
- **Tags:** ehs, facilities

### `data/EHS/ehs_hazard_assessments.csv`
- **Type:** Operational Data
- **Rows:** 20
- **Description:** Hazard assessments.
- **Columns:** AssessmentID, SiteID, Process, RiskScore, Date
- **Tags:** ehs, hazard

### `data/EHS/ehs_incidents.csv`
- **Type:** Operational Data
- **Rows:** 60
- **Description:** Safety incidents (planted facility concentration).
- **Columns:** IncidentID, Date, SiteID, Type, BodyPart, DaysLost, RootCause
- **Tags:** ehs, incidents, ai-scenario

### `data/EHS/ehs_ppe_inspections.csv`
- **Type:** Operational Data
- **Rows:** 30
- **Description:** PPE inspections.
- **Columns:** InspectionID, SiteID, PPEType, PassPct, Date
- **Tags:** ehs, ppe

### `data/EHS/ehs_training_records.csv`
- **Type:** Operational Data
- **Rows:** 150
- **Description:** EHS training records.
- **Columns:** EmployeeID, Course, CompletedDate, Status
- **Tags:** ehs, training

## Engineering

### `data/Engineering/eng_labor_actuals_monthly.csv`
- **Type:** Operational Data
- **Rows:** 288
- **Date range:** 2024-08-01..2026-07-01
- **Description:** Monthly engineering labor by project.
- **Columns:** Month, ProjectID, ProgramID, LaborHours, LaborRateUSD, LaborCostUSD
- **Tags:** engineering, labor, monthly

### `data/Engineering/eng_nre_overrun_watchlist.csv`
- **Type:** Operational Data
- **Rows:** 12
- **Description:** NRE overrun watchlist (planted overrun scenario).
- **Columns:** ProjectID, ProjectName, ProgramID, BudgetUSD, EAC_USD, VarianceUSD, VariancePct, Status
- **Tags:** engineering, nre, overrun, ai-scenario

### `data/Engineering/eng_project_budget_monthly.csv`
- **Type:** Budget
- **Rows:** 288
- **Description:** Monthly engineering project budget.
- **Columns:** Month, ProjectID, ProgramID, Scenario, BudgetUSD
- **Tags:** engineering, budget, monthly

### `data/Engineering/eng_project_forecast_monthly.csv`
- **Type:** Forecast
- **Rows:** 288
- **Description:** Monthly engineering project forecast.
- **Columns:** Month, ProjectID, ProgramID, Scenario, ForecastUSD
- **Tags:** engineering, forecast, monthly

## Executive

### `data/Executive/action_items.csv`
- **Type:** Operational Data
- **Rows:** 50
- **Description:** Action items (planted overdue-Operational trend).
- **Columns:** ActionID, Description, Category, OwnerID, DueDate, Status
- **Tags:** executive, action-items, ai-scenario

### `data/Executive/decision_log.csv`
- **Type:** Operational Data
- **Rows:** 24
- **Description:** Decision log.
- **Columns:** DecisionID, Date, Topic, Decision, OwnerDept
- **Tags:** executive, decisions

### `data/Executive/enterprise_risk_register.csv`
- **Type:** Operational Data
- **Rows:** 10
- **Description:** Enterprise risk register (ties to all planted scenarios).
- **Columns:** RiskID, Title, OwnerDept, Severity, Likelihood, Category, ReferenceID, Status, ReviewDate
- **Tags:** executive, risk, ai-scenario

### `data/Executive/executive_kpi_scorecard_monthly.csv`
- **Type:** Operational Data
- **Rows:** 24
- **Date range:** 2024-08-01..2026-07-01
- **Description:** Executive KPI scorecard.
- **Columns:** Month, RevenueUSD, GrossMarginPct, OperatingMarginPct, OnTimeDeliveryPct, ScrapPct, AttritionPct
- **Tags:** executive, kpi, monthly

### `data/Executive/monthly_review_metrics.csv`
- **Type:** Operational Data
- **Rows:** 7
- **Description:** Monthly review metrics.
- **Columns:** Month, RevenueUSD, BudgetUSD, OpenActions, TopRisk
- **Tags:** executive, monthly-review

### `data/Executive/quarterly_review_metrics.csv`
- **Type:** Operational Data
- **Rows:** 2
- **Description:** Quarterly review metrics.
- **Columns:** Quarter, RevenueUSD, GrossMarginPct, BookToBill, TopRisk
- **Tags:** executive, quarterly-review

### `data/Executive/strategy_initiatives.csv`
- **Type:** Operational Data
- **Rows:** 6
- **Description:** Strategic initiatives.
- **Columns:** InitiativeID, Name, SponsorDept, Status, PctComplete, TargetDate
- **Tags:** executive, strategy

## Finance

### `data/Finance/fin_budget_monthly.csv`
- **Type:** Budget
- **Rows:** 312
- **Description:** FY2026+ budget by account and month.
- **Columns:** Month, Scenario, Version, AccountNumber, AccountName, BudgetUSD
- **Tags:** finance, budget, fy2026

### `data/Finance/fin_budget_vs_actual_monthly.csv`
- **Type:** Operational Data
- **Rows:** 91
- **Description:** Budget vs actual with planted material-cost variance.
- **Columns:** Month, AccountNumber, AccountName, BudgetUSD, ActualUSD, VarianceUSD, VariancePct
- **Tags:** finance, budget-vs-actual, monthly, ai-scenario

### `data/Finance/fin_capex_budget.csv`
- **Type:** Budget
- **Rows:** 16
- **Description:** Capital expenditure budget by site.
- **Columns:** ProjectID, SiteID, Category, BudgetUSD, ApprovedUSD, Status, FiscalYear
- **Tags:** finance, capex, budget

### `data/Finance/fin_cash_flow_forecast.csv`
- **Type:** Forecast
- **Rows:** 24
- **Description:** Monthly cash-flow forecast.
- **Columns:** Month, Scenario, CashInflowUSD, CashOutflowUSD, NetCashUSD, EndingCashUSD
- **Tags:** finance, cash-flow, forecast

### `data/Finance/fin_forecast_monthly.csv`
- **Type:** Forecast
- **Rows:** 312
- **Description:** Rolling forecast by account and month.
- **Columns:** Month, Scenario, Version, AccountNumber, AccountName, ForecastUSD
- **Tags:** finance, forecast, rolling

### `data/Finance/fin_gl_chart_of_accounts.csv`
- **Type:** Master Data
- **Rows:** 14
- **Description:** GL chart of accounts.
- **Columns:** AccountNumber, AccountName, AccountType, Category
- **Tags:** finance, gl, chart-of-accounts, master

### `data/Finance/fin_gl_monthly.csv`
- **Type:** Operational Data
- **Rows:** 312
- **Date range:** 2024-08-01..2026-07-01
- **Description:** Monthly general ledger derived from operating series.
- **Columns:** Month, AccountNumber, AccountName, AmountUSD
- **Tags:** finance, gl, monthly

### `data/Finance/fin_headcount_budget.csv`
- **Type:** Budget
- **Rows:** 11
- **Description:** Headcount budget by department.
- **Columns:** DeptID, DeptName, CurrentHeadcount, BudgetHeadcount, PlannedHiresFY26, FiscalYear
- **Tags:** finance, headcount, budget

### `data/Finance/fin_indirect_rates_monthly.csv`
- **Type:** Operational Data
- **Rows:** 24
- **Date range:** 2024-08-01..2026-07-01
- **Description:** Monthly fringe / overhead / G&A rates.
- **Columns:** Month, FringePct, OverheadPct, GA_Pct
- **Tags:** finance, indirect-rates, monthly

## HR

### `data/HR/hr_attrition_risk.csv`
- **Type:** Operational Data
- **Rows:** 820
- **Description:** Attrition risk with planted spike scenario.
- **Columns:** EmployeeID, DeptID, SiteID, JobClass, AttritionRiskScore, RiskTier
- **Tags:** hr, attrition, ai-scenario

### `data/HR/hr_compensation_changes.csv`
- **Type:** Operational Data
- **Rows:** 150
- **Description:** Compensation change log.
- **Columns:** EmployeeID, EffectiveDate, ChangeType, OldSalaryUSD, NewSalaryUSD
- **Tags:** hr, compensation

### `data/HR/hr_departments.csv`
- **Type:** Master Data
- **Rows:** 11
- **Description:** Department master.
- **Columns:** DeptID, DeptName, Function, CostCenter
- **Tags:** hr, departments, master

### `data/HR/hr_employees.csv`
- **Type:** Master Data
- **Rows:** 820
- **Description:** Employee master with hires, terminations and status.
- **Columns:** EmployeeID, FullName, DeptID, SiteID, JobClass, HireDate, Status, TerminationDate, ManagerID, AnnualSalaryUSD
- **Tags:** hr, employees, master

### `data/HR/hr_headcount_plan.csv`
- **Type:** Operational Data
- **Rows:** 264
- **Description:** Monthly headcount vs plan.
- **Columns:** Month, DeptID, DeptName, Headcount, Plan
- **Tags:** hr, headcount, monthly

### `data/HR/hr_onboarding_status.csv`
- **Type:** Operational Data
- **Rows:** 0
- **Description:** Onboarding status (IT access delay ties to IT scenario).
- **Columns:** EmployeeID, FullName, DeptID, StartDate, ITAccessGrantedDays, TrainingComplete, Status
- **Tags:** hr, onboarding, ai-scenario

### `data/HR/hr_open_requisitions.csv`
- **Type:** Operational Data
- **Rows:** 41
- **Description:** Open requisitions and days-open.
- **Columns:** RequisitionID, DeptID, JobClass, SiteID, OpenedDate, DaysOpen, Status
- **Tags:** hr, requisitions, recruiting

### `data/HR/hr_performance_reviews.csv`
- **Type:** Operational Data
- **Rows:** 250
- **Description:** Annual performance reviews.
- **Columns:** EmployeeID, ReviewCycle, Rating, PromotionReady, ReviewerID
- **Tags:** hr, performance

### `data/HR/hr_sites.csv`
- **Type:** Master Data
- **Rows:** 4
- **Description:** Site master.
- **Columns:** SiteID, SiteName, City, State, Country, Region, SquareFeet, OpenedDate
- **Tags:** hr, sites, master

### `data/HR/hr_timekeeping_exceptions.csv`
- **Type:** Operational Data
- **Rows:** 120
- **Description:** Timekeeping exceptions.
- **Columns:** EmployeeID, SiteID, Week, ExceptionType, Hours
- **Tags:** hr, timekeeping

### `data/HR/hr_training_records.csv`
- **Type:** Operational Data
- **Rows:** 600
- **Description:** Training completion records.
- **Columns:** EmployeeID, Course, CompletedDate, Status
- **Tags:** hr, training

## IT

### `data/IT/it_access_requests.csv`
- **Type:** Operational Data
- **Rows:** 0
- **Description:** Access requests (planted onboarding-delay bottleneck).
- **Columns:** RequestID, EmployeeID, RequestedDate, System, DaysToGrant, Status
- **Tags:** it, access, ai-scenario

### `data/IT/it_assets.csv`
- **Type:** Operational Data
- **Rows:** 820
- **Description:** IT asset inventory.
- **Columns:** AssetID, Type, SiteID, AssignedTo, PurchaseDate, Status
- **Tags:** it, assets

### `data/IT/it_backup_jobs.csv`
- **Type:** Operational Data
- **Rows:** 40
- **Description:** Backup job results.
- **Columns:** JobID, System, Date, Result, DurationMin
- **Tags:** it, backup

### `data/IT/it_change_requests.csv`
- **Type:** Operational Data
- **Rows:** 50
- **Description:** IT change requests.
- **Columns:** ChangeID, SubmittedDate, System, RiskLevel, Status
- **Tags:** it, change-management

### `data/IT/it_incidents.csv`
- **Type:** Operational Data
- **Rows:** 90
- **Description:** IT incident log.
- **Columns:** IncidentID, OpenedDate, Category, Priority, SiteID, ResolutionHours, Status
- **Tags:** it, incidents

### `data/IT/it_saas_vendor_register.csv`
- **Type:** Operational Data
- **Rows:** 25
- **Description:** SaaS vendor register.
- **Columns:** VendorID, VendorName, Category, AnnualCostUSD, RenewalMonth, DataClassification
- **Tags:** it, saas

### `data/IT/it_security_findings.csv`
- **Type:** Operational Data
- **Rows:** 30
- **Description:** Security findings.
- **Columns:** FindingID, Date, Severity, Category, Status
- **Tags:** it, security

### `data/IT/it_system_availability_monthly.csv`
- **Type:** Operational Data
- **Rows:** 120
- **Date range:** 2024-08-01..2026-07-01
- **Description:** System availability.
- **Columns:** Month, System, UptimePct, IncidentCount
- **Tags:** it, availability, monthly

## Legal_Contracts

### `data/Legal_Contracts/contracts_claims_disputes_log.csv`
- **Type:** Operational Data
- **Rows:** 18
- **Description:** Claims and disputes log.
- **Columns:** ClaimID, CounterParty, Type, AmountUSD, Status, OpenedDate
- **Tags:** legal, claims

### `data/Legal_Contracts/contracts_master.csv`
- **Type:** Master Data
- **Rows:** 65
- **Description:** Contracts master.
- **Columns:** ContractID, CounterParty, ContractType, Category, ValueUSD, StartDate, EndDate, Status
- **Tags:** legal, contracts, master

### `data/Legal_Contracts/contracts_nda_register.csv`
- **Type:** Operational Data
- **Rows:** 35
- **Description:** NDA register.
- **Columns:** NDAID, CounterParty, SignedDate, ExpiryDate, Status
- **Tags:** legal, nda

### `data/Legal_Contracts/contracts_obligations.csv`
- **Type:** Operational Data
- **Rows:** 123
- **Description:** Contract obligations.
- **Columns:** ContractID, CounterParty, ObligationType, DueDate, Status
- **Tags:** legal, obligations

### `data/Legal_Contracts/contracts_records_retention_index.csv`
- **Type:** Operational Data
- **Rows:** 30
- **Description:** Records retention index.
- **Columns:** RecordID, RecordType, RetentionYears, Location, DisposalDate
- **Tags:** legal, retention

### `data/Legal_Contracts/contracts_review_log.csv`
- **Type:** Operational Data
- **Rows:** 40
- **Description:** Contract review log.
- **Columns:** ReviewID, ContractID, Reviewer, ReviewDate, Outcome
- **Tags:** legal, review

### `data/Legal_Contracts/contracts_risk_register.csv`
- **Type:** Operational Data
- **Rows:** 30
- **Description:** Contract risk register.
- **Columns:** ContractID, RiskType, Severity, Likelihood, Mitigation
- **Tags:** legal, risk

## Manufacturing

### `data/Manufacturing/mfg_capacity_forecast_monthly.csv`
- **Type:** Forecast
- **Rows:** 288
- **Description:** Capacity vs plan utilization forecast.
- **Columns:** Month, WorkCenterID, SiteID, CapacityUnits, PlannedUnits, UtilizationPct
- **Tags:** manufacturing, capacity, forecast

### `data/Manufacturing/mfg_inventory_forecast.csv`
- **Type:** Forecast
- **Rows:** 60
- **Description:** Inventory position and projected shortfalls.
- **Columns:** PartID, ProgramID, OnHandUnits, SafetyStock, ForecastDemandUnits, ProjectedShortfall
- **Tags:** manufacturing, inventory, forecast

### `data/Manufacturing/mfg_labor_actuals_weekly.csv`
- **Type:** Operational Data
- **Rows:** 1,260
- **Date range:** 2024-07-08..2026-07-06
- **Description:** Weekly direct labor and output by work center.
- **Columns:** WeekStart, WorkCenterID, SiteID, DirectHours, OvertimeHours, UnitsProduced
- **Tags:** manufacturing, labor, weekly

### `data/Manufacturing/mfg_labor_rates.csv`
- **Type:** Master Data
- **Rows:** 12
- **Description:** Labor rates by work center.
- **Columns:** WorkCenterID, SiteID, LaborRateUSDPerHour, OvertimeMultiplier, EffectiveDate
- **Tags:** manufacturing, labor-rates, master

### `data/Manufacturing/mfg_material_actuals_monthly.csv`
- **Type:** Operational Data
- **Rows:** 216
- **Date range:** 2024-08-01..2026-07-01
- **Description:** Monthly material spend with planted cost-inflation scenario.
- **Columns:** Month, ProgramID, Commodity, Quantity, UnitCostUSD, MaterialCostUSD
- **Tags:** manufacturing, material, monthly, ai-scenario

### `data/Manufacturing/mfg_parts.csv`
- **Type:** Master Data
- **Rows:** 260
- **Description:** Part master with standard costs.
- **Columns:** PartID, PartName, Commodity, ProgramID, PrimarySupplierID, StandardCostUSD, UOM
- **Tags:** manufacturing, parts, master

### `data/Manufacturing/mfg_production_plan_monthly.csv`
- **Type:** Forecast
- **Rows:** 288
- **Description:** Monthly production plan by work center.
- **Columns:** Month, WorkCenterID, SiteID, PlannedUnits, Scenario
- **Tags:** manufacturing, production-plan, forecast

### `data/Manufacturing/mfg_scrap_weekly.csv`
- **Type:** Operational Data
- **Rows:** 1,260
- **Date range:** 2024-07-08..2026-07-06
- **Description:** Weekly scrap with planted scrap-creep scenario.
- **Columns:** WeekStart, WorkCenterID, SiteID, UnitsProduced, UnitsScrapped, ScrapPct, ScrapCostUSD
- **Tags:** manufacturing, scrap, weekly, ai-scenario

### `data/Manufacturing/mfg_work_centers.csv`
- **Type:** Master Data
- **Rows:** 12
- **Description:** Work-center master.
- **Columns:** WorkCenterID, WorkCenterName, SiteID, Process, Shifts
- **Tags:** manufacturing, work-centers, master

## Procurement

### `data/Procurement/procurement_late_delivery_log.csv`
- **Type:** Operational Data
- **Rows:** 60
- **Description:** Late delivery log.
- **Columns:** SupplierID, SupplierName, POID, PromiseDate, DaysLate, Impact
- **Tags:** procurement, late-delivery

### `data/Procurement/procurement_material_price_history.csv`
- **Type:** Operational Data
- **Rows:** 240
- **Description:** Commodity price index (planted inflation).
- **Columns:** Month, Commodity, PriceIndex
- **Tags:** procurement, price-index, monthly, ai-scenario

### `data/Procurement/procurement_purchase_orders.csv`
- **Type:** Operational Data
- **Rows:** 260
- **Description:** Purchase orders.
- **Columns:** POID, SupplierID, PartID, OrderDate, Qty, UnitCostUSD, ExtendedUSD, PromiseDate, Status
- **Tags:** procurement, purchase-orders

### `data/Procurement/procurement_source_to_pay_exceptions.csv`
- **Type:** Operational Data
- **Rows:** 40
- **Description:** Source-to-pay exceptions.
- **Columns:** ExceptionID, Type, SupplierID, AmountUSD, Status
- **Tags:** procurement, source-to-pay

### `data/Procurement/procurement_supplier_contracts.csv`
- **Type:** Operational Data
- **Rows:** 32
- **Description:** Supplier contracts.
- **Columns:** ContractID, CounterParty, Category, ValueUSD, StartDate, EndDate, Status
- **Tags:** procurement, contracts

### `data/Procurement/procurement_supplier_master.csv`
- **Type:** Master Data
- **Rows:** 70
- **Description:** Supplier master.
- **Columns:** SupplierID, SupplierName, Commodity, Country, OnboardedDate, RiskTier
- **Tags:** procurement, supplier, master

### `data/Procurement/procurement_supplier_risk_register.csv`
- **Type:** Operational Data
- **Rows:** 70
- **Description:** Supplier risk register.
- **Columns:** SupplierID, SupplierName, RiskTier, FinancialRisk, GeographicRisk, SingleSource, MitigationStatus
- **Tags:** procurement, risk

## Quality

### `data/Quality/quality_audit_findings.csv`
- **Type:** Operational Data
- **Rows:** 18
- **Description:** ISO 9001 audit findings.
- **Columns:** FindingID, AuditDate, SiteID, Clause, Severity, Status
- **Tags:** quality, audit

### `data/Quality/quality_capa_log.csv`
- **Type:** Operational Data
- **Rows:** 24
- **Description:** Corrective/preventive action log.
- **Columns:** CAPAID, OpenedDate, SupplierID, Category, Severity, Status, DaysOpen
- **Tags:** quality, capa

### `data/Quality/quality_customer_complaints.csv`
- **Type:** Operational Data
- **Rows:** 22
- **Description:** Customer complaints log.
- **Columns:** ComplaintID, Date, Customer, ProgramID, Category, Severity, Status
- **Tags:** quality, complaints

### `data/Quality/quality_defect_trends_monthly.csv`
- **Type:** Operational Data
- **Rows:** 96
- **Date range:** 2024-08-01..2026-07-01
- **Description:** Monthly defect trends (tie to scrap site).
- **Columns:** Month, SiteID, DefectPPM, FirstPassYieldPct
- **Tags:** quality, defect-trend, monthly, ai-scenario

### `data/Quality/quality_first_article_inspections.csv`
- **Type:** Operational Data
- **Rows:** 30
- **Description:** First article inspection results.
- **Columns:** FAIID, PartID, SupplierID, Date, Result
- **Tags:** quality, fai

### `data/Quality/quality_nonconformance_log.csv`
- **Type:** Operational Data
- **Rows:** 105
- **Description:** Nonconformance log linked to suppliers/work centers.
- **Columns:** NCRID, Date, SiteID, WorkCenterID, PartID, SupplierID, DefectType, Qty, Disposition
- **Tags:** quality, ncr, ai-scenario

### `data/Quality/quality_supplier_scorecards.csv`
- **Type:** Operational Data
- **Rows:** 70
- **Description:** Supplier scorecards (planted supplier defect trend).
- **Columns:** SupplierID, SupplierName, OnTimeDeliveryPct, DefectPPM, QualityScore, Rating
- **Tags:** quality, supplier-scorecard, ai-scenario

## Sales

### `data/Sales/sales_backlog_monthly.csv`
- **Type:** Operational Data
- **Rows:** 24
- **Description:** Order backlog and coverage months.
- **Columns:** Month, BacklogUSD, CoverageMonths
- **Tags:** sales, backlog, monthly

### `data/Sales/sales_bookings_forecast.csv`
- **Type:** Forecast
- **Rows:** 24
- **Description:** Bookings forecast and book-to-bill ratio.
- **Columns:** Month, Scenario, BookingsUSD, BookToBill
- **Tags:** sales, bookings, forecast

### `data/Sales/sales_pipeline_forecast.csv`
- **Type:** Forecast
- **Rows:** 36
- **Description:** Open pipeline with planted forecast-slippage scenario.
- **Columns:** OpportunityID, ProgramID, Customer, Stage, ExpectedCloseMonth, AmountUSD, ProbabilityPct, Slipped
- **Tags:** sales, pipeline, forecast, ai-scenario

### `data/Sales/sales_programs.csv`
- **Type:** Master Data
- **Rows:** 9
- **Description:** Program master: customer programs and target margins.
- **Columns:** ProgramID, ProgramName, Customer, ProgramType, StartDate, Status, TargetMarginPct
- **Tags:** sales, programs, master

### `data/Sales/sales_revenue_monthly.csv`
- **Type:** Operational Data
- **Rows:** 216
- **Date range:** 2024-08-01..2026-07-01
- **Description:** Recognized revenue by program and month.
- **Columns:** Month, ProgramID, Customer, RevenueUSD, Units
- **Tags:** sales, revenue, monthly
