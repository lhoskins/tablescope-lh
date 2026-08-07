"""HubSpot / QuickBooks source-identifier mapping tests.

Verifies that the local staging column names are translated back to the
API-specific source names used in NAMEINSOURCE by the live Teiid translators.
"""

from __future__ import annotations

from app.services.database_introspection_service import source_identifier


def test_hubspot_base_column_map() -> None:
    assert source_identifier("hubspot", "hubspot_id") == "id"
    assert source_identifier("hubspot", "archived") == "archived"
    assert source_identifier("hubspot", "created_at") == "createdAt"
    assert source_identifier("hubspot", "updated_at") == "updatedAt"
    assert source_identifier("hubspot", "firstname") == "firstname"


def test_quickbooks_base_column_map() -> None:
    assert source_identifier("quickbooks", "quickbooks_id") == "Id"
    assert source_identifier("quickbooks", "sync_token") == "SyncToken"
    assert source_identifier("quickbooks", "created_time") == "MetaData.CreateTime"
    assert source_identifier("quickbooks", "updated_time") == "MetaData.LastUpdatedTime"
    assert source_identifier("quickbooks", "CompanyName") == "CompanyName"
