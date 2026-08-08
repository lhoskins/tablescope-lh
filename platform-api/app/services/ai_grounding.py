"""Proactive AI grounding evidence orchestrator.

Merges four retrieval signals for every conversational turn:
1. Vector similarity (via ai-server /ai/grounding/search)
2. Postgres full-text search over project document chunks and reference docs
3. Query-aware knowledge-graph node ranking
4. Governed KPI matching with rank+limit

The resulting GroundingEvidence is passed to the SQL generator and prose
fallback so answers are grounded in retrieved evidence, not just the stored
KG snapshot or static prompt context.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.ai_grounding import GroundingEvidence, GroundingKGNode, GroundingKPI, GroundingPassage
from app.services import ai_intelligence_client
from app.services.knowledge_graph_builder import _load_stored_graph, enrich_node
from app.services.reference_catalog_service import get_reference_kpis

logger = logging.getLogger(__name__)

_GROUNDING_TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)


def _question_tokens(question: str) -> set[str]:
    """Lowercase alphanumeric tokens from the user's question."""
    return {t.lower() for t in _GROUNDING_TOKEN_RE.findall(question or "") if len(t) > 2}


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
    try:
        result = await session.execute(
            text(
                """
                SELECT
                    id,
                    title,
                    ai_summary,
                    tier,
                    ts_rank(tsv, plainto_tsquery('english', :query)) AS rank
                FROM reference_documents
                WHERE tsv @@ plainto_tsquery('english', :query)
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
                "query": question,
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

    evidence.retrieved_at = datetime.now(UTC)
    logger.info(
        "Gathered grounding evidence tenant=%d project=%d: %d passages, %d kg_nodes, %d kpis",
        tenant_id, project_id, len(evidence.passages), len(evidence.kg_nodes), len(evidence.kpis),
    )
    return evidence
