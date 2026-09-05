"""KG-08: the shared sensitivity-label vocabulary and its strictness
ordering. Pure unit tests for a new, additive module -- no prior behavior
to prove a regression against.

Run from ``platform-api``: ``pytest -q tests/test_kg08_sensitivity_vocabulary.py``.
"""

from __future__ import annotations

from app.services.knowledge_graph.sensitivity import (
    DEFAULT_SENSITIVITY,
    SENSITIVITY_LEVELS,
    sensitivity_rank,
    strictest_sensitivity,
)


def test_levels_are_strictly_increasing_in_rank():
    ranks = [sensitivity_rank(level) for level in SENSITIVITY_LEVELS]
    assert ranks == sorted(ranks)
    assert len(set(ranks)) == len(ranks)


def test_unknown_or_missing_label_ranks_as_the_default():
    assert sensitivity_rank(None) == sensitivity_rank(DEFAULT_SENSITIVITY)
    assert sensitivity_rank("some_legacy_value") == sensitivity_rank(DEFAULT_SENSITIVITY)


def test_strictest_sensitivity_picks_the_most_restrictive_label():
    assert strictest_sensitivity(["public_project", "private", "shared_project"]) == "private"
    assert strictest_sensitivity(["confidential", "regulated", "private"]) == "regulated"


def test_strictest_sensitivity_defaults_when_no_evidence():
    assert strictest_sensitivity([]) == DEFAULT_SENSITIVITY


def test_strictest_sensitivity_ignores_none_entries_unless_alone():
    assert strictest_sensitivity([None, "private"]) == "private"
    assert strictest_sensitivity([None, None]) == DEFAULT_SENSITIVITY
