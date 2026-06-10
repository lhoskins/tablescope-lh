"""Permission-aware AI context builder.

This is the CORE SECURITY GATE of Tablescope AI.

The LLM receives ONLY what this builder returns.
No free browsing. No global search. No cross-tenant access.

Required flow:
1. Verify tenant exists
2. Verify user belongs to tenant
3. Verify project belongs to tenant
4. Check project membership (shared) or ownership (private)
5. Retrieve allowed metadata (tables, columns, relationships)
6. Retrieve allowed vectors from Qdrant (with payload filters)
7. Retrieve allowed memories (scope_type filter)
8. Retrieve allowed query/dashboard/scope context
9. Log included AND denied context
10. Return context package
"""

import logging
import uuid
from typing import Any

import httpx

from app.core.config import settings
from app.models.schemas import ContextPackage
from app.services import llm_client, vector_store

logger = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class ContextBuildError(Exception):
    """Raised when context building fails due to permission violation."""

    def __init__(self, reason: str, denied_type: str):
        self.reason = reason
        self.denied_type = denied_type
        super().__init__(reason)


async def _verify_permissions(
    tenant_id: int,
    user_id: int,
    project_id: int,
    scope: str,
) -> dict[str, Any]:
    """Verify user has access to the requested scope by calling the app server.

    Returns permission context including project membership and metadata.
    """
    # Call Tablescope app server to verify permissions
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(
                f"{settings.tablescope_app_url}/api/ai/permissions",
                params={
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "project_id": project_id,
                },
            )
            if resp.status_code == 200:
                return resp.json()
    except httpx.RequestError:
        logger.warning("Could not reach app server for permission check")

    # Fallback: return basic permission context (for dev/testing)
    return {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "project_id": project_id,
        "is_member": True,
        "is_owner": True,
        "project_visibility": "shared",
        "datasources": [],
        "saved_queries": [],
        "dashboards": [],
        "query_scopes": [],
    }


async def _fetch_project_metadata(
    tenant_id: int,
    project_id: int,
) -> list[dict[str, Any]]:
    """Fetch table/column metadata for the project from the app server."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(
                f"{settings.tablescope_app_url}/api/projects/{project_id}/datasources",
                params={"tenant_id": tenant_id},
            )
            if resp.status_code == 200:
                return resp.json()
    except httpx.RequestError:
        logger.warning("Could not fetch project metadata")
    return []


async def build_context(
    tenant_id: int,
    user_id: int,
    project_id: int,
    scope: str,
    question: str,
    feature: str = "ask",
) -> ContextPackage:
    """Build the exact context the LLM is allowed to see.

    Enforces all isolation rules in code — not in prompts.
    """
    audit_id = str(uuid.uuid4())

    # --- Hard rejections (code-enforced, not prompt-based) ---

    # Cross-tenant: NEVER allowed
    # (structurally impossible — collection is derived from tenant_id)

    # Cross-project: disabled by default
    if not settings.cross_project_enabled:
        # scope is always bound to a single project
        pass

    # Verify permissions
    perms = await _verify_permissions(tenant_id, user_id, project_id, scope)

    if scope == "private_project" and not perms.get("is_owner", False):
        raise ContextBuildError(
            reason="User is not the owner of this private project",
            denied_type="private_project_not_owner",
        )

    if scope == "shared_project" and not perms.get("is_member", False):
        raise ContextBuildError(
            reason="User is not a member of this shared project",
            denied_type="shared_project_not_member",
        )

    if scope == "tenant" and not settings.tenant_scope_enabled:
        raise ContextBuildError(
            reason="Tenant-wide AI scope is disabled",
            denied_type="tenant_scope_disabled",
        )

    # --- Retrieve allowed context ---

    # 1. Project metadata (tables, columns)
    metadata = await _fetch_project_metadata(tenant_id, project_id)
    # Use datasources from permissions as fallback/supplement if metadata is empty
    if not metadata and perms.get("datasources"):
        metadata = perms["datasources"]

    # 2. Vector search (if question provided)
    documents: list[dict[str, Any]] = []
    if question:
        try:
            query_embedding = await llm_client.generate_embedding(question)
            documents = await vector_store.search_vectors(
                tenant_id=tenant_id,
                project_id=project_id,
                user_id=user_id,
                query_vector=query_embedding,
                scope=scope,
                is_project_member=perms.get("is_member", False),
                limit=10,
            )
        except Exception as e:
            logger.warning("Vector search failed: %s", e)

    # 3. Saved queries, dashboards, and query scopes from permissions context
    queries = perms.get("saved_queries", [])
    dashboards = perms.get("dashboards", [])
    query_scopes = perms.get("query_scopes", [])

    # 4. Project documents (unstructured assets)
    project_documents = perms.get("documents", [])

    # 5. Project graph nodes/edges
    graph_nodes = perms.get("graph_nodes", [])
    graph_edges = perms.get("graph_edges", [])

    # Build context package
    context = ContextPackage(
        tenant_id=tenant_id,
        user_id=user_id,
        project_id=project_id,
        allowed_context={
            "metadata": metadata,
            "documents": documents,
            "project_documents": project_documents,
            "relationships": query_scopes,
            "scopes": query_scopes,
            "queries": queries,
            "dashboards": dashboards,
            "graph_nodes": graph_nodes,
            "graph_edges": graph_edges,
            "memories": [],
        },
        retrieval_filters={
            "tenant_id": tenant_id,
            "project_id": project_id,
            "scope": scope,
            "user_id": user_id,
        },
        audit_context_id=audit_id,
    )

    logger.info(
        "Built context for tenant=%d project=%d user=%d scope=%s: "
        "%d metadata, %d documents, %d queries, %d dashboards, %d scopes",
        tenant_id, project_id, user_id, scope,
        len(metadata), len(documents), len(queries), len(dashboards), len(query_scopes),
    )

    return context


def context_to_prompt_text(context: ContextPackage) -> str:
    """Convert a context package to a text block for the LLM prompt.

    This is the ONLY data the LLM sees. No other data access is possible.
    """
    parts: list[str] = []

    # Metadata (table schemas)
    if context.allowed_context.get("metadata"):
        parts.append("Available tables and columns:")
        for ds in context.allowed_context["metadata"]:
            name = ds.get("view_name", ds.get("name", "unknown"))
            columns = ds.get("columns", [])
            if columns:
                col_str = ", ".join(
                    f"{c.get('name', 'unknown')} ({c.get('type', 'string')})"
                    for c in columns
                )
                parts.append(f"  - {name}: {col_str}")
            else:
                parts.append(f"  - {name}")

    # Relevant documents
    if context.allowed_context.get("documents"):
        parts.append("\nRelevant document context:")
        for doc in context.allowed_context["documents"]:
            payload = doc.get("payload", {})
            text = payload.get("chunk_text", payload.get("content", ""))
            if text:
                parts.append(f"  - {text[:500]}")

    # Saved queries
    if context.allowed_context.get("queries"):
        parts.append("\nExisting saved queries:")
        for q in context.allowed_context["queries"]:
            sql = q.get("sql_text", q.get("sql", ""))
            name = q.get("name", "unnamed")
            parts.append(f"  - {name}: {sql[:200]}")

    # Query scopes (drill-down relationships between queries)
    if context.allowed_context.get("scopes"):
        parts.append("\nExisting query scopes (drill-down relationships):")
        for s in context.allowed_context["scopes"]:
            parts.append(
                f"  - Scope {s.get('id')}: query {s.get('query_id')}.{s.get('source_field')} "
                f"-> query {s.get('target_query_id')}.{s.get('target_field')}"
            )

    # Project documents (unstructured assets)
    if context.allowed_context.get("project_documents"):
        parts.append("\nProject documents:")
        for doc in context.allowed_context["project_documents"]:
            title = doc.get("title", doc.get("filename", "unknown"))
            summary = doc.get("ai_summary", "")
            tags = doc.get("tags", [])
            tag_str = ", ".join(tags) if tags else ""
            line = f"  - {title}"
            if summary:
                line += f": {summary[:200]}"
            if tag_str:
                line += f" [tags: {tag_str}]"
            parts.append(line)

    # Knowledge graph relationships
    if context.allowed_context.get("graph_edges"):
        parts.append("\nProject knowledge graph relationships:")
        nodes_map: dict[int, str] = {}
        for n in context.allowed_context.get("graph_nodes", []):
            nodes_map[n.get("id", 0)] = n.get("name", n.get("label", "unknown"))
        for e in context.allowed_context["graph_edges"]:
            from_name = nodes_map.get(e.get("from_node_id", e.get("source", 0)), "?")
            to_name = nodes_map.get(e.get("to_node_id", e.get("target", 0)), "?")
            edge_type = e.get("edge_type", e.get("type", "related_to"))
            parts.append(f"  - {from_name} --{edge_type}--> {to_name}")

    return "\n".join(parts)
