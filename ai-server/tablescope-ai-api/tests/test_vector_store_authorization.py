"""TS-ISO-005 vector authorization regression tests."""

from __future__ import annotations

import pytest
from app.models.schemas import AskRequest, VectorAccessClaims
from app.services import vector_store
from pydantic import ValidationError
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct


def _vector() -> list[float]:
    return [1.0] + [0.0] * (vector_store.EMBEDDING_DIM - 1)


def _access(*, tenant_id: int = 1, project_id: int = 10, user_id: int = 7) -> VectorAccessClaims:
    return VectorAccessClaims(
        tenant_id=tenant_id,
        project_id=project_id,
        principal_user_id=user_id,
        project_access="active_member",
        project_visibility="shared",
        private_document_owner_user_id=user_id,
    )


@pytest.mark.asyncio
async def test_project_search_returns_shared_and_owned_private_only(monkeypatch):
    client = QdrantClient(":memory:")
    monkeypatch.setattr(vector_store, "get_client", lambda: client)
    await vector_store.ensure_collection(1)
    collection = vector_store._collection_name(1)
    vec = _vector()
    client.upsert(
        collection_name=collection,
        points=[
            PointStruct(id=1, vector=vec, payload={"tenant_id": 1, "project_id": 10, "document_id": 1, "visibility": "shared_project", "owner_user_id": 8}),
            PointStruct(id=2, vector=vec, payload={"tenant_id": 1, "project_id": 10, "document_id": 2, "visibility": "private", "owner_user_id": 7}),
            PointStruct(id=3, vector=vec, payload={"tenant_id": 1, "project_id": 10, "document_id": 3, "visibility": "private", "owner_user_id": 8}),
            PointStruct(id=4, vector=vec, payload={"tenant_id": 1, "project_id": 11, "document_id": 4, "visibility": "shared_project", "owner_user_id": 7}),
            PointStruct(id=5, vector=vec, payload={"tenant_id": 1, "project_id": 10, "document_id": 5, "owner_user_id": 7}),
        ],
    )

    results = await vector_store.search_vectors(
        access=_access(), query_vector=vec, limit=20
    )

    assert {r["payload"]["document_id"] for r in results} == {1, 2}


@pytest.mark.asyncio
async def test_reference_project_tier_requires_tenant_and_project(monkeypatch):
    client = QdrantClient(":memory:")
    monkeypatch.setattr(vector_store, "get_client", lambda: client)
    await vector_store.ensure_reference_collection()
    vec = _vector()
    client.upsert(
        collection_name=vector_store.REFERENCE_COLLECTION,
        points=[
            PointStruct(id=1, vector=vec, payload={"tier": "industry", "document_id": 1}),
            PointStruct(id=2, vector=vec, payload={"tier": "company", "tenant_id": 1, "document_id": 2}),
            PointStruct(id=3, vector=vec, payload={"tier": "company", "tenant_id": 2, "document_id": 3}),
            PointStruct(id=4, vector=vec, payload={"tier": "project", "tenant_id": 1, "project_id": 10, "document_id": 4}),
            PointStruct(id=5, vector=vec, payload={"tier": "project", "tenant_id": 2, "project_id": 10, "document_id": 5}),
        ],
    )

    results = await vector_store.search_reference_vectors(
        access=_access(), query_vector=vec, limit=20
    )

    assert {r["payload"]["document_id"] for r in results} == {1, 2, 4}


def test_unknown_or_legacy_scope_fails_schema_validation():
    with pytest.raises(ValidationError):
        AskRequest(
            tenant_id=1,
            user_id=7,
            project_id=10,
            question="secret?",
            scope="private_project",
        )


def test_forged_private_owner_claim_fails_validation():
    with pytest.raises(ValidationError):
        VectorAccessClaims(
            tenant_id=1,
            project_id=10,
            principal_user_id=7,
            project_access="active_member",
            project_visibility="shared",
            private_document_owner_user_id=8,
        )
