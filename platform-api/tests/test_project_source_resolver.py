"""Tests for the shared Project Semantic Source Resolver."""

from __future__ import annotations

import pytest

from app.models.database_data_source import DatabaseDataSource, DataSourceColumn
from app.models.file_source_meta import FileSourceMeta
from app.services.project_source_resolver import resolve_project_source

pytestmark = pytest.mark.asyncio

TENANT = 1
OTHER_TENANT = 2
PROJECT = 10


async def _add_file_source(
    session, *, view_name: str, columns: list[str],
    tenant_id: int = TENANT, project_id: int = PROJECT, summary: str = "",
) -> None:
    session.add(
        FileSourceMeta(
            tenant_id=tenant_id,
            owner_id=1,
            project_id=project_id,
            view_name=view_name,
            file_name=f"{view_name}.csv",
            vdb_type="user",
            column_types=[{"name": c, "type": "string"} for c in columns],
            ai_metadata={"summary": summary} if summary else {},
        )
    )
    await session.commit()


async def _add_db_source(
    session, *, view_name: str, columns: list[str],
    tenant_id: int = TENANT, project_id: int = PROJECT,
) -> None:
    ds = DatabaseDataSource(
        tenant_id=tenant_id,
        project_id=project_id,
        display_name=view_name,
        db_type="postgres",
        host="db",
        port=5432,
        database_name="db",
        table_name=view_name,
        username="u",
        teiid_model_name=view_name,
        teiid_table_name=view_name,
        teiid_view_name=view_name,
        teiid_jndi_name=f"java:/{view_name}",
    )
    ds.columns = [
        DataSourceColumn(column_name=c, ordinal_position=i)
        for i, c in enumerate(columns)
    ]
    session.add(ds)
    await session.commit()


async def _seed_supply_chain(session) -> None:
    await _add_file_source(
        session,
        view_name="SUP_Quality_Inspections_CSV",
        columns=["SupplierID", "DefectRate", "InspectionDate", "PartID"],
    )
    await _add_file_source(
        session,
        view_name="SUP_Purchase_Orders_CSV",
        columns=["SupplierID", "Amount", "Total", "OrderDate"],
    )
    await _add_file_source(
        session,
        view_name="LOG_Shipments_CSV",
        columns=["ShipmentID", "LeadTimeDays", "CarrierID", "TransitDays"],
    )


async def test_resolves_supplier_defect_rate(db_session) -> None:
    await _seed_supply_chain(db_session)
    result = await resolve_project_source(
        db_session,
        tenant_id=TENANT,
        project_id=PROJECT,
        question="What is the defect rate for each supplier?",
    )
    assert result.status == "resolved"
    assert result.preferred_sources == ["SUP_Quality_Inspections_CSV"]
    assert "DefectRate" in result.relevant_columns


async def test_resolves_top_suppliers_by_defect_rate(db_session) -> None:
    await _seed_supply_chain(db_session)
    result = await resolve_project_source(
        db_session,
        tenant_id=TENANT,
        project_id=PROJECT,
        question=(
            "What are the top 10 suppliers with the highest defect rate "
            "based on quality inspections?"
        ),
    )
    assert result.status == "resolved"
    assert result.preferred_sources == ["SUP_Quality_Inspections_CSV"]


async def test_resolves_total_spend_trend(db_session) -> None:
    await _seed_supply_chain(db_session)
    result = await resolve_project_source(
        db_session,
        tenant_id=TENANT,
        project_id=PROJECT,
        question="How has total spend changed across recent periods?",
        intent="investigate",
    )
    assert result.status == "resolved"
    assert result.preferred_sources == ["SUP_Purchase_Orders_CSV"]


async def test_resolves_logistics_delay(db_session) -> None:
    await _seed_supply_chain(db_session)
    result = await resolve_project_source(
        db_session,
        tenant_id=TENANT,
        project_id=PROJECT,
        question="What are the average delivery lead times by carrier?",
    )
    assert result.status == "resolved"
    assert result.preferred_sources == ["LOG_Shipments_CSV"]


async def test_close_scores_auto_pick_top_source(db_session) -> None:
    # Two sources with equally strong evidence (supplier entity + spend metric):
    # the resolver never asks the user to choose — it always auto-selects the
    # single highest-ranked source (deterministic tie-break by score then name).
    await _add_file_source(
        session=db_session,
        view_name="SUP_Spend_A_CSV",
        columns=["SupplierID", "Amount"],
    )
    await _add_file_source(
        session=db_session,
        view_name="SUP_Spend_B_CSV",
        columns=["SupplierID", "Amount"],
    )
    result = await resolve_project_source(
        db_session,
        tenant_id=TENANT,
        project_id=PROJECT,
        question="What is total supplier spend?",
    )
    assert result.status == "resolved"
    assert len(result.preferred_sources) == 1
    # The chosen source is the deterministic top rank, not a user prompt.
    assert result.preferred_sources[0] in {"SUP_Spend_A_CSV", "SUP_Spend_B_CSV"}


async def test_unauthorized_source_never_selected(db_session) -> None:
    # A perfectly-matching source that belongs to a different tenant must be
    # invisible to the resolver.
    await _add_file_source(
        db_session,
        view_name="SUP_Quality_Inspections_CSV",
        columns=["SupplierID", "DefectRate"],
        tenant_id=OTHER_TENANT,
    )
    result = await resolve_project_source(
        db_session,
        tenant_id=TENANT,
        project_id=PROJECT,
        question="What is the defect rate for each supplier?",
    )
    assert result.status == "no_match"
    assert result.preferred_sources == []


async def test_database_data_source_is_included(db_session) -> None:
    await _add_db_source(
        db_session,
        view_name="fin_invoices",
        columns=["CustomerID", "Amount", "InvoiceDate"],
    )
    result = await resolve_project_source(
        db_session,
        tenant_id=TENANT,
        project_id=PROJECT,
        question="What is the total spend by customer?",
    )
    assert result.status == "resolved"
    assert result.preferred_sources == ["fin_invoices"]


async def test_card_context_prefers_authorized_source(db_session) -> None:
    await _seed_supply_chain(db_session)
    result = await resolve_project_source(
        db_session,
        tenant_id=TENANT,
        project_id=PROJECT,
        question="How has total spend changed across recent periods?",
        intent="investigate",
        card_context={
            "sourceTables": ["SUP_Purchase_Orders_CSV"],
            "sourceColumns": ["Amount", "OrderDate"],
            "metric": "spend",
        },
    )
    assert result.status == "resolved"
    assert result.preferred_sources == ["SUP_Purchase_Orders_CSV"]
    assert result.relevant_columns == ["Amount", "OrderDate"]


async def test_card_context_suffix_insensitive_match(db_session) -> None:
    await _seed_supply_chain(db_session)
    # Card names the table without its physical _CSV suffix.
    result = await resolve_project_source(
        db_session,
        tenant_id=TENANT,
        project_id=PROJECT,
        question="Investigate the defect rate risk",
        intent="investigate",
        card_context={"sourceTables": ["SUP_Quality_Inspections"]},
    )
    assert result.status == "resolved"
    assert result.preferred_sources == ["SUP_Quality_Inspections_CSV"]


async def test_no_sources_returns_no_match(db_session) -> None:
    result = await resolve_project_source(
        db_session,
        tenant_id=TENANT,
        project_id=PROJECT,
        question="What is the defect rate?",
    )
    assert result.status == "no_match"
    assert "no authorized data sources" in result.reason.lower()


async def test_partition_questions_splits_answerable_and_needs_data(
    db_session,
) -> None:
    from app.services.project_insight_service import _partition_questions

    await _seed_supply_chain(db_session)
    items = [
        {"id": "a", "question": "What is the defect rate for each supplier?"},
        {"id": "b", "question": "What is the employee headcount by department?"},
    ]
    answerable, needs_data = await _partition_questions(
        db_session,
        tenant_id=TENANT,
        project_id=PROJECT,
        kpi_names=[],
        items=items,
        question_keys=("question",),
        has_sources=True,
    )
    assert [q["id"] for q in answerable] == ["a"]
    assert [q["id"] for q in needs_data] == ["b"]
    assert needs_data[0]["missingDataHint"]  # explains the missing data


async def test_partition_questions_no_sources_keeps_all(db_session) -> None:
    from app.services.project_insight_service import _partition_questions

    items = [{"id": "a", "question": "What is the defect rate?"}]
    answerable, needs_data = await _partition_questions(
        db_session,
        tenant_id=TENANT,
        project_id=PROJECT,
        kpi_names=[],
        items=items,
        question_keys=("question",),
        has_sources=False,
    )
    assert answerable == items
    assert needs_data == []
