"""Tests for matching a conversational question to an existing insight card."""

from __future__ import annotations

import pytest

from app.auth.jwt import create_access_token
from app.models.business_insight_result import BusinessInsightResult
from app.services.insight_card_match import find_matching_insight_card


def _editor_headers(tenant_id: int, user_id: int) -> dict:
    token = create_access_token(
        sub="u", tenant_id=tenant_id, user_id=user_id, role="editor"
    )
    return {"Authorization": f"Bearer {token}"}


async def _tenant_and_headers(client, service_headers):
    r = await client.post(
        "/api/tenants",
        json={"slug": "icm-tenant", "name": "Insight Match Tenant"},
        headers=service_headers,
    )
    assert r.status_code == 201
    tenant = r.json()
    r = await client.post(
        f"/api/tenants/{tenant['id']}/users",
        json={
            "email": "icm@test.com",
            "display_name": "ICM User",
            "role": "editor",
            "external_id": "ext-icm",
        },
        headers=service_headers,
    )
    assert r.status_code == 201
    user = r.json()
    return tenant, _editor_headers(tenant["id"], user["id"])


async def _project_in(client, headers, name: str = "MFG Project"):
    r = await client.post(
        "/api/projects",
        json={"name": name, "description": "t", "is_shared": False},
        headers=headers,
    )
    assert r.status_code == 201
    return r.json()


async def _project(client, service_headers, name: str = "MFG Project"):
    tenant, headers = await _tenant_and_headers(client, service_headers)
    project = await _project_in(client, headers, name)
    return project, tenant


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
    project, tenant = await _project(client, service_headers)
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
        tenant_id=tenant["id"],
        project_id=project["id"],
        question="Why is material cost increasing?",
    )

    assert match is not None
    assert match.insight_id == "abc123"
    assert match.title == "Material cost on the rise"
    assert match.chart == {"type": "line", "data": {"rows": []}}


async def test_no_match_below_threshold(client, db_session, service_headers) -> None:
    project, tenant = await _project(client, service_headers)
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
        tenant_id=tenant["id"],
        project_id=project["id"],
        question="Why is material cost increasing?",
    )

    assert match is None


async def test_scoped_to_the_given_project_only(client, db_session, service_headers) -> None:
    tenant, headers = await _tenant_and_headers(client, service_headers)
    project_a = await _project_in(client, headers, name="MFG Project")
    project_b = await _project_in(client, headers, name="IT Project")
    db_session.add(
        BusinessInsightResult(
            tenant_id=tenant["id"],
            project_id=project_a["id"],
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

    # The exact same matching question, scoped to a different project, must
    # not surface project_a's card.
    match = await find_matching_insight_card(
        db_session,
        tenant_id=tenant["id"],
        project_id=project_b["id"],
        question="Why is material cost increasing?",
    )

    assert match is None


async def test_no_terms_returns_none(client, db_session, service_headers) -> None:
    project, tenant = await _project(client, service_headers)

    match = await find_matching_insight_card(
        db_session,
        tenant_id=tenant["id"],
        project_id=project["id"],
        question="???",
    )

    assert match is None
