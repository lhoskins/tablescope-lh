"""Tests for purpose-driven Deeper analysis: dissect a card, propose actions."""

from __future__ import annotations

from app.services.card_diagnostics import (
    OPPORTUNITY,
    RISK,
    STAGE_LOCALISE,
    TREND,
    card_family,
    period_comparison_triggers,
    plan_card_diagnostics,
    plan_cross_references,
    propose_actions,
    should_compare_periods,
    suggested_followups,
)

RISK_CARD = {
    "insightType": "risk_sla",
    "severity": "warning",
    "title": "On-time delivery below SLA",
    "summary": "On-time delivery fell to 88%, breaching the 95% SLA.",
    "metric": "on_time_rate",
    "sources": {"tables": ["delivery_performance"]},
}
TREND_CARD = {
    "insightType": "trend_spend",
    "title": "Material costs rising",
    "summary": "Material costs increased steadily over six months.",
    "metric": "material_costs",
}
OPP_CARD = {
    "insightType": "opportunity_supplier",
    "severity": "opportunity",
    "title": "Supplier consolidation savings",
    "summary": "Three suppliers cover the same parts.",
    "metric": "unit_cost",
}
NEUTRAL_CARD = {"insightType": "informational", "title": "Row counts", "summary": "counts"}


def _plan(card, **kw):
    base = dict(
        metric=card.get("metric"),
        dimensions=["plant"],
        period_column="month",
        period_count=24,
        row_count=200,
        related_measures=["scrap_rate", "downtime_hours"],
        max_steps=9,
    )
    base.update(kw)
    return plan_card_diagnostics(card, **base)


# ── Card classification ──────────────────────────────────────────────────────


def test_cards_are_classified_by_type_or_severity():
    assert card_family(RISK_CARD) == RISK
    assert card_family(TREND_CARD) == TREND
    assert card_family(OPP_CARD) == OPPORTUNITY
    assert card_family({"severity": "critical"}) == RISK
    assert card_family(NEUTRAL_CARD) is None


def test_a_card_with_no_family_gets_no_diagnostics():
    assert plan_card_diagnostics(NEUTRAL_CARD, dimensions=["plant"]) == []
    assert propose_actions(NEUTRAL_CARD) == []
    assert suggested_followups(NEUTRAL_CARD) == []


# ── The diagnostic ladder ────────────────────────────────────────────────────


def test_localising_the_problem_ranks_first():
    """The most actionable question is *where* the problem sits."""
    specs = _plan(RISK_CARD)
    assert specs[0].stage == STAGE_LOCALISE
    assert specs[0].group_by == "plant"


def test_ladder_covers_where_when_explain_and_project():
    intents = {s.intent for s in _plan(RISK_CARD)}
    assert "compare_multiple_groups" in intents      # where
    assert "contribution_to_change" in intents       # what drove it
    assert "detect_change_point" in intents          # when
    assert "relationship_numeric" in intents         # explain
    assert "forecast_time_series" in intents         # project


def test_every_step_explains_why_it_is_being_run():
    for spec in _plan(RISK_CARD):
        assert spec.rationale, f"{spec.intent} has no rationale"
        assert spec.question.endswith("?")


def test_without_dimensions_there_is_no_segment_localisation():
    intents = {s.intent for s in _plan(RISK_CARD, dimensions=[])}
    assert "compare_multiple_groups" not in intents
    assert "contribution_to_change" not in intents


def test_short_history_drops_the_time_based_steps():
    intents = {s.intent for s in _plan(RISK_CARD, period_count=4)}
    assert "detect_change_point" not in intents
    assert "forecast_time_series" not in intents


def test_plan_is_capped_and_priority_ordered():
    specs = _plan(RISK_CARD, max_steps=3)
    assert len(specs) == 3
    assert [s.priority for s in specs] == sorted((s.priority for s in specs), reverse=True)


# ── Period comparison is demoted to triggered evidence ───────────────────────


def test_period_comparison_is_not_planned_without_a_trigger():
    """MoM/YoY is computable from almost any dated measure — it must earn its place."""
    quiet = {"insightType": "risk_expiry", "title": "Contracts expiring", "summary": "12 contracts expire.", "metric": "days_to_expiry"}
    assert should_compare_periods(quiet) is False
    assert "compare_periods" not in {s.intent for s in _plan(quiet)}


def test_change_language_triggers_a_period_comparison():
    assert should_compare_periods(TREND_CARD) is True
    spec = next(s for s in _plan(TREND_CARD) if s.intent == "compare_periods")
    assert spec.triggered_by
    assert "because" in spec.rationale


def test_threshold_language_triggers_a_period_comparison():
    reasons = period_comparison_triggers(RISK_CARD)
    assert any("threshold" in r for r in reasons)


def test_detected_signals_trigger_a_period_comparison():
    quiet = {"insightType": "risk_expiry", "title": "Contracts expiring", "summary": "12 contracts expire."}
    assert should_compare_periods(quiet, {"change_point_count": 1}) is True
    assert should_compare_periods(quiet, {"anomaly_count": 3}) is True
    assert should_compare_periods(quiet, {"threshold_breached": True}) is True


def test_a_trend_card_always_warrants_a_period_read():
    assert "the card is a trend" in period_comparison_triggers(TREND_CARD)


# ── Cross-referencing ────────────────────────────────────────────────────────


def test_cross_references_skip_the_cards_own_source():
    refs = plan_cross_references(
        RISK_CARD,
        tables=["delivery_performance", "delivery_exceptions"],
        documents=[],
    )
    names = [r.name for r in refs]
    assert "delivery_performance" not in names   # already the card's evidence
    assert "delivery_exceptions" in names


def test_documents_are_offered_as_explanations():
    refs = plan_cross_references(
        RISK_CARD,
        tables=[],
        documents=[{"title": "2026-03 delivery review"}, {"title": "unrelated handbook"}],
    )
    docs = [r for r in refs if r.kind == "document"]
    assert any("delivery" in d.name for d in docs)
    assert all(d.question.endswith("?") for d in docs)


def test_cross_reference_count_is_bounded():
    refs = plan_cross_references(
        RISK_CARD,
        tables=[f"delivery_{i}" for i in range(10)],
        documents=[{"title": f"delivery doc {i}"} for i in range(10)],
        max_refs=3,
    )
    assert len(refs) == 3


# ── Action proposals ─────────────────────────────────────────────────────────


def test_a_concentrated_segment_produces_a_targeted_action():
    actions = propose_actions(RISK_CARD, {"top_segment": "Plant B", "top_segment_share": 0.62})
    assert actions[0].kind == "mitigate"
    assert "Plant B" in actions[0].headline
    assert "62%" in actions[0].rationale
    assert actions[0].confidence == "high"


def test_an_opportunity_proposes_capture_not_mitigation():
    actions = propose_actions(OPP_CARD, {"top_segment": "Supplier A"})
    assert actions[0].kind == "capture"
    assert "Scale" in actions[0].headline


def test_a_dated_shift_proposes_investigating_that_period():
    actions = propose_actions(RISK_CARD, {"change_point_period": "2026-03"})
    assert any("2026-03" in a.headline for a in actions)
    assert any(a.kind == "investigate" for a in actions)


def test_a_driver_proposes_addressing_it():
    actions = propose_actions(TREND_CARD, {"top_driver": "supplier_lead_time"})
    assert any("Supplier Lead Time" in a.headline for a in actions)


def test_worsening_projection_argues_for_acting_now():
    actions = propose_actions(RISK_CARD, {"forecast_direction": "worsening"})
    assert any("compound" in a.rationale or "cost of delay" in a.rationale for a in actions)


def test_no_evidence_yields_an_honest_investigate_rather_than_invention():
    actions = propose_actions(RISK_CARD, {})
    assert len(actions) == 1
    assert actions[0].kind == "investigate"
    assert actions[0].confidence == "low"
    assert "did not isolate" in actions[0].rationale


def test_opportunity_with_no_evidence_monitors_rather_than_investigates():
    actions = propose_actions(OPP_CARD, {})
    assert actions[0].kind == "monitor"


def test_actions_are_capped():
    actions = propose_actions(
        RISK_CARD,
        {
            "top_segment": "Plant B",
            "change_point_period": "2026-03",
            "top_driver": "scrap_rate",
            "forecast_direction": "worsening",
        },
        max_actions=2,
    )
    assert len(actions) == 2


# ── Follow-up questions ──────────────────────────────────────────────────────


def test_followups_are_card_scoped_and_typeable():
    qs = suggested_followups(RISK_CARD, dimensions=["plant", "supplier"])
    assert any("on_time_rate" in q for q in qs)
    assert any("Plant" in q for q in qs)
    assert any("reduce this risk" in q for q in qs)
    assert all(q.endswith("?") or q.startswith(("Break", "Compare")) for q in qs)


def test_opportunity_followups_ask_about_size():
    qs = suggested_followups(OPP_CARD)
    assert any("How large" in q for q in qs)


def test_followups_include_document_cross_reference():
    qs = suggested_followups(TREND_CARD, max_items=9)
    assert any("documents" in q.lower() for q in qs)


# ── Findings extraction (envelope -> the facts an action needs) ──────────────


def test_contribution_results_yield_the_dominant_segment():
    from app.services.card_diagnostics import extract_findings

    facts = extract_findings(
        "contribution_to_change",
        {"results": {"contributions": [
            {"group": "Plant A", "contribution": 0.2},
            {"group": "Plant B", "contribution": 0.62},
        ]}},
    )
    assert facts["top_segment"] == "Plant B"
    assert facts["top_segment_share"] == 0.62


def test_negative_contribution_still_counts_as_dominant():
    """A large negative contributor drives the movement just as much."""
    from app.services.card_diagnostics import extract_findings

    facts = extract_findings(
        "compare_multiple_groups",
        {"results": {"groups": [{"name": "East", "value": 0.1}, {"name": "West", "value": -0.9}]}},
    )
    assert facts["top_segment"] == "West"


def test_change_point_yields_count_and_period():
    from app.services.card_diagnostics import extract_findings

    facts = extract_findings(
        "detect_change_point", {"results": {"change_points": [{"period": "2026-03"}]}}
    )
    assert facts == {"change_point_count": 1, "change_point_period": "2026-03"}


def test_regression_yields_the_strongest_driver():
    from app.services.card_diagnostics import extract_findings

    facts = extract_findings(
        "continuous_prediction",
        {"results": {"coefficients": [
            {"term": "downtime", "estimate": 0.1},
            {"term": "scrap_rate", "estimate": -0.8},
        ]}},
    )
    assert facts["top_driver"] == "scrap_rate"


def test_forecast_direction_is_derived_from_slope():
    from app.services.card_diagnostics import extract_findings

    assert extract_findings("forecast_time_series", {"results": {"slope": 2.5}})[
        "forecast_direction"
    ] == "worsening"
    assert extract_findings("forecast_time_series", {"results": {"slope": -1.0}})[
        "forecast_direction"
    ] == "improving"


def test_malformed_or_unknown_envelopes_contribute_nothing():
    from app.services.card_diagnostics import extract_findings

    assert extract_findings("detect_anomalies", {"results": "not-a-dict"}) == {}
    assert extract_findings("detect_anomalies", None) == {}
    assert extract_findings("some_future_intent", {"results": {"x": 1}}) == {}


def test_extracted_findings_feed_a_targeted_action():
    """The end-to-end contract: envelope -> facts -> grounded proposal."""
    from app.services.card_diagnostics import extract_findings

    facts = extract_findings(
        "contribution_to_change",
        {"results": {"contributions": [{"group": "Plant B", "contribution": 0.62}]}},
    )
    actions = propose_actions(RISK_CARD, facts)
    assert "Plant B" in actions[0].headline
    assert actions[0].confidence == "high"


# ── Chart markers come from the method, not a re-derivation ──────────────────


def test_r_anomaly_indices_are_converted_to_zero_based_positions():
    """R's `which()` is 1-based; the chart indexes from 0."""
    from app.services.card_diagnostics import extract_markers

    markers = extract_markers(
        "detect_anomalies", {"results": {"anomalies": [1, 7, 31]}}
    )
    assert markers["anomalyIndices"] == [0, 6, 30]


def test_anomaly_indices_accept_the_dict_form_too():
    from app.services.card_diagnostics import extract_markers

    markers = extract_markers(
        "detect_anomalies", {"results": {"anomalies": [{"index": 4}, {"position": 9}]}}
    )
    assert markers["anomalyIndices"] == [3, 8]


def test_the_expected_band_travels_with_the_anomalies():
    from app.services.card_diagnostics import extract_markers

    markers = extract_markers(
        "detect_anomalies",
        {"results": {
            "anomalies": [2],
            "expected": [10.0, 11.0, 12.0],
            "lower": [8.0, 9.0, 10.0],
            "upper": [12.0, 13.0, 14.0],
        }},
    )
    assert markers["band"]["expected"] == [10.0, 11.0, 12.0]
    assert markers["band"]["lower"] == [8.0, 9.0, 10.0]


def test_a_ragged_band_is_dropped_rather_than_misaligned():
    """Unequal band arrays would draw the envelope against the wrong points."""
    from app.services.card_diagnostics import extract_markers

    markers = extract_markers(
        "detect_anomalies",
        {"results": {"anomalies": [1], "expected": [1.0, 2.0], "lower": [0.0], "upper": [3.0, 4.0]}},
    )
    assert "band" not in markers
    assert markers["anomalyIndices"] == [0]


def test_a_change_point_index_is_marked():
    from app.services.card_diagnostics import extract_markers

    markers = extract_markers(
        "detect_change_point", {"results": {"change_points": [{"index": 12, "period": "2026-03"}]}}
    )
    assert markers["changePointIndex"] == 11


def test_nothing_to_mark_yields_no_markers():
    from app.services.card_diagnostics import extract_markers

    assert extract_markers("detect_anomalies", {"results": {}}) == {}
    assert extract_markers("detect_anomalies", {"results": "not-a-dict"}) == {}
    assert extract_markers("detect_anomalies", None) == {}
    assert extract_markers("forecast_time_series", {"results": {"slope": 1.0}}) == {}
