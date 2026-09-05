"""Evidence-based severity gating shared by the insight pipelines.

Reference Library documents (DFARS, TCFD, AS9100D, …) are *authoritative
guidance*, not project data. A risk, breach, anomaly, or warning requires
project-specific evidence — a project document, datasource/table, saved query,
dashboard, validated KPI value, or validated relationship. A finding grounded
*only* in reference documents may not exceed an informational/watch severity.

Used by AI Home (`home_intelligence`) and the Knowledge Graph
(`knowledge_graph_ai`) so the rule is applied consistently.
"""

from __future__ import annotations

# Severities that assert an actual risk/problem and therefore demand
# project-specific evidence.
RISK_SEVERITIES = frozenset({"critical", "urgent", "warning", "risk", "anomaly"})

# Reference-only findings are capped here.
GUIDANCE_SEVERITY = "watch"

# Graph node types that are authoritative guidance, never project evidence.
REFERENCE_NODE_TYPES = frozenset({"reference_document"})


def gate_severity(
    severity: str,
    *,
    has_project_evidence: bool,
    has_authoritative_non_industry_evidence: bool = False,
) -> str:
    """Cap a risk-grade severity to ``watch`` when there is no project
    evidence and no authoritative company/project-tier guidance backing it.

    KG-36: the review's own stated source-authority order ranks "approved
    company policy" and "project documentation" above generic "industry
    references" -- a finding resting only on a company-approved reference
    document (or a project-tier one) is not the same as one resting only
    on a generic industry standard, and must not be capped the same way.
    ``has_authoritative_non_industry_evidence`` lets a caller distinguish
    the two without this module needing to know about reference-document
    tiers itself; callers that can't make that distinction simply omit it
    (defaulting to the original, industry-and-company-both-capped
    behavior).

    Returns ``severity`` unchanged when there is project-specific evidence,
    authoritative non-industry guidance, or the severity is already
    informational/opportunity-grade.
    """
    sev = (severity or "").lower()
    if (
        not has_project_evidence
        and not has_authoritative_non_industry_evidence
        and sev in RISK_SEVERITIES
    ):
        return GUIDANCE_SEVERITY
    return severity
