"""Truncated intelligence-plan responses must degrade to "fewer analyses"
(salvage the complete objects) rather than "no analyses" (which triggers the
deterministic floor). Also covers the confidence-ordered, compacted evidence
line rendering.

Run from ``tablescope-ai-api``: ``pytest -q tests/test_plan_truncation_salvage.py``.
"""

from __future__ import annotations

import json

import app.routers.ai as ai


def _plan(n: int) -> dict:
    return {
        "analyses": [
            {"id": f"a{i}", "title": f"Analysis {i}", "sql": "SELECT 1"}
            for i in range(n)
        ]
    }


def test_valid_json_short_circuits_before_salvage(monkeypatch):
    # A well-formed response must never reach the salvage branch.
    called = {"n": 0}
    real = ai._repair_truncated_json

    def spy(text):
        called["n"] += 1
        return real(text)

    monkeypatch.setattr(ai, "_repair_truncated_json", spy)
    out = ai._parse_json_response(json.dumps(_plan(9)))
    assert out is not None
    assert len(out["analyses"]) == 9
    assert called["n"] == 0


def test_salvage_recovers_complete_analyses_from_truncated_plan():
    # 9 analyses generated, response cut off mid-way through the 8th object.
    full = json.dumps(_plan(9))
    # Truncate somewhere inside the array (after ~7 complete objects).
    seventh_end = full.find('"a7"')
    truncated = full[: max(0, seventh_end - 20)]
    out = ai._parse_json_response(truncated)
    assert out is not None
    assert isinstance(out.get("analyses"), list)
    # Every recovered analysis is a complete object, and we kept several.
    assert 1 <= len(out["analyses"]) <= 9
    assert all("id" in a for a in out["analyses"])


def test_salvage_returns_none_for_garbage_without_brace():
    assert ai._parse_json_response("no json here at all") is None
    assert ai._repair_truncated_json("no json here at all") is None


def test_salvage_handles_sql_values_containing_braces():
    # A SQL string with literal braces must not permanently break the repair:
    # the loop retries earlier boundaries until one parses.
    payload = {
        "analyses": [
            {"id": "a0", "sql": "SELECT '{not json}' AS x"},
            {"id": "a1", "sql": "SELECT 2"},
        ]
    }
    full = json.dumps(payload)
    truncated = full[: full.rfind('"a1"') + 2]  # cut mid second object
    out = ai._parse_json_response(truncated)
    assert out is not None
    assert out["analyses"][0]["id"] == "a0"


def _hint(conf: float, reason: str = "measured") -> dict:
    return {
        "left_table": f"L{conf}",
        "right_table": f"R{conf}",
        "left_join_key": "k",
        "right_join_key": "k",
        "relationship_type": "one_to_many",
        "join_confidence": conf,
        "confidence_reason": reason,
        "row_multiplication_risk": "low",
    }


def test_hint_lines_sorted_by_confidence_desc():
    out = ai._build_relationship_hint_lines(
        [_hint(0.3), _hint(0.9), _hint(0.6)]
    )
    lines = [ln for ln in out.splitlines() if ln.startswith('  - "')]
    confs = [float(ln[ln.index("conf=") + 5 :][:4]) for ln in lines]
    assert confs == sorted(confs, reverse=True)
    assert confs[0] == 0.90


def test_hint_reason_capped_at_60_chars_and_no_pair_dropped():
    long_reason = "x" * 200
    hints = [_hint(0.5, long_reason), _hint(0.4), _hint(0.7)]
    out = ai._build_relationship_hint_lines(hints)
    lines = [ln for ln in out.splitlines() if ln.startswith('  - "')]
    assert len(lines) == 3  # every pair rendered
    assert ("x" * 60) in out
    assert ("x" * 61) not in out
