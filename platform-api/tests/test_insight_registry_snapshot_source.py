"""Tests for load_tenant_insight_cards pulling in Project Insight snapshot cards.

The Ask-anything matcher only ever read the shared Business Insight cache
(``business_insight_results``), populated by an hourly background refresh. The
Project Insight page's "Risks"/"Trends"/etc. cards come from a separate
on-demand run cached per-user in ``project_intelligence_snapshots`` and never
land in the shared cache — so a card visible on screen could be unfindable by
the matcher. This covers the fix: those snapshot cards are merged in as a
supplement, scoped to the caller's own project snapshot.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BusinessInsightResult, Project, ProjectIntelligenceSnapshot, Tenant, User
from app.services.insight_registry import load_tenant_insight_cards

pytestmark = pytest.mark.anyio


async def _tenant_user_project(session: AsyncSession, slug: str):
    tenant = Tenant(slug=slug, name=f"{slug} tenant", is_active=True)
    session.add(tenant)
    await session.flush()
    user = User(
        tenant_id=tenant.id,
        email=f"{slug}@example.com",
        password_hash="x",
        role="member",
        is_active=True,
    )
    session.add(user)
    await session.flush()
    project = Project(
        tenant_id=tenant.id, name=f"{slug} Project", owner_id=user.id, is_shared=False
    )
    session.add(project)
    await session.flush()
    return tenant, user, project


async def test_snapshot_cards_are_included_when_business_insight_cache_lacks_them(
    db_session,
):
    tenant, user, project = await _tenant_user_project(db_session, "snap-merge")

    db_session.add(
        BusinessInsightResult(
            tenant_id=tenant.id,
            project_id=project.id,
            granularity=3,
            payload={
                "insights": [
                    {"insightId": "b1", "title": "Vendor Spend vs Data Classification"}
                ]
            },
        )
    )
    db_session.add(
        ProjectIntelligenceSnapshot(
            tenant_id=tenant.id,
            user_id=user.id,
            project_id=project.id,
            suite="project_insight",
            payload={
                "risks": [
                    {
                        "insightId": "p1",
                        "title": "Material Costs vs Scrap Rate Trend",
                        "summary": "Material costs rose alongside scrap rate.",
                        "sql": "SELECT month, material_cost, scrap_rate FROM production_costs",
                        "sourceTables": ["production_costs"],
                    }
                ]
            },
        )
    )
    await db_session.flush()

    cards = await load_tenant_insight_cards(
        db_session, tenant_id=tenant.id, project_id=project.id, user_id=user.id
    )

    titles = {c["title"] for c in cards}
    assert "Vendor Spend vs Data Classification" in titles
    assert "Material Costs vs Scrap Rate Trend" in titles

    snap_card = next(c for c in cards if c["title"] == "Material Costs vs Scrap Rate Trend")
    assert snap_card["sources"] == {"tables": ["production_costs"]}


async def test_business_insight_cache_wins_on_title_collision(db_session):
    tenant, user, project = await _tenant_user_project(db_session, "snap-collide")

    db_session.add(
        BusinessInsightResult(
            tenant_id=tenant.id,
            project_id=project.id,
            granularity=3,
            payload={
                "insights": [
                    {
                        "insightId": "b1",
                        "title": "Scrap Rate Trend",
                        "sql": "SELECT * FROM shared_cache_version",
                    }
                ]
            },
        )
    )
    db_session.add(
        ProjectIntelligenceSnapshot(
            tenant_id=tenant.id,
            user_id=user.id,
            project_id=project.id,
            suite="project_insight",
            payload={
                "risks": [
                    {
                        "insightId": "p1",
                        "title": "Scrap Rate Trend",
                        "sql": "SELECT * FROM snapshot_version",
                    }
                ]
            },
        )
    )
    await db_session.flush()

    cards = await load_tenant_insight_cards(
        db_session, tenant_id=tenant.id, project_id=project.id, user_id=user.id
    )

    matches = [c for c in cards if c["title"] == "Scrap Rate Trend"]
    assert len(matches) == 1
    assert matches[0]["sql"] == "SELECT * FROM shared_cache_version"


async def test_snapshot_lookup_skipped_without_user_id(db_session):
    tenant, user, project = await _tenant_user_project(db_session, "snap-no-user")

    db_session.add(
        ProjectIntelligenceSnapshot(
            tenant_id=tenant.id,
            user_id=user.id,
            project_id=project.id,
            suite="project_insight",
            payload={"risks": [{"insightId": "p1", "title": "Only In Snapshot"}]},
        )
    )
    await db_session.flush()

    cards = await load_tenant_insight_cards(
        db_session, tenant_id=tenant.id, project_id=project.id
    )
    assert cards == []


async def test_snapshot_lookup_skipped_for_tenant_wide_question(db_session):
    """No project_id (e.g. the Business Insight home page) never touches the
    per-project snapshot table — there is no single project to scope it to."""
    tenant, user, project = await _tenant_user_project(db_session, "snap-no-project")

    db_session.add(
        ProjectIntelligenceSnapshot(
            tenant_id=tenant.id,
            user_id=user.id,
            project_id=project.id,
            suite="project_insight",
            payload={"risks": [{"insightId": "p1", "title": "Only In Snapshot"}]},
        )
    )
    await db_session.flush()

    cards = await load_tenant_insight_cards(
        db_session, tenant_id=tenant.id, user_id=user.id
    )
    assert cards == []


async def test_snapshot_scoped_to_caller_not_other_users(db_session):
    tenant, user, project = await _tenant_user_project(db_session, "snap-scope")
    other_user = User(
        tenant_id=tenant.id,
        email="other-snap-scope@example.com",
        password_hash="x",
        role="member",
        is_active=True,
    )
    db_session.add(other_user)
    await db_session.flush()

    db_session.add(
        ProjectIntelligenceSnapshot(
            tenant_id=tenant.id,
            user_id=other_user.id,
            project_id=project.id,
            suite="project_insight",
            payload={"risks": [{"insightId": "p1", "title": "Other User Card"}]},
        )
    )
    await db_session.flush()

    cards = await load_tenant_insight_cards(
        db_session, tenant_id=tenant.id, project_id=project.id, user_id=user.id
    )
    assert cards == []
