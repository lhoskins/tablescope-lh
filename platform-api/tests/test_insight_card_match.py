"""Tests for matching a conversational question to an existing insight card."""

from __future__ import annotations

import pytest

from app.auth.context import RequestContext
from app.auth.jwt import TokenClaims, create_access_token
from app.models.business_insight_result import BusinessInsightResult
from app.services.insight_card_match import find_matching_insight_card


def _editor_headers(tenant_id: int, user_id: int) -> dict:
    token = create_access_token(
        sub="u", tenant_id=tenant_id, user_id=user_id, role="editor"
    )
    return {"Authorization": f"Bearer {token}"}


def _context(tenant_id: int, user_id: int, role: str = "editor") -> RequestContext:
    return RequestContext(
        claims=TokenClaims(sub="u", tenant_id=tenant_id, user_id=user_id, role=role)
    )


async def _tenant(client, service_headers, slug: str = "icm-tenant"):
    r = await client.post(
        "/api/tenants",
        json={"slug": slug, "name": "Insight Match Tenant"},
        headers=service_headers,
    )
    assert r.status_code == 201
    return r.json()


async def _user_in(client, service_headers, tenant_id: int, email: str):
    r = await client.post(
        f"/api/tenants/{tenant_id}/users",
        json={
            "email": email,
            "display_name": "ICM User",
            "role": "editor",
            "external_id": f"ext-{email}",
        },
        headers=service_headers,
    )
    assert r.status_code == 201
    return r.json()


async def _tenant_and_headers(client, service_headers, slug: str = "icm-tenant"):
    tenant = await _tenant(client, service_headers, slug)
    user = await _user_in(client, service_headers, tenant["id"], "icm@test.com")
    return tenant, user, _editor_headers(tenant["id"], user["id"])


async def _project_in(client, headers, name: str = "MFG Project", is_shared: bool = False):
    r = await client.post(
        "/api/projects",
        json={"name": name, "description": "t", "is_shared": is_shared},
        headers=headers,
    )
    assert r.status_code == 201
    return r.json()


async def _project(client, service_headers, name: str = "MFG Project"):
    tenant, user, headers = await _tenant_and_headers(client, service_headers)
    project = await _project_in(client, headers, name)
    return project, tenant, user


@pytest.fixture(autouse=True)
def _mock_supabase(monkeypatch):
    import app.routes.tenants_users as tenants_module
    from app.services.supabase_auth_service import (
        SupabaseAuthService,
        SupabaseUser,
    )

    class _FakeSupabase(SupabaseAuthService):
        def __init__(self) -> None:
            pass

        async def create_or_invite_user(
            self, email, *, first_name=None, last_name=None, redirect_to=None
        ) -> SupabaseUser:
            return SupabaseUser(
                id=f"supa-{email}", email=email, created=True,
                action_link=f"https://invite/{email}",
            )

    class _FakeEmail:
        async def send_transactional_email(self, *, to, template, variables, subject=None, reply_to=None) -> bool:
            return True

    monkeypatch.setattr(tenants_module, "SupabaseAuthService", _FakeSupabase)
    monkeypatch.setattr(tenants_module, "EmailService", _FakeEmail)


def _card(insight_id: str, title: str, summary: str) -> dict:
    return {
        "insightId": insight_id,
        "projectName": "MFG Project",
        "title": title,
        "summary": summary,
        "chart": {"type": "line", "data": {"rows": []}},
        "severity": "warning",
    }


async def test_matches_card_by_lexical_overlap(client, db_session, service_headers) -> None:
    project, tenant, user = await _project(client, service_headers)
    db_session.add(
        BusinessInsightResult(
            tenant_id=tenant["id"],
            project_id=project["id"],
            granularity=3,
            payload={
                "insights": [
                    _card(
                        "abc123",
                        "Material cost on the rise",
                        "Weekly material cost for the MFG program has increased "
                        "steadily since January 2026.",
                    ),
                    _card(
                        "def456",
                        "Supplier on-time delivery slipping",
                        "SLA breach rate for Supplier A rose last quarter.",
                    ),
                ]
            },
        )
    )
    await db_session.commit()

    match = await find_matching_insight_card(
        db_session,
        context=_context(tenant["id"], user["id"]),
        tenant_id=tenant["id"],
        project_id=project["id"],
        question="Why is material cost increasing?",
    )

    assert match is not None
    assert match.insight_id == "abc123"
    assert match.title == "Material cost on the rise"
    assert match.project_id == project["id"]
    assert match.chart == {"type": "line", "data": {"rows": []}}


async def test_prefers_the_card_whose_title_names_the_topic(
    client, db_session, service_headers
) -> None:
    """Reproduces the reported inconsistency: a vaguely-related card (topic
    only in its summary, if at all) and a precisely-on-topic card (topic in
    its own title) both clear the match threshold. The on-topic one must win
    -- deterministically, regardless of which order the two rows/cards come
    back from the database in."""
    project, tenant, user = await _project(client, service_headers)
    db_session.add(
        BusinessInsightResult(
            tenant_id=tenant["id"],
            project_id=project["id"],
            granularity=3,
            payload={
                "insights": [
                    _card(
                        "vendor-spend",
                        "Vendor Spend Over Time (by Category): Cost "
                        "Optimization Opportunities",
                        "Category-level vendor spend trends, including "
                        "material and indirect cost categories, tracked "
                        "over the last four quarters.",
                    ),
                    _card(
                        "material-cost",
                        "Material Cost Over Time Indicates Potential Risks",
                        "Material cost has risen month over month; the "
                        "trend correlates with a known supplier issue.",
                    ),
                ]
            },
        )
    )
    await db_session.commit()

    for question in (
        "Why is material cost increasing?",
        "Why is material cost rising?",
    ):
        match = await find_matching_insight_card(
            db_session,
            context=_context(tenant["id"], user["id"]),
            tenant_id=tenant["id"],
            project_id=project["id"],
            question=question,
        )
        assert match is not None
        assert match.insight_id == "material-cost", (
            f"question {question!r} resolved to {match.insight_id!r}, "
            "expected the card whose own title names the topic"
        )


async def test_no_match_below_threshold(client, db_session, service_headers) -> None:
    project, tenant, user = await _project(client, service_headers)
    db_session.add(
        BusinessInsightResult(
            tenant_id=tenant["id"],
            project_id=project["id"],
            granularity=3,
            payload={
                "insights": [
                    _card(
                        "abc123",
                        "Supplier on-time delivery slipping",
                        "SLA breach rate for Supplier A rose last quarter.",
                    ),
                ]
            },
        )
    )
    await db_session.commit()

    match = await find_matching_insight_card(
        db_session,
        context=_context(tenant["id"], user["id"]),
        tenant_id=tenant["id"],
        project_id=project["id"],
        question="Why is material cost increasing?",
    )

    assert match is None


async def test_widens_to_other_accessible_projects_when_resolved_project_has_no_match(
    client, db_session, service_headers
) -> None:
    """Project routing and Insight Card generation are separate pipelines and
    can disagree on which project "owns" a topic. A card in a project the
    user can access, but that isn't the one this question resolved to, must
    still be found."""
    tenant, user, headers = await _tenant_and_headers(client, service_headers)
    resolved_project = await _project_in(client, headers, name="IT Project")
    card_project = await _project_in(client, headers, name="Finance Project")

    db_session.add(
        BusinessInsightResult(
            tenant_id=tenant["id"],
            project_id=card_project["id"],
            granularity=3,
            payload={
                "insights": [
                    _card(
                        "abc123",
                        "Material cost on the rise",
                        "Weekly material cost has increased steadily since January.",
                    ),
                ]
            },
        )
    )
    await db_session.commit()

    match = await find_matching_insight_card(
        db_session,
        context=_context(tenant["id"], user["id"]),
        tenant_id=tenant["id"],
        project_id=resolved_project["id"],
        question="Why is material cost increasing?",
    )

    assert match is not None
    assert match.insight_id == "abc123"
    assert match.project_id == card_project["id"]


async def test_never_widens_into_a_project_the_user_cannot_access(
    client, db_session, service_headers
) -> None:
    """The widened search must stay inside the caller's own authorization —
    a perfectly matching card in another user's private, unshared project in
    the same tenant must never surface, no matter how well it scores."""
    tenant = await _tenant(client, service_headers)
    owner = await _user_in(client, service_headers, tenant["id"], "owner@test.com")
    owner_headers = _editor_headers(tenant["id"], owner["id"])
    private_project = await _project_in(
        client, owner_headers, name="Finance Project", is_shared=False
    )

    db_session.add(
        BusinessInsightResult(
            tenant_id=tenant["id"],
            project_id=private_project["id"],
            granularity=3,
            payload={
                "insights": [
                    _card(
                        "abc123",
                        "Material cost on the rise",
                        "Weekly material cost has increased steadily since January.",
                    ),
                ]
            },
        )
    )
    await db_session.commit()

    other_user = await _user_in(client, service_headers, tenant["id"], "other@test.com")
    other_headers = _editor_headers(tenant["id"], other_user["id"])
    other_project = await _project_in(client, other_headers, name="IT Project")

    match = await find_matching_insight_card(
        db_session,
        context=_context(tenant["id"], other_user["id"]),
        tenant_id=tenant["id"],
        project_id=other_project["id"],
        question="Why is material cost increasing?",
    )

    assert match is None


async def test_no_terms_returns_none(client, db_session, service_headers) -> None:
    project, tenant, user = await _project(client, service_headers)

    match = await find_matching_insight_card(
        db_session,
        context=_context(tenant["id"], user["id"]),
        tenant_id=tenant["id"],
        project_id=project["id"],
        question="???",
    )

    assert match is None
