"""Tests for the upfront reference-catalog routing check.

A question naming a real Reference Library document by acronym, or explicitly
asking for a governed KPI/tag definition, routes straight to a reference
answer. Ordinary questions that merely contain the same metric/tag words must
still reach SQL generation.

Run from ``platform-api``: ``pytest -q tests/test_question_names_reference_entry.py``.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.models.ai_reference_catalog import (
    AIReferenceCatalog,
    AIReferenceKPI,
    AIReferenceTag,
)
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


async def _seed_catalog_tag(db_session, *, tag_key: str, display_name: str) -> None:
    catalog = AIReferenceCatalog(
        catalog_key="test_operations",
        name="Test Operations",
        industry="operations",
        is_system=True,
        is_active=True,
    )
    db_session.add(catalog)
    await db_session.flush()
    db_session.add(
        AIReferenceTag(
            catalog_id=catalog.id,
            tag_key=tag_key,
            display_name=display_name,
            industry="operations",
            is_active=True,
        )
    )
    await db_session.commit()


async def test_matches_a_kpi_by_its_key(db_session):
    await _seed_catalog_kpi(db_session, kpi_key="scor", display_name="SCOR Model")
    assert await question_names_reference_entry(
        db_session, tenant_id=1, project_id=1, question="Define the SCOR KPI"
    )


async def test_operational_kpi_question_does_not_preempt_sql(db_session):
    await _seed_catalog_kpi(
        db_session,
        kpi_key="backup_success_rate",
        display_name="Backup Success Rate",
    )
    assert not await question_names_reference_entry(
        db_session,
        tenant_id=1,
        project_id=1,
        question="Show me the backup success rate",
    )
    assert await question_names_reference_entry(
        db_session,
        tenant_id=1,
        project_id=1,
        question="Define the Backup Success Rate KPI and its formula",
    )


async def test_operational_tag_question_does_not_preempt_sql(db_session):
    await _seed_catalog_tag(db_session, tag_key="incidents", display_name="Incidents")
    assert not await question_names_reference_entry(
        db_session,
        tenant_id=1,
        project_id=1,
        question="Give me the details of Q2 incidents",
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

    await _seed_reference_document(
        db_session, title="SCOR Framework Overview", tenant_id=1
    )

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

    async def _fake_grounding(*args, **kwargs):
        return None

    monkeypatch.setattr(core_module, "_generate_sql_for_question", _fail_if_called)
    monkeypatch.setattr(core_module, "_resolve_action_sources", _fake_resolver)
    monkeypatch.setattr(core_module, "_forward_prose_answer", _fake_prose)
    monkeypatch.setattr(core_module, "gather_grounding_evidence", _fake_grounding)

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


async def test_ask_and_run_core_generation_proceeds_normally_without_a_match(
    db_session, monkeypatch
):
    """Regression guard: no catalog match -> normal generation attempt, and
    a genuine generation failure still hard-errors with no substituted
    answer -- the exact behavior that must never regress."""
    from app.auth.context import RequestContext
    from app.auth.jwt import TokenClaims
    from app.routes import ai_proxy_ask_and_run as core_module

    await _seed_catalog_kpi(
        db_session,
        kpi_key="backup_success_rate",
        display_name="Backup Success Rate",
    )

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

    async def _fake_grounding(*args, **kwargs):
        return None

    monkeypatch.setattr(core_module, "_generate_sql_for_question", _fake_generate)
    monkeypatch.setattr(core_module, "_resolve_action_sources", _fake_resolver)
    monkeypatch.setattr(core_module, "gather_grounding_evidence", _fake_grounding)

    context = RequestContext(
        claims=TokenClaims(sub="u", tenant_id=tenant.id, user_id=1, role="editor")
    )
    result = await core_module._ask_and_run_core(
        db_session, context,
        project_id=1,
        question="Show me the backup success rate",
        max_rows=100,
    )
    assert result["status"] == "generation_error"
    assert "Could not match" in result["error"]
