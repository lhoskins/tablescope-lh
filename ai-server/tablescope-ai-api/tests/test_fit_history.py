"""Backstop trimming for the conversation-history prompt block.

context_text has been fitted since this endpoint was written; history_text was
not -- it was bounded only by a message count, with no size limit. Since vLLM
answers an oversized prompt with a 400 rather than truncating it, an unbounded
block is a hard failure waiting for a long enough conversation.
"""

from app.routers.ai_ask import _HISTORY_CHAR_BUDGET, _fit_history
from app.routers.ai_shared import _format_conversation_history


def _history(pairs: int, size: int = 100) -> str:
    messages = []
    for i in range(pairs):
        messages.append({"role": "user", "content": f"q{i} " + "u" * size})
        messages.append({"role": "assistant", "content": f"a{i} " + "x" * size})
    return _format_conversation_history(messages)


# The two caps compose: _format_conversation_history keeps only the last 20
# *messages*, and _fit_history then bounds what those messages weigh. So the
# case that reaches the char budget is few-but-long turns, not many short ones
# -- ten 1,000-character exchanges, not sixty 100-character ones.
_LONG = {"pairs": 10, "size": 1000}


def test_short_history_is_untouched():
    text = _history(2)
    assert _fit_history(text) == text


def test_empty_history_stays_empty():
    assert _fit_history("") == ""


def test_oversized_history_is_trimmed_within_budget():
    text = _history(**_LONG)
    assert len(text) > _HISTORY_CHAR_BUDGET

    fitted = _fit_history(text)

    assert len(fitted) <= _HISTORY_CHAR_BUDGET + len("[earlier turns omitted for length]\n")
    assert len(fitted) < len(text)


def test_trimming_keeps_the_newest_exchange_and_drops_the_oldest():
    """A follow-up refers to what was just said, so the tail is what matters."""
    fitted = _fit_history(_history(**_LONG))

    assert "a9 " in fitted  # newest answer survives
    assert "q0 " not in fitted  # oldest question is gone


def test_trimmed_block_still_reads_as_conversation_history():
    fitted = _fit_history(_history(**_LONG))

    assert fitted.startswith("Conversation so far:")
    # The gap is stated rather than silently splicing distant turns together.
    assert "[earlier turns omitted for length]" in fitted


def test_many_short_turns_are_bounded_by_the_message_cap_alone():
    """The count cap runs first, so short conversations never reach the trim.

    Sixty short exchanges collapse to the last twenty messages long before the
    character budget is relevant -- which is why the budget only bites on
    few-but-long turns.
    """
    text = _history(pairs=60, size=200)
    assert len(text) < _HISTORY_CHAR_BUDGET
    assert _fit_history(text) == text


def test_message_count_cap_is_measured_in_messages_not_turns():
    """_MAX_HISTORY_TURNS slices the message list, so 20 is ~10 exchanges.

    Pinned because the name says "turns": aligning a turn-based budget to it
    without halving would double the block this trims.
    """
    text = _format_conversation_history(
        [{"role": "user", "content": f"m{i}"} for i in range(30)]
    )
    kept = [line for line in text.split("\n") if line.startswith("User:")]
    assert len(kept) == 20
