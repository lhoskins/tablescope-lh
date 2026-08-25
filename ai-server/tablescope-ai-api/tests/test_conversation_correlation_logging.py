"""conversation_id/turn_id must appear in ai-api's structured logs.

Without a shared correlation ID, a log line like "needs clarification |
project=44" can't be told apart from an unrelated request from another
tenant's session that just happened to land nearby in the timeline -- exactly
the ambiguity that made a live "Q4 follow-up" incident unprovable (the
project-44 422 could not be confirmed as belonging to the user's project-41
conversation). conversation_id/turn_id are supplied by platform-api (the
persisted conversation/turn row IDs) and threaded straight into every log
line these two endpoints emit.

Run from ``tablescope-ai-api``:
``pytest -q tests/test_conversation_correlation_logging.py``.
"""

from __future__ import annotations

import asyncio

import app.routers.ai_conversation as ai_conversation
import app.routers.ai_query_generate as ai_query_generate
from app.models.schemas import ConversationTurnClassifyRequest, GenerateSQLRequest


def _patch_query_generate(monkeypatch, *, generate_response: str):
    monkeypatch.setattr(ai_query_generate, "verify_signature", lambda *a, **k: None)
    monkeypatch.setattr(ai_query_generate, "update_activity", lambda *a, **k: None)
    monkeypatch.setattr(ai_query_generate, "validate_sql", lambda *a, **k: None)

    async def fake_build_context(**kwargs):
        class _Ctx:
            allowed_context = {"metadata": []}

        return _Ctx()

    monkeypatch.setattr(
        ai_query_generate.context_builder, "build_context", fake_build_context
    )

    async def fake_generate_sql(**kwargs):
        return generate_response

    monkeypatch.setattr(ai_query_generate.llm_client, "generate_sql", fake_generate_sql)


def test_needs_clarification_log_carries_conversation_and_turn(monkeypatch, caplog):
    _patch_query_generate(monkeypatch, generate_response="NEED_CLARIFICATION")
    req = GenerateSQLRequest(
        tenant_id=33,
        user_id=1,
        project_id=44,
        prompt="Is there any details supporting Q4 being the highest quarter?",
        allowed_tables=["it_incidents_CSV"],
        conversation_id=901,
        turn_id=17,
    )

    with caplog.at_level("WARNING"):
        try:
            asyncio.run(ai_query_generate.generate_sql_endpoint(req))
        except Exception:
            pass

    assert any(
        "conversation=901" in record.message and "turn=17" in record.message
        for record in caplog.records
    )


def test_sql_generated_log_carries_conversation_and_turn(monkeypatch, caplog):
    _patch_query_generate(
        monkeypatch, generate_response='SELECT "Month" FROM "sales_revenue_monthly"'
    )
    req = GenerateSQLRequest(
        tenant_id=33,
        user_id=1,
        project_id=41,
        prompt="show me revenue by quarter",
        allowed_tables=["sales_revenue_monthly"],
        conversation_id=901,
        turn_id=16,
    )

    with caplog.at_level("INFO"):
        asyncio.run(ai_query_generate.generate_sql_endpoint(req))

    assert any(
        "conversation=901" in record.message and "turn=16" in record.message
        for record in caplog.records
        if "SQL generated" in record.message
    )


def test_conversation_turn_classification_log_carries_conversation_and_turn(
    monkeypatch, caplog
):
    monkeypatch.setattr(ai_conversation, "verify_signature", lambda *a, **k: None)
    monkeypatch.setattr(ai_conversation, "update_activity", lambda *a, **k: None)

    async def fake_generate(**kwargs):
        return '{"intent": "new_analysis", "chart": {}, "confidence": 0.8, "reason": "ok"}'

    monkeypatch.setattr(ai_conversation.llm_client, "generate", fake_generate)

    req = ConversationTurnClassifyRequest(
        tenant_id=33,
        user_id=1,
        project_id=41,
        message="Is there any details supporting Q4 being the highest quarter?",
        conversation_id=901,
        turn_id=17,
    )

    with caplog.at_level("INFO"):
        asyncio.run(ai_conversation.classify_conversation_turn(req))

    assert any(
        "conversation=901" in record.message and "turn=17" in record.message
        for record in caplog.records
    )
