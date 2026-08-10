"""Proactive AI grounding evidence orchestrator.

Merges seven retrieval signals for every conversational turn:
1. Vector similarity (via ai-server /ai/grounding/search)
2. Postgres full-text search over project document chunks and reference docs
3. Query-aware knowledge-graph node ranking
4. Governed KPI matching with rank+limit
5. Precomputed Business/Project Insight snapshots (with SQL and result previews)
6. Approved SMB/UNC network file connections
7. AI-profiled Reference Library documents

The resulting GroundingEvidence is passed to the SQL generator and prose
fallback so answers are grounded in retrieved evidence, not just the stored
KG snapshot or static prompt context.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.business_insight_result import BusinessInsightResult
from app.models.network_file_connection import NetworkFileConnection
from app.models.project import Project, ProjectMember
from app.models.project_intelligence_snapshot import ProjectIntelligenceSnapshot
from app.schemas.ai_grounding import (
    GroundingEvidence,
    GroundingInsightSnapshot,
    GroundingKGNode,
    GroundingKPI,
    GroundingNetworkConnection,
    GroundingPassage,
    GroundingReferenceDocument,
)
from app.services import ai_intelligence_client, insight_registry
from app.services.insight_card_match import _chart_signature, _data_shape_score, _extract_terms
from app.services.knowledge_graph_builder import _load_stored_graph, enrich_node
from app.services.reference_catalog_service import get_reference_kpis

logger = logging.getLogger(__name__)

_GROUNDING_TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)


def _question_tokens(question: str) -> set[str]:
    """Lowercase alphanumeric tokens from the user's question."""
    return {t.lower() for t in _GROUNDING_TOKEN_RE.findall(question or "") if len(t) > 2}


# Phrases to strip from reference-document search queries so natural-language
# wrappers ("list documents about ...", "tell me more about ...") do not AND
# filler words into the full-text search.
_REFERENCE_QUERY_FILLER_PATTERNS = [
    re.compile(r"^\s*(?:list|show|give me|what are|which)\s+(?:of\s+)?(?:the\s+)?(?:document|documents|doc|docs|policy|policies|procedure|procedures|guideline|guidelines|standard|standards)\s+(?:about|for|on|related to|in|in the|that)\s*", re.IGNORECASE),
    re.compile(r"^\s*(?:what does|what is in|what do|tell me more about|more about|details? (?:for|about|on)|describe|explain)\s+(?:the|a|an)?\s*", re.IGNORECASE),
    re.compile(r"^\s*(?:the|a|an)\s+(?:document|doc|policy|procedure|guideline|standard|framework)\s+(?:called|named|titled)\s*", re.IGNORECASE),
    re.compile(r"^\s*(?:reference\s+library|reference\s+libraries)\s+(?:say|says|say about|says about)?\s*", re.IGNORECASE),
]
_REFERENCE_QUERY_STOPWORDS = {
    "list", "show", "give", "what", "which", "are", "tell", "more", "about", "does", "is",
    "do", "in", "the", "a", "an", "and", "or", "of", "to", "for", "on", "from", "by",
    "with", "that", "this", "these", "those", "they", "them", "their", "there", "where",
    "when", "who", "why", "how", "can", "could", "would", "should", "will", "shall",
    "may", "might", "must", "have", "has", "had", "be", "been", "being", "am", "was",
    "were", "it", "its", "i", "you", "we", "he", "she", "me", "us", "him", "her", "my",
    "your", "our", "his", "say", "says", "said", "document", "documents", "doc", "docs",
}


def _clean_reference_search_query(question: str) -> list[str]:
    """Return the meaningful search tokens for a Reference Library query."""
    text = question or ""
    for pattern in _REFERENCE_QUERY_FILLER_PATTERNS:
        text = pattern.sub("", text)
    tokens = [t for t in _GROUNDING_TOKEN_RE.findall(text) if t.lower() not in _REFERENCE_QUERY_STOPWORDS and len(t) > 2]
    return tokens


def _token_overlap_score(texts: list[str], tokens: set[str]) -> float:
    """Simple overlap score: fraction of question tokens present in the texts."""
    if not tokens:
        return 0.0
    joined = " ".join(t.lower() for t in texts if t)
    joined_tokens = set(_GROUNDING_TOKEN_RE.findall(joined))
    hits = joined_tokens & tokens
    return len(hits) / len(tokens)


def _kpi_match_score(
    kpi: dict[str, Any],
    question_tokens: set[str],
    relevant_columns: list[str] | None,
) -> float:
    """Score a governed KPI against the question and relevant columns."""
    score = 0.0

    names = [kpi.get("kpi_key", ""), kpi.get("display_name", "")]
    if question_tokens:
        score += _token_overlap_score(names, question_tokens) * 2.0

    fields = [f.lower().replace("_", "") for f in (kpi.get("required_fields") or [])]
    tags = [t.lower() for t in (kpi.get("related_tags") or [])]
    if relevant_columns:
        col_set = {c.lower().replace("_", "") for c in relevant_columns}
        matches = sum(1 for f in fields if f in col_set) + sum(1 for t in tags if t in col_set)
        score += matches * 1.5

    if question_tokens:
        score += _token_overlap_score(fields + tags, question_tokens)

    return score


async def _lexical_project_chunks(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: int,
    question: str,
    limit: int = 10,
) -> list[GroundingPassage]:
    """Postgres FTS over project document chunks."""
    try:
        result = await session.execute(
            text(
                """
                SELECT
                    id,
                    document_id,
                    chunk_index,
                    chunk_text,
                    ts_rank(chunk_tsv, plainto_tsquery('english', :query)) AS rank
                FROM ai_document_chunks
                WHERE tenant_id = :tenant_id
                  AND project_id = :project_id
                  AND chunk_tsv @@ plainto_tsquery('english', :query)
                ORDER BY rank DESC
                LIMIT :limit
                """
            ),
            {
                "tenant_id": tenant_id,
                "project_id": project_id,
                "query": question,
                "limit": limit,
            },
        )
        rows = result.fetchall()
    except Exception as exc:
        logger.warning("Project chunk FTS failed: %s", exc)
        return []

    passages: list[GroundingPassage] = []
    for row in rows:
        passages.append(
            GroundingPassage(
                id=str(row.id) if row.id is not None else None,
                document_id=row.document_id,
                chunk_index=row.chunk_index,
                title="",
                text=row.chunk_text or "",
                source_type="project_asset",
                retrieval_score=float(row.rank or 0.0),
                retrieval_method="lexical",
            )
        )
    return passages


async def _lexical_reference_documents(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: int,
    question: str,
    limit: int = 8,
) -> list[GroundingPassage]:
    """Postgres FTS over reference documents (title + AI summary)."""
    search_tokens = _clean_reference_search_query(question)
    if not search_tokens:
        return []
    tsquery = " | ".join(search_tokens)
    try:
        result = await session.execute(
            text(
                """
                SELECT
                    id,
                    title,
                    ai_summary,
                    tier,
                    ts_rank(tsv, to_tsquery('english', :tsquery)) AS rank
                FROM reference_documents
                WHERE tsv @@ to_tsquery('english', :tsquery)
                  AND status = 'active'
                  AND (
                    tier = 'industry'
                    OR (tier = 'company' AND tenant_id = :tenant_id)
                    OR (tier = 'project' AND project_id = :project_id)
                  )
                ORDER BY rank DESC
                LIMIT :limit
                """
            ),
            {
                "tenant_id": tenant_id,
                "project_id": project_id,
                "tsquery": tsquery,
                "limit": limit,
            },
        )
        rows = result.fetchall()
    except Exception as exc:
        logger.warning("Reference document FTS failed: %s", exc)
        return []

    passages: list[GroundingPassage] = []
    for row in rows:
        passage_text = " ".join(filter(None, [row.title, row.ai_summary]))
        passages.append(
            GroundingPassage(
                id=str(row.id) if row.id is not None else None,
                document_id=row.id,
                title=row.title or "",
                text=passage_text,
                tier=row.tier or "",
                source_type="reference_library",
                retrieval_score=float(row.rank or 0.0),
                retrieval_method="lexical",
            )
        )
    return passages


async def _ranked_kg_nodes(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: int,
    question: str,
    limit: int = 8,
) -> list[GroundingKGNode]:
    """Load the project KG and re-rank nodes by question relevance."""
    try:
        raw_nodes, _raw_edges = await _load_stored_graph(
            session, tenant_id=tenant_id, project_id=project_id
        )
    except Exception as exc:
        logger.warning("KG load failed for grounding: %s", exc)
        return []

    if not raw_nodes:
        return []

    question_tokens = _question_tokens(question)
    scored: list[tuple[float, GroundingKGNode]] = []
    for n in raw_nodes:
        try:
            node = enrich_node(n)
        except Exception:
            continue
        label = str(node.get("label") or "")
        summary = str(node.get("summary") or node.get("businessValue") or "")
        node_type = str(node.get("type") or "")
        confidence = float(node.get("confidence") or 0.0)

        relevance = _token_overlap_score([label, summary], question_tokens)
        # Weight labels heavily; bump structural node types.
        score = relevance * 2.0
        if confidence:
            score += confidence * 0.3
        if node_type in {"kpi", "metric", "risk", "opportunity", "gap", "warning"}:
            score += 0.1

        scored.append(
            (
                score,
                GroundingKGNode(
                    id=node.get("id"),
                    node_type=node_type,
                    title=label,
                    summary=(summary[:400] if summary else ""),
                    confidence=confidence,
                    relevance_score=relevance,
                ),
            )
        )

    scored.sort(key=lambda x: x[0], reverse=True)
    return [node for _score, node in scored[:limit]]


async def _ranked_kpis(
    session: AsyncSession,
    *,
    tenant_id: int,
    question: str,
    relevant_columns: list[str] | None,
    limit: int = 10,
) -> list[GroundingKPI]:
    """Return governed KPIs ranked by question/column relevance."""
    try:
        kpis = await get_reference_kpis(session, tenant_id)
    except Exception as exc:
        logger.warning("KPI retrieval failed: %s", exc)
        return []

    if not kpis:
        return []

    question_tokens = _question_tokens(question)
    scored = [
        (
            _kpi_match_score(kpi, question_tokens, relevant_columns),
            GroundingKPI(
                kpi_key=kpi.get("kpi_key", ""),
                display_name=kpi.get("display_name", ""),
                business_domain=kpi.get("business_domain"),
                required_fields=kpi.get("required_fields") or [],
                related_tags=kpi.get("related_tags") or [],
            ),
        )
        for kpi in kpis
    ]
    scored.sort(key=lambda x: x[0], reverse=True)

    # Keep a minimum set when nothing strongly matches, but prefer ranked top-N.
    filtered = [(s, k) for s, k in scored if s > 0]
    if len(filtered) < 3:
        filtered = scored[:limit]
    return [kpi for _score, kpi in filtered[:limit]]


async def _authorized_project_ids(
    session: AsyncSession,
    tenant_id: int,
    user_id: int,
) -> list[int]:
    """All project IDs the user can access within this tenant."""
    try:
        member_sub = select(ProjectMember.project_id).where(
            ProjectMember.user_id == user_id,
            ProjectMember.is_active.is_(True),
        )
        rows = (
            await session.scalars(
                select(Project.id).where(
                    Project.tenant_id == tenant_id,
                    or_(
                        Project.owner_id == user_id,
                        Project.id.in_(member_sub),
                    ),
                )
            )
        ).all()
        return list(rows)
    except Exception as exc:
        logger.warning("Could not resolve authorized projects: %s", exc)
        return []


async def _project_names(
    session: AsyncSession,
    project_ids: list[int],
) -> dict[int, str]:
    """Map project IDs to names."""
    if not project_ids:
        return {}
    try:
        rows = (
            await session.execute(
                select(Project.id, Project.name).where(Project.id.in_(project_ids))
            )
        ).all()
        return {row[0]: row[1] for row in rows}
    except Exception as exc:
        logger.warning("Could not load project names: %s", exc)
        return {}


def _score_insight_card(
    card: dict[str, Any],
    question: str,
    q_terms: set[str],
) -> float:
    """Score an insight card by data shape + title/summary token overlap."""
    score = _data_shape_score(question, card)
    title = str(card.get("title") or "")
    summary = str(card.get("summary") or "")
    text_terms = _extract_terms(title + " " + summary)
    score += len(q_terms & text_terms) * 0.5
    return score


def _grounding_snapshot_from_card(
    card: dict[str, Any],
    project_id: int,
    project_name: str,
    score: float,
) -> GroundingInsightSnapshot:
    """Convert a normalized insight card into a grounding snapshot."""
    chart_val = card.get("chart")
    chart: dict[str, Any] = chart_val if isinstance(chart_val, dict) else {}
    ctype = chart.get("type") or card.get("chartType") or "chart"

    _, series_str, trend_str = _chart_signature(card)
    series = [s.strip() for s in series_str.split(",") if s.strip()]

    result_val = card.get("result")
    result: dict[str, Any] = result_val if isinstance(result_val, dict) else {}
    rows_val = result.get("rows")
    rows: list[Any] = rows_val if isinstance(rows_val, list) else []
    preview_lines: list[str] = []
    for row in rows[:5]:
        if isinstance(row, dict):
            preview_lines.append(
                ", ".join(f"{k}={v}" for k, v in row.items())
            )
        else:
            preview_lines.append(str(row))
    result_preview = "\n".join(preview_lines)[:1200]

    sql = str(card.get("sql") or "")
    if not sql:
        sources = card.get("sources")
        if isinstance(sources, dict):
            sql = str(sources.get("sql") or "")

    card_type = (
        card.get("type")
        or card.get("insightType")
        or card.get("cardType")
        or card.get("category")
        or ""
    )

    return GroundingInsightSnapshot(
        insight_id=str(card.get("insightId") or card.get("id") or ""),
        project_id=project_id,
        project_name=project_name,
        title=str(card.get("title") or ""),
        summary=str(card.get("summary") or ""),
        card_type=str(card_type),
        sql=sql[:2000],
        result_preview=result_preview,
        chart_type=str(ctype),
        series=series,
        trend=trend_str,
        retrieval_score=round(float(score), 3),
    )


async def _insight_snapshots_for_question(
    session: AsyncSession,
    *,
    tenant_id: int,
    user_id: int,
    project_id: int,
    question: str,
    limit: int = 8,
) -> list[GroundingInsightSnapshot]:
    """Load relevant Business + Project Insight snapshot cards for grounding.

    Cards are scored by the question's data shape and token overlap, then ranked.
    The result is scoped to all projects the user can access so cross-project
    insight context is available to the LLM (it still only generates SQL against
    the tables the generator allows for the active project).
    """
    project_ids = await _authorized_project_ids(session, tenant_id, user_id)
    if project_id and project_id not in project_ids:
        project_ids.append(project_id)
    project_names = await _project_names(session, project_ids)
    q_terms = _extract_terms(question)

    pairs: list[tuple[float, int, dict[str, Any]]] = []
    seen_ids: set[str] = set()

    try:
        bir_rows = (
            (
                await session.execute(
                    select(BusinessInsightResult).where(
                        BusinessInsightResult.tenant_id == tenant_id,
                        BusinessInsightResult.project_id.in_(project_ids),
                    )
                )
            )
            .scalars()
            .all()
        )
    except Exception as exc:
        logger.warning("Business insight result lookup failed: %s", exc)
        bir_rows = []

    for row in bir_rows:
        for card in (row.payload or {}).get("insights", []):
            if not isinstance(card, dict) or not card.get("title"):
                continue
            insight_id = str(card.get("insightId") or card.get("id") or "")
            if insight_id and insight_id in seen_ids:
                continue
            if insight_id:
                seen_ids.add(insight_id)
            card_copy = dict(card)
            card_copy["project_id"] = row.project_id
            score = _score_insight_card(card_copy, question, q_terms)
            pairs.append((score, row.project_id, card_copy))

    try:
        pis_rows = (
            (
                await session.execute(
                    select(ProjectIntelligenceSnapshot).where(
                        ProjectIntelligenceSnapshot.tenant_id == tenant_id,
                        ProjectIntelligenceSnapshot.user_id == user_id,
                        ProjectIntelligenceSnapshot.project_id.in_(project_ids),
                        ProjectIntelligenceSnapshot.suite == "project_insight",
                    )
                )
            )
            .scalars()
            .all()
        )
    except Exception as exc:
        logger.warning("Project intelligence snapshot lookup failed: %s", exc)
        pis_rows = []

    for snap in pis_rows:
        payload = snap.payload or {}
        for section in ("risks", "trends", "opportunities", "analysis"):
            for card in payload.get(section, []):
                if not isinstance(card, dict) or not card.get("title"):
                    continue
                insight_id = str(card.get("insightId") or card.get("id") or "")
                if insight_id and insight_id in seen_ids:
                    continue
                if insight_id:
                    seen_ids.add(insight_id)
                normalized = insight_registry._normalize_project_insight_card(dict(card))
                normalized["project_id"] = snap.project_id
                score = _score_insight_card(normalized, question, q_terms)
                pairs.append((score, snap.project_id, normalized))

    pairs.sort(key=lambda x: x[0], reverse=True)
    return [
        _grounding_snapshot_from_card(card, pid, project_names.get(pid, ""), score)
        for score, pid, card in pairs[:limit]
    ]


async def _network_connections_for_project(
    session: AsyncSession,
    *,
    tenant_id: int,
    question: str,
    limit: int = 10,
) -> list[GroundingNetworkConnection]:
    """Load enabled network file connections for the tenant, ranked by question."""
    try:
        rows = (
            await session.scalars(
                select(NetworkFileConnection).where(
                    NetworkFileConnection.tenant_id == tenant_id,
                    NetworkFileConnection.archived.is_(False),
                    NetworkFileConnection.enabled.is_(True),
                )
            )
        ).all()
    except Exception as exc:
        logger.warning("Network connection lookup failed: %s", exc)
        return []

    q_terms = _extract_terms(question)
    scored: list[tuple[float, NetworkFileConnection]] = []
    for conn in rows:
        text = f"{conn.name} {conn.share_name} {conn.approved_root_path}"
        name_terms = _extract_terms(text)
        score = len(q_terms & name_terms) if q_terms else 0.0
        scored.append((score, conn))

    scored.sort(key=lambda x: x[0], reverse=True)
    result: list[GroundingNetworkConnection] = []
    for _score, conn in scored[:limit]:
        result.append(
            GroundingNetworkConnection(
                id=conn.id,
                name=conn.name,
                protocol=conn.protocol,
                host=conn.host,
                share_name=conn.share_name,
                approved_root_path=conn.approved_root_path,
                domain=conn.domain,
                enabled=conn.enabled,
            )
        )
    return result


async def _reference_documents_for_question(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: int,
    question: str,
    limit: int = 6,
) -> list[GroundingReferenceDocument]:
    """Rank Reference Library documents by full-text relevance to the question."""
    search_tokens = _clean_reference_search_query(question)
    if not search_tokens:
        return []
    tsquery = " | ".join(search_tokens)
    try:
        result = await session.execute(
            text(
                """
                SELECT
                    id,
                    title,
                    ai_summary,
                    domain_tag,
                    source_url,
                    tier,
                    ts_rank(tsv, to_tsquery('english', :tsquery)) AS rank
                FROM reference_documents
                WHERE tsv @@ to_tsquery('english', :tsquery)
                  AND status = 'active'
                  AND (
                    tier = 'industry'
                    OR (tier = 'company' AND tenant_id = :tenant_id)
                    OR (tier = 'project' AND project_id = :project_id)
                  )
                ORDER BY rank DESC
                LIMIT :limit
                """
            ),
            {
                "tenant_id": tenant_id,
                "project_id": project_id,
                "tsquery": tsquery,
                "limit": limit,
            },
        )
        rows = result.fetchall()
    except Exception as exc:
        logger.warning("Reference document FTS failed: %s", exc)
        return []

    return [
        GroundingReferenceDocument(
            id=row.id,
            title=row.title or "",
            ai_summary=row.ai_summary or "",
            tier=row.tier or "",
            domain_tag=row.domain_tag,
            source_url=row.source_url,
            retrieval_score=float(row.rank or 0.0),
        )
        for row in rows
    ]


def _merge_passages(
    vector: list[GroundingPassage],
    lexical: list[GroundingPassage],
    *,
    max_passages: int = 12,
) -> list[GroundingPassage]:
    """Deduplicate and merge vector + lexical passages, capping total budget."""
    by_key: dict[tuple[int | None, int | None, str], GroundingPassage] = {}

    # Normalize vector scores to [0, 1] for combination.
    max_vec = max((p.retrieval_score for p in vector), default=1.0) or 1.0
    for p in vector:
        key = (p.document_id, p.chunk_index, p.source_type)
        normalized = GroundingPassage.model_validate(p)
        normalized.retrieval_score = p.retrieval_score / max_vec
        by_key[key] = normalized

    max_lex = max((p.retrieval_score for p in lexical), default=1.0) or 1.0
    for p in lexical:
        key = (p.document_id, p.chunk_index, p.source_type)
        normalized = GroundingPassage.model_validate(p)
        normalized.retrieval_score = p.retrieval_score / max_lex
        if key in by_key:
            existing = by_key[key]
            # Boost score when both retrieval methods agree.
            existing.retrieval_score = min(1.0, existing.retrieval_score + normalized.retrieval_score * 0.5)
            existing.retrieval_method = "hybrid"
        else:
            by_key[key] = normalized

    merged = sorted(by_key.values(), key=lambda p: p.retrieval_score, reverse=True)
    return merged[:max_passages]


def _format_passage_for_ai(p: GroundingPassage) -> GroundingPassage:
    """Keep passages bounded for prompt context windows."""
    text = (p.text or "")[:1200]
    return GroundingPassage.model_validate({**p.model_dump(), "text": text})


async def gather_grounding_evidence(
    session: AsyncSession,
    *,
    tenant_id: int,
    user_id: int,
    project_id: int,
    question: str,
    relevant_columns: list[str] | None = None,
    scope: str = "project",
) -> GroundingEvidence | None:
    """Retrieve and merge all authorized grounding evidence for a question.

    Returns ``None`` only when the AI service is disabled and no local signals
    can be collected; callers should proceed with the existing non-grounded path.
    """
    if not question or not question.strip():
        return None

    evidence = GroundingEvidence(question=question)

    # 1. Vector search (remote AI server).
    vector_passages: list[GroundingPassage] = []
    if ai_intelligence_client.is_enabled():
        try:
            search_result = await ai_intelligence_client.search_grounding_vectors(
                tenant_id=tenant_id,
                user_id=user_id,
                project_id=project_id,
                question=question,
                scope=scope,
                limit=12,
            )
            if search_result:
                for field, source_type in (
                    ("project_passages", "project_asset"),
                    ("reference_passages", "reference_library"),
                ):
                    for p in (search_result.get(field) or []):
                        # ai-server returns GroundingPassage-compatible dicts.
                        passage = GroundingPassage.model_validate(p)
                        if source_type and not passage.source_type:
                            passage.source_type = source_type
                        vector_passages.append(passage)
        except Exception as exc:
            logger.warning("Vector grounding search failed: %s", exc)

    # 2. Lexical search (Postgres FTS).
    lexical_project = await _lexical_project_chunks(
        session, tenant_id=tenant_id, project_id=project_id, question=question, limit=10
    )
    lexical_reference = await _lexical_reference_documents(
        session, tenant_id=tenant_id, project_id=project_id, question=question, limit=8
    )

    evidence.passages = _merge_passages(
        vector_passages,
        lexical_project + lexical_reference,
        max_passages=12,
    )
    evidence.passages = [_format_passage_for_ai(p) for p in evidence.passages]

    # 3. Query-aware KG ranking.
    evidence.kg_nodes = await _ranked_kg_nodes(
        session, tenant_id=tenant_id, project_id=project_id, question=question, limit=8
    )

    # 4. Governed KPI matching with rank+limit.
    evidence.kpis = await _ranked_kpis(
        session, tenant_id=tenant_id, question=question, relevant_columns=relevant_columns, limit=10
    )

    # 5. Precomputed insight snapshots (Business + Project Insight cards with SQL).
    evidence.insight_snapshots = await _insight_snapshots_for_question(
        session,
        tenant_id=tenant_id,
        user_id=user_id,
        project_id=project_id,
        question=question,
        limit=8,
    )

    # 6. Approved network file connections.
    evidence.network_connections = await _network_connections_for_project(
        session,
        tenant_id=tenant_id,
        question=question,
        limit=10,
    )

    # 7. AI-profiled Reference Library documents.
    evidence.reference_documents = await _reference_documents_for_question(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        question=question,
        limit=6,
    )

    evidence.retrieved_at = datetime.now(UTC)
    logger.info(
        "Gathered grounding evidence tenant=%d project=%d: %d passages, %d kg_nodes, %d kpis, "
        "%d insight_snapshots, %d network_connections, %d reference_documents",
        tenant_id, project_id, len(evidence.passages), len(evidence.kg_nodes), len(evidence.kpis),
        len(evidence.insight_snapshots), len(evidence.network_connections), len(evidence.reference_documents),
    )
    return evidence
