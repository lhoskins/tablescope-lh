"""Tests for the upfront reference-catalog routing check.

A question naming a real Reference Library document or Industry KPI/tag
catalog entry by its actual key/name/acronym (e.g. "tell me about SCOR")
should route straight to a reference answer -- *before* SQL generation is
ever attempted, not as a fallback after generation fails. This is a
deliberately exact/deterministic match against real catalog content, never
a fuzzy relevance score: a question that doesn't name anything real must
still fall through to normal SQL generation and hard-error if that fails,
with no guessing either way.

Run from ``platform-api``: ``pytest -q tests/test_question_names_reference_entry.py``.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.models.ai_reference_catalog import AIReferenceCatalog, AIReferenceKPI
from app.models.reference_library import TIER_INDUSTRY, ReferenceDocument
from app.models.tenant import Tenant
from app.services.ai_grounding import question_names_reference_entry

pytestmark = pytest.mark.anyio


async def _seed_catalog_kpi(db_session, *, kpi_key: str, display_name: str) -> None:
    catalog = AIReferenceCatalog(
        catalog_key="test_supply_chain",
        name="Test Supply Chain",
        industry="supply_chain",
        is_system=True,
        is_active=True,
    )
    db_session.add(catalog)
    await db_session.flush()
    db_session.add(
        AIReferenceKPI(
            catalog_id=catalog.id,
            kpi_key=kpi_key,
            display_name=display_name,
            industry="supply_chain",
            is_active=True,
        )
    )
    await db_session.commit()


async def _seed_reference_document(db_session, *, title: str, tenant_id: int) -> None:
    db_session.add(
        ReferenceDocument(tier=TIER_INDUSTRY, title=title, status="active")
    )
    await db_session.commit()


async def test_matches_a_kpi_by_its_key(db_session):
    await _seed_catalog_kpi(db_session, kpi_key="scor", display_name="SCOR Model")
    assert await question_names_reference_entry(
        db_session, tenant_id=1, project_id=1, question="Tell me about SCOR"
    )


async def test_matches_a_document_title_by_acronym(db_session):
    await _seed_reference_document(
        db_session, title="SCOR Framework Overview", tenant_id=1
    )
    assert await question_names_reference_entry(
        db_session, tenant_id=1, project_id=1, question="Please tell me about SCOR"
    )


async def test_does_not_match_when_nothing_real_is_named(db_session):
    await _seed_catalog_kpi(
        db_session, kpi_key="oee", display_name="Overall Equipment Effectiveness"
    )
    await _seed_reference_document(
        db_session, title="SCOR Framework Overview", tenant_id=1
    )
    assert not await question_names_reference_entry(
        db_session,
        tenant_id=1,
        project_id=1,
        question="What were IT vendor renewals last month?",
    )


async def test_matches_a_document_title_by_acronym_typed_lowercase(db_session):
    """Live regression: "Tell me about scor" (lowercase) fell through to SQL
    generation and matched an unrelated "Score" data source instead of the
    real SCOR reference document, because the acronym check only looked for
    an all-caps run already present in the question -- a user rarely types
    an acronym in caps. The match still has to land on a real document's
    title acronym below, so this only widens which question words get
    checked, not what counts as a match."""
    await _seed_reference_document(
        db_session, title="SCOR Framework Overview", tenant_id=1
    )
    assert await question_names_reference_entry(
        db_session, tenant_id=1, project_id=1, question="Tell me about scor"
    )


async def test_multi_word_display_name_requires_every_word(db_session):
    # Regression guard against the exact false-positive shape that was
    # rejected: a KPI/tag whose name shares only ONE common word with the
    # question must not match just because that word overlaps -- every
    # significant word of the catalog entry's name must be present.
    await _seed_catalog_kpi(
        db_session, kpi_key="on_time_delivery", display_name="On Time Delivery"
    )
    # Only one of the three significant words ("delivery") is present --
    # must not match.
    assert not await question_names_reference_entry(
        db_session,
        tenant_id=1,
        project_id=1,
        question="What is the delivery schedule for next week?",
    )
    # All three significant words present (any order/wrapping) -- matches.
    assert await question_names_reference_entry(
        db_session,
        tenant_id=1,
        project_id=1,
        question="Tell me about on time delivery as a metric",
    )


async def test_ask_and_run_core_routes_to_reference_answer_before_generation(
    db_session, monkeypatch
):
    """End-to-end: a confident catalog match skips SQL generation entirely."""
    from app.auth.context import RequestContext
    from app.auth.jwt import TokenClaims
    from app.routes import ai_proxy_ask_and_run as core_module

    await _seed_catalog_kpi(db_session, kpi_key="scor", display_name="SCOR Model")

    tenant = Tenant(slug="reflib-routing", name="Reflib Routing")
    db_session.add(tenant)
    await db_session.flush()
    await db_session.commit()

    async def _fail_if_called(*args, **kwargs):
        raise AssertionError(
            "SQL generation must never be attempted for a confident "
            "reference-catalog match"
        )

    async def _fake_resolver(*args, **kwargs):
        from app.services.project_source_resolver.types import ResolverResult

        return ResolverResult(status="no_match")

    async def _fake_prose(*args, **kwargs):
        return {"answer": "SCOR is the Supply Chain Operations Reference model."}

    monkeypatch.setattr(core_module, "_generate_sql_for_question", _fail_if_called)
    monkeypatch.setattr(core_module, "_resolve_action_sources", _fake_resolver)
    monkeypatch.setattr(core_module, "_forward_prose_answer", _fake_prose)

    context = RequestContext(
        claims=TokenClaims(sub="u", tenant_id=tenant.id, user_id=1, role="editor")
    )
    result = await core_module._ask_and_run_core(
        db_session, context,
        project_id=1, question="Tell me about SCOR", max_rows=100,
    )
    assert result["status"] == "reference_library_answer"
    assert "Supply Chain Operations Reference" in result["explanation"]
    assert result["sql"] == ""


async def test_ask_and_run_core_passes_conversation_history_to_reference_answer(
    db_session, monkeypatch
):
    """Live regression: a chat follow-up like "give me a detail summary of
    the SCOR model" was answered from scratch every time, with no memory of
    the prior exchange, because _ask_and_run_core had no way to receive the
    conversation's history at all -- unlike the older Phase D document-Q&A
    bypass in conversational_analytics, which always passed it. Callers that
    have a conversation (conversational_analytics._run_analytical_turn) must
    thread ``history`` through to the reference-answer path."""
    from app.auth.context import RequestContext
    from app.auth.jwt import TokenClaims
    from app.routes import ai_proxy_ask_and_run as core_module

    await _seed_catalog_kpi(db_session, kpi_key="scor", display_name="SCOR Model")

    tenant = Tenant(slug="reflib-history", name="Reflib History")
    db_session.add(tenant)
    await db_session.flush()
    await db_session.commit()

    captured: dict = {}

    async def _fake_resolver(*args, **kwargs):
        from app.services.project_source_resolver.types import ResolverResult

        return ResolverResult(status="no_match")

    async def _fake_prose(*args, **kwargs):
        captured["history"] = kwargs.get("history")
        return {"answer": "More detail on the SCOR model."}

    monkeypatch.setattr(core_module, "_resolve_action_sources", _fake_resolver)
    monkeypatch.setattr(core_module, "_forward_prose_answer", _fake_prose)

    context = RequestContext(
        claims=TokenClaims(sub="u", tenant_id=tenant.id, user_id=1, role="editor")
    )
    conversation_history = [
        {"role": "user", "content": "Tell me about SCOR"},
        {"role": "assistant", "content": "SCOR is a supply-chain framework."},
    ]
    result = await core_module._ask_and_run_core(
        db_session, context,
        project_id=1,
        question="Give me a detail summary of the SCOR model",
        max_rows=100,
        history=conversation_history,
    )
    assert result["status"] == "reference_library_answer"
    assert captured["history"] == conversation_history


async def test_ask_and_run_core_generation_proceeds_normally_without_a_match(
    db_session, monkeypatch
):
    """Regression guard: no catalog match -> normal generation attempt, and
    a genuine generation failure still hard-errors with no substituted
    answer -- the exact behavior that must never regress."""
    from app.auth.context import RequestContext
    from app.auth.jwt import TokenClaims
    from app.routes import ai_proxy_ask_and_run as core_module

    tenant = Tenant(slug="reflib-nomatch", name="Reflib No Match")
    db_session.add(tenant)
    await db_session.flush()
    await db_session.commit()

    async def _fake_generate(*args, **kwargs):
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Could not match part of your request to an authorized project source.",
                "reason": "Model could not find a matching authorized source.",
            },
        )

    async def _fake_resolver(*args, **kwargs):
        from app.services.project_source_resolver.types import ResolverResult

        return ResolverResult(status="no_match")

    monkeypatch.setattr(core_module, "_generate_sql_for_question", _fake_generate)
    monkeypatch.setattr(core_module, "_resolve_action_sources", _fake_resolver)

    context = RequestContext(
        claims=TokenClaims(sub="u", tenant_id=tenant.id, user_id=1, role="editor")
    )
    result = await core_module._ask_and_run_core(
        db_session, context,
        project_id=1,
        question="What were the deployment metrics for a thing that does not exist?",
        max_rows=100,
    )
    assert result["status"] == "generation_error"
    assert "Could not match" in result["error"]
