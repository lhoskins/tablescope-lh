
from __future__ import annotations

from .graph_primitives import AUTO_LINK_THRESHOLD as AUTO_LINK_THRESHOLD
from .graph_primitives import FAMILY_RELATIONSHIP_TYPES as FAMILY_RELATIONSHIP_TYPES
from .graph_primitives import SUGGEST_THRESHOLD as SUGGEST_THRESHOLD
from .graph_primitives import _as_dict as _as_dict
from .graph_primitives import _upsert_edge as _upsert_edge
from .graph_primitives import _upsert_typed_node as _upsert_typed_node
from .graph_primitives import log_family_event as log_family_event
from .graph_primitives import logger as logger
from .graph_primitives import normalize_family_key as normalize_family_key
from .lifecycle import archive_empty_family as archive_empty_family
from .lifecycle import deactivate_document_edges as deactivate_document_edges
from .lifecycle import upsert_document_family_node as upsert_document_family_node
from .linking import _edge_role as _edge_role
from .linking import apply_document_family as apply_document_family
from .linking import create_family_relationship_edges as create_family_relationship_edges
from .linking import link_document_to_family as link_document_to_family
from .queries import get_family_members as get_family_members
from .queries import get_family_node as get_family_node

"""Document-family helpers over the project knowledge graph.

Families reuse the existing ``ai_project_graph_nodes`` / ``ai_project_graph_edges``
tables (node_type='document_family', edge_type='belongs_to_family' plus typed
relationship edges). No dedicated family table is created.

Auto-link thresholds (per plan):
    confidence >= 0.90  → auto-link the document to its family
    0.70 .. 0.89        → store as a suggestion (no belongs_to_family edge)
    < 0.70              → ignore
"""
