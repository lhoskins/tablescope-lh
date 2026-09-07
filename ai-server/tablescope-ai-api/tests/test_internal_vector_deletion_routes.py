"""TS-ISO-011: signed internal routes for tenant/project vector deletion.

Mirrors the existing ``/vector-store/reindex`` route's HMAC-signing contract
-- these two new routes are what platform-api's tenant/project deletion
flows call to clean up Qdrant, so they must reject an unsigned or forged
request exactly like every other internal endpoint.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from qdrant_client import QdrantClient

from app.core import security
from app.core.config import settings
from app.routers import internal
from app.services import vector_store


@pytest.fixture(autouse=True)
def _configured_secret():
    original = settings.ai_signing_secret
    settings.ai_signing_secret = "test-secret"
    yield
    settings.ai_signing_secret = original


@pytest.fixture
def qdrant_client(monkeypatch):
    client = QdrantClient(":memory:")
    monkeypatch.setattr(vector_store, "get_client", lambda: client)
    return client


def _signed(payload: dict) -> dict:
    signed = dict(payload)
    signed["timestamp"] = __import__("time").time()
    signed["signature"] = security.sign_request(signed)
    return signed


@pytest.mark.asyncio
async def test_delete_tenant_collection_route_deletes_with_valid_signature(qdrant_client):
    await vector_store.ensure_collection(1)
    body = _signed({"tenant_id": 1})

    result = await internal.delete_tenant_collection(
        internal.DeleteTenantCollectionRequest(**body)
    )

    assert result.status == "ok"
    assert vector_store._collection_name(1) not in [
        c.name for c in qdrant_client.get_collections().collections
    ]


@pytest.mark.asyncio
async def test_delete_tenant_collection_route_rejects_bad_signature(qdrant_client):
    body = {"tenant_id": 1, "timestamp": __import__("time").time(), "signature": "forged"}

    with pytest.raises(HTTPException) as exc:
        await internal.delete_tenant_collection(
            internal.DeleteTenantCollectionRequest(**body)
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_delete_project_vectors_route_deletes_with_valid_signature(qdrant_client):
    from qdrant_client.models import PointStruct

    await vector_store.ensure_collection(1)
    collection = vector_store._collection_name(1)
    vec = [1.0] + [0.0] * (vector_store.EMBEDDING_DIM - 1)
    qdrant_client.upsert(
        collection_name=collection,
        points=[PointStruct(id=1, vector=vec, payload={"tenant_id": 1, "project_id": 10})],
    )
    body = _signed({"tenant_id": 1, "project_id": 10})

    result = await internal.delete_project_vectors(
        internal.DeleteProjectVectorsRequest(**body)
    )

    assert result.status == "ok"
    remaining = qdrant_client.scroll(collection_name=collection, limit=10)[0]
    assert remaining == []


@pytest.mark.asyncio
async def test_delete_project_vectors_route_rejects_bad_signature(qdrant_client):
    body = {
        "tenant_id": 1,
        "project_id": 10,
        "timestamp": __import__("time").time(),
        "signature": "forged",
    }

    with pytest.raises(HTTPException) as exc:
        await internal.delete_project_vectors(
            internal.DeleteProjectVectorsRequest(**body)
        )
    assert exc.value.status_code == 403
