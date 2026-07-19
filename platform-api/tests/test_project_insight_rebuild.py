"""Tests for the Project Insight event-driven stale-while-revalidate rebuild.

Covers:
1. Data-change triggers mark stale and enqueue a debounced rebuild.
2. Knowledge Graph build success marks stale and enqueues.
3. The worker stale gate skips when nothing is stale.
4. The worker refreshes only existing snapshot owners, clears is_stale,
   respects the user cap, and keeps going through per-user failures.
5. The GET route exposes stale/generatedAt and refresh=true writes is_stale=False.
6. Acknowledged insight ids survive a background regeneration.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.jwt import create_access_token
from app.config import get_settings
from app.models import AIProjectGraphNode, Project, Tenant, User
from app.models.project_asset import ProjectAsset
from app.models.project_intelligence_snapshot import ProjectIntelligenceSnapshot
from app.schemas.project_insight import ProjectInsightProject, ProjectInsightResponse
from app.services.knowledge_graph_lifecycle import KnowledgeGraphLifecycleManager

pytestmark = pytest.mark.anyio


_AI_RESULT = {
    "executiveSummary": {
        "summary": "Supplier risk and budget watch.",
        "critical": ["Supplier A lead time breached SLA"],
        "warnings": ["Budget variance trending up"],
        "opportunities": ["Consolidate spend with Supplier B"],
        "recommendations": ["Renegotiate Supplier A contract"],
    },
    "questionsToAsk": [],
    "trendDetection": [],
    "recommendedDashboards": [],
    "recommendedQueries": [],
    "recommendedKpis": [],
    "insightValidationWorkflow": [
        {"id": "i1", "title": "Supplier A risk", "priority": "high", "status": "new"},
        {"id": "i2", "title": "Budget watch", "priority": "medium", "status": "new"},
    ],
}


async def _tenant_user(
    session: AsyncSession, slug: str, *, user_id: int | None = None
) -> tuple[Tenant, User]:
    tenant = Tenant(slug=slug, name=f"{slug} tenant", is_active=True)
    session.add(tenant)
    await session.flush()
    user = User(
        tenant_id=tenant.id,
        email=f"{slug}@test.com",
        external_id=f"ext-{slug}",
        display_name="Test User",
        status="active",
        role="editor",
    )
    session.add(user)
    await session.flush()
    if user_id is not None:
        # Some tests need a stable id for deterministic snapshots.
        user.id = user_id
        await session.flush()
    return tenant, user


async def _project(session: AsyncSession, tenant_id: int, owner_id: int, slug: str) -> Project:
    project = Project(
        tenant_id=tenant_id,
        name=f"{slug} Project",
        owner_id=owner_id,
        is_shared=False,
    )
    session.add(project)
    await session.flush()
    return project


def _editor_headers(tenant_id: int, user_id: int) -> dict:
    token = create_access_token(
        sub="u", tenant_id=tenant_id, user_id=user_id, role="editor"
    )
    return {"Authorization": f"Bearer {token}"}


def _bind_sessions(monkeypatch, db_engine):
    """Point worker-side SessionLocal factories at the test engine."""
    import app.routes.home_intelligence as hir
    import app.tasks.workflows as workflows

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    monkeypatch.setattr(workflows, "SessionLocal", factory)
    monkeypatch.setattr(hir, "SessionLocal", factory)


def _patch_queue(monkeypatch):
    """Fake Redis-backed run-queue helpers used by the worker tasks."""
    import app.services.home_intel_queue as q

    async def _true(*args, **kwargs):
        return True

    async def _none(*args, **kwargs):
        return None

    monkeypatch.setattr(q, "acquire_tenant_slot", _true)
    monkeypatch.setattr(q, "release_tenant_slot", _none)


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


# ── 1. Document processing marks stale and enqueues rebuild ─────────────


async def test_document_processing_marks_project_insight_stale_and_enqueues(
    db_session, tmp_path, ai_documents_table, monkeypatch
):
    import app.tasks.workflows as workflows
    from app.services import document_processing_service as dps

    tenant, user = await _tenant_user(db_session, "doc-stale")
    project = await _project(db_session, tenant.id, user.id, "doc-stale")

    snap = ProjectIntelligenceSnapshot(
        tenant_id=tenant.id,
        user_id=user.id,
        project_id=project.id,
        suite="project_insight",
        payload={"stale": False},
        is_stale=False,
    )
    db_session.add(snap)

    doc = tmp_path / "doc.txt"
    doc.write_bytes(b"new content")
    new_digest = hashlib.sha256(b"new content").hexdigest()
    asset = ProjectAsset(
        tenant_id=tenant.id,
        project_id=project.id,
        owner_user_id=user.id,
        asset_type="txt",
        source_type="uploaded_file",
        title="Doc",
        filename="doc.txt",
        content_type="text/plain",
        file_extension=".txt",
        storage_provider="local",
        storage_location=str(doc),
        file_hash="old-hash",
        ai_status="profiled",
        ai_metadata={},
    )
    db_session.add(asset)
    await db_session.execute(
        text(
            "INSERT INTO ai_documents (source_type, source_id, file_hash, status) "
            "VALUES ('project_asset', :sid, :fh, 'profiled')"
        ),
        {"sid": asset.id, "fh": "old-hash"},
    )
    await db_session.commit()

    # Stub the heavy pipeline stages so no AI or vector store is needed.
    monkeypatch.setattr(dps, "extract_text", lambda path, ext: {"document_text": "Some text."})
    monkeypatch.setattr(
        dps,
        "chunk_document",
        lambda extraction: [
            {"chunk_index": 0, "chunk_text": "chunk", "content_hash": "h1", "token_count": 1}
        ],
    )
    async def _fake_profile(**kw):
        return {"summary": "A summary"}

    monkeypatch.setattr(dps, "_call_ai_profile", _fake_profile)

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(dps, "_build_graph", _noop)
    monkeypatch.setattr(dps, "_link_to_datasources", _noop)
    monkeypatch.setattr(dps, "_index_document_vectors", _noop)
    monkeypatch.setattr(
        "app.services.knowledge_graph_lifecycle.request_event_driven_rebuild",
        _noop,
    )

    enqueued: list[tuple[int, int]] = []

    async def fake_enqueue(*, tenant_id: int, project_id: int) -> str:
        enqueued.append((tenant_id, project_id))
        return "pi-job"

    monkeypatch.setattr(workflows, "enqueue_rebuild_project_insight", fake_enqueue)
    monkeypatch.setattr(get_settings(), "project_insight_event_rebuild_enabled", True)

    result = await dps.process_document_asset(
        db_session, asset, tenant.id, project.id, user.id
    )

    assert result == "processed"
    await db_session.refresh(asset)
    assert asset.file_hash == new_digest

    row = await db_session.scalar(
        select(ProjectIntelligenceSnapshot).where(
            ProjectIntelligenceSnapshot.tenant_id == tenant.id,
            ProjectIntelligenceSnapshot.project_id == project.id,
        )
    )
    assert row is not None
    assert row.is_stale is True
    assert enqueued == [(tenant.id, project.id)]


# ── 2. KG build success marks stale and enqueues rebuild ────────────────


async def test_kg_build_success_marks_project_insight_stale_and_enqueues(
    db_engine, db_session, monkeypatch
):
    import app.tasks.workflows as workflows

    _bind_sessions(monkeypatch, db_engine)
    tenant, user = await _tenant_user(db_session, "kg-stale")
    project = await _project(db_session, tenant.id, user.id, "kg-stale")

    snap = ProjectIntelligenceSnapshot(
        tenant_id=tenant.id,
        user_id=user.id,
        project_id=project.id,
        suite="project_insight",
        payload={},
        is_stale=False,
    )
    db_session.add(snap)

    db_session.add(
        AIProjectGraphNode(
            tenant_id=tenant.id,
            project_id=project.id,
            node_type="project",
            source_type="project",
            source_id=project.id,
            name=project.name,
            created_by=user.id,
            is_active=True,
        )
    )
    await db_session.commit()

    enqueued: list[tuple[int, int]] = []

    async def fake_enqueue(*, tenant_id: int, project_id: int) -> str:
        enqueued.append((tenant_id, project_id))
        return "pi-job"

    monkeypatch.setattr(workflows, "enqueue_rebuild_project_insight", fake_enqueue)
    monkeypatch.setattr(get_settings(), "project_insight_event_rebuild_enabled", True)

    manager = KnowledgeGraphLifecycleManager(db_session)
    build, _ = await manager.request_full_rebuild(project.id, requested_by=user.id)
    await db_session.commit()

    result = await workflows.rebuild_knowledge_graph({}, build.id)
    assert result["status"] == "ok"

    await db_session.refresh(snap)
    assert snap.is_stale is True
    assert enqueued == [(tenant.id, project.id)]


# ── 3. Worker stale gate skips when nothing is stale ─────────────────────


async def test_rebuild_project_insight_skips_when_not_stale(
    db_engine, db_session, monkeypatch
):
    import app.tasks.workflows as workflows

    _bind_sessions(monkeypatch, db_engine)
    _patch_queue(monkeypatch)
    monkeypatch.setattr(get_settings(), "project_insight_event_rebuild_enabled", True)

    tenant, user = await _tenant_user(db_session, "no-stale")
    project = await _project(db_session, tenant.id, user.id, "no-stale")

    db_session.add(
        ProjectIntelligenceSnapshot(
            tenant_id=tenant.id,
            user_id=user.id,
            project_id=project.id,
            suite="project_insight",
            payload={},
            is_stale=False,
        )
    )
    await db_session.commit()

    result = await workflows.rebuild_project_insight(
        {"job_try": 1}, tenant_id=tenant.id, project_id=project.id
    )
    assert result == {
        "status": "skipped",
        "reason": "not_stale",
        "project_id": project.id,
    }


# ── 4. Worker refreshes audience, clears is_stale, caps users, survives failures ──


async def test_rebuild_project_insight_refreshes_existing_owners_and_caps_users(
    db_engine, db_session, monkeypatch
):
    import app.services.project_insight_service as pi
    import app.tasks.workflows as workflows

    _bind_sessions(monkeypatch, db_engine)
    _patch_queue(monkeypatch)
    monkeypatch.setattr(get_settings(), "project_insight_event_rebuild_enabled", True)
    monkeypatch.setattr(get_settings(), "project_insight_max_rebuild_users", 2)

    tenant = Tenant(slug="cap", name="cap tenant", is_active=True)
    db_session.add(tenant)
    await db_session.flush()

    users: list[User] = []
    for i in range(3):
        u = User(
            tenant_id=tenant.id,
            email=f"u{i}@test.com",
            external_id=f"u{i}",
            display_name=f"User {i}",
            status="active",
            role="editor",
        )
        db_session.add(u)
        await db_session.flush()
        users.append(u)

    project = await _project(db_session, tenant.id, users[0].id, "cap")

    now = datetime.now(UTC)
    snapshots: list[ProjectIntelligenceSnapshot] = []
    for i, u in enumerate(users):
        snap = ProjectIntelligenceSnapshot(
            tenant_id=tenant.id,
            user_id=u.id,
            project_id=project.id,
            suite="project_insight",
            payload={"user_index": i},
            is_stale=True,
        )
        # Spread updated_at so ordering is deterministic.
        snap.updated_at = datetime.fromtimestamp(now.timestamp() + i, tz=UTC)
        db_session.add(snap)
        snapshots.append(snap)
    await db_session.commit()

    built: list[int] = []

    async def fake_build(session, *, project, tenant_id, user_id, runner):
        built.append(user_id)
        return ProjectInsightResponse(
            project=ProjectInsightProject(id=project.id, name=project.name, status="Active"),
            generatedAt="now",
            lastUpdatedAt="now",
        )

    monkeypatch.setattr(pi, "build_project_insight", fake_build)

    result = await workflows.rebuild_project_insight(
        {"job_try": 1}, tenant_id=tenant.id, project_id=project.id
    )
    assert result["status"] == "ok"
    assert result["refreshed"] == 2
    assert result["failed"] == 0
    # Most recently updated first: users 2 and 1 (indices 2, 1).
    assert built == [users[2].id, users[1].id]

    refreshed = (
        await db_session.scalars(
            select(ProjectIntelligenceSnapshot).where(
                ProjectIntelligenceSnapshot.tenant_id == tenant.id,
                ProjectIntelligenceSnapshot.project_id == project.id,
                ProjectIntelligenceSnapshot.is_stale.is_(False),
            )
        )
    ).all()
    assert {s.user_id for s in refreshed} == {users[1].id, users[2].id}

    untouched = await db_session.get(ProjectIntelligenceSnapshot, snapshots[0].id)
    assert untouched.is_stale is True


async def test_rebuild_project_insight_continues_past_per_user_failure(
    db_engine, db_session, monkeypatch
):
    import app.services.project_insight_service as pi
    import app.tasks.workflows as workflows

    _bind_sessions(monkeypatch, db_engine)
    _patch_queue(monkeypatch)
    monkeypatch.setattr(get_settings(), "project_insight_event_rebuild_enabled", True)

    tenant, user = await _tenant_user(db_session, "fail-open")
    user2 = User(
        tenant_id=tenant.id,
        email="u2@test.com",
        external_id="u2",
        display_name="User 2",
        status="active",
        role="editor",
    )
    db_session.add(user2)
    await db_session.flush()

    project = await _project(db_session, tenant.id, user.id, "fail-open")
    for uid in (user.id, user2.id):
        db_session.add(
            ProjectIntelligenceSnapshot(
                tenant_id=tenant.id,
                user_id=uid,
                project_id=project.id,
                suite="project_insight",
                payload={},
                is_stale=True,
            )
        )
    await db_session.commit()

    async def fake_build(session, *, project, tenant_id, user_id, runner):
        if user_id == user.id:
            raise RuntimeError("boom")
        return ProjectInsightResponse(
            project=ProjectInsightProject(id=project.id, name=project.name, status="Active"),
            generatedAt="now",
            lastUpdatedAt="now",
        )

    monkeypatch.setattr(pi, "build_project_insight", fake_build)

    result = await workflows.rebuild_project_insight(
        {"job_try": 1}, tenant_id=tenant.id, project_id=project.id
    )
    assert result["status"] == "ok"
    assert result["refreshed"] == 1
    assert result["failed"] == 1

    rows = {
        r.user_id: r.is_stale
        for r in (
            (await db_session.scalars(
                select(ProjectIntelligenceSnapshot).where(
                    ProjectIntelligenceSnapshot.project_id == project.id
                )
            )).all()
        )
    }
    assert rows[user.id] is True
    assert rows[user2.id] is False


# ── 5. GET route exposes stale and refresh=true writes is_stale=False ────


async def test_get_project_insight_exposes_stale_and_refresh_clears_it(
    client, db_session, monkeypatch
):
    tenant, user = await _tenant_user(db_session, "route-stale")
    project = await _project(db_session, tenant.id, user.id, "route-stale")

    db_session.add(
        ProjectIntelligenceSnapshot(
            tenant_id=tenant.id,
            user_id=user.id,
            project_id=project.id,
            suite="project_insight",
            payload={"executiveSummary": {"summary": "old"}},
            is_stale=True,
        )
    )
    await db_session.commit()

    headers = _editor_headers(tenant.id, user.id)
    r = await client.get(f"/api/projects/{project.id}/insight", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["stale"] is True
    assert body["generatedAt"]  # set from updated_at

    async def _mock_ai(**kw):
        return _AI_RESULT

    monkeypatch.setattr(
        "app.services.ai_intelligence_client.project_insight",
        _mock_ai,
    )

    r = await client.get(
        f"/api/projects/{project.id}/insight?refresh=true", headers=headers
    )
    assert r.status_code == 200
    body = r.json()
    assert body["stale"] is False
    assert body["aiAvailable"] is True


# ── 6. Acknowledged insight ids survive a background regeneration ────────


async def test_acknowledged_insight_ids_survive_regeneration(
    client, db_session, monkeypatch
):
    tenant, user = await _tenant_user(db_session, "ack-survive")
    project = await _project(db_session, tenant.id, user.id, "ack-survive")

    db_session.add(
        ProjectIntelligenceSnapshot(
            tenant_id=tenant.id,
            user_id=user.id,
            project_id=project.id,
            suite="project_insight",
            payload={"insightValidationWorkflow": _AI_RESULT["insightValidationWorkflow"]},
            is_stale=False,
        )
    )
    await db_session.commit()

    headers = _editor_headers(tenant.id, user.id)
    r = await client.post(
        f"/api/projects/{project.id}/insights/i1/acknowledge",
        json={"note": None},
        headers=headers,
    )
    assert r.status_code == 200

    async def _mock_ai(**kw):
        return _AI_RESULT

    monkeypatch.setattr(
        "app.services.ai_intelligence_client.project_insight",
        _mock_ai,
    )

    r = await client.get(
        f"/api/projects/{project.id}/insight?refresh=true", headers=headers
    )
    assert r.status_code == 200
    body = r.json()
    workflow = {w["id"]: w for w in body["insightValidationWorkflow"]}
    assert workflow["i1"]["status"] == "reviewed"
    assert workflow["i2"]["status"] == "new"
