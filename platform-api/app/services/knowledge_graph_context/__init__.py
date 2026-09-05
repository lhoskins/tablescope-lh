
from __future__ import annotations

from .collectors import collect_structural_graph as collect_structural_graph
from .collectors import logger as logger
from .coverage import compute_source_coverage as compute_source_coverage
from .graph_primitives import _KPI_EDGE_TYPES as _KPI_EDGE_TYPES
from .graph_primitives import _KPI_PHRASE_MIN as _KPI_PHRASE_MIN
from .graph_primitives import _MAX_PER_KIND as _MAX_PER_KIND
from .graph_primitives import _REF_REL_BY_TIER as _REF_REL_BY_TIER
from .graph_primitives import _REL_DASHBOARD as _REL_DASHBOARD
from .graph_primitives import _REL_DASHBOARD_VISUALIZES as _REL_DASHBOARD_VISUALIZES
from .graph_primitives import _REL_DATA_SOURCE as _REL_DATA_SOURCE
from .graph_primitives import _REL_DOCUMENT as _REL_DOCUMENT
from .graph_primitives import _REL_QUERY as _REL_QUERY
from .graph_primitives import _REL_QUERY_MEASURES as _REL_QUERY_MEASURES
from .graph_primitives import _REL_QUERY_READS as _REL_QUERY_READS
from .graph_primitives import _REL_RECOMMENDED_KPI as _REL_RECOMMENDED_KPI
from .graph_primitives import _REL_SUPPORTS_KPI as _REL_SUPPORTS_KPI
from .graph_primitives import _edge as _edge
from .graph_primitives import _haystack as _haystack
from .graph_primitives import _kpi_phrases as _kpi_phrases
from .graph_primitives import _node as _node
from .graph_primitives import _norm as _norm
from .graph_primitives import _phrase_in as _phrase_in
from .graph_primitives import (
    active_reference_document_conditions as active_reference_document_conditions,
)

"""Evidence Collector for the Insight-First Knowledge Graph.

Builds *structural* graph nodes and edges from the project's real assets — the
documents, the authoritative reference library (project + company + industry),
the linked data sources / tables, the saved queries, and the dashboards — and
connects them to the project hub so the node-centric graph always shows the data
sources related to a node (with directional, labelled edges).

These synthetic nodes/edges are merged with the AI-generated
``ai_project_graph_nodes`` / ``ai_project_graph_edges`` (processes, KPIs, risks,
relationships, gaps) before the node-centric payload is built. Dedup is by the
stable ``graph_key`` so a stored node and its structural twin collapse into one.

Nothing here is fabricated: every node maps to a row the user actually owns, and
every edge is a factual containment/lineage relationship (confidence 1.0).
"""
