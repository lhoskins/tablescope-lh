
from app.services.insight_evidence_fingerprint import (
    EvidenceFingerprint,
    build_plan_fingerprint,
    build_result_fingerprint,
    build_semantic_fingerprint,
    deduplicate_by_evidence,
    fingerprint_for_card,
)


def test_result_fingerprint_includes_rows_and_columns():
    result = {
        "columns": ["month", "value"],
        "rows": [
            {"month": "2024-01", "value": 10},
            {"month": "2024-02", "value": 20},
        ],
    }
    fp = build_result_fingerprint(result)
    assert fp
    assert fp == build_result_fingerprint(result)
    # Reordering columns changes fingerprint
    result2 = {
        "columns": ["value", "month"],
        "rows": [
            {"value": 10, "month": "2024-01"},
            {"value": 20, "month": "2024-02"},
        ],
    }
    assert build_result_fingerprint(result2) != fp


def test_semantic_fingerprint_excludes_title_and_summary():
    same = build_semantic_fingerprint(
        title="Different title A",
        summary="Different summary A",
        columns=["month", "value"],
        row_count=3,
        label_column="month",
        value_column="value",
        insight_type="trend",
    )
    other = build_semantic_fingerprint(
        title="Different title B",
        summary="Different summary B",
        columns=["month", "value"],
        row_count=3,
        label_column="month",
        value_column="value",
        insight_type="trend",
    )
    assert same == other


def test_plan_fingerprint_stable_for_reordered_keys():
    a = build_plan_fingerprint(
        {
            "metric": "Revenue",
            "period": "month",
        },
        project_id=1,
        tenant_id=2,
    )
    b = build_plan_fingerprint(
        {
            "period": "month",
            "metric": "Revenue",
        },
        project_id=1,
        tenant_id=2,
    )
    assert a == b


def test_deduplicate_by_evidence_prefers_result_then_series_then_semantic():
    cards = [
        {
            "insightId": "i1",
            "title": "Title One",
            "evidenceFingerprint": {
                "resultFingerprint": "A",
                "seriesFingerprint": "S1",
                "semanticFingerprint": "M1",
                "planFingerprint": "P1",
            },
            "priority": 1,
        },
        {
            "insightId": "i2",
            "title": "Title Two",
            "evidenceFingerprint": {
                "resultFingerprint": "A",
                "seriesFingerprint": "S2",
                "semanticFingerprint": "M2",
                "planFingerprint": "P2",
            },
            "priority": 2,
        },
    ]
    unique = deduplicate_by_evidence(cards)
    # result fingerprint same -> duplicate, first in input wins
    assert len(unique) == 1
    assert unique[0]["insightId"] == "i1"


def test_deduplicate_by_evidence_keeps_unique_series():
    cards = [
        {
            "insightId": "i1",
            "evidenceFingerprint": {"seriesFingerprint": "S1"},
            "priority": 1,
        },
        {
            "insightId": "i2",
            "evidenceFingerprint": {"seriesFingerprint": "S2"},
            "priority": 2,
        },
    ]
    unique = deduplicate_by_evidence(cards)
    assert len(unique) == 2


def test_fingerprint_for_card_falls_back_to_fields():
    card = {
        "insightId": "x",
        "title": "t",
        "summary": "s",
        "chart": {
            "type": "bar",
            "data": {
                "series": [
                    {"label": "a", "value": 1},
                    {"label": "b", "value": 2},
                ]
            },
        },
        "validation": {
            "columnsReturned": ["month", "value"],
            "rowCount": 2,
        },
    }
    fp = fingerprint_for_card(card)
    assert isinstance(fp, EvidenceFingerprint)
    assert fp.dedupe_key


def test_evidence_fingerprint_dedupe_key_priority():
    fp = EvidenceFingerprint(
        result_fingerprint="r",
        series_fingerprint="s",
        semantic_fingerprint="m",
        plan_fingerprint="p",
    )
    assert fp.dedupe_key == "r"
    fp2 = EvidenceFingerprint(series_fingerprint="s")
    assert fp2.dedupe_key == "s"
