"""Regression tests for TS-003: preserve View Family metadata across profiling."""

from __future__ import annotations

import pytest_asyncio
from sqlalchemy import text

from app.models.project_asset import ProjectAsset


@pytest_asyncio.fixture
async def asset(db_session):
    await db_session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS ai_documents (
                id INTEGER PRIMARY KEY,
                source_type TEXT,
                source_id INTEGER,
                chunk_count INTEGER,
                status TEXT
            )
        """
        )
    )
    await db_session.commit()

    asset = ProjectAsset(
        tenant_id=1,
        project_id=1,
        owner_user_id=1,
        asset_type="document",
        source_type="uploaded_file",
        title="Test doc",
        filename="test.pdf",
        content_type="application/pdf",
        file_extension=".pdf",
        storage_provider="local",
        storage_location="/tmp/test.pdf",
        ai_status="pending",
        ai_metadata={"document_family": "policy"},
    )
    db_session.add(asset)
    await db_session.commit()
    await db_session.refresh(asset)
    return asset


async def test_process_document_asset_preserves_existing_metadata(db_session, asset, monkeypatch):
    from app.services import document_processing_service as dps

    monkeypatch.setattr(
        dps, "extract_text", lambda path, ext: {"document_text": "Some document text."}
    )
    monkeypatch.setattr(
        dps,
        "chunk_document",
        lambda extraction: [
            {
                "chunk_index": 0,
                "chunk_text": "chunk",
                "content_hash": "h1",
                "token_count": 1,
            }
        ],
    )
    async def fake_profile(*args, **kwargs):
        return {
            "summary": "A summary",
            "tags": ["tag"],
        }

    monkeypatch.setattr(dps, "_call_ai_profile", fake_profile)
    monkeypatch.setattr(dps, "_build_graph", lambda *args, **kwargs: None)
    monkeypatch.setattr(dps, "_link_to_datasources", lambda *args, **kwargs: None)

    await dps.process_document_asset(
        session=db_session,
        asset=asset,
        tenant_id=1,
        project_id=1,
        user_id=1,
    )

    await db_session.refresh(asset)
    assert asset.ai_metadata["document_family"] == "policy"
    assert asset.ai_metadata["summary"] == "A summary"
    assert asset.ai_metadata["tags"] == ["tag"]


async def test_process_document_asset_overrides_with_explicit_family(db_session, asset, monkeypatch):
    from app.services import document_processing_service as dps

    monkeypatch.setattr(
        dps, "extract_text", lambda path, ext: {"document_text": "Some document text."}
    )
    monkeypatch.setattr(
        dps,
        "chunk_document",
        lambda extraction: [
            {
                "chunk_index": 0,
                "chunk_text": "chunk",
                "content_hash": "h1",
                "token_count": 1,
            }
        ],
    )
    async def fake_profile(*args, **kwargs):
        return {
            "summary": "Updated summary",
            "document_family": "procedure",
        }

    monkeypatch.setattr(dps, "_call_ai_profile", fake_profile)
    monkeypatch.setattr(dps, "_build_graph", lambda *args, **kwargs: None)
    monkeypatch.setattr(dps, "_link_to_datasources", lambda *args, **kwargs: None)

    await dps.process_document_asset(
        session=db_session,
        asset=asset,
        tenant_id=1,
        project_id=1,
        user_id=1,
    )

    await db_session.refresh(asset)
    assert asset.ai_metadata["document_family"] == "procedure"
    assert asset.ai_metadata["summary"] == "Updated summary"
