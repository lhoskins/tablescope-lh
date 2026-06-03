"""Connector registry — maps a connector type to its implementation."""

from __future__ import annotations

from app.connectors.base import SaasConnector, SaasConnectorError
from app.connectors.saas.hubspot import HubSpotConnector
from app.connectors.saas.quickbooks import QuickBooksConnector
from app.connectors.saas.salesforce import SalesforceConnector

_REGISTRY: dict[str, SaasConnector] = {
    HubSpotConnector.connector_type: HubSpotConnector(),
    SalesforceConnector.connector_type: SalesforceConnector(),
    QuickBooksConnector.connector_type: QuickBooksConnector(),
}


def get_connector(connector_type: str) -> SaasConnector:
    connector = _REGISTRY.get(connector_type)
    if connector is None:
        raise SaasConnectorError(f"Unknown connector type: {connector_type!r}")
    return connector


def supported_connectors() -> list[str]:
    return sorted(_REGISTRY.keys())
