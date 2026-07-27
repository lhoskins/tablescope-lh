"""Tests for checking the causal claims a card's narrative makes."""

from __future__ import annotations

from app.services.claim_verification import (
    CONTRADICTED,
    INCONCLUSIVE,
    SUPPORTED,
    UNTESTABLE,
    Claim,
    check_claim,
    extract_claims,
    match_measure,
    percent_change,
)

# The reported card, verbatim.
MARGIN_CARD = {
    "title": "Rising Material Costs Trend Threatens Profitability",
    "summary": (
        "The company's gross margin has been declining over the past two years, "
        "with a significant drop in 2025-02 and 2025-03, indicating rising "
        "material costs and potential profitability issues."
    ),
}

TABLES = [
    ("fin_pnl_monthly", "GrossMargin"),
    ("fin_pnl_monthly", "RevenueUSD"),
    ("mfg_material_costs", "MaterialCostUSD"),
    ("mfg_labor_actuals", "OvertimeHours"),
]


def _trend(slope: float, p: float = 0.001) -> dict:
    return {"results": {"slope": slope, "p_value": p}}


# ── Pulling the assertion out of the prose ──────────────────────────────────


def test_the_indicating_clause_is_extracted_as_a_claim():
    claims = extract_claims(MARGIN_CARD)
    assert claims, "the card asserts a cause and none was found"
    assert "material cost" in claims[0].text.lower()


def test_the_asserted_direction_is_captured():
    assert extract_claims(MARGIN_CARD)[0].direction == "up"
    falling = extract_claims(
        {"summary": "Volumes slipped, suggesting declining demand."}
    )
    assert falling[0].direction == "down"


def test_every_causal_connective_is_recognised():
    for phrase, expected in (
        ("driven by higher freight rates", "freight"),
        ("due to falling utilisation", "utilisation"),
        ("because of rising scrap rates", "scrap"),
        ("reflecting increased overtime hours", "overtime"),
        ("attributable to supplier delays", "supplier"),
        ("resulting from lower throughput", "throughput"),
    ):
        claims = extract_claims({"summary": f"Margin fell, {phrase}."})
        assert claims, phrase
        assert any(expected in t for t in claims[0].terms), (phrase, claims[0].terms)


def test_a_coordinated_clause_is_split_into_separate_claims():
    """"rising material costs and potential profitability issues" is two claims."""
    claims = extract_claims(MARGIN_CARD)
    texts = [c.text.lower() for c in claims]
    assert "rising material costs" in texts
    # Blurred together, the terms match neither column.
    assert match_measure(claims[0], TABLES) == ("mfg_material_costs", "MaterialCostUSD")


def test_a_shared_verb_distributes_across_conjuncts():
    claims = extract_claims(
        {"summary": "Margin fell, driven by rising material costs and freight rates."}
    )
    assert {c.direction for c in claims} == {"up"}


def test_a_hedged_conjunct_does_not_inherit_the_direction():
    """Otherwise "potential X issues" acquires a claim the card never made."""
    hedged = next(
        c for c in extract_claims(MARGIN_CARD) if "profitability" in c.text.lower()
    )
    assert hedged.direction == ""


def test_a_unit_suffix_does_not_dilute_a_good_match():
    """`MaterialCostUSD` is the same measure as `MaterialCost`."""
    claim = Claim(text="rising material costs", terms=("material", "cost"), direction="up")
    assert match_measure(claim, [("t", "MaterialCostUSD")]) == ("t", "MaterialCostUSD")


def test_a_claim_that_names_nothing_is_not_checkable():
    """"indicating potential issues" asserts nothing a column could confirm."""
    assert extract_claims({"summary": "Margin fell, indicating potential issues."}) == []


def test_prose_without_an_assertion_yields_no_claims():
    assert extract_claims({"summary": "Gross margin fell to 24.4% in December."}) == []
    assert extract_claims({}) == []


def test_claims_are_deduplicated_and_capped():
    card = {
        "summary": (
            "A, indicating rising material costs. B, suggesting rising material "
            "costs. C, driven by freight rates. D, due to supplier delays. "
            "E, because of labour shortages."
        )
    }
    claims = extract_claims(card, max_claims=2)
    assert len(claims) == 2
    assert len({c.terms for c in claims}) == 2


# ── Finding the measure the claim is about ──────────────────────────────────


def test_the_claimed_measure_is_located_across_tables():
    """The claim names a measure in a DIFFERENT table from the card's own."""
    claim = extract_claims(MARGIN_CARD)[0]
    assert match_measure(claim, TABLES) == ("mfg_material_costs", "MaterialCostUSD")


def test_plural_and_singular_forms_match():
    claim = Claim(text="rising costs", terms=("cost",), direction="up")
    assert match_measure(claim, [("t", "TotalCosts")]) == ("t", "TotalCosts")


def test_an_unmatched_claim_returns_nothing_rather_than_a_guess():
    """A confident verdict about the wrong column is worse than no verdict."""
    claim = Claim(text="rising freight rates", terms=("freight", "rate"), direction="up")
    assert match_measure(claim, [("t", "GrossMargin"), ("t", "HeadCount")]) is None


def test_a_loose_single_word_overlap_does_not_qualify():
    claim = Claim(text="rising material costs", terms=("material", "cost"), direction="up")
    # `CostCenterDescription` shares one word but is not the claimed measure.
    assert match_measure(claim, [("t", "CostCenterDescriptionText")]) is None


# ── The verdict ─────────────────────────────────────────────────────────────


def test_a_confirmed_claim_reports_the_magnitude():
    """"rising material costs" must become "rose 18.4%"."""
    claim = extract_claims(MARGIN_CARD)[0]
    check = check_claim(
        claim,
        measure="MaterialCostUSD",
        table="mfg_material_costs",
        envelope=_trend(1200.0),
        change_percent=18.4,
        period_label="2024-01 to 2026-01",
    )
    assert check.verdict == SUPPORTED
    assert "18.4%" in check.finding
    assert "rose" in check.finding
    assert "2024-01 to 2026-01" in check.finding


def test_a_claim_the_data_contradicts_is_called_out():
    """The most valuable outcome: the card's own narrative is wrong."""
    claim = extract_claims(MARGIN_CARD)[0]
    check = check_claim(
        claim,
        measure="MaterialCostUSD",
        table="mfg_material_costs",
        envelope=_trend(-800.0),
        change_percent=-12.0,
    )
    assert check.verdict == CONTRADICTED
    assert "Not supported" in check.finding
    assert "fell" in check.finding
    assert "12.0%" in check.finding


def test_an_insignificant_move_is_inconclusive_not_confirmation():
    claim = extract_claims(MARGIN_CARD)[0]
    check = check_claim(
        claim, measure="MaterialCostUSD", table="t",
        envelope=_trend(50.0, p=0.42),
    )
    assert check.verdict == INCONCLUSIVE
    assert "0.42" in check.finding


def test_a_flat_measure_is_inconclusive():
    claim = extract_claims(MARGIN_CARD)[0]
    check = check_claim(claim, measure="MaterialCostUSD", table="t", envelope=_trend(0.0))
    assert check.verdict == INCONCLUSIVE


def test_an_unmatched_claim_says_so_rather_than_going_quiet():
    claim = Claim(text="rising freight rates", terms=("freight",), direction="up")
    check = check_claim(claim, measure=None, table=None, envelope=None)
    assert check.verdict == UNTESTABLE
    assert "could not be checked" in check.finding


def test_a_directionless_claim_reports_movement_without_contradicting():
    claim = Claim(text="supplier concentration", terms=("supplier",), direction="")
    check = check_claim(
        claim, measure="SupplierCount", table="t", envelope=_trend(3.0),
    )
    assert check.verdict == SUPPORTED
    assert "Not supported" not in check.finding


def test_a_malformed_envelope_is_inconclusive_not_a_crash():
    claim = extract_claims(MARGIN_CARD)[0]
    for bad in ({"results": "nope"}, {}, None):
        assert check_claim(claim, measure="m", table="t", envelope=bad).verdict == INCONCLUSIVE


# ── Magnitude ───────────────────────────────────────────────────────────────


def test_percent_change_spans_first_to_last_period():
    rows = [{"m": 100.0}, {"m": 110.0}, {"m": 118.4}]
    assert round(percent_change(rows, "m"), 1) == 18.4


def test_percent_change_handles_a_decline():
    assert round(percent_change([{"m": 200.0}, {"m": 150.0}], "m"), 1) == -25.0


def test_percent_change_needs_a_baseline():
    assert percent_change([{"m": 0.0}, {"m": 5.0}], "m") is None
    assert percent_change([{"m": 5.0}], "m") is None
    assert percent_change([], "m") is None
    assert percent_change([{"m": "n/a"}, {"m": None}], "m") is None
