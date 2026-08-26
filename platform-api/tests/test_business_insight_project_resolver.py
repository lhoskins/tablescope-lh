"""Tests for the cross-project resolver's anchor bias.

Live incident: a "backup job failure rate" question, asked from Business
Insight, bounced between two projects across consecutive identical asks
before landing on the right one. resolve_business_insight_project re-scores
the question against every authorized project on *every* turn with no bias
toward a conversation's already-established project, so a vague follow-up
with no clear topical signal can score an unrelated project just high enough
to clear the resolve floor and silently re-pin an already-correct
conversation to the wrong one.

These tests monkeypatch resolve_project_source (already covered by
test_project_source_resolver.py) to return controlled scores, isolating the
new anchor-margin logic itself rather than re-testing the underlying scoring
engine.
"""

from __future__ import annotations

import pytest

from app.auth.context import RequestContext
from app.auth.jwt import TokenClaims
from app.models.project import Project
from app.services import business_insight_project_resolver as bipr
from app.services.project_source_resolver.types import ResolverCandidate, ResolverResult

pytestmark = pytest.mark.anyio

TENANT = 1


def _context() -> RequestContext:
    return RequestContext(
        claims=TokenClaims(sub="u", tenant_id=TENANT, user_id=1, role="admin")
    )


async def _make_projects(session) -> tuple[int, int]:
    """Two plain projects with names that don't overlap the test questions,
    so the fast (explicit project-name) path never fires."""
    a = Project(tenant_id=TENANT, name="Alpha", owner_id=1, is_shared=True)
    b = Project(tenant_id=TENANT, name="Bravo", owner_id=1, is_shared=True)
    session.add_all([a, b])
    await session.flush()
    return a.id, b.id


def _result(score: float) -> ResolverResult:
    if score <= 0:
        return ResolverResult(status="no_match")
    return ResolverResult(
        status="resolved",
        preferred_sources=["some_CSV"],
        confidence=score / 100,
        reason="test",
        candidates=[ResolverCandidate(source="some_CSV", score=score, matched_columns=[], reason="test")],
    )


def _patch_scores(monkeypatch, scores: dict[int, float]) -> None:
    async def fake_resolve_project_source(session, *, tenant_id, project_id, question, intent="question_answer"):
        return _result(scores.get(project_id, 0.0))

    monkeypatch.setattr(bipr, "resolve_project_source", fake_resolve_project_source)


async def test_no_anchor_picks_the_top_scoring_project(db_session, monkeypatch) -> None:
    a, b = await _make_projects(db_session)
    _patch_scores(monkeypatch, {a: 50.0, b: 80.0})
    result = await bipr.resolve_business_insight_project(db_session, _context(), "vague question")
    assert result.status == "resolved"
    assert result.project_id == b


async def test_anchor_holds_when_competitor_only_edges_it_out(db_session, monkeypatch) -> None:
    """A narrow lead (less than the switch margin) is not confident enough
    to move an already-anchored conversation -- this is the exact shape of
    the live incident: the wrong project scored just enough to win outright,
    but not by a meaningful margin over the project the conversation was
    already correctly grounded in."""
    a, b = await _make_projects(db_session)
    _patch_scores(monkeypatch, {a: 50.0, b: 60.0})
    result = await bipr.resolve_business_insight_project(
        db_session, _context(), "vague question", anchor_project_id=a
    )
    assert result.status == "resolved"
    assert result.project_id == a


async def test_anchor_yields_to_a_confidently_better_match(db_session, monkeypatch) -> None:
    """A real topic switch -- the new project clears the anchor's score by
    more than the margin -- still switches, same as before this fix."""
    a, b = await _make_projects(db_session)
    _patch_scores(monkeypatch, {a: 40.0, b: 90.0})
    result = await bipr.resolve_business_insight_project(
        db_session, _context(), "clearly about the other project", anchor_project_id=a
    )
    assert result.status == "resolved"
    assert result.project_id == b


async def test_anchor_ignored_when_question_names_a_different_project(db_session, monkeypatch) -> None:
    """An explicit project-name mention is a deliberate switch, not an
    ambiguous one -- the anchor margin must not block it even when the
    named project's score barely clears the floor."""
    a, b = await _make_projects(db_session)
    _patch_scores(monkeypatch, {a: 90.0, b: 41.0})
    result = await bipr.resolve_business_insight_project(
        db_session, _context(), "Show me Bravo's data", anchor_project_id=a
    )
    assert result.status == "resolved"
    assert result.project_id == b


async def test_no_anchor_project_id_behaves_as_before(db_session, monkeypatch) -> None:
    """Without an anchor (e.g. the first-ever turn in a conversation), the
    top score always wins -- no behavior change from before this fix."""
    a, b = await _make_projects(db_session)
    _patch_scores(monkeypatch, {a: 50.0, b: 55.0})
    result = await bipr.resolve_business_insight_project(db_session, _context(), "vague question")
    assert result.status == "resolved"
    assert result.project_id == b
