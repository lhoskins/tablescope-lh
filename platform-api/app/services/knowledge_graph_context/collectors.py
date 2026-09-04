
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_project_graph import AIProjectGraphEdge, AIProjectGraphNode
from app.models.dashboard import Dashboard
from app.models.database_data_source import DatabaseDataSource
from app.models.file_source_meta import FileSourceMeta
from app.models.project import Project
from app.models.project_asset import ProjectAsset
from app.models.reference_library import (
    TIER_COMPANY,
    TIER_INDUSTRY,
    TIER_PROJECT,
    ReferenceDocument,
)
from app.models.saved_query import SavedQuery

from .graph_primitives import (
    _KPI_EDGE_TYPES,
    _MAX_PER_KIND,
    _REF_REL_BY_TIER,
    _REL_DASHBOARD,
    _REL_DASHBOARD_VISUALIZES,
    _REL_DATA_SOURCE,
    _REL_DOCUMENT,
    _REL_QUERY,
    _REL_QUERY_MEASURES,
    _REL_QUERY_READS,
    _REL_RECOMMENDED_KPI,
    _edge,
    _haystack,
    _kpi_phrases,
    _node,
    _norm,
    _phrase_in,
)

logger = logging.getLogger(__name__)


async def collect_structural_graph(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    """Return ``(nodes, edges, project_hub_key)`` for the project's real assets.

    The project hub node (graph_key ``project:{id}``) is always returned so the
    structural sources radiate from it with directional edges.
    """
    project = await session.get(Project, project_id)
    if project is None or project.tenant_id != tenant_id:
        return [], [], ""

    hub_id = f"s:project:{project_id}"
    hub_key = f"project:{project_id}"
    nodes: list[dict[str, Any]] = [
        _node(
            hub_id,
            "project",
            project.name or f"Project {project_id}",
            source_type="project",
            source_id=project_id,
            properties={
                "project_id": project_id,
                "graph_key": hub_key,
                "summary": (project.description or "")[:400],
                # The project stays the security/data boundary but is never
                # drawn on the canvas (Knowledge Graph centers on a real node).
                "hidden_on_canvas": True,
                "structural_hub": True,
            },
        )
    ]
    edges: list[dict[str, Any]] = []

    # Map of normalized data-source identifiers → synthetic node id, so saved
    # queries can be linked to the tables they actually read.
    ds_by_name: dict[str, str] = {}

    # ── Linked data sources (uploaded files) ─────────────────────────
    file_sources = (
        await session.scalars(
            select(FileSourceMeta)
            .where(
                FileSourceMeta.project_id == project_id,
                FileSourceMeta.tenant_id == tenant_id,
                FileSourceMeta.archived.is_(False),
            )
            .order_by(FileSourceMeta.id)
            .limit(_MAX_PER_KIND)
        )
    ).all()
    for fs in file_sources:
        nid = f"s:datasource:file:{fs.id}"
        label = fs.view_name or fs.file_name or f"table {fs.id}"
        nodes.append(
            _node(
                nid,
                "data_source",
                label,
                source_type="file_source",
                source_id=fs.id,
                properties={
                    "graph_key": f"datasource:{_norm(label)}",
                    "summary": f"Uploaded data source ({fs.source_format or 'file'}).",
                    "kind": "file",
                },
            )
        )
        edges.append(
            _edge(
                f"se:ds:file:{fs.id}", hub_id, nid, _REL_DATA_SOURCE,
                f"{label} is a data source in this project.",
            )
        )
        for key in {_norm(fs.view_name), _norm(fs.file_name)}:
            if key:
                ds_by_name[key] = nid

    # ── Linked data sources (database tables) ────────────────────────
    db_sources = (
        await session.scalars(
            select(DatabaseDataSource)
            .where(
                DatabaseDataSource.project_id == project_id,
                DatabaseDataSource.tenant_id == tenant_id,
                DatabaseDataSource.archived.is_(False),
            )
            .order_by(DatabaseDataSource.id)
            .limit(_MAX_PER_KIND)
        )
    ).all()
    for ds in db_sources:
        nid = f"s:datasource:db:{ds.id}"
        label = ds.display_name or ds.table_name or f"table {ds.id}"
        nodes.append(
            _node(
                nid,
                "data_source",
                label,
                source_type="database_data_source",
                source_id=ds.id,
                properties={
                    "graph_key": f"datasource:{_norm(label)}",
                    "summary": f"{ds.db_type} table {ds.table_name}.",
                    "kind": "database",
                },
            )
        )
        edges.append(
            _edge(
                f"se:ds:db:{ds.id}", hub_id, nid, _REL_DATA_SOURCE,
                f"{label} is a data source in this project.",
            )
        )
        for key in {_norm(ds.display_name), _norm(ds.table_name), _norm(ds.teiid_view_name)}:
            if key:
                ds_by_name[key] = nid

    # ── Saved queries (and their table lineage) ──────────────────────
    # SavedQuery has no tenant_id column -- project_id alone is safe here
    # because collect_structural_graph already verified the project itself
    # belongs to tenant_id above, and project ids are never reused across
    # tenants.
    queries = (
        await session.scalars(
            select(SavedQuery)
            .where(SavedQuery.project_id == project_id)
            .order_by(SavedQuery.id)
            .limit(_MAX_PER_KIND)
        )
    ).all()
    # (node_id, display name, normalized searchable text) per query/dashboard,
    # used to detect which KPIs a query/dashboard actually measures.
    query_haystacks: list[tuple[str, str, str]] = []
    dashboard_haystacks: list[tuple[str, str, str]] = []
    for q in queries:
        nid = f"s:query:{q.id}"
        query_haystacks.append((
            nid,
            q.name or f"query {q.id}",
            _haystack(
                q.name, q.description, q.sql_text,
                q.left_column, q.right_column,
                q.left_datasource, q.right_datasource,
            ),
        ))
        nodes.append(
            _node(
                nid,
                "saved_query",
                q.name or f"query {q.id}",
                source_type="saved_query",
                source_id=q.id,
                properties={
                    "graph_key": f"query:{q.id}",
                    "summary": (q.description or "")[:300],
                },
            )
        )
        edges.append(
            _edge(
                f"se:q:{q.id}", hub_id, nid, _REL_QUERY,
                f"{q.name} is a saved query in this project.",
            )
        )
        for raw in (q.left_datasource, q.right_datasource):
            key = _norm(raw)
            target = ds_by_name.get(key)
            if target:
                edges.append(
                    _edge(
                        f"se:qds:{q.id}:{target}", nid, target, _REL_QUERY_READS,
                        f"{q.name} reads from this data source.",
                    )
                )

    # ── Dashboards ───────────────────────────────────────────────────
    dashboards = (
        await session.scalars(
            select(Dashboard)
            .where(
                Dashboard.project_id == project_id,
                Dashboard.tenant_id == tenant_id,
            )
            .order_by(Dashboard.id)
            .limit(_MAX_PER_KIND)
        )
    ).all()
    for d in dashboards:
        nid = f"s:dashboard:{d.id}"
        dashboard_haystacks.append((
            nid,
            d.name or f"dashboard {d.id}",
            _haystack(d.name, d.description, d.config),
        ))
        nodes.append(
            _node(
                nid,
                "dashboard",
                d.name or f"dashboard {d.id}",
                source_type="dashboard",
                source_id=d.id,
                properties={
                    "graph_key": f"dashboard:{d.id}",
                    "summary": (d.description or "")[:300],
                },
            )
        )
        edges.append(
            _edge(
                f"se:dash:{d.id}", hub_id, nid, _REL_DASHBOARD,
                f"{d.name} is a dashboard in this project.",
            )
        )

    # ── Project documents (assets) ───────────────────────────────────
    assets = (
        await session.scalars(
            select(ProjectAsset)
            .where(
                ProjectAsset.project_id == project_id,
                ProjectAsset.tenant_id == tenant_id,
            )
            .order_by(ProjectAsset.id)
            .limit(_MAX_PER_KIND)
        )
    ).all()
    for a in assets:
        nid = f"s:asset:{a.id}"
        nodes.append(
            _node(
                nid,
                "document",
                a.title or a.filename or f"document {a.id}",
                source_type="project_asset",
                source_id=a.id,
                properties={
                    "summary": (a.ai_summary or a.description or "")[:300],
                },
            )
        )
        edges.append(
            _edge(
                f"se:doc:{a.id}", hub_id, nid, _REL_DOCUMENT,
                f"{a.title} is a document in this project.",
            )
        )

    # ── KPIs & Metrics (same source of truth as the View Family panel) ─
    # KPIs live in ``ai_project_graph_nodes`` (node_type='kpi'/'metric'),
    # connected to the documents that reference them via supports_kpi edges.
    # Surface them as a structural asset class so they always render in the
    # KPIs & Metrics group and recenter cleanly — never fabricated.
    kpi_nodes = (
        await session.scalars(
            select(AIProjectGraphNode)
            .where(
                AIProjectGraphNode.tenant_id == tenant_id,
                AIProjectGraphNode.project_id == project_id,
                AIProjectGraphNode.is_active.is_(True),
                AIProjectGraphNode.node_type.in_(("kpi", "metric")),
            )
            .order_by(AIProjectGraphNode.id)
            .limit(_MAX_PER_KIND)
        )
    ).all()
    if kpi_nodes:
        kpi_id_set = {k.id for k in kpi_nodes}
        # Map each KPI to the names of the documents/processes that reference it.
        kpi_sources: dict[int, list[str]] = {kid: [] for kid in kpi_id_set}
        kpi_edges = (
            await session.execute(
                select(
                    AIProjectGraphEdge.to_node_id,
                    AIProjectGraphNode.name,
                )
                .join(
                    AIProjectGraphNode,
                    AIProjectGraphNode.id == AIProjectGraphEdge.from_node_id,
                )
                .where(
                    AIProjectGraphEdge.tenant_id == tenant_id,
                    AIProjectGraphEdge.project_id == project_id,
                    AIProjectGraphEdge.is_active.is_(True),
                    AIProjectGraphEdge.to_node_id.in_(kpi_id_set),
                    AIProjectGraphEdge.relationship_type.in_(_KPI_EDGE_TYPES),
                    AIProjectGraphNode.is_active.is_(True),
                )
            )
        ).all()
        for kpi_id, src_name in kpi_edges:
            if src_name and src_name not in kpi_sources[kpi_id]:
                kpi_sources[kpi_id].append(src_name)
        for k in kpi_nodes:
            kp = k.properties if isinstance(k.properties, dict) else {}
            label = kp.get("display_name") or k.name or f"kpi {k.id}"
            nid = f"s:kpi:{k.id}"
            docs = kpi_sources.get(k.id, [])

            # Detect whether a saved query or dashboard actually depicts this
            # KPI (by name / description / SQL aliases / dashboard config). Only
            # then is the KPI "measured" and given a visible edge — recommended
            # KPIs stay edgeless so the canvas isn't flooded with document lines.
            phrases = _kpi_phrases(k.name, kp)
            measuring_queries = [
                (qid, qname) for qid, qname, hay in query_haystacks
                if phrases and _phrase_in(phrases, hay)
            ]
            measuring_dashboards = [
                (did, dname) for did, dname, hay in dashboard_haystacks
                if phrases and _phrase_in(phrases, hay)
            ]
            is_measured = bool(measuring_queries or measuring_dashboards)
            kpi_status = "measured" if is_measured else "recommended"

            if is_measured:
                measured_names = [n for _id, n in (*measuring_queries, *measuring_dashboards)]
                summary = f"KPI measured by {', '.join(measured_names[:3])}."
            elif docs:
                summary = f"KPI recommended by {', '.join(docs[:3])}."
            else:
                summary = "KPI recommended from project document analysis."

            nodes.append(
                _node(
                    nid,
                    "kpi",
                    label,
                    source_type="ai_graph_node",
                    source_id=k.id,
                    properties={
                        "graph_key": f"kpi:{_norm(k.name)}",
                        "kpi_key": k.name,
                        "kpiStatus": kpi_status,
                        "summary": summary,
                        "source_documents": docs,
                        "confidence": 0.9,
                    },
                )
            )

            if is_measured:
                # Visible measured relationships: query → KPI, dashboard → KPI.
                for qid, qname in measuring_queries:
                    edges.append(
                        _edge(
                            f"se:kpi:{k.id}:meas:{qid}", qid, nid,
                            _REL_QUERY_MEASURES,
                            f"{qname} measures {label}.",
                        )
                    )
                for did, dname in measuring_dashboards:
                    edges.append(
                        _edge(
                            f"se:kpi:{k.id}:viz:{did}", did, nid,
                            _REL_DASHBOARD_VISUALIZES,
                            f"{dname} visualizes {label}.",
                        )
                    )
            else:
                # Recommended KPI: keep it attached to the hub so it renders in
                # the KPIs & Metrics group, but with a hidden relationship type
                # (no visible line unless detailed/inferred mode is enabled).
                edges.append(
                    _edge(
                        f"se:kpi:{k.id}", hub_id, nid, _REL_RECOMMENDED_KPI,
                        summary, confidence=0.9,
                    )
                )

    # ── Authoritative reference library (project + company + industry) ─
    ref_docs = (
        await session.scalars(
            select(ReferenceDocument)
            .where(
                ReferenceDocument.status == "active",
                or_(
                    ReferenceDocument.tier == TIER_INDUSTRY,
                    and_(
                        ReferenceDocument.tier == TIER_COMPANY,
                        ReferenceDocument.tenant_id == tenant_id,
                    ),
                    and_(
                        ReferenceDocument.tier == TIER_PROJECT,
                        ReferenceDocument.project_id == project_id,
                    ),
                ),
            )
            .order_by(ReferenceDocument.updated_at.desc())
            .limit(_MAX_PER_KIND)
        )
    ).all()
    for r in ref_docs:
        nid = f"s:reference:{r.id}"
        rel = _REF_REL_BY_TIER.get(r.tier, "reference")
        nodes.append(
            _node(
                nid,
                "reference_document",
                r.title or f"reference {r.id}",
                source_type="reference_document",
                source_id=r.id,
                properties={
                    "graph_key": f"reference:{r.id}",
                    "summary": (r.ai_summary or "")[:300],
                    "tier": r.tier,
                    "issuing_body": r.issuing_body or "",
                },
            )
        )
        edges.append(
            _edge(
                f"se:ref:{r.id}", hub_id, nid, rel,
                f"{r.title} is an authoritative reference for this project.",
            )
        )

    return nodes, edges, hub_key
