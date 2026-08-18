"""_build_relationship_hint_lines must render a compound join key as a single
ON clause with every equality ANDed together, not just the first pair.

find_relationship_candidates (platform-api) enriches a relationship candidate
with join_key_pairs when two tables share both an entity key (e.g.
AccountNumber) and a reporting-period column (e.g. Month) -- exactly the
fin_gl_monthly / fin_forecast_monthly shape. Rendering only the singular
left_join_key/right_join_key, as this function used to, silently dropped the
period equality: the LLM joined on the entity key alone and fanned each
month's rows out against every other month for the same entity.

Run from ``tablescope-ai-api``:
``pytest -q tests/test_relationship_hint_compound_keys.py``.
"""

from __future__ import annotations

from app.routers.ai_dashboard import _dashboard_relationship_floor_line
from app.routers.ai_plan_prompt import _build_relationship_hint_lines


def _compound_hint() -> dict:
    return {
        "left_table": "fin_gl_monthly",
        "right_table": "fin_forecast_monthly",
        "left_join_key": "AccountNumber",
        "right_join_key": "AccountNumber",
        "join_key_pairs": [
            {"left": "AccountNumber", "right": "AccountNumber", "is_period": False},
            {"left": "Month", "right": "Month", "is_period": True},
        ],
        "relationship_type": "one_to_one",
        "join_confidence": 0.6,
        "confidence_reason": "shared join key 'AccountNumber'",
        "row_multiplication_risk": "medium",
    }


def _single_key_hint() -> dict:
    return {
        "left_table": "a0",
        "right_table": "b0",
        "left_join_key": "k",
        "right_join_key": "k",
        "join_key_pairs": [{"left": "k", "right": "k", "is_period": False}],
        "relationship_type": "one_to_many",
        "join_confidence": 0.8,
        "confidence_reason": "measured",
        "row_multiplication_risk": "low",
    }


def _legacy_hint_without_join_key_pairs() -> dict:
    return {
        "left_table": "a0",
        "right_table": "b0",
        "left_join_key": "k",
        "right_join_key": "k",
        "relationship_type": "one_to_many",
        "join_confidence": 0.8,
        "confidence_reason": "measured",
        "row_multiplication_risk": "low",
    }


def test_compound_key_renders_both_equalities_anded_together():
    prompt = _build_relationship_hint_lines([_compound_hint()])
    assert '"fin_gl_monthly"."AccountNumber" = "fin_forecast_monthly"."AccountNumber"' in prompt
    assert '"fin_gl_monthly"."Month" = "fin_forecast_monthly"."Month"' in prompt
    assert (
        '"fin_gl_monthly"."AccountNumber" = "fin_forecast_monthly"."AccountNumber" '
        'AND "fin_gl_monthly"."Month" = "fin_forecast_monthly"."Month"'
    ) in prompt
    assert "compound key" in prompt


def test_single_key_pair_has_no_compound_note():
    prompt = _build_relationship_hint_lines([_single_key_hint()])
    assert '"a0"."k" = "b0"."k"' in prompt
    # The evidence row itself carries no per-pair compound-key annotation;
    # the static rule text below always explains what one would mean.
    evidence_line = next(
        line for line in prompt.splitlines() if line.strip().startswith('- "a0"')
    )
    assert "compound key" not in evidence_line


def test_falls_back_to_singular_fields_without_join_key_pairs():
    prompt = _build_relationship_hint_lines([_legacy_hint_without_join_key_pairs()])
    assert '"a0"."k" = "b0"."k"' in prompt


def test_compound_key_rule_instructs_anding_all_equalities():
    prompt = _build_relationship_hint_lines([_compound_hint()])
    assert "MUST include ALL of them together with AND" in prompt


def test_dashboard_floor_line_has_no_evidence_reference_when_empty():
    assert _dashboard_relationship_floor_line(False) == ""


def test_dashboard_floor_line_does_not_dangle_reference_to_missing_section():
    line = _dashboard_relationship_floor_line(True)
    assert "described below" not in line
    assert "depth guidance" not in line
    assert "RELATIONSHIP EVIDENCE" in line
