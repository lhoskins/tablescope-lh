"""Unstructured document generators (Markdown).

Produces the company policy set, department standard-operating procedures,
executive monthly/quarterly review packages, and the department "business
operations" narrative reports.  Every narrative references the same planted
scenario entities used by the datasets (scrap work center, overrun projects,
defect supplier, etc.) so document-intelligence and cross-department analytics
demos stay consistent with the numbers.
"""

from __future__ import annotations

import random

from . import config as C
from .dimensions import Dimensions
from .io_utils import Registry

_PROJECT = {d.key: d.project for d in C.DEPARTMENTS}

_SYNTHETIC = (
    "> **Synthetic demo content.** All names, financials, employees, suppliers, "
    "and events in this document are fictional and generated for Tablescope "
    "demonstrations only.\n"
)


def generate_documents(reg: Registry, dims: Dimensions) -> None:
    rng = random.Random(dims.spec.seed ^ 0x1234ABCD)
    _policies(reg, dims)
    _procedures(reg, dims)
    _executive_reviews(reg, dims, rng)
    _business_ops(reg, dims, rng)


# ── Policies ───────────────────────────────────────────────────────────────
_POLICIES = [
    ("code_of_conduct", "Code of Conduct", "Legal", "Board of Directors"),
    ("respectful_workplace_policy", "Anti-Harassment and Respectful Workplace Policy", "HR", "Chief HR Officer"),
    ("equal_employment_opportunity_policy", "Equal Employment Opportunity Policy", "HR", "Chief HR Officer"),
    ("information_security_policy", "Information Security Policy", "IT", "Chief Information Officer"),
    ("acceptable_use_policy", "Acceptable Use Policy", "IT", "Chief Information Officer"),
    ("data_classification_and_handling_policy", "Data Classification and Handling Policy", "IT", "Chief Information Officer"),
    ("records_retention_policy", "Records Retention Policy", "Legal", "General Counsel"),
    ("travel_and_expense_policy", "Travel and Expense Policy", "Finance", "Chief Financial Officer"),
    ("procurement_policy", "Procurement Policy", "Procurement", "Chief Financial Officer"),
    ("delegation_of_authority_policy", "Delegation of Authority Policy", "Executive", "Chief Executive Officer"),
    ("conflict_of_interest_policy", "Conflict of Interest Policy", "Legal", "General Counsel"),
    ("supplier_ethics_policy", "Supplier Ethics Policy", "Procurement", "Chief Procurement Officer"),
    ("quality_policy", "Quality Policy", "Quality", "VP Quality"),
    ("safety_policy", "Safety Policy", "EHS", "VP Operations"),
    ("remote_hybrid_work_policy", "Remote / Hybrid Work Policy", "HR", "Chief HR Officer"),
    ("ai_acceptable_use_policy", "AI Acceptable Use Policy", "IT", "Chief Information Officer"),
]


def _policies(reg: Registry, dims: Dimensions) -> None:
    name = dims.spec.display_name
    for slug, title, owner, approver in _POLICIES:
        body = f"""# {title}

{_SYNTHETIC}
**Company:** {name}
**Owner Department:** {owner}
**Approval Authority:** {approver}
**Effective Date:** 2026-01-01
**Review Frequency:** Annual
**Document ID:** POL-{slug.upper().replace('_', '-')}

## Purpose
This policy establishes {name}'s expectations regarding {title.lower()}. It
protects employees, customers, suppliers, and company assets while supporting
compliant and ethical operations.

## Scope
This policy applies to all {name} employees, contractors, temporary workers,
and third parties acting on the company's behalf across all sites and functions.

## Policy Statement
{name} is committed to the principles described in this document. All personnel
are required to understand and comply with the policy. The {owner} function
maintains the policy and monitors adherence through periodic review, training,
and audit.

## Roles and Responsibilities
- **{approver}** — approves the policy and any material changes.
- **{owner} Department** — owns, maintains, and communicates the policy.
- **People Managers** — ensure their teams understand and follow the policy.
- **All Employees** — comply with the policy and report concerns.

## Exceptions Process
Exceptions must be requested in writing to the {owner} Department and approved
by the {approver}. Approved exceptions are documented, time-bound, and reviewed
at the next policy cycle.

## Related Procedures and Controls
- Corresponding standard operating procedures maintained by the {owner} function.
- Annual compliance training and acknowledgement.
- Internal audit sampling and management review.

## Review and Revision History
| Version | Date | Author | Summary |
| --- | --- | --- | --- |
| 1.0 | 2026-01-01 | {owner} Department | Initial synthetic demo release. |
"""
        reg.write_text(
            f"docs/policies/{slug}.md", body,
            department="Policies", project="Policies", artifact_type="Policy",
            tags=["policy", "compliance", owner.lower()],
            description=f"{title} (owner: {owner}).")


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
                department="Procedures", project="Procedures",
                artifact_type="Procedure",
                tags=["procedure", "sop", dept_name.lower().replace(" & ", "-")],
                description=f"{title} ({dept_name}).")


# ── Executive reviews ──────────────────────────────────────────────────────
def _executive_reviews(reg: Registry, dims: Dimensions, rng: random.Random) -> None:
    name = dims.spec.display_name
    sc = dims.scenarios
    for m in range(1, 8):  # 2026-01 .. 2026-07
        period = f"2026-{m:02d}"
        rev = rng.uniform(3.8, 4.6)
        gm = rng.uniform(24, 30)
        body = f"""# {name} — Executive Monthly Review ({period})

{_SYNTHETIC}
**Period:** {period}
**Prepared for:** Executive Leadership Team
**Prepared by:** Office of the CFO

## Executive Summary
{name} delivered revenue of ${rev:.1f}M in {period} at a gross margin of
{gm:.1f}%. Operating performance was stable, with three watch items requiring
leadership attention: rising material costs on program {sc.material_cost_program},
scrap creep at work center {sc.scrap_work_center} ({sc.scrap_site}), and NRE
overrun on projects {', '.join(sc.overrun_projects)}.

## Financial Performance
- Revenue: ${rev:.1f}M (budget ${rev * rng.uniform(0.97, 1.03):.1f}M)
- Gross Margin: {gm:.1f}%
- Operating Margin: {rng.uniform(8, 13):.1f}%
- Budget vs Actual: unfavorable material variance concentrated on {sc.material_cost_program}.

## Forecast Changes
Full-year forecast revised for material inflation and the {sc.slipping_customer}
opportunity slippage in the sales pipeline.

## Manufacturing
Throughput on plan; scrap rate elevated at {sc.scrap_work_center} ({sc.scrap_site}).
Containment underway (see Manufacturing scrap investigation report).

## Engineering
NRE overrun watchlist flags {', '.join(sc.overrun_projects)}; rebaseline requested.

## Sales
Pipeline healthy overall; slippage from {sc.slipping_customer} opportunities.
Backlog coverage remains above target.

## HR
Attrition elevated among {sc.attrition_job_class} at {sc.attrition_site};
retention actions in progress.

## Quality
Supplier defect trend from {sc.defect_supplier_name} driving nonconformances;
CAPA open.

## IT / Security
Access-request turnaround elevated for new hires (onboarding bottleneck).

## Top Risks and Mitigations
1. Material cost inflation ({sc.material_cost_program}) — resource re-sourcing.
2. Scrap creep ({sc.scrap_work_center}) — process containment + PM.
3. NRE overrun ({', '.join(sc.overrun_projects)}) — rebaseline & scope control.

## Decisions Needed
- Approve re-sourcing plan for {sc.material_cost_program}.
- Approve retention package for {sc.attrition_job_class} at {sc.attrition_site}.

## Action Items
| Action | Owner | Due | Status |
| --- | --- | --- | --- |
| Contain scrap at {sc.scrap_work_center} | VP Operations | {period}-28 | Open |
| Re-source material for {sc.material_cost_program} | Procurement | {period}-28 | Open |
| Rebaseline NRE {', '.join(sc.overrun_projects)} | Engineering | {period}-28 | In Progress |
| {sc.defect_supplier_name} CAPA closure | Quality | {period}-28 | Open |
"""
        reg.write_text(
            f"docs/executive/monthly_reviews/{period}_executive_monthly_review.md",
            body, department="Executive_Reviews", project="Executive Reviews",
            artifact_type="Monthly Review",
            tags=["executive", "monthly-review", period],
            description=f"Executive monthly review {period}.")

    for q in ["Q1", "Q2"]:
        period = f"2026-{q}"
        body = f"""# {name} — Executive Quarterly Review ({period})

{_SYNTHETIC}
**Period:** {period}
**Prepared for:** Board of Directors

## Executive Summary
{name} closed {period} with solid demand and stable margins, offset by three
operational headwinds: material inflation on {sc.material_cost_program}, scrap
creep at {sc.scrap_work_center}, and NRE overrun on {', '.join(sc.overrun_projects)}.

## Financial Results
- Quarterly revenue: ${rng.uniform(11, 15):.1f}M
- Gross margin: {rng.uniform(25, 30):.1f}%
- Book-to-bill: {rng.uniform(0.95, 1.15):.2f}

## Budget vs Actual and Forecast
Unfavorable variance driven by material and NRE; forecast rebaselined.

## Operational Highlights
- Manufacturing: scrap containment at {sc.scrap_site}.
- Quality: {sc.defect_supplier_name} corrective action in progress.
- HR: {sc.attrition_job_class} attrition at {sc.attrition_site}.
- Sales: {sc.slipping_customer} slippage; backlog coverage healthy.

## Top Risks
Material inflation, scrap creep, NRE overrun, critical-role attrition, supplier
defect trend.

## Strategic Initiatives
Operational Excellence and Supplier Consolidation prioritized for the next quarter.

## Decisions and Action Items
| Action | Owner | Due | Status |
| --- | --- | --- | --- |
| Approve re-sourcing for {sc.material_cost_program} | CFO | {period} | Open |
| Fund automation at {sc.scrap_site} | COO | {period} | Open |
| Rebaseline NRE {', '.join(sc.overrun_projects)} | CTO | {period} | In Progress |
"""
        reg.write_text(
            f"docs/executive/quarterly_reviews/{period}_executive_quarterly_review.md",
            body, department="Executive_Reviews", project="Executive Reviews",
            artifact_type="Quarterly Review",
            tags=["executive", "qbr", period.lower()],
            description=f"Executive quarterly review {period}.")


# ── Business operations narrative reports ──────────────────────────────────
def _business_ops(reg: Registry, dims: Dimensions, rng: random.Random) -> None:
    """Department narrative reports (the list attached to issue #15)."""
    sc = dims.scenarios
    name = dims.spec.display_name

    def doc(dept_key: str, code: str, slug: str, title: str, summary: str,
            sections: list[tuple[str, str]]) -> None:
        dept_name = _PROJECT.get(dept_key, dept_key)
        parts = [f"# {title}\n", _SYNTHETIC,
                 f"**Company:** {name}  |  **Department:** {dept_name}  |  "
                 f"**Document ID:** {code}  |  **Date:** 2026-07-01\n",
                 "## Summary\n" + summary + "\n"]
        for h, t in sections:
            parts.append(f"## {h}\n{t}\n")
        body = "\n".join(parts)
        reg.write_text(
            f"docs/business_ops/{dept_key.lower()}/{code}-{slug}.md", body,
            department=dept_key, project=dept_name,
            artifact_type="Business Report",
            tags=["business-ops", dept_name.lower().replace(" & ", "-"), "narrative"],
            description=title)

    ov = ", ".join(sc.overrun_projects)
    # EHS
    doc("EHS", "EHS-001", "q2-2026-safety-performance-report",
        "Q2 2026 Safety Performance Report",
        f"Recordable incidents in Q2 2026 concentrated at {sc.incident_site}. TRIR "
        f"trend up quarter-over-quarter driven by PPE and housekeeping causes.",
        [("Incident Trend", f"{sc.incident_site} accounts for the largest share of "
          "recordables; near-miss reporting improved."),
         ("Root Causes", "PPE compliance and housekeeping dominate root-cause coding."),
         ("Actions", f"Targeted PPE audits and 5S blitz at {sc.incident_site}.")])
    doc("EHS", "EHS-002", "may-2026-incident-investigation-report",
        "May 2026 Incident Investigation Report",
        f"Lost-time incident at {sc.incident_site} investigated; corrective actions assigned.",
        [("Event", "Operator hand injury during changeover."),
         ("Findings", "Guard interlock bypassed; procedure not followed."),
         ("Corrective Actions", "Retraining, guard verification, lockout/tagout audit.")])
    doc("EHS", "EHS-003", "annual-ehs-program-audit-findings",
        "Annual EHS Program Audit Findings",
        "Annual EHS management-system audit completed across all sites.",
        [("Findings", f"Two majors at {sc.incident_site}; minors elsewhere."),
         ("Closure Plan", "Findings tracked to closure with owners and due dates.")])
    # Engineering
    doc("Engineering", "ENG-001", "eprj003-eprj007-overrun-analysis",
        f"{ov} Overrun Analysis",
        f"Projects {ov} are trending over budget on non-recurring engineering, "
        f"tied to program {sc.material_cost_program}.",
        [("Overrun Drivers", "Scope growth and rework on qualification testing."),
         ("EAC vs Budget", f"Estimate-at-complete exceeds budget by ~28% on {ov}."),
         ("Recovery Plan", "Rebaseline, scope freeze, weekly burn review.")])
    doc("Engineering", "ENG-002", "q2-2026-engineering-project-portfolio-review",
        "Q2 2026 Engineering Project Portfolio Review",
        "Portfolio review of active engineering projects and budget health.",
        [("Portfolio Status", f"Majority on track; {ov} flagged as overrun."),
         ("Resource Load", "Design and Test engineering near capacity.")])
    doc("Engineering", "ENG-003", "new-product-introduction-readiness-report",
        "New Product Introduction Readiness Report",
        "NPI readiness assessment for upcoming program launches.",
        [("Readiness", "Gate reviews mostly green; tooling lead-time risk noted."),
         ("Risks", "First-article and PPAP timing dependencies.")])
    # Executive
    doc("Executive", "EXEC-001", "q2-2026-board-meeting-minutes",
        "Q2 2026 Board Meeting Minutes",
        "Board reviewed Q2 performance, risks, and strategic initiatives.",
        [("Decisions", f"Approved re-sourcing for {sc.material_cost_program}."),
         ("Risk Review", "Material inflation, scrap creep, NRE overrun highlighted.")])
    doc("Executive", "EXEC-002", "strategic-initiative-status-report",
        "Strategic Initiative Status Report",
        "Status of enterprise strategic initiatives.",
        [("Initiatives", "Operational Excellence and Supplier Consolidation on track."),
         ("At Risk", "Margin Expansion at risk from material inflation.")])
    doc("Executive", "EXEC-003", "q2-2026-leadership-offsite-notes",
        "Q2 2026 Leadership Offsite Notes",
        "Leadership offsite alignment on priorities for H2 2026.",
        [("Themes", "Cost discipline, supplier quality, talent retention."),
         ("Commitments", f"Retention plan for {sc.attrition_job_class}.")])
    # Finance
    doc("Finance", "FIN-001", "q2-2026-budget-variance-report",
        "Q2 2026 Budget Variance Report",
        f"Unfavorable material variance concentrated on program {sc.material_cost_program}.",
        [("Variance Drivers", "Direct material inflation; NRE overrun."),
         ("Corrective Actions", "Re-sourcing and rebaseline underway.")])
    doc("Finance", "FIN-002", "june-2026-cash-flow-analysis",
        "June 2026 Cash Flow Analysis",
        "Cash position healthy; capex phasing under review.",
        [("Operating Cash", "Within forecast."),
         ("Capex", "Automation capex at scrap site under evaluation.")])
    doc("Finance", "FIN-003", "fy2026-forecast-revision-memo",
        "FY2026 Forecast Revision Memo",
        "Full-year forecast revised for material inflation and sales slippage.",
        [("Revenue", f"Trimmed for {sc.slipping_customer} slippage."),
         ("Margin", "Pressured by material and NRE.")])
    # HR
    doc("HR", "HR-001", "q2-2026-workforce-report",
        "Q2 2026 Workforce Report",
        f"Attrition elevated among {sc.attrition_job_class} at {sc.attrition_site}.",
        [("Headcount", "Broadly on plan."),
         ("Attrition", f"Spike in {sc.attrition_job_class} at {sc.attrition_site}."),
         ("Actions", "Retention package and accelerated backfill.")])
    doc("HR", "HR-002", "june-2026-exit-interview-summary",
        "June 2026 Exit Interview Summary",
        "Exit interview themes for departing employees.",
        [("Themes", "Compensation and shift patterns cited."),
         ("Hotspot", f"{sc.attrition_site} {sc.attrition_job_class}.")])
    doc("HR", "HR-003", "2026-performance-review-calibration-notes",
        "2026 Performance Review Calibration Notes",
        "Calibration notes for the 2026 review cycle.",
        [("Distribution", "Ratings calibrated across departments."),
         ("Actions", "Development plans for key roles.")])
    doc("HR", "HR-004", "recruiting-pipeline-report",
        "Recruiting Pipeline Report",
        "Open requisitions and time-to-fill trends.",
        [("Pipeline", "Critical roles taking longer to fill."),
         ("Bottlenecks", "Onboarding access delays extend effective time-to-productivity.")])
    # IT
    doc("IT", "IT-001", "erp-upgrade-project-status",
        "ERP Upgrade Project Status",
        "ERP upgrade tracking to plan with change-management controls.",
        [("Status", "On schedule; UAT in progress."),
         ("Risks", "Integration testing dependencies.")])
    doc("IT", "IT-002", "q2-2026-helpdesk-metrics-report",
        "Q2 2026 Helpdesk Metrics Report",
        "Incident volumes and resolution times for Q2.",
        [("Volumes", "Access-category incidents elevated for new hires."),
         ("Actions", "Automate onboarding access provisioning.")])
    doc("IT", "IT-003", "cybersecurity-incident-report",
        "Cybersecurity Incident Report",
        "Summary of security findings and remediation.",
        [("Findings", "Phishing and patch findings tracked."),
         ("Remediation", "Prioritized by severity.")])
    # Legal
    doc("Legal_Contracts", "LEG-001", "q2-2026-contracts-status-report",
        "Q2 2026 Contracts Status Report",
        "Contract portfolio status, renewals, and obligations.",
        [("Renewals", "Several contracts approaching expiry."),
         ("Obligations", "Overdue obligations flagged for follow-up.")])
    doc("Legal_Contracts", "LEG-002", "export-compliance-review",
        "Export Compliance Review",
        "Export control screening review across programs.",
        [("Screening", "Screening current; a few items pending classification."),
         ("Actions", "Complete classifications; update records.")])
    doc("Legal_Contracts", "LEG-003", "ip-portfolio-summary",
        "IP Portfolio Summary",
        "Summary of intellectual property portfolio.",
        [("Portfolio", "Patents and trade secrets catalogued."),
         ("Risks", "Ensure invention disclosures kept current.")])
    # Manufacturing
    doc("Manufacturing", "MFG-001", "line2-scrap-investigation-report",
        "Line 2 Scrap Investigation Report",
        f"Scrap creep at work center {sc.scrap_work_center} ({sc.scrap_site}) "
        "investigated; trend rising through H1 2026.",
        [("Trend", f"Weekly scrap % at {sc.scrap_work_center} climbing since Jan 2026."),
         ("Root Cause", f"Correlates with defect trend from {sc.defect_supplier_name}."),
         ("Containment", "SPC tightening, incoming inspection, PM refresh.")])
    doc("Manufacturing", "MFG-002", "june-2026-production-review",
        "June 2026 Production Review",
        "Monthly production performance review.",
        [("Output", "On plan overall."),
         ("Watch Items", f"Scrap at {sc.scrap_work_center}.")])
    doc("Manufacturing", "MFG-003", "q2-2026-maintenance-summary",
        "Q2 2026 Maintenance Summary",
        "Preventive and corrective maintenance summary.",
        [("PM Compliance", "Above target at most sites."),
         ("Actions", f"Add PM frequency at {sc.scrap_work_center}.")])
    doc("Manufacturing", "MFG-004", "capacity-planning-memo",
        "Capacity Planning Memo",
        "Capacity outlook against the production plan.",
        [("Utilization", "Approaching capacity on key lines."),
         ("Investment", f"Automation case for {sc.scrap_site}.")])
    # Quality
    doc("Quality", "QA-001", "q2-2026-quality-management-review",
        "Q2 2026 Quality Management Review",
        "Quality management system review for Q2.",
        [("KPIs", "PPM and first-pass yield reviewed."),
         ("Hotspots", f"{sc.defect_supplier_name} defect trend; scrap at {sc.scrap_site}.")])
    doc("Quality", "QA-002", "apex-metalworks-corrective-action-report",
        f"{sc.defect_supplier_name} Corrective Action Report",
        f"Corrective action for elevated defect PPM from {sc.defect_supplier_name} "
        f"(supplier {sc.defect_supplier_id}).",
        [("Problem", f"Defect PPM from {sc.defect_supplier_name} well above threshold."),
         ("Impact", f"Drives nonconformances and scrap at {sc.scrap_work_center}."),
         ("CAPA", "8D in progress; containment and source inspection in place.")])
    doc("Quality", "QA-003", "iso9001-internal-audit-findings",
        "ISO 9001 Internal Audit Findings",
        "Internal ISO 9001 audit findings and closure plan.",
        [("Findings", "Minor nonconformities in documented information."),
         ("Closure", "Owners and due dates assigned.")])
    # Sales
    doc("Sales", "SAL-001", "q2-2026-sales-performance-review",
        "Q2 2026 Sales Performance Review",
        "Sales performance, bookings, and backlog review.",
        [("Bookings", "Book-to-bill near 1.0."),
         ("Slippage", f"{sc.slipping_customer} opportunities slipped.")])
    doc("Sales", "SAL-002", "customer-at-risk-report",
        "Customer At-Risk Report",
        f"{sc.slipping_customer} flagged at risk due to delivery and pricing.",
        [("At-Risk", f"{sc.slipping_customer} revenue trending down in H1 2026."),
         ("Actions", "Executive sponsor engagement; delivery recovery.")])
    doc("Sales", "SAL-003", "q3-2026-sales-forecast-package",
        "Q3 2026 Sales Forecast Package",
        "Forward sales forecast and pipeline coverage.",
        [("Forecast", "Coverage healthy excluding slipped deals."),
         ("Risks", f"{sc.slipping_customer} timing.")])
