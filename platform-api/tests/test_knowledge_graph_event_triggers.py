"""Tests for event-driven knowledge graph rebuilds and hash-gated reprocessing.

Covers the three interlocking behaviors:
1. File-hash gate — document reprocessing skips unchanged, already-profiled
   files unless forced.
2. Event triggers — document processing and the stale-graph cron request and
   enqueue lifecycle rebuilds without user intervention.
3. Project-wide reprocess cascade — all documents first, one terminal graph
   rebuild only when something changed.
"""

from __future__ import annotations

import hashlib

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.context import RequestContext
from app.auth.jwt import TokenClaims
from app.models import (
    AIProjectGraphNode,
    KnowledgeGraphBuild,
    KnowledgeGraphVersion,
    Project,
)
from app.models.project_asset import ProjectAsset
from app.services.knowledge_graph_lifecycle import (
    KnowledgeGraphLifecycleManager,
    request_event_driven_rebuild,
)

pytestmark = pytest.mark.anyio


def _manager(session: AsyncSession, tenant_id: int, user_id: int, role: str = "editor"):
    return KnowledgeGraphLifecycleManager(
        session,
        RequestContext(
            claims=TokenClaims(
                sub=str(user_id), tenant_id=tenant_id, user_id=user_id, role=role
            )
        ),
    )


async def _project(session: AsyncSession, tenant_id: int, owner_id: int, slug: str):
    project = Project(
        tenant_id=tenant_id,
        name=f"{slug} Project",
        owner_id=owner_id,
        is_shared=False,
    )
    session.add(project)
    await session.flush()
    return project


@pytest_asyncio.fixture
async def ai_documents_table(db_session):
    await db_session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS ai_documents (
                id INTEGER PRIMARY KEY,
                source_type TEXT,
                source_id INTEGER,
                file_hash TEXT,
                chunk_count INTEGER,
                status TEXT
            )
            """
        )
    )
    await db_session.commit()


async def _asset(
    session: AsyncSession,
    project: Project,
    *,
    path: str,
    file_hash: str | None,
    ai_status: str,
) -> ProjectAsset:
    asset = ProjectAsset(
        tenant_id=project.tenant_id,
        project_id=project.id,
        owner_user_id=project.owner_id,
        asset_type="txt",
        source_type="uploaded_file",
        title="Doc",
        filename="doc.txt",
        content_type="text/plain",
        file_extension=".txt",
        storage_provider="local",
        storage_location=path,
        file_hash=file_hash,
        ai_status=ai_status,
        ai_metadata={},
    )
    session.add(asset)
    await session.commit()
    await session.refresh(asset)
    return asset


def _patch_pipeline(monkeypatch):
    """Stub extraction/chunking/profiling/graph stages of the document pipeline."""
    from app.services import document_processing_service as dps

    monkeypatch.setattr(
        dps, "extract_text", lambda path, ext: {"document_text": "Some text."}
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
        return {"summary": "A summary"}

    async def noop(*args, **kwargs):
        return None

    monkeypatch.setattr(dps, "_call_ai_profile", fake_profile)
    monkeypatch.setattr(dps, "_build_graph", noop)
    monkeypatch.setattr(dps, "_link_to_datasources", noop)
    return dps


def _capture_enqueue(monkeypatch):
    """Replace the arq enqueue with a recorder so tests never touch Redis."""
    import app.tasks.workflows as workflows

    enqueued: list[int] = []

    async def fake_enqueue(build_id: int) -> str:
        enqueued.append(build_id)
        return f"kg-build:{build_id}"

    monkeypatch.setattr(workflows, "enqueue_rebuild_knowledge_graph", fake_enqueue)
    return enqueued


# ── File-hash gate ───────────────────────────────────────────────────


async def test_hash_gate_skips_unchanged_profiled_asset(
    db_session, tmp_path, ai_documents_table, monkeypatch
):
    from app.services import document_processing_service as dps

    doc = tmp_path / "doc.txt"
    doc.write_bytes(b"same content")
    digest = hashlib.sha256(b"same content").hexdigest()

    project = await _project(db_session, 1, 1, "gate")
    asset = await _asset(
        db_session, project, path=str(doc), file_hash=digest, ai_status="profiled"
    )

    result = await dps.process_document_asset(
        db_session, asset, project.tenant_id, project.id, 1
    )

    assert result == "skipped_unchanged"
    await db_session.refresh(asset)
    assert asset.ai_status == "profiled"
    builds = (await db_session.scalars(select(KnowledgeGraphBuild))).all()
    assert builds == []


async def test_changed_bytes_reprocess_updates_hash_and_triggers_rebuild(
    db_session, tmp_path, ai_documents_table, monkeypatch
):
    dps = _patch_pipeline(monkeypatch)
    enqueued = _capture_enqueue(monkeypatch)

    doc = tmp_path / "doc.txt"
    doc.write_bytes(b"new content")
    new_digest = hashlib.sha256(b"new content").hexdigest()

    project = await _project(db_session, 1, 1, "changed")
    asset = await _asset(
        db_session, project, path=str(doc), file_hash="old-hash", ai_status="profiled"
    )

    result = await dps.process_document_asset(
        db_session, asset, project.tenant_id, project.id, 1
    )

    assert result == "processed"
    await db_session.refresh(asset)
    assert asset.file_hash == new_digest
    assert asset.ai_status == "profiled"

    build = await db_session.scalar(select(KnowledgeGraphBuild))
    assert build is not None
    assert build.trigger_type == "document_processed"
    assert build.requested_by == 1
    assert enqueued == [build.id]


async def test_force_bypasses_hash_gate(
    db_session, tmp_path, ai_documents_table, monkeypatch
):
    dps = _patch_pipeline(monkeypatch)
    _capture_enqueue(monkeypatch)

    doc = tmp_path / "doc.txt"
    doc.write_bytes(b"same content")
    digest = hashlib.sha256(b"same content").hexdigest()

    project = await _project(db_session, 1, 1, "force")
    asset = await _asset(
        db_session, project, path=str(doc), file_hash=digest, ai_status="profiled"
    )

    result = await dps.process_document_asset(
        db_session, asset, project.tenant_id, project.id, 1, force=True
    )
    assert result == "processed"


async def test_cascade_suppresses_per_document_rebuild(
    db_session, tmp_path, ai_documents_table, monkeypatch
):
    dps = _patch_pipeline(monkeypatch)
    enqueued = _capture_enqueue(monkeypatch)

    doc = tmp_path / "doc.txt"
    doc.write_bytes(b"content")

    project = await _project(db_session, 1, 1, "suppress")
    asset = await _asset(
        db_session, project, path=str(doc), file_hash=None, ai_status="pending"
    )

    result = await dps.process_document_asset(
        db_session,
        asset,
        project.tenant_id,
        project.id,
        1,
        trigger_graph_rebuild=False,
    )
    assert result == "processed"
    builds = (await db_session.scalars(select(KnowledgeGraphBuild))).all()
    assert builds == []
    assert enqueued == []


# ── Lifecycle manager: headless requests + coalescing + incremental reload ──


async def test_headless_system_context_can_request_rebuild(db_session):
    project = await _project(db_session, 1, 7, "headless")
    manager = KnowledgeGraphLifecycleManager(db_session)  # no request context

    build, build_type = await manager.request_full_rebuild(
        project.id, trigger="source_drift", requested_by=7
    )
    assert build_type == "full"
    assert build.requested_by == 7
    assert build.trigger_type == "source_drift"


async def test_incremental_requests_coalesce_onto_queued_build(db_session):
    project = await _project(db_session, 1, 1, "coalesce")
    manager = _manager(db_session, 1, 1)

    change = [
        {
            "entity_type": "document",
            "entity_id": 1,
            "action": "processed",
            "change_scope": "content",
        }
    ]
    first, _ = await manager.request_incremental_rebuild(project.id, change_set=change)
    second, _ = await manager.request_incremental_rebuild(project.id, change_set=change)
    assert second.id == first.id

    builds = (await db_session.scalars(select(KnowledgeGraphBuild))).all()
    assert len(builds) == 1


async def test_incremental_rebuild_reloads_stored_graph_rows(db_session):
    tenant_id, user_id = 1, 1
    project = await _project(db_session, tenant_id, user_id, "reload")

    db_session.add(
        AIProjectGraphNode(
            tenant_id=tenant_id,
            project_id=project.id,
            node_type="project",
            source_type="project",
            source_id=project.id,
            name=project.name,
            created_by=user_id,
            is_active=True,
        )
    )
    await db_session.flush()

    manager = _manager(db_session, tenant_id, user_id)
    full_build, _ = await manager.request_full_rebuild(project.id)
    await manager.run_full_rebuild(full_build.id)
    await db_session.commit()

    # A new document node lands in the base tables after the full build.
    db_session.add(
        AIProjectGraphNode(
            tenant_id=tenant_id,
            project_id=project.id,
            node_type="document",
            source_type="project_asset",
            source_id=99,
            name="fresh-document.txt",
            created_by=user_id,
            # SQLite stores the server_default literally as the string 'true',
            # which the is_active=true filter doesn't match; set it explicitly.
            is_active=True,
        )
    )
    await db_session.flush()

    inc_build, build_type = await manager.request_incremental_rebuild(
        project.id,
        change_set=[
            {
                "entity_type": "document",
                "entity_id": 99,
                "action": "processed",
                "change_scope": "content",
            }
        ],
    )
    assert build_type == "incremental"
    await db_session.commit()
    await manager.run_incremental_rebuild(inc_build.id)
    await db_session.commit()

    graph = await manager.ensure_graph(project.id)
    active = await db_session.get(KnowledgeGraphVersion, graph.active_version_id)
    assert active is not None and active.build_type == "incremental"

    payload = await manager.get_active_snapshot_payload(project.id)
    names = {n.get("name") for n in payload["fullGraph"]["nodes"]}
    assert "fresh-document.txt" in names


async def test_request_event_driven_rebuild_attributes_project_owner(
    db_session, monkeypatch
):
    enqueued = _capture_enqueue(monkeypatch)
    project = await _project(db_session, 1, 42, "owner")

    build = await request_event_driven_rebuild(
        db_session,
        project_id=project.id,
        change_set=[
            {
                "entity_type": "data_source",
                "entity_id": 5,
                "action": "synced",
                "change_scope": "content",
            }
        ],
        trigger="saas_sync",
    )
    assert build is not None
    assert build.requested_by == 42  # falls back to the project owner
    assert build.trigger_type == "saas_sync"
    assert enqueued == [build.id]


async def test_request_event_driven_rebuild_never_raises(db_session, monkeypatch):
    # Nonexistent project: the helper must swallow the failure and return None.
    build = await request_event_driven_rebuild(
        db_session,
        project_id=999999,
        change_set=[],
        trigger="document_processed",
    )
    assert build is None


# ── Stale-graph cron auto-rebuild ────────────────────────────────────


async def test_evaluate_stale_graphs_task_enqueues_rebuilds(
    db_engine, db_session, monkeypatch
):
    import app.tasks.workflows as workflows

    enqueued = _capture_enqueue(monkeypatch)
    monkeypatch.setattr(
        workflows, "SessionLocal", async_sessionmaker(db_engine, expire_on_commit=False)
    )

    project = await _project(db_session, 1, 7, "drift")
    manager = KnowledgeGraphLifecycleManager(db_session)
    graph = await manager.ensure_graph(project.id)
    graph.current_source_fingerprint = "old-fingerprint"
    await db_session.commit()

    result = await workflows.evaluate_stale_graphs({})
    assert result["status"] == "ok"
    assert project.id in result["marked_project_ids"]
    assert len(result["enqueued_build_ids"]) == 1
    assert enqueued == result["enqueued_build_ids"]

    build = await db_session.get(KnowledgeGraphBuild, result["enqueued_build_ids"][0])
    assert build.trigger_type == "source_drift"
    assert build.requested_by == 7  # project owner, so AI enrichment still runs


# ── Project-wide reprocess cascade ───────────────────────────────────


async def test_reprocess_project_rebuilds_graph_when_documents_changed(
    db_engine, db_session, monkeypatch, tmp_path
):
    import app.tasks.workflows as workflows
    from app.services import document_processing_service as dps

    enqueued = _capture_enqueue(monkeypatch)
    monkeypatch.setattr(
        workflows, "SessionLocal", async_sessionmaker(db_engine, expire_on_commit=False)
    )

    project = await _project(db_session, 1, 1, "cascade")
    doc = tmp_path / "doc.txt"
    doc.write_bytes(b"content")
    changed = await _asset(
        db_session, project, path=str(doc), file_hash="old", ai_status="profiled"
    )
    unchanged = await _asset(
        db_session,
        project,
        path=str(doc),
        file_hash=hashlib.sha256(b"content").hexdigest(),
        ai_status="profiled",
    )

    seen: dict[int, dict] = {}

    async def fake_process(session, asset, tenant_id, project_id, user_id, **kwargs):
        seen[asset.id] = kwargs
        if asset.id == changed.id:
            return "processed"
        return "skipped_unchanged"

    monkeypatch.setattr(dps, "process_document_asset", fake_process)

    result = await workflows.reprocess_project(
        {}, tenant_id=project.tenant_id, project_id=project.id, user_id=1
    )

    assert result["status"] == "ok"
    assert result["changed_count"] == 1
    assert result["documents"][changed.id] == "processed"
    assert result["documents"][unchanged.id] == "skipped_unchanged"
    # Per-document rebuilds are suppressed inside the cascade...
    assert all(k["trigger_graph_rebuild"] is False for k in seen.values())
    # ...and exactly one terminal rebuild is requested and enqueued.
    assert result["graph_build_id"] is not None
    assert enqueued == [result["graph_build_id"]]
    build = await db_session.get(KnowledgeGraphBuild, result["graph_build_id"])
    assert build.trigger_type == "project_reprocess"


async def test_reprocess_project_skips_rebuild_when_nothing_changed(
    db_engine, db_session, monkeypatch, tmp_path
):
    import app.tasks.workflows as workflows
    from app.services import document_processing_service as dps

    enqueued = _capture_enqueue(monkeypatch)
    monkeypatch.setattr(
        workflows, "SessionLocal", async_sessionmaker(db_engine, expire_on_commit=False)
    )

    project = await _project(db_session, 1, 1, "noop-cascade")
    doc = tmp_path / "doc.txt"
    doc.write_bytes(b"content")
    await _asset(
        db_session,
        project,
        path=str(doc),
        file_hash=hashlib.sha256(b"content").hexdigest(),
        ai_status="profiled",
    )

    async def fake_process(session, asset, tenant_id, project_id, user_id, **kwargs):
        return "skipped_unchanged"

    monkeypatch.setattr(dps, "process_document_asset", fake_process)

    result = await workflows.reprocess_project(
        {}, tenant_id=project.tenant_id, project_id=project.id, user_id=1
    )
    assert result["changed_count"] == 0
    assert result["graph_build_id"] is None
    assert enqueued == []
