"""KG-50: prove downstream Knowledge Graph use with grounded-answer evaluations.

Validated against the real code first: of the six features the review names
(AI Assistant, Business Insights, Project Insights, Executive Brief,
dashboard generation, query generation), only four actually consume
``collect_knowledge_graph_ai_context`` -- business_insights, project_insights,
dashboard_generation, query_generation (confirmed by grepping every
``surface="..."`` call site in app/routes and app/services). AI Assistant's
conversational-turn route never references Knowledge Graph context at all
(reconfirms the same finding from Phase 2/KG-07); "Executive Brief" is a
frontend-only presentation over Business Insight cards with no separate
backend AI-generation path, so it inherits Business Insights' grounding
automatically -- neither needs (or gets) separate wiring here.

This suite proves the "active KG version + evidence IDs in every response
envelope" half of the Accept criterion for the two surfaces most directly
testable without heavy AI-server-pass-through mocking (project_insights,
business_insights): the response's ``kgGrounding`` carries the real active
KG version id and evidence node ids that actually informed it, and never
another project's. Dashboard/query generation wiring is covered by the
(passing) existing regression suites plus code review -- see the Phase's
Devin doc for that scoping decision.

Run from `platform-api`: `pytest -q tests/test_kg50_grounded_answer_evaluations.py`.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.jwt import TokenClaims, create_access_token
from app.models import AIProjectGraphNode, Project
from app.services.knowledge_graph_ai_context import collect_knowledge_graph_ai_context
from app.services.knowledge_graph_lifecycle import KnowledgeGraphLifecycleManager
from app.services.supabase_auth_service import SupabaseAuthService, SupabaseUser

pytestmark = pytest.mark.anyio


class _FakeSupabase(SupabaseAuthService):
    def __init__(self) -> None:
        pass

    async def create_or_invite_user(
        self, email, *, first_name=None, last_name=None, redirect_to=None
    ) -> SupabaseUser:
        return SupabaseUser(id=f"supa-{email}", email=email, created=True, action_link="x")


class _FakeEmail:
    async def send_transactional_email(
        self, *, to, template, variables, subject=None, reply_to=None, **kwargs
    ) -> bool:
        return True


@pytest.fixture(autouse=True)
def _mock_supabase(monkeypatch):
    import app.routes.tenants_users as tenants_module

    monkeypatch.setattr(tenants_module, "SupabaseAuthService", _FakeSupabase)
    monkeypatch.setattr(tenants_module, "EmailService", _FakeEmail)


def _manager(session: AsyncSession, tenant_id: int, user_id: int) -> KnowledgeGraphLifecycleManager:
    return KnowledgeGraphLifecycleManager(
        session,
        RequestContext(
            claims=TokenClaims(sub=str(user_id), tenant_id=tenant_id, user_id=user_id, role="editor")
        ),
    )


def _headers(tenant_id: int, user_id: int) -> dict:
    token = create_access_token(sub="u", tenant_id=tenant_id, user_id=user_id, role="editor")
    return {"Authorization": f"Bearer {token}"}


async def _seeded_project(
    session: AsyncSession, tenant_id: int, user_id: int, slug: str,
) -> tuple[Project, int]:
    """A project with one real, distinctive risk node, fully rebuilt/activated."""
    project = Project(tenant_id=tenant_id, name=f"{slug} Project", owner_id=user_id, is_shared=False)
    session.add(project)
    await session.flush()

    node = AIProjectGraphNode(
        tenant_id=tenant_id, project_id=project.id, node_type="risk",
        name=f"{slug} distinctive risk", created_by=user_id, is_active=True,
    )
    session.add(node)
    await session.flush()

    manager = _manager(session, tenant_id, user_id)
    build, _ = await manager.request_full_rebuild(project.id)
    await session.commit()
    await session.refresh(build)
    await manager.run_full_rebuild(build.id)
    await session.commit()

    return project, node.id


# ── Unit-level: the grounding block itself ─────────────────────────────────

async def test_kg_context_grounding_matches_the_real_active_version_and_evidence(db_session):
    tenant_id, user_id = 901, 1
    project, node_id = await _seeded_project(db_session, tenant_id, user_id, "kg50a")

    graph = await _manager(db_session, tenant_id, user_id).ensure_graph(project.id)
    assert graph.active_version_id is not None

    context = await collect_knowledge_graph_ai_context(
        db_session, tenant_id=tenant_id, project_id=project.id, user_id=user_id,
        surface="project_insights",
    )
    grounding = context["kg_grounding"]
    assert grounding is not None
    assert grounding["kgVersionId"] == graph.active_version_id
    assert node_id in grounding["nodeIds"]


async def test_kg_context_grounding_is_none_with_no_content(db_session):
    tenant_id, user_id = 902, 1
    project = Project(tenant_id=tenant_id, name="kg50b Project", owner_id=user_id, is_shared=False)
    db_session.add(project)
    await db_session.flush()

    context = await collect_knowledge_graph_ai_context(
        db_session, tenant_id=tenant_id, project_id=project.id, user_id=user_id,
        surface="project_insights",
    )
    assert context["kg_grounding"] is None


# ── project_insights: the real HTTP response envelope, cross-project safe ──

@pytest.fixture()
def _mock_project_insight_ai(monkeypatch):
    async def fake(**kwargs):
        return {
            "executiveSummary": {
                "summary": "ok", "critical": [], "warnings": [],
                "opportunities": [], "recommendations": [],
            },
            "questionsToAsk": [], "trendDetection": [],
            "recommendedDashboards": [], "recommendedQueries": [],
            "recommendedKpis": [], "insightValidationWorkflow": [],
            "model_used": "test-model",
        }

    monkeypatch.setattr("app.services.ai_intelligence_client.project_insight", fake)


async def test_project_insight_envelope_carries_kg_grounding_without_cross_project_leak(
    client, db_session, _mock_project_insight_ai,
):
    tenant_a, user_a = 903, 1
    tenant_b, user_b = 904, 2
    project_a, node_a = await _seeded_project(db_session, tenant_a, user_a, "kg50c-a")
    project_b, node_b = await _seeded_project(db_session, tenant_b, user_b, "kg50c-b")

    resp_a = await client.get(
        f"/api/projects/{project_a.id}/insight", headers=_headers(tenant_a, user_a),
    )
    assert resp_a.status_code == 200
    body_a = resp_a.json()
    grounding_a = body_a["kgGrounding"]
    assert grounding_a is not None
    assert node_a in grounding_a["nodeIds"]
    assert node_b not in grounding_a["nodeIds"]

    resp_b = await client.get(
        f"/api/projects/{project_b.id}/insight", headers=_headers(tenant_b, user_b),
    )
    assert resp_b.status_code == 200
    body_b = resp_b.json()
    grounding_b = body_b["kgGrounding"]
    assert grounding_b is not None
    assert node_b in grounding_b["nodeIds"]
    assert node_a not in grounding_b["nodeIds"]
    # Distinct KG versions -- never each other's.
    assert grounding_a["kgVersionId"] != grounding_b["kgVersionId"]


# ── business_insights: the real HTTP response envelope ─────────────────────

async def test_business_insights_envelope_carries_kg_grounding(client, db_session, monkeypatch):
    from app.services import ai_intelligence_client as ai

    monkeypatch.setattr(ai, "is_enabled", lambda: True)

    async def fake_plan(**kwargs):
        return []

    monkeypatch.setattr(ai, "plan", fake_plan)

    tenant_id, user_id = 905, 1
    project, node_id = await _seeded_project(db_session, tenant_id, user_id, "kg50d")

    graph = await _manager(db_session, tenant_id, user_id).ensure_graph(project.id)

    resp = await client.post(
        "/api/ai/run-intelligence-suite",
        json={"project_id": project.id},
        headers=_headers(tenant_id, user_id),
    )
    assert resp.status_code == 200
    body = resp.json()
    grounding = body["kgGrounding"]
    assert grounding is not None
    assert grounding["kgVersionId"] == graph.active_version_id
    assert node_id in grounding["nodeIds"]
