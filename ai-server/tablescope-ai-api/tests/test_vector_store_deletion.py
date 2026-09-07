"""TS-ISO-011 cross-store deletion regression tests.

``delete_tenant_collection`` and ``delete_project_vectors`` were previously
dead code (no callers) with mismatched exception handling: the tenant-level
delete swallowed *every* exception as "not found" and the project-level
delete had no exception handling at all. These tests lock in the corrected
behaviour -- a genuine "not found" is a no-op, but any other Qdrant failure
must propagate as ``VectorStoreError`` so a caller doing best-effort cleanup
during tenant/project deletion can tell the difference.
"""

from __future__ import annotations

import pytest
from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import UnexpectedResponse
from qdrant_client.models import PointStruct

from app.services import vector_store


def _vector() -> list[float]:
    return [1.0] + [0.0] * (vector_store.EMBEDDING_DIM - 1)


def _not_found() -> UnexpectedResponse:
    return UnexpectedResponse(
        status_code=404, reason_phrase="Not Found", content=b"", headers=None
    )


def _server_error() -> UnexpectedResponse:
    return UnexpectedResponse(
        status_code=500, reason_phrase="Internal Server Error", content=b"", headers=None
    )


@pytest.mark.asyncio
async def test_delete_tenant_collection_removes_real_collection(monkeypatch):
    client = QdrantClient(":memory:")
    monkeypatch.setattr(vector_store, "get_client", lambda: client)
    await vector_store.ensure_collection(1)
    assert vector_store._collection_name(1) in [
        c.name for c in client.get_collections().collections
    ]

    await vector_store.delete_tenant_collection(1)

    assert vector_store._collection_name(1) not in [
        c.name for c in client.get_collections().collections
    ]


@pytest.mark.asyncio
async def test_delete_tenant_collection_not_found_is_a_no_op(monkeypatch):
    class FakeClient:
        def delete_collection(self, collection_name: str) -> None:
            raise _not_found()

    monkeypatch.setattr(vector_store, "get_client", lambda: FakeClient())

    # Must not raise.
    await vector_store.delete_tenant_collection(999)


@pytest.mark.asyncio
async def test_delete_tenant_collection_real_error_propagates(monkeypatch):
    class FakeClient:
        def delete_collection(self, collection_name: str) -> None:
            raise _server_error()

    monkeypatch.setattr(vector_store, "get_client", lambda: FakeClient())

    with pytest.raises(vector_store.VectorStoreError):
        await vector_store.delete_tenant_collection(1)


@pytest.mark.asyncio
async def test_delete_project_vectors_removes_only_matching_points(monkeypatch):
    client = QdrantClient(":memory:")
    monkeypatch.setattr(vector_store, "get_client", lambda: client)
    await vector_store.ensure_collection(1)
    collection = vector_store._collection_name(1)
    vec = _vector()
    client.upsert(
        collection_name=collection,
        points=[
            PointStruct(id=1, vector=vec, payload={"tenant_id": 1, "project_id": 10}),
            PointStruct(id=2, vector=vec, payload={"tenant_id": 1, "project_id": 11}),
        ],
    )

    await vector_store.delete_project_vectors(1, 10)

    remaining = client.scroll(collection_name=collection, limit=10)[0]
    assert {p.id for p in remaining} == {2}


@pytest.mark.asyncio
async def test_delete_project_vectors_not_found_is_a_no_op(monkeypatch):
    class FakeClient:
        def delete(self, collection_name: str, points_selector) -> None:
            raise _not_found()

    monkeypatch.setattr(vector_store, "get_client", lambda: FakeClient())

    # Must not raise.
    await vector_store.delete_project_vectors(999, 1)


@pytest.mark.asyncio
async def test_delete_project_vectors_real_error_propagates(monkeypatch):
    class FakeClient:
        def delete(self, collection_name: str, points_selector) -> None:
            raise _server_error()

    monkeypatch.setattr(vector_store, "get_client", lambda: FakeClient())

    with pytest.raises(vector_store.VectorStoreError):
        await vector_store.delete_project_vectors(1, 10)
