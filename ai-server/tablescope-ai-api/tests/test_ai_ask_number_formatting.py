"""_format_row_value / _round_long_decimals: keep the /ai/ask answer-
synthesis prompt (and its returned answer) from leaking a Teiid-computed
aggregate's raw float precision into chat.

Live finding: "What is the average resolution hours by category?" answered
"Network has the highest average resolution time at 44.42777777777778
hours" -- copied verbatim from this endpoint's row dump into the prompt,
even though the same value was rounded correctly earlier in the same
sentence ("44.43 hours"). Fixed at the source (row values are rounded
before they ever reach the prompt) with a deterministic backstop on the
returned answer for any number the model computes/derives itself.

Run from ``tablescope-ai-api``:
``pytest -q tests/test_ai_ask_number_formatting.py``.
"""

from __future__ import annotations

from app.routers.ai_ask import _format_row_value, _round_long_decimals


def test_format_row_value_rounds_float_to_two_places():
    assert _format_row_value(44.42777777777778) == "44.43"
    assert _format_row_value(28.550000000000004) == "28.55"


def test_format_row_value_leaves_non_float_values_alone():
    assert _format_row_value("Network") == "Network"
    assert _format_row_value(42) == "42"
    assert _format_row_value(None) == "None"


def test_round_long_decimals_rounds_three_or_more_decimal_digits():
    text = (
        "Network has the highest average resolution time at "
        "44.42777777777778 hours, while Application is the lowest at "
        "28.550000000000004 hours."
    )
    rounded = _round_long_decimals(text)
    assert "44.42777777777778" not in rounded
    assert "28.550000000000004" not in rounded
    assert "44.43 hours" in rounded
    assert "28.55 hours" in rounded


def test_round_long_decimals_leaves_already_short_decimals_unchanged():
    text = "Network 44.43 hours, Hardware 36.20 hours, and a whole 100 jobs."
    assert _round_long_decimals(text) == text
