"""Tests for Business Insights Phase 1: KG grounding + snapshot staleness.

1a — the analyst loop passes the project's Knowledge Graph digest to the AI
plan call (fail-open, capped) so planned analyses target graph-surfaced
hypotheses instead of re-deriving salience from raw schema.
1b — the Home snapshot endpoint flags projects whose Knowledge Graph rebuilt
after the briefing was written, so the UI can nudge a refresh with zero AI
cost.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.auth.jwt import create_access_token
from app.models import IntelligenceSnapshot, KnowledgeGraph, Project
from app.services import home_intelligence as hi

pytestmark = pytest.mark.anyio

KG_CONTEXT = {
    "risks": [{"title": "Supplier concentration", "severity": "high", "summary": "s"}],
    "recommended_kpis": [{"title": "Defect rate", "summary": "k"}],
}


def _headers(tenant_id: int, user_id: int, role: str = "viewer") -> dict:
    token = create_access_token(
        sub="u", tenant_id=tenant_id, user_id=user_id, role=role
    )
    return {"Authorization": f"Bearer {token}"}


# ── 1a: KG grounding of the plan call ────────────────────────────────


async def test_plan_payload_includes_kg_context(db_session, monkeypatch):
    import app.services.ai_intelligence_client as ai
    import app.services.knowledge_graph_ai_context as kg_ctx

    project = Project(tenant_id=1, name="Grounded", owner_id=1, is_shared=False)
    db_session.add(project)
    await db_session.flush()

    async def fake_collect(session, **kwargs):
        assert kwargs["project_id"] == project.id
        assert kwargs["max_items"] == 10
        return KG_CONTEXT

    monkeypatch.setattr(
        kg_ctx, "collect_knowledge_graph_ai_context", fake_collect
    )
    monkeypatch.setattr(ai, "is_enabled", lambda: True)

    seen: dict = {}

    async def fake_plan(**kwargs):
        seen.update(kwargs)
        return []  # AI reachable, nothing planned — loop returns [] early

    monkeypatch.setattr(ai, "plan", fake_plan)

    cards = await hi.run_ai_intelligence(
        project,
        hi.ProjectContext(tables=[], documents=[]),
        runner=None,
        session=db_session,
        tenant_id=1,
        user_id=1,
    )
    assert cards == []
    assert seen["knowledge_graph_context"] == KG_CONTEXT


async def test_plan_proceeds_when_kg_collect_fails(db_session, monkeypatch):
    import app.services.ai_intelligence_client as ai
    import app.services.knowledge_graph_ai_context as kg_ctx

    project = Project(tenant_id=1, name="NoGraph", owner_id=1, is_shared=False)
    db_session.add(project)
    await db_session.flush()

    async def boom(session, **kwargs):
        raise RuntimeError("graph exploded")

    monkeypatch.setattr(kg_ctx, "collect_knowledge_graph_ai_context", boom)
    monkeypatch.setattr(ai, "is_enabled", lambda: True)

    seen: dict = {}

    async def fake_plan(**kwargs):
        seen.update(kwargs)
        return []

    monkeypatch.setattr(ai, "plan", fake_plan)

    cards = await hi.run_ai_intelligence(
        project,
        hi.ProjectContext(tables=[], documents=[]),
        runner=None,
        session=db_session,
        tenant_id=1,
        user_id=1,
    )
    assert cards == []  # the failure degraded to an empty block, not an error
    assert seen["knowledge_graph_context"] == {}


# ── 1b: snapshot staleness stamp ─────────────────────────────────────


async def test_snapshot_fresh_when_no_kg_build_postdates_it(client, db_session):
    db_session.add(
        IntelligenceSnapshot(
            tenant_id=1,
            user_id=1,
            granularity=3,
            payload={"projects": [{"id": "1", "name": "P1"}], "results": []},
        )
    )
    await db_session.commit()

    r = await client.get(
        "/api/ai/home-intelligence/snapshot", headers=_headers(1, 1)
    )
    assert r.status_code == 200, r.text
    snap = r.json()["snapshot"]
    assert snap["stale"] is False
    assert snap["staleProjects"] == []


async def test_snapshot_stale_after_kg_rebuild(client, db_session):
    db_session.add(
        IntelligenceSnapshot(
            tenant_id=1,
            user_id=1,
            granularity=3,
            payload={
                "projects": [{"id": "1", "name": "P1"}, {"id": "2", "name": "P2"}],
                "results": [],
            },
        )
    )
    # Project 1's graph rebuilt after the snapshot; project 2's has not.
    db_session.add(
        KnowledgeGraph(
            tenant_id=1,
            project_id=1,
            lifecycle_status="active",
            enabled=True,
            version=1,
            last_successful_build_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    db_session.add(
        KnowledgeGraph(
            tenant_id=1,
            project_id=2,
            lifecycle_status="active",
            enabled=True,
            version=1,
            last_successful_build_at=datetime.now(UTC) - timedelta(days=1),
        )
    )
    await db_session.commit()

    r = await client.get(
        "/api/ai/home-intelligence/snapshot", headers=_headers(1, 1)
    )
    assert r.status_code == 200, r.text
    snap = r.json()["snapshot"]
    assert snap["stale"] is True
    assert snap["staleProjects"] == ["1"]


async def test_snapshot_null_without_run(client):
    r = await client.get(
        "/api/ai/home-intelligence/snapshot", headers=_headers(1, 9)
    )
    assert r.status_code == 200
    assert r.json() == {"snapshot": None}
