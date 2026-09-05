"""Unit tests for the SaaS connector framework (pure logic, no network)."""

from __future__ import annotations

import pytest

from app.connectors.base import RAW_JSON_KEY, StagingColumn
from app.connectors.registry import get_connector, supported_connectors
from app.connectors.saas.hubspot import HubSpotConnector, _coerce, _pg_type_for
from app.connectors.saas.servicenow import (
    ServiceNowConnector,
)
from app.connectors.saas.servicenow import (
    _pg_type_for as _servicenow_pg_type_for,
)
from app.services import saas_staging_service as staging


def test_registry_lists_and_resolves_connectors():
    supported = supported_connectors()
    assert "hubspot" in supported
    assert "salesforce" in supported
    assert "servicenow" in supported
    assert get_connector("hubspot").connector_type == "hubspot"
    assert get_connector("salesforce").connector_type == "salesforce"
    assert get_connector("servicenow").connector_type == "servicenow"


def test_registry_rejects_unknown_connector():
    from app.connectors.base import SaasConnectorError

    with pytest.raises(SaasConnectorError):
        get_connector("nope")


def test_hubspot_pg_type_mapping():
    assert _pg_type_for("number") == "double precision"
    assert _pg_type_for("bool") == "boolean"
    assert _pg_type_for("datetime") == "timestamptz"
    assert _pg_type_for("date") == "date"
    assert _pg_type_for("string") == "text"
    assert _pg_type_for("enumeration") == "text"


def test_hubspot_value_coercion():
    assert _coerce(None, "number") is None
    assert _coerce("", "string") is None
    assert _coerce("3.5", "number") == 3.5
    assert _coerce("true", "bool") is True
    assert _coerce("no", "bool") is False
    assert _coerce("hi", "string") == "hi"


def test_hubspot_normalize_carries_raw_json_and_fields():
    conn = HubSpotConnector()
    item = {
        "id": "42",
        "archived": False,
        "createdAt": "2024-01-01T00:00:00Z",
        "updatedAt": "2024-01-02T00:00:00Z",
        "properties": {"email": "a@b.com", "amount": "10.5"},
    }
    row = conn._normalize(item, ["email", "amount"], {"amount": "number"})
    assert row["hubspot_id"] == "42"
    assert row["email"] == "a@b.com"
    assert row["amount"] == 10.5
    assert row[RAW_JSON_KEY] == item


def test_servicenow_pg_type_mapping():
    assert _servicenow_pg_type_for("integer") == "integer"
    assert _servicenow_pg_type_for("decimal") == "double precision"
    assert _servicenow_pg_type_for("currency") == "double precision"
    assert _servicenow_pg_type_for("boolean") == "boolean"
    assert _servicenow_pg_type_for("glide_date_time") == "timestamptz"
    assert _servicenow_pg_type_for("glide_date") == "date"
    assert _servicenow_pg_type_for("string") == "text"
    assert _servicenow_pg_type_for("reference") == "text"


def test_servicenow_accepts_valid_table_names_and_rejects_invalid():
    from app.connectors.base import SaasConnectorError

    conn = ServiceNowConnector()
    conn._check_object("incident")
    conn._check_object("sc_request")
    conn._check_object("change_request")
    conn._check_object("sys_user")
    conn._check_object("cmdb_ci")
    with pytest.raises(SaasConnectorError):
        conn._check_object("bad;injection")
    with pytest.raises(SaasConnectorError):
        conn._check_object("")


def test_servicenow_normalize_carries_raw_json_and_fields():
    conn = ServiceNowConnector()
    item = {
        "sys_id": "abc123",
        "number": "INC0010001",
        "sys_created_on": "2024-01-01 00:00:00",
        "sys_updated_on": "2024-01-02 00:00:00",
        "short_description": "VPN down",
        "priority": "1",
    }
    row = conn._normalize(item, ["short_description", "priority"])
    assert row["sys_id"] == "abc123"
    assert row["number"] == "INC0010001"
    assert row["short_description"] == "VPN down"
    assert row["priority"] == "1"
    assert row[RAW_JSON_KEY] == item


def test_servicenow_base_url_normalizes_bare_host():
    conn = ServiceNowConnector()
    assert conn._base_url({"instance_url": "mycompany.service-now.com"}) == (
        "https://mycompany.service-now.com"
    )
    assert conn._base_url({"instance_url": "https://mycompany.service-now.com/"}) == (
        "https://mycompany.service-now.com"
    )


def test_all_columns_appends_raw_json_and_dedups():
    base = [
        StagingColumn(name="hubspot_id", pg_type="text", primary_key=True),
        StagingColumn(name="archived", pg_type="boolean"),
    ]
    selected = [
        StagingColumn(name="archived", pg_type="boolean"),  # duplicate -> dropped
        StagingColumn(name="email", pg_type="text"),
    ]
    cols = staging.all_columns(base, selected)
    names = [c.name for c in cols]
    assert names.count("archived") == 1
    assert "email" in names
    assert names[-1] == RAW_JSON_KEY
    assert cols[-1].pg_type == "jsonb"


def test_staging_identifier_validation():
    assert staging._validate_ident("good_name1") == "good_name1"
    # Salesforce custom fields end in __c and are valid.
    assert staging._validate_ident("My_Field__c") == "My_Field__c"
    for bad in ["", "1abc", "drop table", "a;b", 'a"b']:
        with pytest.raises(ValueError):
            staging._validate_ident(bad)


def test_staging_pg_type_validation():
    for ok in ["text", "boolean", "double precision", "timestamptz", "jsonb"]:
        assert staging._validate_pg_type(ok) == ok
    with pytest.raises(ValueError):
        staging._validate_pg_type("text; drop table")


# ── requires_reauth: rejected credentials must be distinguishable from a ──
# ── transient/network failure, so a caller can prompt reconnection      ──
# ── instead of surfacing a dead-end error.                              ──

def _http_status_error(status: int):
    import httpx

    request = httpx.Request("GET", "https://example.test")
    response = httpx.Response(status, request=request)
    return httpx.HTTPStatusError("boom", request=request, response=response)


def test_servicenow_connector_error_marks_401_and_403_as_requires_reauth():
    from app.connectors.saas.servicenow import _connector_error

    for status in (401, 403):
        err = _connector_error(_http_status_error(status))
        assert err.requires_reauth is True
    err = _connector_error(_http_status_error(500))
    assert err.requires_reauth is False


def test_hubspot_connector_error_marks_401_and_403_as_requires_reauth():
    from app.connectors.saas.hubspot import _connector_error

    for status in (401, 403):
        err = _connector_error(_http_status_error(status))
        assert err.requires_reauth is True
    err = _connector_error(_http_status_error(429))
    assert err.requires_reauth is False


def test_quickbooks_connector_error_marks_401_and_403_as_requires_reauth():
    from app.connectors.saas.quickbooks import _connector_error

    for status in (401, 403):
        err = _connector_error(_http_status_error(status))
        assert err.requires_reauth is True
    err = _connector_error(_http_status_error(500))
    assert err.requires_reauth is False


def test_salesforce_connector_error_marks_400_401_403_as_requires_reauth():
    from app.connectors.saas.salesforce import _connector_error

    for status in (400, 401, 403):
        err = _connector_error(_http_status_error(status))
        assert err.requires_reauth is True
    err = _connector_error(_http_status_error(500))
    assert err.requires_reauth is False


def test_connector_error_is_false_for_a_network_failure():
    import httpx

    from app.connectors.saas.servicenow import _connector_error

    request = httpx.Request("GET", "https://example.test")
    err = _connector_error(httpx.ConnectError("refused", request=request))
    assert err.requires_reauth is False
