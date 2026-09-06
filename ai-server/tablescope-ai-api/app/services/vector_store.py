"""Qdrant vector store with tenant-isolated collections.

Collection naming:  tablescope_tenant_{tenant_id}
Every search enforces tenant_id + project_id payload filters.
Cross-tenant queries are structurally impossible (different collections).
"""

import logging
import uuid
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import UnexpectedResponse
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from app.core.config import settings
from app.models.schemas import VectorAccessClaims
from app.services import llm_client


class VectorStoreError(Exception):
    """A vector-store operation could not be completed safely."""

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 768  # nomic-embed-text dimension

# Reference Library docs are governed, cross-project knowledge (industry /
# company / project tier), so they live in one shared collection rather than a
# per-tenant one. Tier-based payload filters enforce who may retrieve each doc.
REFERENCE_COLLECTION = "tablescope_reference_library"


def _collection_name(tenant_id: int) -> str:
    """Derive collection name server-side from authenticated tenant.
    Never accept collection names from user input or LLM output."""
    return f"tablescope_tenant_{tenant_id}"


def get_client() -> QdrantClient:
    return QdrantClient(url=settings.qdrant_url)


async def ensure_collection(tenant_id: int) -> None:
    """Create tenant collection if it doesn't exist."""
    client = get_client()
    name = _collection_name(tenant_id)
    collections = [c.name for c in client.get_collections().collections]
    if name not in collections:
        client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
        )
        logger.info("Created Qdrant collection: %s", name)


async def upsert_vectors(
    tenant_id: int,
    vectors: list[list[float]],
    payloads: list[dict[str, Any]],
) -> list[str]:
    """Upsert vectors into tenant-specific collection. Returns point IDs."""
    client = get_client()
    name = _collection_name(tenant_id)
    await ensure_collection(tenant_id)

    point_ids = []
    points = []
    for vec, payload in zip(vectors, payloads):
        if payload.get("tenant_id") != tenant_id:
            raise VectorStoreError("Vector payload tenant does not match target collection")
        if payload.get("visibility") not in {"shared_project", "private"}:
            raise VectorStoreError("Vector payload has an unsupported document visibility")
        if payload.get("visibility") == "private" and not payload.get("owner_user_id"):
            raise VectorStoreError("Private vector payload requires owner_user_id")
        pid = str(uuid.uuid4())
        point_ids.append(pid)
        payload["vector_id"] = pid
        points.append(PointStruct(id=pid, vector=vec, payload=payload))

    client.upsert(collection_name=name, points=points)
    logger.info("Upserted %d vectors into %s", len(points), name)
    return point_ids


async def search_vectors(
    access: VectorAccessClaims,
    query_vector: list[float],
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Search vectors using only platform-minted authorization claims.

    Every result must be either shared with active members of this project, or
    private content owned by this exact principal. Missing/unknown visibility
    values match neither branch and are therefore denied. Legacy private
    visibility labels remain owner-gated during re-indexing.
    """
    client = get_client()
    name = _collection_name(access.tenant_id)

    must_conditions: list[Any] = [
        FieldCondition(key="tenant_id", match=MatchValue(value=access.tenant_id)),
        FieldCondition(key="project_id", match=MatchValue(value=access.project_id)),
    ]
    visibility_branches: list[Any] = []
    if access.can_read_shared_documents:
        visibility_branches.append(
            FieldCondition(key="visibility", match=MatchValue(value="shared_project"))
        )
    for private_visibility in ("private", "private_project", "personal"):
        visibility_branches.append(
            Filter(
                must=[
                    FieldCondition(
                        key="visibility", match=MatchValue(value=private_visibility)
                    ),
                    FieldCondition(
                        key="owner_user_id",
                        match=MatchValue(value=access.private_document_owner_user_id),
                    ),
                ]
            )
        )
    if not visibility_branches:
        raise VectorStoreError("Vector access claims authorize no document visibility")
    must_conditions.append(Filter(should=visibility_branches))

    results = client.query_points(
        collection_name=name,
        query=query_vector,
        query_filter=Filter(must=must_conditions),
        limit=limit,
        with_payload=True,
    ).points

    return [
        {"id": r.id, "score": r.score, "payload": r.payload}
        for r in results
    ]


async def delete_tenant_collection(tenant_id: int) -> None:
    """Drop entire tenant collection — used during tenant deletion."""
    client = get_client()
    name = _collection_name(tenant_id)
    try:
        client.delete_collection(collection_name=name)
        logger.info("Deleted Qdrant collection: %s", name)
    except Exception:
        logger.warning("Collection %s not found for deletion", name)


async def delete_project_vectors(tenant_id: int, project_id: int) -> None:
    """Delete all vectors for a specific project within a tenant."""
    client = get_client()
    name = _collection_name(tenant_id)
    client.delete(
        collection_name=name,
        points_selector=Filter(
            must=[
                FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id)),
                FieldCondition(key="project_id", match=MatchValue(value=project_id)),
            ]
        ),
    )
    logger.info("Deleted project %d vectors from %s", project_id, name)


async def reindex_collection(
    *,
    source: str,
    target: str,
    embedding_model: str,
    embedding_dim: int,
    recall_query_limit: int = 10,
) -> dict[str, Any]:
    """Create a new collection, re-embed every source vector, and compute recall.

    The source collection is read but never modified. The target collection is
    created with the requested dimension, then source payloads are re-embedded
    using the requested Ollama model and upserted. Recall is estimated by using
    a sample of chunk_texts from the source as queries and comparing the top-K
    overlap between source and target search results.

    Returns a dict with points_total, points_indexed, recall_score, and status.
    """
    client = get_client()

    try:
        collections = {c.name for c in client.get_collections().collections}
    except Exception as exc:
        raise VectorStoreError(f"Could not list Qdrant collections: {exc}") from exc

    if source not in collections:
        raise VectorStoreError(f"Source collection {source} does not exist")

    if target in collections:
        raise VectorStoreError(f"Target collection {target} already exists")

    try:
        client.create_collection(
            collection_name=target,
            vectors_config=VectorParams(size=embedding_dim, distance=Distance.COSINE),
        )
    except UnexpectedResponse as exc:
        raise VectorStoreError(f"Could not create target collection {target}: {exc}") from exc

    batch_size = 64
    offset = None
    points_total = 0
    points_indexed = 0
    query_texts: list[str] = []

    while True:
        try:
            batch, offset = client.scroll(
                collection_name=source,
                limit=batch_size,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
        except Exception as exc:
            raise VectorStoreError(f"Failed to scroll source collection {source}: {exc}") from exc

        if not batch:
            break

        texts = []
        payloads = []
        for point in batch:
            chunk_text = point.payload.get("chunk_text", "") if point.payload else ""
            if not isinstance(chunk_text, str):
                chunk_text = ""
            texts.append(chunk_text)
            payloads.append(point.payload or {})
            if len(query_texts) < recall_query_limit and chunk_text:
                query_texts.append(chunk_text)

        if texts:
            try:
                embeddings = await llm_client.generate_embeddings_with_model(
                    texts, model=embedding_model
                )
            except Exception as exc:
                raise VectorStoreError(f"Ollama embedding failed for {embedding_model}: {exc}") from exc

            new_points = []
            for vec, payload in zip(embeddings, payloads):
                if not vec or len(vec) != embedding_dim:
                    vec = [0.0] * embedding_dim
                payload = dict(payload)
                payload["embedding_model"] = embedding_model
                payload["reindexed_from"] = source
                new_points.append(
                    PointStruct(id=str(uuid.uuid4()), vector=vec, payload=payload)
                )

            for start in range(0, len(new_points), batch_size):
                client.upsert(
                    collection_name=target,
                    points=new_points[start : start + batch_size],
                )
            points_indexed += len(new_points)

        if offset is None:
            break

    recall_score = None
    if query_texts:
        try:
            source_embeddings = await llm_client.generate_embeddings_with_model(
                query_texts, model=settings.embedding_model
            )
            target_embeddings = await llm_client.generate_embeddings_with_model(
                query_texts, model=embedding_model
            )
        except Exception:
            source_embeddings = target_embeddings = []

        overlaps = []
        for src_vec, tgt_vec in zip(source_embeddings, target_embeddings):
            if not src_vec or not tgt_vec:
                continue
            try:
                src_result = client.query_points(
                    collection_name=source,
                    query=src_vec,
                    limit=recall_query_limit,
                    with_payload=False,
                ).points
                tgt_result = client.query_points(
                    collection_name=target,
                    query=tgt_vec,
                    limit=recall_query_limit,
                    with_payload=False,
                ).points
            except Exception:
                continue
            src_ids = {str(p.id) for p in src_result}
            tgt_ids = {str(p.id) for p in tgt_result}
            if src_ids:
                overlaps.append(len(src_ids & tgt_ids) / len(src_ids))

        if overlaps:
            recall_score = sum(overlaps) / len(overlaps)

    return {
        "status": "completed",
        "points_total": points_total,
        "points_indexed": points_indexed,
        "recall_score": recall_score,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Reference Library (shared, tier-scoped knowledge)
# ─────────────────────────────────────────────────────────────────────────────


async def ensure_reference_collection() -> None:
    """Create the shared reference-library collection if it doesn't exist."""
    client = get_client()
    collections = [c.name for c in client.get_collections().collections]
    if REFERENCE_COLLECTION not in collections:
        client.create_collection(
            collection_name=REFERENCE_COLLECTION,
            vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
        )
        logger.info("Created Qdrant collection: %s", REFERENCE_COLLECTION)


async def delete_reference_document(document_id: int) -> None:
    """Remove all chunks for a reference document (so re-indexing is idempotent)."""
    client = get_client()
    await ensure_reference_collection()
    client.delete(
        collection_name=REFERENCE_COLLECTION,
        points_selector=Filter(
            must=[FieldCondition(key="document_id", match=MatchValue(value=document_id))]
        ),
    )


async def upsert_reference_vectors(
    vectors: list[list[float]],
    payloads: list[dict[str, Any]],
) -> list[str]:
    """Upsert reference-doc chunk vectors into the shared collection."""
    client = get_client()
    await ensure_reference_collection()

    point_ids: list[str] = []
    points = []
    for vec, payload in zip(vectors, payloads):
        pid = str(uuid.uuid4())
        point_ids.append(pid)
        payload["vector_id"] = pid
        points.append(PointStruct(id=pid, vector=vec, payload=payload))

    # Upsert in batches: a single request for a large document can exceed
    # Qdrant's 32 MB JSON payload limit and fail with a 400.
    batch_size = 256
    for start in range(0, len(points), batch_size):
        client.upsert(
            collection_name=REFERENCE_COLLECTION,
            points=points[start : start + batch_size],
        )
    logger.info("Upserted %d reference vectors", len(points))
    return point_ids


async def search_reference_vectors(
    access: VectorAccessClaims,
    query_vector: list[float],
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Search reference docs visible to this tenant/project.

    Tier scoping: industry docs are global; company docs match the tenant;
    project docs match the project. Enforced here (the LLM never chooses scope).
    """
    client = get_client()
    scope_filter = Filter(
        should=[
            Filter(must=[FieldCondition(key="tier", match=MatchValue(value="industry"))]),
            Filter(
                must=[
                    FieldCondition(key="tier", match=MatchValue(value="company")),
                    FieldCondition(key="tenant_id", match=MatchValue(value=access.tenant_id)),
                ]
            ),
            Filter(
                must=[
                    FieldCondition(key="tier", match=MatchValue(value="project")),
                    FieldCondition(key="tenant_id", match=MatchValue(value=access.tenant_id)),
                    FieldCondition(key="project_id", match=MatchValue(value=access.project_id)),
                ]
            ),
        ]
    )
    try:
        results = client.query_points(
            collection_name=REFERENCE_COLLECTION,
            query=query_vector,
            query_filter=scope_filter,
            limit=limit,
            with_payload=True,
        ).points
    except Exception as e:
        # Collection may not exist yet (nothing indexed) — degrade to no results.
        logger.warning("Reference vector search failed: %s", e)
        return []

    return [
        {"id": r.id, "score": r.score, "payload": r.payload}
        for r in results
    ]
