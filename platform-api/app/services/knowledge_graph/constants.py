"""Knowledge graph shared constants and pure helpers."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from decimal import Decimal
from typing import Any

logger = logging.getLogger(__name__)


PIPELINE_VERSION = "knowledge_graph_node_centric_v2"
# Cached full-graph snapshot pipeline version. Bumped to v2 for the connector
# -style policy: reference-library edges are no longer solid by default, and v3
# adds the dashed (recommended) + faint (weak) connector tiers, so any snapshot
# built under an older version is rebuilt automatically on read.
SNAPSHOT_PIPELINE_VERSION = "knowledge_graph_connector_styles_v3"

# Default edge/node confidence floor for the visible graph.
DEFAULT_MIN_CONFIDENCE = 0.70
# Below this an edge is only shown when include_inferred is set.
INFERRED_FLOOR = 0.50
# Keep the canvas readable.
MAX_NEIGHBORHOOD_NODES = 60
MAX_CARDS = 8
# Pre-cache AI insight cards for up to this many centre-eligible nodes at
# snapshot-rebuild time (bounds rebuild cost on very large graphs).
MAX_PRECACHE_CENTERS = 120
# Number of centres enriched concurrently during a snapshot rebuild.
PRECACHE_CONCURRENCY = 3

# ── Node taxonomy ────────────────────────────────────────────────────

_LAYER_BY_TYPE: dict[str, str] = {
    "project": "project",
    "document": "evidence",
    "document_family": "semantic",
    "reference_document": "evidence",
    "policy": "evidence",
    "procedure": "evidence",
    "standard": "evidence",
    "control": "evidence",
    "data_source": "evidence",
    "datasource": "evidence",
    "table": "evidence",
    "column": "evidence",
    "saved_query": "evidence",
    "query": "evidence",
    "dashboard": "evidence",
    "kpi": "kpi",
    "metric": "kpi",
    "threshold": "kpi",
    "benchmark": "kpi",
    "process": "semantic",
    "business_entity": "semantic",
    "entity": "semantic",
    "supplier": "semantic",
    "customer": "semantic",
    "product": "semantic",
    "facility": "semantic",
    "contract": "semantic",
    "tag": "semantic",
    "risk": "insight",
    "warning": "insight",
    "opportunity": "insight",
    "anomaly": "insight",
    "audit_finding": "insight",
    "compliance_gap": "insight",
    "process_gap": "insight",
    "data_gap": "insight",
    "gap": "insight",
    "insight": "insight",
    "relationship_insight": "insight",
    "recommendation": "action",
    "action": "action",
}

_DISPLAY_GROUP_BY_TYPE: dict[str, str] = {
    "project": "Project",
    "document": "Supporting & Governing Documents",
    "document_family": "Supporting & Governing Documents",
    "reference_document": "Authoritative Reference Library",
    "policy": "Governing Policies / SOPs",
    "procedure": "Governing Policies / SOPs",
    "standard": "Governing Policies / SOPs",
    "control": "Governing Policies / SOPs",
    "kpi": "KPIs & Metrics",
    "metric": "KPIs & Metrics",
    "threshold": "KPIs & Metrics",
    "benchmark": "KPIs & Metrics",
    "saved_query": "Queries",
    "query": "Queries",
    "dashboard": "Dashboards",
    "data_source": "Linked Data Sources",
    "datasource": "Linked Data Sources",
    "table": "Linked Data Sources",
    "column": "Linked Data Sources",
    "process": "Related Processes",
    "business_entity": "Related Entities",
    "entity": "Related Entities",
    "supplier": "Related Entities",
    "customer": "Related Entities",
    "product": "Related Entities",
    "facility": "Related Entities",
    "contract": "Related Entities",
    "tag": "Related Entities",
    "risk": "Insights / Findings",
    "warning": "Insights / Findings",
    "opportunity": "Insights / Findings",
    "anomaly": "Insights / Findings",
    "audit_finding": "Insights / Findings",
    "compliance_gap": "Insights / Findings",
    "process_gap": "Insights / Findings",
    "data_gap": "Insights / Findings",
    "gap": "Insights / Findings",
    "insight": "Insights / Findings",
    "relationship_insight": "Insights / Findings",
    "recommendation": "Recommendations",
    "action": "Recommendations",
}

# Default severity per node type when properties.severity is absent.
_SEVERITY_BY_TYPE: dict[str, str] = {
    "risk": "urgent",
    "audit_finding": "urgent",
    "compliance_gap": "warning",
    "warning": "warning",
    "anomaly": "warning",
    "process_gap": "warning",
    "data_gap": "warning",
    "gap": "warning",
    "opportunity": "opportunity",
}

_ALLOWED_SEVERITIES = ("critical", "urgent", "warning", "watch", "opportunity", "info")
_SEVERITY_RANK = {
    "critical": 6, "urgent": 5, "warning": 4, "watch": 3, "opportunity": 3, "info": 1,
}

# Node types that are themselves a "finding" the right panel surfaces as a card.
_INSIGHT_TYPES = {
    "risk", "warning", "opportunity", "anomaly", "audit_finding",
    "compliance_gap", "process_gap", "data_gap", "gap", "insight",
    "relationship_insight",
}
_GAP_TYPES = {"gap", "process_gap", "data_gap", "compliance_gap"}
_ACTION_TYPES = {"recommendation", "action"}

# High-value node types that must never be crowded out of the capped
# neighborhood by the bulk reference library / generic assets. KPIs & metrics
# (recommended or measured) and findings/gaps/actions always get a seat first.
_PRIORITY_NEIGHBOR_TYPES = (
    {"kpi", "metric", "threshold", "benchmark"} | _INSIGHT_TYPES | _ACTION_TYPES
)

# Edge types that point an insight/gap/recommendation at its evidence.
_EVIDENCE_EDGE_TYPES = {
    "evidence_for", "governs", "governed_by", "references", "supports",
    "measures", "calculated_from", "derived_from", "visualizes", "uses",
    "defines", "indicates", "drives", "follows_from", "recommends",
    "mitigates", "threshold_from", "benchmarked_against",
}

# Maps a node type onto a Knowledge Graph card category.
_CARD_CATEGORY_BY_TYPE: dict[str, str] = {
    "risk": "risk",
    "audit_finding": "risk",
    "warning": "warning",
    "anomaly": "warning",
    "opportunity": "opportunity",
    "gap": "gap",
    "process_gap": "gap",
    "data_gap": "gap",
    "compliance_gap": "gap",
    "insight": "business_insight",
    "relationship_insight": "business_insight",
}

# Best lens to switch to when a node of the given type is selected.
_LENS_BY_TYPE: dict[str, str] = {
    "document": "document-centric",
    "document_family": "family-centric",
    "reference_document": "document-centric",
    "policy": "process-centric",
    "procedure": "process-centric",
    "process": "process-centric",
    "kpi": "kpi-centric",
    "metric": "kpi-centric",
    "dashboard": "lineage",
    "query": "lineage",
    "saved_query": "lineage",
    "data_source": "lineage",
    "table": "lineage",
    "risk": "insight-first",
    "warning": "insight-first",
    "opportunity": "insight-first",
    "gap": "evidence",
}


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (value or "").lower()).strip("_")


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (ValueError, TypeError):
            return {}
    return {}


def _layer_for(node_type: str) -> str:
    return _LAYER_BY_TYPE.get(node_type, "semantic")


def _display_group_for(node_type: str) -> str:
    return _DISPLAY_GROUP_BY_TYPE.get(node_type, "Related Entities")


def _normalize_severity(value: Any) -> str:
    if isinstance(value, str) and value.lower() in _ALLOWED_SEVERITIES:
        return value.lower()
    return ""


def _severity_for(node_type: str, props: dict[str, Any]) -> str:
    explicit = _normalize_severity(props.get("severity"))
    if explicit:
        return explicit
    return _SEVERITY_BY_TYPE.get(node_type, "info")


def graph_key_for(node: dict[str, Any]) -> str:
    """Return a stable graph key for a raw node row.

    Prefers an explicit ``properties.graph_key``; otherwise derives one from the
    node type and its most stable identifier so clicks/URLs survive rebuilds.
    """
    props = _as_dict(node.get("properties"))
    explicit = str(props.get("graph_key") or "").strip()
    if explicit:
        return explicit

    ntype = str(node.get("node_type") or node.get("type") or "node")
    name = str(node.get("name") or node.get("label") or "")
    source_id = node.get("source_id")
    node_id = node.get("id")

    if ntype == "project":
        return f"project:{props.get('project_id', node_id)}"
    if ntype in ("document", "reference_document"):
        return f"document:{source_id or node_id}"
    if ntype == "document_family":
        return f"document_family:{props.get('family_key') or _norm(name) or node_id}"
    if ntype in ("data_source", "datasource", "table"):
        return f"datasource:{_norm(name) or node_id}"
    if ntype in ("saved_query", "query"):
        return f"query:{source_id or node_id}"
    if ntype == "dashboard":
        return f"dashboard:{source_id or node_id}"
    if ntype in ("kpi", "metric"):
        return f"kpi:{props.get('kpi_key') or _norm(name) or node_id}"
    if ntype == "process":
        return f"process:{_norm(name) or node_id}"
    if ntype in _GAP_TYPES:
        return f"gap:{props.get('gap_key') or _norm(name) or node_id}"
    if ntype in _ACTION_TYPES:
        return f"action:{node_id}"
    if ntype in _INSIGHT_TYPES:
        return f"insight:{node_id}"
    if _layer_for(ntype) == "semantic":
        return f"entity:{_norm(name) or node_id}"
    return f"{ntype}:{node_id}"


# ── Enrichment ───────────────────────────────────────────────────────

def _json_safe(obj: Any) -> Any:
    """Recursively coerce a value into JSON-serializable primitives.

    Postgres ``NUMERIC`` columns (e.g. edge confidence) come back as ``Decimal``
    and datetimes as ``datetime`` — neither is JSON-serializable for the JSONB
    snapshot payload, so convert them to ``float`` / ISO strings.
    """
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    return obj


