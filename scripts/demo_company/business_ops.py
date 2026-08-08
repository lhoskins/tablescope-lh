from __future__ import annotations

import random

from ._common import _PROJECT, _SYNTHETIC
from .dimensions import Dimensions
from .io_utils import Registry


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
    # Procurement
    doc("Procurement", "PROC-001", "supplier-consolidation-analysis",
        "Supplier Consolidation Analysis",
        "Analysis of the supplier base and consolidation opportunities.",
        [("Base", "Long tail of low-spend suppliers identified for consolidation."),
         ("At-Risk", f"{sc.defect_supplier_name} flagged high risk on quality.")])
    doc("Procurement", "PROC-002", "material-inflation-report",
        "Material Inflation Report",
        f"Direct-material cost inflation concentrated on program {sc.material_cost_program}.",
        [("Trend", "Price index rising since 2025-10 on key commodities."),
         ("Impact", f"Unfavorable variance on {sc.material_cost_program}; re-sourcing planned.")])
    doc("Procurement", "PROC-003", "supplier-late-delivery-report",
        "Supplier Late Delivery Report",
        "On-time delivery performance and late-delivery drivers.",
        [("OTD", f"{sc.defect_supplier_name} below on-time-delivery target."),
         ("Actions", "Expedite plans and dual-sourcing for critical parts.")])
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
