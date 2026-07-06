"""Tests for column-reference validation in generated SQL.

Ensures hallucinated column names (columns a source does not expose) are
rejected so the repair pass can remap them, while valid queries pass.

Run from the ``tablescope-ai-api`` directory: ``pytest -q``.
"""

from __future__ import annotations

import pytest

from app.routers.ai import _catalog_table_columns
from app.models.schemas import SourceCatalogEntry
from app.services.sql_validator import SQLValidationError, validate_sql

ALLOWED = ["SUP_Quality_Inspections_CSV", "LOG_Shipments_CSV"]

QUALITY_COLS = [
    "InspectionID", "PurchaseOrderID", "SupplierID", "PartID",
    "InspectionDate", "ReceivedQty", "DefectQty", "DefectType",
    "Severity", "Disposition", "CAPARequired",
]
SHIPMENT_COLS = [
    "ShipmentID", "PurchaseOrderID", "SupplierID", "Carrier", "Mode",
    "OriginCountry", "DestinationSite", "ShipDate", "DeliveryDate",
    "FreightCostUSD", "ShipmentStatus", "DelayReason",
]

TABLE_COLUMNS = {
    "SUP_Quality_Inspections_CSV": QUALITY_COLS,
    "LOG_Shipments_CSV": SHIPMENT_COLS,
}


def test_rejects_hallucinated_qualified_column() -> None:
    # q.DefectRate does not exist (real column is DefectQty).
    sql = (
        "SELECT q.SupplierID, AVG(q.DefectRate) AS AverageDefectRate "
        "FROM SUP_Quality_Inspections_CSV q GROUP BY q.SupplierID"
    )
    with pytest.raises(SQLValidationError) as exc:
        validate_sql(sql, ALLOWED, table_columns=TABLE_COLUMNS)
    assert "DefectRate" in exc.value.reason
    # The error lists the real columns so the repair pass can remap.
    assert "DefectQty" in exc.value.reason


def test_rejects_hallucinated_bare_column_single_table() -> None:
    sql = (
        "SELECT supplier_quality_score, COUNT(*) AS number_of_suppliers "
        "FROM SUP_Quality_Inspections_CSV GROUP BY supplier_quality_score"
    )
    with pytest.raises(SQLValidationError) as exc:
        validate_sql(sql, ALLOWED, table_columns=TABLE_COLUMNS)
    assert "supplier_quality_score" in exc.value.reason


def test_rejects_hallucinated_column_in_join() -> None:
    # l.SupplierName does not exist (real column is SupplierID).
    sql = (
        "SELECT l.SupplierName, COUNT(*) AS LateShipmentsCount "
        "FROM LOG_Shipments_CSV l WHERE l.ShipmentStatus = 'Late' "
        "GROUP BY l.SupplierName"
    )
    with pytest.raises(SQLValidationError) as exc:
        validate_sql(sql, ALLOWED, table_columns=TABLE_COLUMNS)
    assert "SupplierName" in exc.value.reason


def test_accepts_valid_qualified_columns() -> None:
    sql = (
        "SELECT q.SupplierID, "
        "SUM(CAST(q.DefectQty AS double)) AS TotalDefects "
        "FROM SUP_Quality_Inspections_CSV q GROUP BY q.SupplierID"
    )
    validate_sql(sql, ALLOWED, table_columns=TABLE_COLUMNS)


def test_accepts_valid_bare_columns_with_string_literal() -> None:
    sql = (
        "SELECT SupplierID, COUNT(*) AS LateCount "
        "FROM LOG_Shipments_CSV WHERE ShipmentStatus = 'Late' "
        "GROUP BY SupplierID"
    )
    validate_sql(sql, ALLOWED, table_columns=TABLE_COLUMNS)


def test_no_column_check_without_table_columns() -> None:
    # Backwards compatible: without a column map, only tables are validated.
    sql = "SELECT q.DefectRate FROM SUP_Quality_Inspections_CSV q"
    validate_sql(sql, ALLOWED)


def test_multi_table_bare_columns_not_flagged() -> None:
    # Ambiguous bare columns across joined tables are left to qualified checks.
    sql = (
        "SELECT SupplierID, COUNT(*) AS c "
        "FROM SUP_Quality_Inspections_CSV q "
        "JOIN LOG_Shipments_CSV l ON q.PurchaseOrderID = l.PurchaseOrderID "
        "GROUP BY SupplierID"
    )
    validate_sql(sql, ALLOWED, table_columns=TABLE_COLUMNS)


def test_catalog_table_columns_skips_queries_and_empty() -> None:
    catalog = [
        SourceCatalogEntry(
            name="SUP_Quality_Inspections_CSV",
            columns=QUALITY_COLS,
            kind="table",
        ),
        SourceCatalogEntry(name="Saved Q", columns=[], kind="query"),
        SourceCatalogEntry(name="No Cols", columns=[], kind="table"),
    ]
    out = _catalog_table_columns(catalog)
    assert out == {"SUP_Quality_Inspections_CSV": QUALITY_COLS}
