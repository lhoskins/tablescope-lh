
from app.services.insight_confidence import evaluate_confidence


def test_document_only_capped_low():
    ev = evaluate_confidence(
        validation={},
        method_envelope={"name": "narrative_summary"},
        result={},
        is_document_only=True,
    )
    assert ev.score < 0.55
    assert ev.level == "low"
    assert "document_only" in ev.caps


def test_tentative_method_capped():
    ev = evaluate_confidence(
        validation={"executionStatus": "ok", "rowCount": 50},
        method_envelope={"name": "correlation", "confidence": "tentative"},
        result={"columns": ["a", "b"], "rows": [{"a": 1, "b": 2}] * 50},
    )
    assert ev.score <= 0.74
    assert "tentative_method" in ev.caps


def test_high_join_risk_capped():
    ev = evaluate_confidence(
        validation={"executionStatus": "ok", "rowCount": 100},
        relationship_meta={"joinRiskScore": 0.9},
        result={"columns": ["a", "b"], "rows": [{"a": 1, "b": 2}] * 100},
    )
    assert ev.score < 0.55
    assert "high_join_risk" in ev.caps


def test_few_rows_low_confidence():
    ev = evaluate_confidence(
        validation={"executionStatus": "ok", "rowCount": 2},
        result={"columns": ["a", "b"], "rows": [{"a": 1, "b": 2}, {"a": 2, "b": 3}]},
    )
    assert ev.level == "low"
    assert "few_rows" in ev.caps or ev.score < 0.6


def test_strong_evidence_high_confidence():
    ev = evaluate_confidence(
        validation={"executionStatus": "ok", "rowCount": 100},
        method_envelope={"name": "describe_numeric", "confidence": "validated"},
        result={
            "columns": ["month", "value"],
            "rows": [{"month": f"2024-{i:02d}", "value": i} for i in range(1, 101)],
        },
        source_context={"sourceTables": ["sales"], "periodColumn": "month"},
        has_project_evidence=True,
    )
    assert ev.score >= 0.8
    assert ev.level == "high"
    assert not ev.caps


def test_confidence_factors_sum_to_score():
    ev = evaluate_confidence(
        validation={"executionStatus": "ok", "rowCount": 50},
        method_envelope={"name": "describe_numeric"},
        result={
            "columns": ["a", "b"],
            "rows": [{"a": i, "b": i * 2} for i in range(50)],
        },
    )
    total = sum(f.score * f.weight for f in ev.factors)
    assert abs(total - ev.score) < 0.01
