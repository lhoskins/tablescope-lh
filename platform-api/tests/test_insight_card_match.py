"""Tests for matching a conversational question to an existing insight card.

Relevance judgment is LLM-driven (``ai_intelligence_client.select_matching_insight_card``,
mocked below), not a local heuristic -- these tests cover what
``insight_card_match.py`` itself is responsible for: which cards get
offered as candidates at all (access control, project-scoping, the
resolved-project-first/widen-on-miss search order) and how the model's
decision gets trusted or rejected, not what "good" relevance looks like.
"""

from __future__ import annotations

import pytest

from app.auth.context import RequestContext
from app.auth.jwt import TokenClaims, create_access_token
from app.models.business_insight_result import BusinessInsightResult
from app.models.project_intelligence_snapshot import ProjectIntelligenceSnapshot
from app.services import insight_card_match as icm
from app.services.ai_intelligence_client import AIUnavailableError


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


@pytest.fixture(autouse=True)
def _ai_enabled(monkeypatch):
    monkeypatch.setattr(icm.ai_intelligence_client, "is_enabled", lambda: True)


def _card(insight_id: str, title: str, summary: str) -> dict:
    return {
        "insightId": insight_id,
        "projectName": "MFG Project",
        "title": title,
        "summary": summary,
        "chart": {"type": "line", "data": {"rows": []}},
        "severity": "warning",
    }


def _mock_select(monkeypatch, fn):
    monkeypatch.setattr(icm.ai_intelligence_client, "select_matching_insight_card", fn)


async def test_returns_the_llm_chosen_card(
    client, db_session, service_headers, monkeypatch
) -> None:
    project, tenant, user = await _project(client, service_headers)
    db_session.add(
        BusinessInsightResult(
            tenant_id=tenant["id"],
            project_id=project["id"],
            granularity=3,
            payload={
                "insights": [
                    _card("abc123", "Material cost on the rise", "..."),
                    _card("def456", "Supplier on-time delivery slipping", "..."),
                ]
            },
        )
    )
    await db_session.commit()

    captured: dict = {}

    async def _fake_select(**kwargs):
        captured.update(kwargs)
        return {"insight_id": "abc123", "confidence": 0.9, "reason": "on topic"}

    _mock_select(monkeypatch, _fake_select)

    match = await icm.find_matching_insight_card(
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

    # Both candidates in the resolved project were offered -- the model
    # judges relevance, this module never pre-filters by its own guess.
    offered_ids = {c["insight_id"] for c in captured["candidates"]}
    assert offered_ids == {"abc123", "def456"}
    assert captured["question"] == "Why is material cost increasing?"


async def test_offers_the_callers_project_insight_snapshot_cards(
    client, db_session, service_headers, monkeypatch
) -> None:
    """A card that only exists in the caller's on-demand Project Insight
    snapshot (never the hourly-refreshed Business Insight cache) must still
    be offered to the selector -- otherwise a question naming it can only
    ever be answered by an unrelated cached card, if any."""
    project, tenant, user = await _project(client, service_headers)
    db_session.add(
        ProjectIntelligenceSnapshot(
            tenant_id=tenant["id"],
            user_id=user["id"],
            project_id=project["id"],
            suite="project_insight",
            payload={
                "risks": [
                    _card(
                        "snap789",
                        "Material Costs vs Scrap Rate Trend",
                        "Material costs are rising alongside scrap rate.",
                    )
                ]
            },
        )
    )
    await db_session.commit()

    captured: dict = {}

    async def _fake_select(**kwargs):
        captured.update(kwargs)
        return {"insight_id": "snap789", "confidence": 0.9, "reason": "on topic"}

    _mock_select(monkeypatch, _fake_select)

    match = await icm.find_matching_insight_card(
        db_session,
        context=_context(tenant["id"], user["id"]),
        tenant_id=tenant["id"],
        project_id=project["id"],
        question="Why is material cost increasing?",
    )

    assert match is not None
    assert match.insight_id == "snap789"
    assert match.title == "Material Costs vs Scrap Rate Trend"
    offered_ids = {c["insight_id"] for c in captured["candidates"]}
    assert "snap789" in offered_ids


async def test_snapshot_card_skipped_when_cache_already_has_the_title(
    client, db_session, service_headers, monkeypatch
) -> None:
    """The shared Business Insight cache is authoritative on a title
    collision -- the snapshot only supplements what the cache is missing."""
    project, tenant, user = await _project(client, service_headers)
    db_session.add(
        BusinessInsightResult(
            tenant_id=tenant["id"],
            project_id=project["id"],
            granularity=3,
            payload={
                "insights": [_card("cache111", "Material cost on the rise", "...")]
            },
        )
    )
    db_session.add(
        ProjectIntelligenceSnapshot(
            tenant_id=tenant["id"],
            user_id=user["id"],
            project_id=project["id"],
            suite="project_insight",
            payload={
                "risks": [
                    _card("snap222", "Material cost on the rise", "duplicate title")
                ]
            },
        )
    )
    await db_session.commit()

    captured: dict = {}

    async def _fake_select(**kwargs):
        captured.update(kwargs)
        return {"insight_id": "cache111", "confidence": 0.9, "reason": "on topic"}

    _mock_select(monkeypatch, _fake_select)

    match = await icm.find_matching_insight_card(
        db_session,
        context=_context(tenant["id"], user["id"]),
        tenant_id=tenant["id"],
        project_id=project["id"],
        question="Why is material cost increasing?",
    )

    assert match is not None
    assert match.insight_id == "cache111"
    offered_ids = {c["insight_id"] for c in captured["candidates"]}
    assert offered_ids == {"cache111"}


async def test_llm_decline_returns_no_match(
    client, db_session, service_headers, monkeypatch
) -> None:
    project, tenant, user = await _project(client, service_headers)
    db_session.add(
        BusinessInsightResult(
            tenant_id=tenant["id"],
            project_id=project["id"],
            granularity=3,
            payload={"insights": [_card("abc123", "Supplier on-time delivery slipping", "...")]},
        )
    )
    await db_session.commit()

    async def _fake_select(**kwargs):
        return {"insight_id": None, "confidence": 0.0, "reason": "no candidate is on topic"}

    _mock_select(monkeypatch, _fake_select)

    match = await icm.find_matching_insight_card(
        db_session,
        context=_context(tenant["id"], user["id"]),
        tenant_id=tenant["id"],
        project_id=project["id"],
        question="Why is material cost increasing?",
    )

    assert match is None


async def test_rejects_an_id_the_model_was_not_offered(
    client, db_session, service_headers, monkeypatch
) -> None:
    """Defense in depth: even though the ai-server endpoint already enforces
    this, the platform must never trust an id it didn't actually offer as a
    candidate, in case that validation is ever weakened independently."""
    project, tenant, user = await _project(client, service_headers)
    db_session.add(
        BusinessInsightResult(
            tenant_id=tenant["id"],
            project_id=project["id"],
            granularity=3,
            payload={"insights": [_card("abc123", "Material cost on the rise", "...")]},
        )
    )
    await db_session.commit()

    async def _fake_select(**kwargs):
        return {"insight_id": "not-a-real-id", "confidence": 0.9, "reason": "hallucinated"}

    _mock_select(monkeypatch, _fake_select)

    match = await icm.find_matching_insight_card(
        db_session,
        context=_context(tenant["id"], user["id"]),
        tenant_id=tenant["id"],
        project_id=project["id"],
        question="Why is material cost increasing?",
    )

    assert match is None


async def test_no_cards_never_calls_the_model(
    client, db_session, service_headers, monkeypatch
) -> None:
    project, tenant, user = await _project(client, service_headers)

    async def _fail_if_called(**kwargs):
        raise AssertionError("selector must not be called with no candidates")

    _mock_select(monkeypatch, _fail_if_called)

    match = await icm.find_matching_insight_card(
        db_session,
        context=_context(tenant["id"], user["id"]),
        tenant_id=tenant["id"],
        project_id=project["id"],
        question="Why is material cost increasing?",
    )

    assert match is None


async def test_ai_disabled_returns_none_without_calling_selector(
    client, db_session, service_headers, monkeypatch
) -> None:
    project, tenant, user = await _project(client, service_headers)
    db_session.add(
        BusinessInsightResult(
            tenant_id=tenant["id"],
            project_id=project["id"],
            granularity=3,
            payload={"insights": [_card("abc123", "Material cost on the rise", "...")]},
        )
    )
    await db_session.commit()

    monkeypatch.setattr(icm.ai_intelligence_client, "is_enabled", lambda: False)

    async def _fail_if_called(**kwargs):
        raise AssertionError("selector must not be called when AI is disabled")

    _mock_select(monkeypatch, _fail_if_called)

    match = await icm.find_matching_insight_card(
        db_session,
        context=_context(tenant["id"], user["id"]),
        tenant_id=tenant["id"],
        project_id=project["id"],
        question="Why is material cost increasing?",
    )

    assert match is None


async def test_selector_unavailable_degrades_to_no_match(
    client, db_session, service_headers, monkeypatch
) -> None:
    project, tenant, user = await _project(client, service_headers)
    db_session.add(
        BusinessInsightResult(
            tenant_id=tenant["id"],
            project_id=project["id"],
            granularity=3,
            payload={"insights": [_card("abc123", "Material cost on the rise", "...")]},
        )
    )
    await db_session.commit()

    async def _fake_unavailable(**kwargs):
        raise AIUnavailableError("AI server timed out; retry shortly.")

    _mock_select(monkeypatch, _fake_unavailable)

    match = await icm.find_matching_insight_card(
        db_session,
        context=_context(tenant["id"], user["id"]),
        tenant_id=tenant["id"],
        project_id=project["id"],
        question="Why is material cost increasing?",
    )

    assert match is None


async def test_low_confidence_pick_is_treated_as_a_decline_and_widens(
    client, db_session, service_headers, monkeypatch
) -> None:
    """Reproduces the reported production case: the resolved project only
    has a tangentially-related card ("Vendor Spend..." for a material-cost
    question). The model is expected to decline per its own best-practices
    doc, but is not guaranteed to -- if it instead returns a weak, non-zero
    confidence pick, that must still be treated as a decline so the search
    widens to the other project that actually has the on-topic card, rather
    than locking in on whatever the resolved project happened to offer."""
    tenant, user, headers = await _tenant_and_headers(client, service_headers)
    resolved_project = await _project_in(client, headers, name="IT Project")
    card_project = await _project_in(client, headers, name="Finance Project")

    db_session.add(
        BusinessInsightResult(
            tenant_id=tenant["id"],
            project_id=resolved_project["id"],
            granularity=3,
            payload={
                "insights": [
                    _card(
                        "vendor1",
                        "Vendor Spend vs Data Classification Over Time",
                        "Category-level vendor spend, only mentions cost in passing.",
                    )
                ]
            },
        )
    )
    db_session.add(
        BusinessInsightResult(
            tenant_id=tenant["id"],
            project_id=card_project["id"],
            granularity=3,
            payload={
                "insights": [
                    _card(
                        "material1",
                        "Material Cost Over Time Indicates Potential Risks",
                        "Material cost has risen month over month.",
                    )
                ]
            },
        )
    )
    await db_session.commit()

    async def _fake_select(*, candidates, **kwargs):
        ids = [c["insight_id"] for c in candidates]
        if "material1" in ids:
            return {"insight_id": "material1", "confidence": 0.9, "reason": "on topic"}
        # The resolved project's only candidate is tangential -- a weak,
        # non-zero confidence pick rather than a clean decline.
        return {"insight_id": "vendor1", "confidence": 0.35, "reason": "mentions cost"}

    _mock_select(monkeypatch, _fake_select)

    match = await icm.find_matching_insight_card(
        db_session,
        context=_context(tenant["id"], user["id"]),
        tenant_id=tenant["id"],
        project_id=resolved_project["id"],
        question="Why is material cost increasing?",
    )

    assert match is not None
    assert match.insight_id == "material1"


async def test_widens_to_other_accessible_projects_when_resolved_project_has_no_match(
    client, db_session, service_headers, monkeypatch
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
            payload={"insights": [_card("abc123", "Material cost on the rise", "...")]},
        )
    )
    await db_session.commit()

    calls: list[list[str]] = []

    async def _fake_select(*, candidates, **kwargs):
        ids = [c["insight_id"] for c in candidates]
        calls.append(ids)
        if "abc123" in ids:
            return {"insight_id": "abc123", "confidence": 0.9, "reason": "on topic"}
        return {"insight_id": None, "confidence": 0.0, "reason": "nothing here"}

    _mock_select(monkeypatch, _fake_select)

    match = await icm.find_matching_insight_card(
        db_session,
        context=_context(tenant["id"], user["id"]),
        tenant_id=tenant["id"],
        project_id=resolved_project["id"],
        question="Why is material cost increasing?",
    )

    assert match is not None
    assert match.insight_id == "abc123"
    assert match.project_id == card_project["id"]
    # The resolved project (IT) has no cards at all, so the selector is
    # never called for it -- nothing to offer -- and the search widens
    # straight to the accessible-projects pass, which finds the card.
    assert calls == [["abc123"]]


async def test_never_widens_into_a_project_the_user_cannot_access(
    client, db_session, service_headers, monkeypatch
) -> None:
    """The widened search must stay inside the caller's own authorization --
    a card in another user's private, unshared project in the same tenant
    must never even be offered as a candidate, no matter how eager to match
    the model is."""
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
            payload={"insights": [_card("abc123", "Material cost on the rise", "...")]},
        )
    )
    await db_session.commit()

    other_user = await _user_in(client, service_headers, tenant["id"], "other@test.com")
    other_headers = _editor_headers(tenant["id"], other_user["id"])
    other_project = await _project_in(client, other_headers, name="IT Project")

    all_offered_ids: list[str] = []

    async def _eager_select(*, candidates, **kwargs):
        # Deliberately maximally eager: "match" whatever it's given, to prove
        # the private card is excluded at the offering stage, not because
        # the model happened to decline it.
        all_offered_ids.extend(c["insight_id"] for c in candidates)
        if candidates:
            return {"insight_id": candidates[0]["insight_id"], "confidence": 1.0, "reason": "eager"}
        return {"insight_id": None, "confidence": 0.0, "reason": "nothing offered"}

    _mock_select(monkeypatch, _eager_select)

    match = await icm.find_matching_insight_card(
        db_session,
        context=_context(tenant["id"], other_user["id"]),
        tenant_id=tenant["id"],
        project_id=other_project["id"],
        question="Why is material cost increasing?",
    )

    assert match is None
    assert "abc123" not in all_offered_ids


async def test_allow_cross_project_false_never_widens(
    client, db_session, service_headers, monkeypatch
) -> None:
    """Project Insights (and a card's own follow-up box) are pinned to one
    project by the surface itself -- widening there would answer from a
    different project than the page the question was asked on. This must
    stay scoped even though the same user can access the other project and
    it does hold a matching card."""
    tenant, user, headers = await _tenant_and_headers(client, service_headers)
    resolved_project = await _project_in(client, headers, name="IT Project")
    card_project = await _project_in(client, headers, name="Finance Project")

    db_session.add(
        BusinessInsightResult(
            tenant_id=tenant["id"],
            project_id=card_project["id"],
            granularity=3,
            payload={"insights": [_card("abc123", "Material cost on the rise", "...")]},
        )
    )
    await db_session.commit()

    calls: list[list[str]] = []

    async def _fake_select(*, candidates, **kwargs):
        calls.append([c["insight_id"] for c in candidates])
        return {"insight_id": None, "confidence": 0.0, "reason": "nothing here"}

    _mock_select(monkeypatch, _fake_select)

    match = await icm.find_matching_insight_card(
        db_session,
        context=_context(tenant["id"], user["id"]),
        tenant_id=tenant["id"],
        project_id=resolved_project["id"],
        question="Why is material cost increasing?",
        allow_cross_project=False,
    )

    assert match is None
    # The resolved project (IT) has no cards, so the selector is never even
    # called -- and critically, the widen pass to Finance never runs either.
    assert calls == []


# --- _data_shape_score --------------------------------------------------
#
# Live incident: "Can you tell me the backup job failure rate?" -- answered
# directly by a live SQL query against it_backup_jobs_CSV -- still surfaced
# an unrelated Quality-category CAPA-aging card alongside the answer. The
# card's summary had no genuine overlap with the question's subject, but its
# text happened to contain filler words like "rate", and the pre-fix scorer
# counted *any* question-term appearing anywhere in the card's chart/summary
# text toward the match score, generic filler words included. These tests
# exercise the scorer directly (a pure function, no DB/LLM involved) to
# confirm generic-term-only overlap no longer scores above zero.


def _capa_style_card() -> dict:
    return {
        "insightId": "capa-001",
        "projectName": "Quality Project",
        "title": "High-severity CAPAs aging with limited closure velocity",
        "summary": (
            "Certification risk is distributed across documentation "
            "control, production execution, and audit process at a "
            "steady closure rate for open jobs across systems."
        ),
        "chart": {
            "type": "bar",
            "data": {"series": []},
            "roles": {"x": "Severity", "y": "DaysOpen"},
        },
    }


def test_data_shape_score_ignores_generic_filler_overlap() -> None:
    """A card with zero subject-specific overlap must score 0, even though
    the question and the card both happen to contain generic filler words
    ("rate" in "closure rate", "job" in "open jobs") that mean nothing about
    whether the card is actually about backup jobs. Before the fix, this
    exact filler-only overlap scored 2 -- enough, combined with a series
    subject bonus, to clear the 0.65 confidence floor and surface this card
    as if it answered a "backup job failure rate" question, which is
    precisely what was reported live."""
    card = _capa_style_card()
    score = icm._data_shape_score("Can you tell me the backup job failure rate?", card)
    assert score == 0.0


def test_data_shape_score_still_rewards_genuine_subject_overlap() -> None:
    """A card whose series/summary genuinely discusses the question's
    subject must still score above zero -- the fix removes credit for
    generic filler, not for real topical matches."""
    card = {
        "insightId": "backup-001",
        "projectName": "IT Project",
        "title": "Backup job failures climbing",
        "summary": "Backup job failures have increased across most systems this quarter.",
        "chart": {
            "type": "line",
            "data": {"series": []},
            "roles": {"x": "Month", "y": "BackupFailures"},
        },
    }
    score = icm._data_shape_score("Can you tell me the backup job failure rate?", card)
    assert score > 0.0
