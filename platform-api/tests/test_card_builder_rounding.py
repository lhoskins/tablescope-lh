"""Tests for card_builder._round_long_decimals, which keeps an insight
card's title/summary from citing a raw Teiid-computed float verbatim.

Live finding: an insight card's summary read "AvgVariancePct moves from
-1.4538461538461154% in 2026-01 to 13.13846153846154% in 2026-02, peaks at
14.6923076923077695% in 2026-04..." -- applied at ``_card()``, the single
constructor every insight card's title/summary passes through regardless of
which analysis method produced it.

Run from ``platform-api``: ``pytest -q tests/test_card_builder_rounding.py``.
"""

from __future__ import annotations

from app.services.home_intelligence.card_builder import _round_long_decimals


def test_rounds_long_decimal_percentages_to_two_places():
    text = (
        "AvgVariancePct moves from -1.4538461538461154% in 2026-01 to "
        "13.13846153846154% in 2026-02, peaks at 14.6923076923077695% in "
        "2026-04, then turns negative to -2.8384615384615390% in 2026-06."
    )
    rounded = _round_long_decimals(text)
    assert "-1.45%" in rounded
    assert "13.14%" in rounded
    assert "14.69%" in rounded
    assert "-2.84%" in rounded
    assert "4615" not in rounded  # no raw-precision digits survive


def test_leaves_already_short_decimals_and_plain_text_unchanged():
    text = "AvgVariancePct 14.69% in 2026-04 with PGM-003 material variance flagged"
    assert _round_long_decimals(text) == text
