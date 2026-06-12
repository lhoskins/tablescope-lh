"""Qdrant vector store with tenant-isolated collections.

Collection naming:  tablescope_tenant_{tenant_id}
Every search enforces tenant_id + project_id payload filters.
Cross-tenant queries are structurally impossible (different collections).
"""

import logging
import uuid
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from app.core.config import settings

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 768  # nomic-embed-text dimension


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
        pid = str(uuid.uuid4())
        point_ids.append(pid)
        payload["vector_id"] = pid
        points.append(PointStruct(id=pid, vector=vec, payload=payload))

    client.upsert(collection_name=name, points=points)
    logger.info("Upserted %d vectors into %s", len(points), name)
    return point_ids


async def search_vectors(
    tenant_id: int,
    project_id: int,
    user_id: int,
    query_vector: list[float],
    scope: str = "project",
    is_project_member: bool = True,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Search vectors with mandatory tenant + project + visibility filters.

    The LLM never decides what to search. The caller (context_builder)
    provides the authenticated scope, and this function enforces it.
    """
    client = get_client()
    name = _collection_name(tenant_id)

    # Build mandatory filters
    must_conditions: list[FieldCondition] = [
        FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id)),
        FieldCondition(key="project_id", match=MatchValue(value=project_id)),
    ]

    if scope == "personal":
        must_conditions.append(
            FieldCondition(key="owner_user_id", match=MatchValue(value=user_id))
        )
    elif scope == "private_project":
        must_conditions.append(
            FieldCondition(key="owner_user_id", match=MatchValue(value=user_id))
        )
        must_conditions.append(
            FieldCondition(key="visibility", match=MatchValue(value="private_project"))
        )
    elif scope == "shared_project":
        if not is_project_member:
            logger.warning(
                "Non-member user %d attempted shared_project search on project %d",
                user_id, project_id,
            )
            return []
        must_conditions.append(
            FieldCondition(key="visibility", match=MatchValue(value="shared_project"))
        )

    results = client.search(
        collection_name=name,
        query_vector=query_vector,
        query_filter=Filter(must=must_conditions),
        limit=limit,
    )

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
