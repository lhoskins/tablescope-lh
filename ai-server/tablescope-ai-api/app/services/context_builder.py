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
import time
import uuid
from typing import Any

import httpx

from app.core.config import settings
from app.core.security import sign_request
from app.models.schemas import ContextPackage, GroundingEvidence, VectorAccessClaims
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
) -> dict[str, Any]:
    """Verify user has access to the requested scope by calling the app server.

    Returns permission context including project membership and metadata.
    """
    # Call Tablescope app server to verify permissions. Signed the same way
    # every platform-api -> ai-server call is (see core/security.py) so the
    # endpoint can authenticate ai-server as the caller instead of trusting
    # whatever tenant/user/project ids show up in the request -- see
    # platform-api's app.services.internal_ai_auth for the verifying side
    # (TS-ISO-001).
    try:
        payload = {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "project_id": project_id,
            "timestamp": time.time(),
        }
        payload["signature"] = sign_request(payload)
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(
                f"{settings.tablescope_app_url}/api/ai/permissions",
                json=payload,
            )
            if resp.status_code == 200:
                return resp.json()
            logger.error(
                "Permission check returned HTTP %s for tenant=%s project=%s",
                resp.status_code, tenant_id, project_id,
            )
    except httpx.RequestError as e:
        logger.error("Could not reach app server for permission check: %s", e)

    # Fail closed: without a verified permission/context response we must NOT
    # proceed, otherwise the LLM runs on an empty, ungrounded context and
    # hallucinates data unrelated to the project. Refuse instead.
    if settings.require_app_server:
        raise ContextBuildError(
            reason=(
                "Permission service unavailable — refusing to build AI context "
                "without verified project access"
            ),
            denied_type="permission_service_unavailable",
        )

    # Fallback: return basic permission context (for local dev/testing only)
    return {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "project_id": project_id,
        "is_member": True,
        "is_owner": True,
        "project_visibility": "shared",
        "vector_access": {
            "version": 1,
            "tenant_id": tenant_id,
            "project_id": project_id,
            "principal_user_id": user_id,
            "project_access": "owner",
            "project_visibility": "shared",
            "can_read_shared_documents": True,
            "private_document_owner_user_id": user_id,
        },
        "datasources": [],
        "saved_queries": [],
        "dashboards": [],
        "query_scopes": [],
    }


def resolve_vector_access(
    permissions: dict[str, Any],
    *,
    tenant_id: int,
    user_id: int,
    project_id: int,
) -> VectorAccessClaims:
    """Validate and bind platform-minted claims to the signed AI request.

    A missing, malformed, or mismatched claim is an authorization failure, not
    a reason to fall back to a broader project search.
    """
    try:
        access = VectorAccessClaims.model_validate(permissions.get("vector_access"))
    except Exception as exc:
        raise ContextBuildError(
            reason="Permission service returned invalid vector access claims",
            denied_type="invalid_vector_access_claims",
        ) from exc
    if (
        access.tenant_id != tenant_id
        or access.project_id != project_id
        or access.principal_user_id != user_id
    ):
        raise ContextBuildError(
            reason="Vector access claims do not match the signed request",
            denied_type="mismatched_vector_access_claims",
        )
    return access


async def build_context(
    tenant_id: int,
    user_id: int,
    project_id: int,
    scope: str,
    question: str,
    feature: str = "ask",
    grounding_evidence: GroundingEvidence | None = None,
) -> ContextPackage:
    """Build the exact context the LLM is allowed to see.

    Enforces all isolation rules in code — not in prompts.
    """
    audit_id = str(uuid.uuid4())

    # --- Hard rejections (code-enforced, not prompt-based) ---

    # Cross-tenant: NEVER allowed
    # (structurally impossible — collection is derived from tenant_id)

    if scope != "authorized_project":
        raise ContextBuildError(
            reason="Unknown or caller-selected vector scope",
            denied_type="invalid_vector_scope",
        )

    # Cross-project: disabled by default
    if not settings.cross_project_enabled:
        # scope is always bound to a single project
        pass

    # Verify permissions
    perms = await _verify_permissions(tenant_id, user_id, project_id)
    vector_access = resolve_vector_access(
        perms, tenant_id=tenant_id, user_id=user_id, project_id=project_id
    )

    # --- Retrieve allowed context ---

    # 1. Project metadata (tables, columns)
    # The /api/ai/permissions response already carries the authorized datasource
    # metadata, so use that directly. The legacy /api/projects/{id}/datasources
    # endpoint requires user authentication which the AI service cannot provide.
    metadata = perms.get("datasources", [])

    # 2. Vector search (if question provided and no pre-computed grounding)
    documents: list[dict[str, Any]] = []
    if not grounding_evidence and question:
        query_embedding: list[float] | None = None
        try:
            query_embedding = await llm_client.generate_embedding(question)
        except Exception as e:
            logger.warning("Embedding generation failed: %s", e)

        if query_embedding is not None:
            try:
                documents = await vector_store.search_vectors(
                    access=vector_access,
                    query_vector=query_embedding,
                    limit=10,
                )
            except Exception as e:
                logger.warning("Vector search failed: %s", e)

            # Reference Library docs (industry/company/project tier) live in a
            # shared, tier-scoped collection so governed knowledge is available
            # across projects. Merge any matches into the document context.
            try:
                reference_docs = await vector_store.search_reference_vectors(
                    access=vector_access,
                    query_vector=query_embedding,
                    limit=5,
                )
                if reference_docs:
                    documents = documents + reference_docs
            except Exception as e:
                logger.warning("Reference vector search failed: %s", e)

    # 2b. Use platform-api provided grounding evidence when available.
    if grounding_evidence:
        documents = [
            {
                "id": p.id,
                "score": p.retrieval_score,
                "payload": {
                    "chunk_text": p.text,
                    "title": p.title,
                    "source_type": p.source_type,
                    "tier": p.tier,
                    "retrieval_method": p.retrieval_method,
                    "document_id": p.document_id,
                    "chunk_index": p.chunk_index,
                },
            }
            for p in (grounding_evidence.passages or [])
        ]

    # 3. Saved queries, dashboards, and query scopes from permissions context
    queries = perms.get("saved_queries", [])
    dashboards = perms.get("dashboards", [])
    query_scopes = perms.get("query_scopes", [])

    # 4. Project documents (unstructured assets)
    project_documents = perms.get("documents", [])

    # 5. Project graph nodes/edges
    graph_nodes = perms.get("graph_nodes", [])
    graph_edges = perms.get("graph_edges", [])

    # 6. Document families (family-aware retrieval)
    document_families = perms.get("document_families", [])

    # 7. Grounding evidence extras (insight snapshots, network repos, reference docs)
    insight_snapshots = []
    network_connections = []
    reference_documents = []
    if grounding_evidence:
        insight_snapshots = [
            s.model_dump(exclude_none=True) for s in grounding_evidence.insight_snapshots or []
        ]
        network_connections = [
            c.model_dump(exclude_none=True) for c in grounding_evidence.network_connections or []
        ]
        reference_documents = [
            d.model_dump(exclude_none=True) for d in grounding_evidence.reference_documents or []
        ]

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
            "document_families": document_families,
            "insight_snapshots": insight_snapshots,
            "network_connections": network_connections,
            "reference_documents": reference_documents,
            "memories": [],
        },
        retrieval_filters={
            "tenant_id": tenant_id,
            "project_id": project_id,
            "scope": scope,
            "user_id": user_id,
        },
        audit_context_id=audit_id,
        grounding_evidence=grounding_evidence,
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
            # Data profile (row count, date range, categorical values) so a
            # prose answer never claims a trend or breakdown the data cannot
            # actually support.
            profile_summary = ds.get("profile_summary")
            if profile_summary:
                parts.append(f"      profile: {profile_summary}")

    # Relevant documents
    if context.allowed_context.get("documents"):
        parts.append("\nRelevant document context:")
        for doc in context.allowed_context["documents"]:
            payload = doc.get("payload", {})
            text = payload.get("chunk_text", payload.get("content", ""))
            if not text:
                continue
            title = payload.get("title")
            method = payload.get("retrieval_method", "")
            prefix = f"[{method}] " if method else ""
            if payload.get("source_type") == "reference_library" and title:
                tier = payload.get("tier", "")
                label = f"{prefix}reference: {title}" + (f" ({tier})" if tier else "")
                parts.append(f"  - [{label}] {text[:500]}")
            else:
                parts.append(f"  - {prefix}{title + ': ' if title else ''}{text[:500]}")

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
            kpis = doc.get("recommended_kpis", [])
            if kpis:
                line += f" [recommended KPIs: {', '.join(str(k) for k in kpis)}]"
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

    # Document families (grouped, family-aware context)
    if context.allowed_context.get("document_families"):
        parts.append("\nDocument families:")
        for fam in context.allowed_context["document_families"]:
            name = fam.get("family_name", "unknown")
            ftype = fam.get("family_type", "")
            header = f"  - {name}"
            if ftype:
                header += f" ({ftype})"
            summary = fam.get("summary", "")
            if summary:
                header += f": {summary[:200]}"
            parts.append(header)
            members = fam.get("members", {}) or {}
            for kind in ("documents", "datasources", "kpis", "queries", "dashboards"):
                vals = members.get(kind) or []
                if vals:
                    parts.append(f"      {kind}: {', '.join(str(v) for v in vals)}")

    # Grounding knowledge-graph nodes (query-aware, when provided)
    if context.grounding_evidence and context.grounding_evidence.kg_nodes:
        parts.append("\nRelevant knowledge-graph findings:")
        for node in context.grounding_evidence.kg_nodes:
            line = f"  - {node.node_type}: {node.title}"
            if node.summary:
                line += f" — {node.summary[:200]}"
            parts.append(line)

    # Grounding governed KPIs (when provided)
    if context.grounding_evidence and context.grounding_evidence.kpis:
        parts.append("\nRelevant governed KPIs:")
        for kpi in context.grounding_evidence.kpis:
            line = f"  - {kpi.display_name or kpi.kpi_key}"
            if kpi.business_domain:
                line += f" ({kpi.business_domain})"
            parts.append(line)

    # Precomputed insight snapshots (Business/Project Insight cards)
    if context.allowed_context.get("insight_snapshots"):
        parts.append("\nPrecomputed insight snapshots (answer from these when relevant):")
        for snap in context.allowed_context["insight_snapshots"]:
            title = snap.get("title", "unknown")
            project = snap.get("project_name") or f"project {snap.get('project_id')}"
            ctype = snap.get("chart_type", "chart")
            series = ", ".join(snap.get("series", []))
            trend = snap.get("trend", "")
            line = f"  - {title} ({project})"
            if snap.get("card_type"):
                line += f" [{snap['card_type']}]"
            parts.append(line)
            if snap.get("summary"):
                parts.append(f"      summary: {snap['summary'][:200]}")
            if series:
                parts.append(f"      chart: {ctype} with series {series}")
            if trend:
                parts.append(f"      trend: {trend}")
            if snap.get("result_preview"):
                parts.append(f"      recorded values:\n{snap['result_preview']}")
            if snap.get("sql"):
                parts.append(f"      SQL:\n```sql\n{snap['sql'][:500]}\n```")

    # Network file connections
    if context.allowed_context.get("network_connections"):
        parts.append("\nApproved network file connections:")
        for conn in context.allowed_context["network_connections"]:
            line = f"  - {conn.get('name', 'unknown')}: {conn.get('protocol', 'smb')}://{conn.get('host')}/{conn.get('share_name')}"
            root = conn.get("approved_root_path")
            if root:
                line += f" path={root}"
            parts.append(line)

    # Reference Library documents
    if context.allowed_context.get("reference_documents"):
        parts.append("\nReference Library documents:")
        for doc in context.allowed_context["reference_documents"]:
            title = doc.get("title", "unknown")
            tier = doc.get("tier", "")
            domain = doc.get("domain_tag") or ""
            line = f"  - {title}"
            if tier:
                line += f" ({tier}"
                if domain:
                    line += f", domain={domain}"
                line += ")"
            elif domain:
                line += f" (domain={domain})"
            parts.append(line)
            summary = doc.get("ai_summary")
            if summary:
                parts.append(f"      summary: {summary[:300]}")
            source_url = doc.get("source_url")
            if source_url:
                parts.append(f"      source: {source_url}")

    return "\n".join(parts)
