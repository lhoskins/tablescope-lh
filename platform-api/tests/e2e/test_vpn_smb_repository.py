"""End-to-end validation of the VPN/SMB repository import workflow.

These tests are designed to run against a disposable TableScope staging tenant
that has an active AWS Site-to-Site VPN to the customer simulator.  They are
skipped unless the required environment variables are present.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("VPN_SMB_E2E_API_URL"),
    reason="VPN_SMB_E2E_API_URL is not set (skipping live VPN/SMB E2E)",
)


@pytest.mark.asyncio
async def test_tenant_smb_data_source_imports_and_queries():
    """Full workflow: create tenant/project, provision VPN, register
    connection, import a structured fixture, and query the resulting Teiid
    source through the public TableScope API."""
    raise AssertionError("VPN_SMB_E2E_API_URL is set but the full scenario is not implemented yet")


@pytest.mark.asyncio
async def test_smb_import_cannot_escape_approved_root():
    """A path outside the approved root must be rejected even when the VPN and
    SMB session are otherwise valid."""
    pass


@pytest.mark.asyncio
async def test_cross_tenant_smb_connection_is_rejected():
    """A network_file_connection belonging to another tenant must not be
    usable from the control tenant."""
    pass


@pytest.mark.asyncio
async def test_ai_pipeline_never_receives_smb_credentials():
    """Inspect project prompts/audit to confirm no UNC path, password, or
    share name reaches the AI context."""
    pass
