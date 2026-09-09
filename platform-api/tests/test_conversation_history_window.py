"""Conversation memory: the recent-turns window sent with answer synthesis.

Covers the two things that made this non-obvious to get right:

1. The window must reach the *analytical* answer call, not only the document
   Q&A bypass. Those are separate code paths in execute_turn, and wiring only
   the bypass leaves ordinary chat exactly as memory-less as before while
   looking fixed.
2. It must be built with a query, never by walking ``conversation.turns``.
   That relationship is lazily loaded and no caller of execute_turn eagerly
   loads it, so touching it raises MissingGreenlet on an AsyncSession.
"""

import pytest

from app.models import AnalyticsConversation, AnalyticsConversationTurn
from app.services.conversational_analytics import (
    _HISTORY_MSG_CHARS,
    _HISTORY_TOTAL_CHARS,
    _build_llm_history,
)

pytestmark = pytest.mark.anyio


async def _conversation(db_session) -> AnalyticsConversation:
    conversation = AnalyticsConversation(
        tenant_id=1,
        user_id=1,
        project_id=1,
        surface="project_workspace",
        title="Workspace",
        status="active",
    )
    db_session.add(conversation)
    await db_session.flush()
    return conversation


async def _turn(
    db_session,
    conversation: AnalyticsConversation,
    sequence: int,
    user_message: str,
    assistant_message: str | None,
    status: str = "success",
) -> AnalyticsConversationTurn:
    turn = AnalyticsConversationTurn(
        conversation_id=conversation.id,
        sequence=sequence,
        user_message=user_message,
        assistant_message=assistant_message,
        status=status,
    )
    db_session.add(turn)
    await db_session.flush()
    return turn


async def test_history_is_oldest_first_role_content_pairs(db_session):
    conversation = await _conversation(db_session)
    await _turn(db_session, conversation, 1, "first question", "first answer")
    await _turn(db_session, conversation, 2, "second question", "second answer")
    current = await _turn(db_session, conversation, 3, "third question", None, "pending")

    history = await _build_llm_history(db_session, conversation, current)

    assert history == [
        {"role": "user", "content": "first question"},
        {"role": "assistant", "content": "first answer"},
        {"role": "user", "content": "second question"},
        {"role": "assistant", "content": "second answer"},
    ]


async def test_excludes_the_in_flight_turn_and_failed_turns(db_session):
    conversation = await _conversation(db_session)
    await _turn(db_session, conversation, 1, "good question", "good answer")
    # A failed turn's assistant_message is an error string; replaying it would
    # teach the model that the failure was the answer.
    await _turn(
        db_session, conversation, 2, "doomed question", "Something went wrong.", "error"
    )
    current = await _turn(db_session, conversation, 3, "current question", None, "pending")

    history = await _build_llm_history(db_session, conversation, current)

    contents = [m["content"] for m in history]
    assert contents == ["good question", "good answer"]
    assert "current question" not in contents


async def test_both_roles_are_truncated_not_just_the_answer(db_session):
    conversation = await _conversation(db_session)
    await _turn(
        db_session,
        conversation,
        1,
        "u" * (_HISTORY_MSG_CHARS * 3),  # e.g. a pasted log
        "a" * (_HISTORY_MSG_CHARS * 3),
    )
    current = await _turn(db_session, conversation, 2, "now what?", None, "pending")

    history = await _build_llm_history(db_session, conversation, current)

    assert [len(m["content"]) for m in history] == [
        _HISTORY_MSG_CHARS,
        _HISTORY_MSG_CHARS,
    ]


async def test_budget_drops_oldest_first_and_keeps_the_newest_exchange(db_session):
    conversation = await _conversation(db_session)
    # Each turn contributes ~1200 chars, so the 8000-char budget cannot hold
    # all eight turns the query returns.
    for i in range(1, 9):
        await _turn(
            db_session,
            conversation,
            i,
            f"q{i} " + "u" * _HISTORY_MSG_CHARS,
            f"a{i} " + "x" * _HISTORY_MSG_CHARS,
        )
    current = await _turn(db_session, conversation, 9, "latest", None, "pending")

    history = await _build_llm_history(db_session, conversation, current)

    assert sum(len(m["content"]) for m in history) <= _HISTORY_TOTAL_CHARS
    # The newest exchange survives -- it is what a follow-up refers to.
    assert history[-1]["content"].startswith("a8")
    assert any(m["content"].startswith("q8") for m in history)
    # ...and the oldest were the ones dropped.
    assert not any(m["content"].startswith("q1") for m in history)


async def test_first_ever_turn_has_no_history(db_session):
    conversation = await _conversation(db_session)
    current = await _turn(db_session, conversation, 1, "opening question", None, "pending")

    assert await _build_llm_history(db_session, conversation, current) == []


async def test_does_not_touch_the_lazy_turns_relationship(db_session):
    """Guards the MissingGreenlet trap.

    Every caller of execute_turn passes a conversation loaded without
    ``selectinload(AnalyticsConversation.turns)``. If the helper ever goes back
    to walking that relationship, this fails loudly instead of at runtime.
    """
    conversation = await _conversation(db_session)
    await _turn(db_session, conversation, 1, "question", "answer")
    current = await _turn(db_session, conversation, 2, "follow-up", None, "pending")

    # Evict everything so the relationship is provably unloaded, the way the
    # canonical SELECT ... FOR UPDATE path leaves it.
    db_session.expunge_all()
    reloaded = await db_session.get(AnalyticsConversation, conversation.id)
    assert "turns" not in reloaded.__dict__  # not eagerly loaded

    history = await _build_llm_history(db_session, reloaded, current)
    assert [m["content"] for m in history] == ["question", "answer"]
