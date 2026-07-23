"""Tests for the multi-source, multi-entity insight planner.

These are unit-level tests with a fake Teiid-style runner so they can run
without a live database or analytical-method engine catalog.
"""

from __future__ import annotations

import re
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.services.multi_entity_insights.candidate_selector import (
    select_candidates,
)
from app.services.multi_entity_insights.contract import (
    EntitySpec,
    InsightLineage,
    MeasureSpec,
    MethodBundle,
    MethodRef,
    MultiEntityInsightPayload,
    MultiEntityPlan,
    RelationshipSpec,
    SourceSpec,
    SourceStrategy,
    TimeSpec,
)
from app.services.multi_entity_insights.frame_validator import MultiEntityFrameValidator
from app.services.multi_entity_insights.join_validator import MultiEntityJoinValidator
from app.services.multi_entity_insights.method_bundle import (
    ExecutionEnvelope,
    MethodBundleExecutor,
    synthesize_evidence,
)
from app.services.multi_entity_insights.sql_builder import MultiEntitySQLBuilder


def _make_table(name: str, columns: list[tuple[str, str]]) -> Any:
    t: Any = type("Table", (), {})
    t.view_name = name
    t.kind = "native"
    t.columns = columns
    return t


def test_contract_valid_multi_entity_plan() -> None:
    plan = MultiEntityPlan(
        analysis_id="test_1",
        intent="compare_entities",
        title="Supplier comparison",
        business_question="Compare A and B",
        source_strategy=SourceStrategy(
            preference="multi_source_first",
            allow_single_source_fallback=True,
            selected_source_count=2,
            fallback_used=False,
            candidates_evaluated=2,
        ),
        entity=EntitySpec(
            type="supplier",
            id_column="supplier_id",
            name_column="supplier_name",
            selection_mode="explicit",
            requested_names=["Supplier A", "Supplier B"],
            maximum_entities=3,
        ),
        sources=[
            SourceSpec(
                table="invoices",
                columns=["supplier_name", "amount", "invoice_date"],
                grain=["supplier_name", "period_month"],
                measures=[MeasureSpec(name="spend", column="amount", aggregation="sum", table="invoices")],
            ),
            SourceSpec(
                table="quality",
                columns=["supplier_name", "defect_rate"],
                grain=["supplier_name"],
                measures=[MeasureSpec(name="defect_rate", column="defect_rate", aggregation="avg", table="quality")],
            ),
        ],
        relationships=[
            RelationshipSpec(
                left_table="invoices",
                right_table="quality",
                left_key=["supplier_name"],
                right_key=["supplier_name"],
                declared_cardinality="one_to_one",
                join_confidence=0.9,
            )
        ],
        time=TimeSpec(period_column="invoice_date", period_grain="month"),
        final_grain=["supplier_name"],
        measures=[
            MeasureSpec(name="total_spend", column="amount", aggregation="sum", table="invoices"),
            MeasureSpec(name="avg_defects", column="defect_rate", aggregation="avg", table="quality", format="percent"),
        ],
        method_bundle=MethodBundle(
            primary=MethodRef(method_id="compare_multiple_groups"),
            supporting=[MethodRef(method_id="detect_trend")],
        ),
    )
    assert len(plan.sources) == 2
    assert plan.entity.requested_names == ["Supplier A", "Supplier B"]


def test_contract_rejects_single_entity() -> None:
    with pytest.raises(ValueError, match="At least two explicit entity names"):
        MultiEntityPlan(
            analysis_id="test_2",
            intent="compare_entities",
            title="Bad",
            business_question="Bad",
            source_strategy=SourceStrategy(
                preference="multi_source_first",
                allow_single_source_fallback=True,
                selected_source_count=1,
                fallback_used=False,
                candidates_evaluated=1,
            ),
            entity=EntitySpec(
                type="supplier",
                id_column="id",
                name_column="name",
                selection_mode="explicit",
                requested_names=["OnlyOne"],
                maximum_entities=3,
            ),
            sources=[
                SourceSpec(
                    table="invoices",
                    columns=["name", "amount"],
                    grain=["name"],
                    measures=[MeasureSpec(name="m", column="amount", aggregation="sum", table="invoices")],
                )
            ],
            relationships=[],
            time=TimeSpec(),
            final_grain=["name"],
            measures=[MeasureSpec(name="m", column="amount", aggregation="sum", table="invoices")],
            method_bundle=MethodBundle(primary=MethodRef(method_id="x")),
        )


def test_candidate_selector_prefers_multi_source() -> None:
    tables = [
        _make_table("invoices", [("supplier_name", "string"), ("amount", "double")]),
        _make_table("quality", [("supplier_name", "string"), ("defect_rate", "double")]),
        _make_table("shipping", [("supplier_name", "string"), ("days", "int")]),
    ]
    hints = [
        {
            "left_table": "invoices",
            "right_table": "quality",
            "left_join_key": "supplier_name",
            "right_join_key": "supplier_name",
            "relationship_type": "one_to_one",
            "join_confidence": 0.9,
            "confidence_reason": "shared supplier_name",
        },
        {
            "left_table": "quality",
            "right_table": "shipping",
            "left_join_key": "supplier_name",
            "right_join_key": "supplier_name",
            "relationship_type": "one_to_one",
            "join_confidence": 0.85,
            "confidence_reason": "shared supplier_name",
        },
    ]
    candidates = select_candidates(
        "Compare supplier spend and quality",
        tables,
        hints,
        max_sources=3,
    )
    assert candidates
    top = candidates[0]
    assert top.plan is not None
    assert len(top.plan.sources) >= 2
    assert top.plan.source_strategy.selected_source_count == len(top.plan.sources)


def test_candidate_selector_single_source_fallback() -> None:
    tables = [
        _make_table("invoices", [("supplier_name", "string"), ("amount", "double")]),
    ]
    candidates = select_candidates("Compare suppliers", tables, [], max_sources=3)
    assert candidates
    top = candidates[0]
    assert top.plan is not None
    assert len(top.plan.sources) == 1
    assert top.plan.source_strategy.fallback_used


def test_sql_builder_grain_safe_query() -> None:
    plan = MultiEntityPlan(
        analysis_id="sql_test",
        intent="compare_entities",
        title="Spend by supplier",
        business_question="Compare suppliers",
        source_strategy=SourceStrategy(
            preference="multi_source_first",
            allow_single_source_fallback=False,
            selected_source_count=2,
            fallback_used=False,
            candidates_evaluated=1,
        ),
        entity=EntitySpec(
            type="supplier",
            id_column="supplier_id",
            name_column="supplier_name",
            selection_mode="explicit",
            requested_names=["A", "B"],
            maximum_entities=3,
        ),
        sources=[
            SourceSpec(
                table="invoices",
                alias="invoices",
                columns=["supplier_name", "amount", "invoice_date"],
                grain=["supplier_name"],
                measures=[MeasureSpec(name="spend", column="amount", aggregation="sum", table="invoices")],
            ),
            SourceSpec(
                table="quality",
                alias="quality",
                columns=["supplier_name", "defect_rate"],
                grain=["supplier_name"],
                measures=[MeasureSpec(name="defects", column="defect_rate", aggregation="avg", table="quality")],
            ),
        ],
        relationships=[
            RelationshipSpec(
                left_table="invoices",
                right_table="quality",
                left_key=["supplier_name"],
                right_key=["supplier_name"],
                declared_cardinality="one_to_one",
            )
        ],
        time=TimeSpec(),
        final_grain=["supplier_name"],
        measures=[
            MeasureSpec(name="total_spend", column="amount", aggregation="sum", table="invoices"),
            MeasureSpec(name="avg_defects", column="defect_rate", aggregation="avg", table="quality"),
        ],
        method_bundle=MethodBundle(primary=MethodRef(method_id="x")),
    )
    sql = MultiEntitySQLBuilder(plan).build_sql()
    # Each source should be aggregated in its own CTE before joining.
    assert '"invoices_agg"' in sql
    assert '"quality_agg"' in sql
    assert '"invoices_agg".' in sql and '"quality_agg".' in sql
    # Measures should be aggregated in the CTE and referenced in the outer SELECT.
    assert "total_spend" in sql
    assert "avg_defects" in sql
    # Outer SELECT projects the joined aggregate CTEs and ends with a FROM clause.
    assert re.search(r'FROM\s+"invoices_agg"', sql, re.IGNORECASE) is not None
    # Requested names filtered in the outer WHERE.
    assert "'A'" in sql and "'B'" in sql


def test_sql_builder_query_hash_stable() -> None:
    plan = MultiEntityPlan(
        analysis_id="hash_test",
        intent="compare_entities",
        title="Spend by supplier",
        business_question="Compare suppliers",
        source_strategy=SourceStrategy(
            preference="multi_source_first",
            allow_single_source_fallback=False,
            selected_source_count=2,
            fallback_used=False,
            candidates_evaluated=1,
        ),
        entity=EntitySpec(
            type="supplier",
            id_column="id",
            name_column="name",
            selection_mode="explicit",
            requested_names=["A", "B"],
            maximum_entities=3,
        ),
        sources=[
            SourceSpec(
                table="invoices",
                columns=["name", "amount"],
                grain=["name"],
                measures=[MeasureSpec(name="m", column="amount", aggregation="sum", table="invoices")],
            )
        ],
        relationships=[],
        time=TimeSpec(),
        final_grain=["name"],
        measures=[MeasureSpec(name="m", column="amount", aggregation="sum", table="invoices")],
        method_bundle=MethodBundle(primary=MethodRef(method_id="x")),
    )
    hash1 = MultiEntitySQLBuilder(plan).query_hash()
    hash2 = MultiEntitySQLBuilder(plan).query_hash()
    assert hash1 == hash2
    assert len(hash1) == 64
    # Changing requested names changes the hash.
    plan.entity.requested_names = ["A", "C"]
    assert MultiEntitySQLBuilder(plan).query_hash() != hash1


@pytest.mark.asyncio
async def test_join_validator_rejects_many_to_many_fanout() -> None:
    """Simulate a one-to-many fan-out and verify the validator rejects it."""

    async def runner(sql: str) -> dict[str, Any]:
        # Join cardinality: 3 joined rows, 2 distinct on each side -> fan-out > 1.0.
        if "joined_rows" in sql.lower():
            return {
                "rows": [{"joined_rows": 3, "distinct_left": 2, "distinct_right": 2}],
                "columns": ["joined_rows", "distinct_left", "distinct_right"],
            }
        if "duplicate_rows" in sql.lower():
            return {"rows": [{"duplicate_rows": 0}], "columns": ["duplicate_rows"]}
        if "distinct_keys" in sql.lower() and "\"invoices\"" in sql:
            return {"rows": [{"distinct_keys": 2}], "columns": ["distinct_keys"]}
        if "distinct_keys" in sql.lower() and "\"quality\"" in sql:
            return {"rows": [{"distinct_keys": 2}], "columns": ["distinct_keys"]}
        if "FROM \"invoices\"" in sql and "COUNT(" in sql:
            return {"rows": [{"n": 2}], "columns": ["n"]}
        if "FROM \"quality\"" in sql and "COUNT(" in sql:
            return {"rows": [{"n": 3}], "columns": ["n"]}
        return {"rows": [], "columns": []}

    plan = MultiEntityPlan(
        analysis_id="join_test",
        intent="compare_entities",
        title="Join test",
        business_question="Compare suppliers",
        source_strategy=SourceStrategy(
            preference="multi_source_first",
            allow_single_source_fallback=False,
            selected_source_count=2,
            fallback_used=False,
            candidates_evaluated=1,
        ),
        entity=EntitySpec(
            type="supplier",
            id_column="id",
            name_column="supplier_name",
            selection_mode="explicit",
            requested_names=["A", "B"],
            maximum_entities=3,
        ),
        sources=[
            SourceSpec(
                table="invoices",
                columns=["supplier_name", "amount"],
                grain=["supplier_name"],
                measures=[MeasureSpec(name="m", column="amount", aggregation="sum", table="invoices")],
            ),
            SourceSpec(
                table="quality",
                columns=["supplier_name", "score"],
                grain=["supplier_name"],
                measures=[MeasureSpec(name="m", column="score", aggregation="avg", table="quality")],
            ),
        ],
        relationships=[
            RelationshipSpec(
                left_table="invoices",
                right_table="quality",
                left_key=["supplier_name"],
                right_key=["supplier_name"],
                declared_cardinality="one_to_one",
            )
        ],
        time=TimeSpec(),
        final_grain=["supplier_name"],
        measures=[MeasureSpec(name="m", column="amount", aggregation="sum", table="invoices")],
        method_bundle=MethodBundle(primary=MethodRef(method_id="x")),
    )

    validator = MultiEntityJoinValidator(runner)
    with pytest.raises(ValueError, match="Many-to-many fan-out"):
        await validator.validate_plan(plan)


def test_frame_validator_accepts_valid_frame() -> None:
    plan = MultiEntityPlan(
        analysis_id="frame_test",
        intent="compare_entities",
        title="Spend by supplier",
        business_question="Compare suppliers",
        source_strategy=SourceStrategy(
            preference="multi_source_first",
            allow_single_source_fallback=False,
            selected_source_count=2,
            fallback_used=False,
            candidates_evaluated=1,
        ),
        entity=EntitySpec(
            type="supplier",
            id_column="id",
            name_column="supplier_name",
            selection_mode="explicit",
            requested_names=["A", "B"],
            maximum_entities=3,
        ),
        sources=[
            SourceSpec(
                table="invoices",
                columns=["supplier_name", "amount"],
                grain=["supplier_name"],
                measures=[MeasureSpec(name="m", column="amount", aggregation="sum", table="invoices")],
            )
        ],
        relationships=[],
        time=TimeSpec(),
        final_grain=["supplier_name"],
        measures=[MeasureSpec(name="m", column="amount", aggregation="sum", table="invoices")],
        method_bundle=MethodBundle(primary=MethodRef(method_id="x")),
    )
    result = {"columns": ["supplier_name", "m"], "rows": [{"supplier_name": "A", "m": 10}, {"supplier_name": "B", "m": 20}]}
    frame = MultiEntityFrameValidator(plan).validate(result)
    assert frame.status == "valid"
    assert frame.entity_count == 2
    assert frame.missing_requested_entities == []


def test_frame_validator_warns_missing_entity() -> None:
    plan = MultiEntityPlan(
        analysis_id="frame_test2",
        intent="compare_entities",
        title="Spend by supplier",
        business_question="Compare suppliers",
        source_strategy=SourceStrategy(
            preference="multi_source_first",
            allow_single_source_fallback=False,
            selected_source_count=1,
            fallback_used=False,
            candidates_evaluated=1,
        ),
        entity=EntitySpec(
            type="supplier",
            id_column="id",
            name_column="supplier_name",
            selection_mode="explicit",
            requested_names=["A", "B", "C"],
            maximum_entities=3,
        ),
        sources=[
            SourceSpec(
                table="invoices",
                columns=["supplier_name", "amount"],
                grain=["supplier_name"],
                measures=[MeasureSpec(name="m", column="amount", aggregation="sum", table="invoices")],
            )
        ],
        relationships=[],
        time=TimeSpec(),
        final_grain=["supplier_name"],
        measures=[MeasureSpec(name="m", column="amount", aggregation="sum", table="invoices")],
        method_bundle=MethodBundle(primary=MethodRef(method_id="x")),
    )
    result = {"columns": ["supplier_name", "m"], "rows": [{"supplier_name": "A", "m": 10}, {"supplier_name": "B", "m": 20}]}
    frame = MultiEntityFrameValidator(plan).validate(result)
    assert frame.status == "valid_with_warnings"
    assert "C" in frame.missing_requested_entities


def test_synthesize_evidence_conflicting() -> None:
    env = ExecutionEnvelope(
        method_id="compare_multiple_groups",
        status="ok",
        envelope={"status": "ok", "result": {"p_value": 0.01}},
        result={"p_value": 0.01},
    )
    env2 = ExecutionEnvelope(
        method_id="detect_trend",
        status="ok",
        envelope={"status": "error"},
        result={},
    )
    synth = synthesize_evidence([env, env2], "Compare A and B")
    assert synth.status == "conflicting"
    assert synth.confidence == "medium"


def test_synthesize_evidence_supported() -> None:
    env = ExecutionEnvelope(
        method_id="compare_multiple_groups",
        status="ok",
        envelope={"status": "ok", "result": {"p_value": 0.01}},
        result={"p_value": 0.01},
    )
    env2 = ExecutionEnvelope(
        method_id="detect_trend",
        status="ok",
        envelope={"status": "ok"},
        result={},
    )
    synth = synthesize_evidence([env, env2], "Compare A and B")
    assert synth.status == "supported"
    assert synth.confidence == "high"


@pytest.mark.asyncio
async def test_method_bundle_executor_runs_primary_and_supporting() -> None:
    bundle = MethodBundle(
        primary=MethodRef(method_id="compare_multiple_groups"),
        supporting=[MethodRef(method_id="detect_trend")],
    )
    session = AsyncMock()

    def _fake_analyze(*args: Any, **kwargs: Any) -> dict[str, Any]:
        method_id = kwargs.get("method_id")
        if method_id == "compare_multiple_groups":
            return {"status": "ok", "result": {"p_value": 0.01}, "method": method_id}
        return {"status": "ok", "method": method_id}

    with patch(
        "app.services.multi_entity_insights.method_bundle.analyze",
        side_effect=_fake_analyze,
    ) as mock_analyze:
        executor = MethodBundleExecutor(session, tenant_id=1)
        executions = await executor.execute(
            bundle,
            columns=["group", "value"],
            rows=[{"group": "A", "value": 10}, {"group": "B", "value": 20}],
            question="Compare A and B",
        )
        assert len(executions) == 2
        assert executions[0].method_id == "compare_multiple_groups"
        assert executions[0].envelope.get("status") == "ok"
        assert executions[1].method_id == "detect_trend"
        assert mock_analyze.call_count == 2


@pytest.mark.asyncio
async def test_method_bundle_executor_stops_at_max_three() -> None:
    bundle = MethodBundle(
        primary=MethodRef(method_id="m1"),
        supporting=[MethodRef(method_id="m2"), MethodRef(method_id="m3")],
    )
    session = AsyncMock()

    def _fake_analyze(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"status": "ok", "method": kwargs.get("method_id")}

    with patch(
        "app.services.multi_entity_insights.method_bundle.analyze",
        side_effect=_fake_analyze,
    ):
        executor = MethodBundleExecutor(session, tenant_id=1)
        executions = await executor.execute(
            bundle,
            columns=["x"],
            rows=[{"x": 1}],
            question="Q",
        )
        assert len(executions) == 3


def test_insight_payload_serializes_lineage() -> None:
    strategy = SourceStrategy(
        preference="multi_source_first",
        allow_single_source_fallback=False,
        selected_source_count=1,
        fallback_used=False,
        candidates_evaluated=1,
    )
    lineage = InsightLineage(
        source_strategy=strategy,
        sources=[],
        joins=[],
        grain={},
        filters=[],
        aggregations=[],
        resolved_entities=[],
        query_hash="abc",
        executions={},
        validation={},
    )
    payload = MultiEntityInsightPayload(
        insight_type="multi_entity_compare_entities",
        severity="info",
        title="Supplier comparison",
        summary="A is higher than B.",
        business_question="Compare suppliers",
        tables=["invoices"],
        sql="SELECT * FROM invoices",
        method_envelope={"status": "ok"},
        evidence_status="supported",
        entity_type="supplier",
        entities=[
            {
                "id": "1",
                "name": "A",
                "metrics": [
                    {"key": "spend", "label": "Spend", "value": 100, "formattedValue": "$100"}
                ],
            }
        ],
        lineage=lineage,
        source_strategy=strategy,
    )
    d = payload.model_dump(mode="json")
    assert d["evidence_status"] == "supported"
    assert d["entities"][0]["name"] == "A"
