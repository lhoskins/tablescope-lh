"""KG-07: write path for the Knowledge Graph evidence-access audit log.

Called once per KG context collection (``collect_knowledge_graph_ai_context``)
so every AI-generated answer that used Knowledge Graph evidence -- Business
Insights, Project Insights, dashboard generation, query generation -- leaves
a record of exactly which node/document/query ids (and the active KG
version) informed it, for a given tenant/project/user.

Best-effort by design: an audit-write failure must never break the feature
it's auditing.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge_graph_evidence_access import KnowledgeGraphEvidenceAccess
from app.models.knowledge_graph_lifecycle import KnowledgeGraph

logger = logging.getLogger(__name__)

# source_type values (see knowledge_graph_context/collectors.py and the
# stored AI graph) that identify a node as a document vs. a query, for the
# document_ids / query_ids columns.
_DOCUMENT_SOURCE_TYPES = {"reference_document", "project_asset"}
_QUERY_SOURCE_TYPES = {"query", "saved_query"}


async def _active_kg_version_id(
    session: AsyncSession, *, tenant_id: int, project_id: int,
) -> int | None:
    return await session.scalar(
        select(KnowledgeGraph.active_version_id).where(
            KnowledgeGraph.tenant_id == tenant_id,
            KnowledgeGraph.project_id == project_id,
        )
    )


def evidence_ids_from_nodes(nodes: list[dict[str, Any]]) -> tuple[list, list, list]:
    """Split a node list into (node_ids, document_ids, query_ids) for the
    audit record, using each node's own graph id plus its structural
    source_id when it's backed by a document or a saved query."""
    node_ids: list = []
    document_ids: list = []
    query_ids: list = []
    for n in nodes:
        nid = n.get("id")
        if nid is not None:
            node_ids.append(nid)
        source_type = n.get("source_type")
        source_id = n.get("source_id")
        if source_id is None:
            continue
        if source_type in _DOCUMENT_SOURCE_TYPES:
            document_ids.append(source_id)
        elif source_type in _QUERY_SOURCE_TYPES:
            query_ids.append(source_id)
    return node_ids, document_ids, query_ids


async def record_kg_evidence_access(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: int,
    user_id: int | None,
    surface: str,
    node_ids: list,
    document_ids: list,
    query_ids: list,
) -> None:
    """Persist one audit row. Best-effort: never raises into the caller."""
    if not node_ids and not document_ids and not query_ids:
        return
    try:
        kg_version_id = await _active_kg_version_id(
            session, tenant_id=tenant_id, project_id=project_id,
        )
        session.add(
            KnowledgeGraphEvidenceAccess(
                tenant_id=tenant_id,
                project_id=project_id,
                user_id=user_id,
                surface=surface,
                kg_version_id=kg_version_id,
                node_ids=node_ids,
                document_ids=document_ids,
                query_ids=query_ids,
            )
        )
        await session.flush()
    except Exception:
        logger.exception(
            "Failed to record KG evidence-access audit row (tenant=%s project=%s surface=%s)",
            tenant_id, project_id, surface,
        )
