
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import ColumnElement, bindparam, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_project_graph import AIProjectGraphEdge, AIProjectGraphNode
from app.models.dashboard import Dashboard
from app.models.database_data_source import DatabaseDataSource
from app.models.file_source_meta import FileSourceMeta
from app.models.project import Project
from app.models.project_asset import ProjectAsset
from app.models.reference_library import ReferenceDocument
from app.models.saved_query import SavedQuery
from app.services.sql_lineage import extract_referenced_tables

from .graph_primitives import (
    _KPI_EDGE_TYPES,
    _MAX_PER_KIND,
    _REF_REL_BY_TIER,
    _REL_DASHBOARD,
    _REL_DASHBOARD_USES_QUERY,
    _REL_DASHBOARD_VISUALIZES,
    _REL_DATA_SOURCE,
    _REL_DOCUMENT,
    _REL_HAS_PASSAGE,
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
    active_reference_document_conditions,
)

logger = logging.getLogger(__name__)

# KG-12: a project's *graph* must index every matching row, not just the
# first `_MAX_PER_KIND` -- that cap stays as the per-round-trip batch size
# (so a single query is never unbounded), but collection now keeps paging
# until a source kind is exhausted. `_MAX_TOTAL_PER_KIND` is a generous
# safety ceiling against a genuinely pathological project, not a
# display-oriented limit -- canvas/neighborhood limits are a separate,
# already-existing concern (MAX_PRECACHE_CENTERS, node-centric neighborhood
# sizing) applied at render time, not here.
_MAX_TOTAL_PER_KIND = 5000


async def _fetch_all_in_batches(
    session: AsyncSession,
    model: type[Any],
    *conditions: ColumnElement[bool],
    batch_size: int = _MAX_PER_KIND,
    max_total: int = _MAX_TOTAL_PER_KIND,
) -> list[Any]:
    """Fetch every row matching ``conditions``, keyset-paginated by ``model.id``.

    Replaces a single ``.limit(batch_size)`` query (which silently and
    permanently drops everything past the first batch) with a loop that pages
    until the source kind is exhausted or ``max_total`` is hit.
    """
    rows: list[Any] = []
    last_id = 0
    while len(rows) < max_total:
        remaining = max_total - len(rows)
        batch = (
            await session.scalars(
                select(model)
                .where(*conditions, model.id > last_id)
                .order_by(model.id)
                .limit(min(batch_size, remaining))
            )
        ).all()
        if not batch:
            break
        rows.extend(batch)
        last_id = batch[-1].id
        if len(batch) < batch_size:
            break
    return rows


# KG-16: cap on how many chunk/passage nodes a single document contributes,
# so one very long document doesn't dwarf the rest of the graph.
_MAX_PASSAGES_PER_DOCUMENT = 20


async def _fetch_document_passages(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: int,
    asset_ids: list[int],
) -> dict[int, list[Any]]:
    """KG-16: chunk-level passages for project-asset documents, keyed by
    ``ProjectAsset.id``, each capped at ``_MAX_PASSAGES_PER_DOCUMENT``.

    ``ai_document_chunks``/``ai_documents`` are plain tables (no ORM model --
    ``app.services.ai_grounding`` already queries them the same way for
    retrieval), populated only once the asset has actually been chunked by
    the document-processing pipeline. Reference-library documents have no
    equivalent persistent chunk store today, so passage-level evidence is
    deliberately scoped to project assets here.
    """
    if not asset_ids:
        return {}
    try:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT ad.source_id AS asset_id, adc.id, adc.chunk_index, adc.chunk_text
                    FROM ai_document_chunks adc
                    JOIN ai_documents ad ON ad.id = adc.document_id
                    WHERE ad.source_type = 'project_asset'
                      AND ad.source_id IN :asset_ids
                      AND adc.tenant_id = :tenant_id
                      AND adc.project_id = :project_id
                    ORDER BY ad.source_id, adc.chunk_index
                    """
                ).bindparams(bindparam("asset_ids", expanding=True)),
                {"asset_ids": asset_ids, "tenant_id": tenant_id, "project_id": project_id},
            )
        ).all()
    except Exception:
        logger.debug("KG-16: could not load document chunks for passage evidence", exc_info=True)
        return {}

    by_asset: dict[int, list[Any]] = {}
    for row in rows:
        bucket = by_asset.setdefault(row.asset_id, [])
        if len(bucket) < _MAX_PASSAGES_PER_DOCUMENT:
            bucket.append(row)
    return by_asset


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
    file_sources = await _fetch_all_in_batches(
        session, FileSourceMeta,
        FileSourceMeta.project_id == project_id,
        FileSourceMeta.tenant_id == tenant_id,
        FileSourceMeta.archived.is_(False),
    )
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
    db_sources = await _fetch_all_in_batches(
        session, DatabaseDataSource,
        DatabaseDataSource.project_id == project_id,
        DatabaseDataSource.tenant_id == tenant_id,
        DatabaseDataSource.archived.is_(False),
    )
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
    # KG-09: an archived query is a soft-delete (DELETE requires archiving
    # first, per app/routes/projects_queries.py) -- it must stop appearing
    # in the graph the same way archived FileSourceMeta/DatabaseDataSource
    # rows already do below, not linger until the row is hard-deleted.
    queries = await _fetch_all_in_batches(
        session, SavedQuery,
        SavedQuery.project_id == project_id,
        SavedQuery.is_archived.is_(False),
    )
    # (node_id, display name, normalized searchable text) per query/dashboard,
    # used to detect which KPIs a query/dashboard actually measures.
    query_haystacks: list[tuple[str, str, str]] = []
    dashboard_haystacks: list[tuple[str, str, str]] = []
    # KG-18: SavedQuery.id -> its node id, so a dashboard's own stored widget
    # bindings can be resolved to a direct edge instead of relying only on
    # text/phrase matching.
    query_nid_by_id: dict[int, str] = {}
    for q in queries:
        nid = f"s:query:{q.id}"
        query_nid_by_id[q.id] = nid
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
        reads_from_targets: set[str] = set()
        for raw in (q.left_datasource, q.right_datasource):
            key = _norm(raw)
            target = ds_by_name.get(key)
            if target:
                reads_from_targets.add(target)
                edges.append(
                    _edge(
                        f"se:qds:{q.id}:{target}", nid, target, _REL_QUERY_READS,
                        f"{q.name} reads from this data source.",
                    )
                )
        # KG-17: parsed SQL lineage catches every table the query actually
        # references, not only the join-builder's two configured
        # datasources -- this is the *only* lineage source for
        # hand-written/AI-generated queries, which never populate
        # left_datasource/right_datasource at all.
        for table_name in extract_referenced_tables(q.sql_text):
            target = ds_by_name.get(_norm(table_name))
            if target is None or target in reads_from_targets:
                continue
            reads_from_targets.add(target)
            edges.append(
                _edge(
                    f"se:qsql:{q.id}:{target}", nid, target, _REL_QUERY_READS,
                    f"{q.name} reads from this data source (parsed from its SQL).",
                )
            )

    # ── Dashboards ───────────────────────────────────────────────────
    dashboards = await _fetch_all_in_batches(
        session, Dashboard,
        Dashboard.project_id == project_id,
        Dashboard.tenant_id == tenant_id,
    )
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
        # KG-18: resolve each widget's own stored ``dataSource.queryId``
        # binding to a direct edge, instead of relying solely on KPI phrase
        # matching (which stays in place below for KPI "visualizes" edges,
        # since no equivalent stored KPI id exists in the widget shape).
        config = d.config if isinstance(d.config, dict) else {}
        widgets = config.get("widgets")
        seen_query_nids: set[str] = set()
        if isinstance(widgets, list):
            for widget in widgets:
                if not isinstance(widget, dict):
                    continue
                data_source = widget.get("dataSource")
                if not isinstance(data_source, dict):
                    continue
                query_id = data_source.get("queryId")
                if not isinstance(query_id, int):
                    continue
                query_nid = query_nid_by_id.get(query_id)
                if query_nid is None or query_nid in seen_query_nids:
                    continue
                seen_query_nids.add(query_nid)
                edges.append(
                    _edge(
                        f"se:dashq:{d.id}:{query_id}", nid, query_nid,
                        _REL_DASHBOARD_USES_QUERY,
                        f"{d.name} uses a widget bound to this saved query.",
                    )
                )

    # ── Project documents (assets) ───────────────────────────────────
    assets = await _fetch_all_in_batches(
        session, ProjectAsset,
        ProjectAsset.project_id == project_id,
        ProjectAsset.tenant_id == tenant_id,
    )
    passages_by_asset = await _fetch_document_passages(
        session, tenant_id=tenant_id, project_id=project_id,
        asset_ids=[a.id for a in assets],
    )
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
        # KG-16: chunk/passage-level evidence, so a claim can be traced to
        # the specific passage that supports it instead of only the
        # document as a whole.
        for chunk in passages_by_asset.get(a.id, []):
            passage_nid = f"s:passage:{chunk.id}"
            nodes.append(
                _node(
                    passage_nid,
                    "document_passage",
                    f"{a.title or a.filename or 'Document'} — passage {chunk.chunk_index + 1}",
                    source_type="ai_document_chunk",
                    source_id=chunk.id,
                    properties={
                        "chunk_index": chunk.chunk_index,
                        "summary": (chunk.chunk_text or "")[:300],
                        # KG-08: a passage is exactly its parent document's
                        # evidence, so visibility filtering needs a way back
                        # to the ProjectAsset id without a second query --
                        # it can never be visible to someone the parent
                        # document itself is hidden from.
                        "asset_id": a.id,
                    },
                )
            )
            edges.append(
                _edge(
                    f"se:passage:{chunk.id}", nid, passage_nid, _REL_HAS_PASSAGE,
                    f"Passage {chunk.chunk_index + 1} of {a.title or a.filename or 'this document'}.",
                )
            )

    # ── KPIs & Metrics (same source of truth as the View Family panel) ─
    # KPIs live in ``ai_project_graph_nodes`` (node_type='kpi'/'metric'),
    # connected to the documents that reference them via supports_kpi edges.
    # Surface them as a structural asset class so they always render in the
    # KPIs & Metrics group and recenter cleanly — never fabricated.
    kpi_nodes = await _fetch_all_in_batches(
        session, AIProjectGraphNode,
        AIProjectGraphNode.tenant_id == tenant_id,
        AIProjectGraphNode.project_id == project_id,
        AIProjectGraphNode.is_active.is_(True),
        AIProjectGraphNode.node_type.in_(("kpi", "metric")),
    )
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
    ref_docs = await _fetch_all_in_batches(
        session, ReferenceDocument,
        *active_reference_document_conditions(tenant_id, project_id),
    )
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
