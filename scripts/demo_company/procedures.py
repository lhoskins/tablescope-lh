from __future__ import annotations

from ._common import _PROJECT, _SYNTHETIC, C
from .dimensions import Dimensions
from .io_utils import Registry

# ── Procedures ───────────────────────────────────────────────────────────
_PROCEDURES: dict[str, list[tuple[str, str]]] = {
    "Executive": [
        ("annual_operating_plan_procedure", "Annual Operating Plan Procedure"),
        ("monthly_business_review_procedure", "Monthly Business Review Procedure"),
        ("quarterly_business_review_procedure", "Quarterly Business Review Procedure"),
        ("risk_register_review_procedure", "Risk Register Review Procedure"),
        ("delegation_of_authority_procedure", "Delegation of Authority Procedure"),
    ],
    "Finance": [
        ("month_end_close_procedure", "Month-End Close Procedure"),
        ("budget_and_forecast_procedure", "Budget and Forecast Procedure"),
        ("capital_expenditure_approval_procedure", "Capital Expenditure Approval Procedure"),
        ("indirect_rate_review_procedure", "Indirect Rate Review Procedure"),
        ("revenue_recognition_review_procedure", "Revenue Recognition Review Procedure"),
        ("purchase_to_pay_procedure", "Purchase-to-Pay Procedure"),
        ("expense_reimbursement_procedure", "Expense Reimbursement Procedure"),
    ],
    "HR": [
        ("hiring_and_onboarding_procedure", "Hiring and Onboarding Procedure"),
        ("termination_and_offboarding_procedure", "Termination and Offboarding Procedure"),
        ("annual_performance_review_procedure", "Annual Performance Review Procedure"),
        ("training_records_procedure", "Training Records Procedure"),
        ("timekeeping_and_attendance_procedure", "Timekeeping and Attendance Procedure"),
        ("compensation_change_approval_procedure", "Compensation Change Approval Procedure"),
    ],
    "Manufacturing": [
        ("production_planning_procedure", "Production Planning Procedure"),
        ("work_order_release_procedure", "Work Order Release Procedure"),
        ("labor_reporting_procedure", "Labor Reporting Procedure"),
        ("material_issue_and_inventory_adjustment_procedure", "Material Issue and Inventory Adjustment Procedure"),
        ("scrap_and_rework_procedure", "Scrap and Rework Procedure"),
        ("preventive_maintenance_procedure", "Preventive Maintenance Procedure"),
        ("capacity_planning_procedure", "Capacity Planning Procedure"),
    ],
    "Procurement": [
        ("supplier_onboarding_procedure", "Supplier Onboarding Procedure"),
        ("sourcing_and_rfq_procedure", "Sourcing and RFQ Procedure"),
        ("purchase_order_management_procedure", "Purchase Order Management Procedure"),
        ("supplier_performance_review_procedure", "Supplier Performance Review Procedure"),
        ("supplier_risk_management_procedure", "Supplier Risk Management Procedure"),
    ],
    "Engineering": [
        ("engineering_change_request_procedure", "Engineering Change Request Procedure"),
        ("design_review_procedure", "Design Review Procedure"),
        ("bom_revision_procedure", "Bill of Material Revision Procedure"),
        ("non_recurring_engineering_budget_review_procedure", "Non-Recurring Engineering Budget Review Procedure"),
        ("test_and_validation_procedure", "Test and Validation Procedure"),
    ],
    "Sales": [
        ("opportunity_review_procedure", "Opportunity Review Procedure"),
        ("quote_and_proposal_approval_procedure", "Quote and Proposal Approval Procedure"),
        ("contract_handoff_procedure", "Contract Handoff Procedure"),
        ("program_margin_review_procedure", "Program Margin Review Procedure"),
        ("backlog_review_procedure", "Backlog Review Procedure"),
    ],
    "Quality": [
        ("nonconformance_report_procedure", "Nonconformance Report Procedure"),
        ("corrective_action_preventive_action_procedure", "Corrective Action / Preventive Action Procedure"),
        ("supplier_quality_procedure", "Supplier Quality Procedure"),
        ("first_article_inspection_procedure", "First Article Inspection Procedure"),
        ("audit_finding_closure_procedure", "Audit Finding Closure Procedure"),
    ],
    "IT": [
        ("access_request_procedure", "Access Request Procedure"),
        ("incident_response_procedure", "Incident Response Procedure"),
        ("backup_and_recovery_procedure", "Backup and Recovery Procedure"),
        ("change_management_procedure", "Change Management Procedure"),
        ("data_classification_procedure", "Data Classification Procedure"),
        ("vendor_saas_review_procedure", "Vendor / SaaS Review Procedure"),
    ],
    "Legal_Contracts": [
        ("contract_review_procedure", "Contract Review Procedure"),
        ("nda_review_procedure", "NDA Review Procedure"),
        ("export_control_screening_procedure", "Export Control Screening Procedure"),
        ("records_retention_procedure", "Records Retention Procedure"),
        ("claims_disputes_escalation_procedure", "Claims / Disputes Escalation Procedure"),
    ],
    "EHS": [
        ("safety_incident_reporting_procedure", "Safety Incident Reporting Procedure"),
        ("hazard_assessment_procedure", "Hazard Assessment Procedure"),
        ("ppe_procedure", "PPE Procedure"),
        ("emergency_evacuation_procedure", "Emergency Evacuation Procedure"),
        ("lockout_tagout_procedure", "Lockout/Tagout Procedure"),
    ],
}


def _procedures(reg: Registry, dims: Dimensions) -> None:
    name = dims.spec.display_name
    for dept_key, procs in _PROCEDURES.items():
        dept_name = _PROJECT.get(dept_key, dept_key)
        for slug, title in procs:
            body = f"""# {title}

{_SYNTHETIC}
**Company:** {name}
**Owning Function:** {dept_name}
**Document ID:** PRC-{slug.upper().replace('_', '-')}
**Effective Date:** 2026-01-01
**Review Frequency:** Annual

## 1. Purpose
Define the standard steps {name} follows for {title.lower().replace(' procedure', '')}
so the process is consistent, auditable, and repeatable across all sites.

## 2. Scope
Applies to the {dept_name} function and any personnel participating in this
process at {name}.

## 3. Roles and Responsibilities
- **Process Owner ({dept_name})** — maintains the procedure and trains staff.
- **Performers** — execute the steps and record results.
- **Approver** — reviews outputs and authorizes exceptions.

## 4. Procedure Steps
1. **Initiate** — a trigger event starts the process and required inputs are gathered.
2. **Prepare** — validate inputs against master data and applicable policies.
3. **Execute** — perform the work following the controls defined below.
4. **Review** — the approver verifies completeness and accuracy.
5. **Record** — capture the outcome in the system of record and notify stakeholders.
6. **Close** — confirm actions are complete and file supporting records.

## 5. Controls and Checks
- Segregation of duties between preparer and approver.
- Master-data validation (departments, sites, programs, accounts).
- Exception handling with documented approval.

## 6. Records
Retain records per the Records Retention Policy. Store outputs in the relevant
Tablescope project for {dept_name}.

## 7. Related Documents
- Applicable company policies.
- Related datasets in the {dept_name} project.

## Revision History
| Version | Date | Author | Summary |
| --- | --- | --- | --- |
| 1.0 | 2026-01-01 | {dept_name} | Initial synthetic demo release. |
"""
            reg.write_text(
                f"docs/procedures/{dept_key}/{slug}.md", body,
                department=dept_key, project=C.COMPANY_LIBRARY,
                artifact_type="Procedure",
                tags=["procedure", "sop", dept_name.lower().replace(" & ", "-")],
                description=f"{title} ({dept_name}).")


