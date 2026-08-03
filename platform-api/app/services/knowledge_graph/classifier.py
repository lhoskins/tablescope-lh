"""Knowledge graph relationship classification."""

from __future__ import annotations

import logging
from typing import Any

from .constants import _as_dict

logger = logging.getLogger(__name__)

def _edge_confidence(edge: dict[str, Any]) -> float:
    try:
        return float(edge.get("confidence") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _evidence_summary(edge: dict[str, Any]) -> str:
    ev = edge.get("evidence")
    d = _as_dict(ev)
    if d:
        return str(d.get("evidence_summary") or d.get("reason") or d.get("text") or "")
    return str(ev or "")


# ── Relationship evidence classification (connector-style policy) ─────
#
# Every edge is classified by evidence strength so the UI can draw it with the
# right connector: a solid line for explicit project evidence, a dashed line for
# high-confidence inference, a faint/optional line for best-practice
# recommendations, and nothing for low-confidence noise.  See
# ``prompts/knowledge_graph_insight_best_practices.md``.

# Relationships that only ever express a *recommendation* (a missing
# best-practice item), never proven project evidence.
_RECOMMENDED_REL_TYPES = {
    "recommended_kpi", "suggested_kpi", "recommends",
    "missing_required_evidence", "missing_required_policy",
    "missing_required_procedure", "missing_required_kpi",
    "missing_required_datasource",
}
# Relationships that are inferred rather than explicitly stated.
_INFERRED_REL_TYPES = {"linked_by_inferred_join", "mentions", "applies_to"}
# Minimum confidence for an inferred (dotted) relationship to display by default.
_INFERRED_DISPLAY_FLOOR = 0.75

# Reference-library membership relationships (a project/company/industry
# reference doc attached to the project hub). Belonging to the library is NOT
# proof the project uses or cites the document, so these are guidance by default
# — recommended/hidden — unless there is explicit-citation or inference evidence.
_REFERENCE_MEMBERSHIP_REL_TYPES = {
    "reference", "project_reference", "company_reference", "industry_standard",
}
# Relationships expressing that a project document explicitly cites a reference.
_CITATION_REL_TYPES = {"cites", "cited_by", "references_document", "citation"}


def _evidence_basis(rel_type: str, src: dict[str, Any] | None, tgt: dict[str, Any] | None) -> str:
    if rel_type in _RECOMMENDED_REL_TYPES:
        return "best_practice_recommendation"
    if rel_type in ("measures", "calculated_from", "threshold_from", "benchmarked_against"):
        return "kpi_mapping"
    if rel_type == "visualizes":
        return "dashboard_lineage"
    if rel_type in (
        "uses", "feeds", "derived_from", "reads_from",
        "linked_by_validated_join", "linked_by_inferred_join",
    ):
        return "query_lineage"
    if rel_type in _CITATION_REL_TYPES:
        return "explicit_citation"
    if rel_type in _REFERENCE_MEMBERSHIP_REL_TYPES:
        return "reference_membership"
    if rel_type in ("mentions", "applies_to"):
        return "semantic_inference"
    types = {
        str((src or {}).get("type") or ""),
        str((tgt or {}).get("type") or ""),
    }
    if types & {
        "business_entity", "supplier", "customer", "product", "facility", "contract",
    }:
        return "entity_extraction"
    return "explicit_citation"


def _classify_relationship(
    edge: dict[str, Any],
    src: dict[str, Any] | None,
    tgt: dict[str, Any] | None,
) -> dict[str, Any]:
    """Assign connector style + evidence strength to an edge.

    Five-tier evidence model (most-to-least supported); see
    ``app/prompts/knowledge_graph_insight_best_practices.md``:

    1. explicit / validated        → solid line   (shown by default)
    2. inferred / high confidence  → dotted line  (shown by default)
    3. recommended / best practice → dashed line  (hidden by default)
    4. weak                        → faint dotted (hidden by default)
    5. hidden / rejected           → no line

    The returned payload always carries the full connector contract so the
    frontend can render and toggle every tier:
    ``relationshipStrength``, ``connectorStyle``, ``displayByDefault``,
    ``validationStatus``, ``evidenceBasis`` and ``evidenceSummary``.
    """
    rel_type = str(edge.get("relationship_type") or edge.get("edge_type") or "")
    conf = _edge_confidence(edge)
    ev = _as_dict(edge.get("evidence"))
    vstatus = str(ev.get("validation_status") or "").lower()
    ev_basis = str(ev.get("evidence_basis") or "").lower()
    summary = _evidence_summary(edge)

    def _result(
        strength: str, style: str, display: bool, vstat: str, basis: str
    ) -> dict[str, Any]:
        return {
            "relationshipStrength": strength,
            "connectorStyle": style,
            "displayByDefault": display,
            "validationStatus": vstat,
            "evidenceBasis": basis,
            "evidenceSummary": summary,
        }

    # Reference-library membership: a reference doc attached to the project hub.
    # Membership alone is guidance, not proof the project uses/cites it, so it is
    # NOT solid by default. It becomes solid only with explicit-citation
    # evidence, dotted with inference/semantic evidence, otherwise recommended
    # (dashed, hidden by default).
    if rel_type in _REFERENCE_MEMBERSHIP_REL_TYPES:
        is_citation = ev_basis == "explicit_citation" or bool(
            ev.get("citation") or ev.get("cited_by")
        )
        is_inferred_ref = (
            vstatus == "inferred"
            or ev_basis == "semantic_inference"
            or bool(ev.get("semantic_match"))
        )
        if is_citation:
            return _result("explicit", "solid", True, "validated", "explicit_citation")
        if is_inferred_ref:
            return _result(
                "inferred", "dotted", conf >= _INFERRED_DISPLAY_FLOOR,
                "inferred", "semantic_inference",
            )
        return _result(
            "recommended", "dashed", False, "suggested", "reference_membership"
        )

    # A KPI endpoint that the collector marked "recommended" makes the edge a
    # recommendation regardless of its raw relationship type.
    kpi_recommended = any(
        str(_as_dict((n or {}).get("properties")).get("kpiStatus") or "") == "recommended"
        for n in (src, tgt)
        if n and str(n.get("type") or "") in ("kpi", "metric")
    )

    is_recommended = (
        rel_type in _RECOMMENDED_REL_TYPES
        or rel_type.startswith("recommended")
        or vstatus in ("suggested", "gap")
        or kpi_recommended
    )
    basis = _evidence_basis(rel_type, src, tgt)

    if vstatus == "rejected":
        return _result("hidden", "hidden", False, "rejected", basis)
    if is_recommended:
        return _result("recommended", "dashed", False, "suggested", basis)
    if vstatus == "inferred" or rel_type in _INFERRED_REL_TYPES:
        return _result(
            "inferred", "dotted", conf >= _INFERRED_DISPLAY_FLOOR, "inferred", basis
        )
    if vstatus == "validated" or conf >= 0.90:
        return _result("explicit", "solid", True, "validated", basis)
    if conf >= _INFERRED_DISPLAY_FLOOR:
        # Strong-but-not-validated: treat as high-confidence inference.
        return _result("inferred", "dotted", True, "inferred", basis)
    if conf >= 0.50:
        # Weak relationship: faint dotted, hidden unless the user enables it.
        return _result("weak", "dotted", False, "weak", basis)
    return _result("hidden", "hidden", False, "rejected", basis)


def classify_connector_style(edge: dict[str, Any]) -> dict[str, Any]:
    """Public, node-agnostic wrapper around :func:`_classify_relationship`.

    Classifies an edge purely from its own ``relationship_type``/``evidence``/
    ``confidence`` (no neighbouring-node context). Used by callers/tests that
    only have the raw edge dict.
    """
    return _classify_relationship(edge, None, None)


# ── Neighborhood selection ───────────────────────────────────────────

