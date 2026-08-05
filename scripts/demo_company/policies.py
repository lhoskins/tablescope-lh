from __future__ import annotations

from ._common import _SYNTHETIC, C
from .dimensions import Dimensions
from .io_utils import Registry

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
            department=owner, project=C.COMPANY_LIBRARY, artifact_type="Policy",
            tags=["policy", "compliance", owner.lower()],
            description=f"{title} (owner: {owner}).")


