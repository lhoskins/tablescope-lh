"""Path-resolution security for UNC/SMB imports.

``resolve_network_path`` is pure, so the whole traversal/allowlist surface is
testable without a share. Anything it accepts is what the gateway will open.
"""

from __future__ import annotations

import pytest

from app.config import get_settings
from app.models.network_file_connection import NetworkFileConnection
from app.services.smb_gateway import NetworkPathError, resolve_network_path


@pytest.fixture(autouse=True)
def _allow_host(monkeypatch):
    monkeypatch.setenv("FILE_IMPORT_ALLOWED_SMB_HOSTS", "fileserver,other-host")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _connection(**overrides) -> NetworkFileConnection:
    defaults = {
        "tenant_id": 1,
        "name": "Finance share",
        "host": "fileserver",
        "port": 445,
        "share_name": "data",
        "approved_root_path": "finance",
        "enabled": True,
        "archived": False,
    }
    defaults.update(overrides)
    return NetworkFileConnection(**defaults)


def _expect(path: str, code: str, **overrides) -> None:
    with pytest.raises(NetworkPathError) as exc:
        resolve_network_path(path, _connection(**overrides))
    assert exc.value.code == code


# ── Accepted forms ───────────────────────────────────────────────────────


def test_unc_path_inside_approved_root_resolves():
    resolved = resolve_network_path(
        r"\\fileserver\data\finance\q3\sales.xlsx", _connection()
    )
    assert resolved.host == "fileserver"
    assert resolved.share == "data"
    assert resolved.relative_path == "finance/q3/sales.xlsx"
    assert resolved.filename == "sales.xlsx"
    assert resolved.unc_path == r"\\fileserver\data\finance\q3\sales.xlsx"


def test_smb_url_is_accepted_and_normalised():
    resolved = resolve_network_path(
        "smb://fileserver/data/finance/q3/sales.xlsx", _connection()
    )
    assert resolved.relative_path == "finance/q3/sales.xlsx"


def test_redacted_locator_hides_intermediate_folders():
    resolved = resolve_network_path(
        r"\\fileserver\data\finance\project-atlas-acquisition\sales.xlsx",
        _connection(),
    )
    assert "project-atlas-acquisition" not in resolved.redacted_locator
    assert resolved.redacted_locator.endswith("sales.xlsx")


# ── Refusals ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "path",
    [
        r"\\fileserver\data\finance\..\..\windows\system32\config\sam",
        r"\\fileserver\data\finance\..\hr\salaries.xlsx",
        "smb://fileserver/data/finance/../hr/salaries.xlsx",
    ],
)
def test_traversal_is_refused(path):
    _expect(path, "OUTSIDE_APPROVED_ROOT")


def test_path_outside_approved_root_is_refused():
    _expect(r"\\fileserver\data\hr\salaries.xlsx", "OUTSIDE_APPROVED_ROOT")


def test_other_host_is_refused_even_when_allowlisted():
    _expect(r"\\other-host\data\finance\sales.xlsx", "HOST_NOT_APPROVED")


def test_host_absent_from_allowlist_is_refused(monkeypatch):
    monkeypatch.setenv("FILE_IMPORT_ALLOWED_SMB_HOSTS", "")
    get_settings.cache_clear()
    _expect(r"\\fileserver\data\finance\sales.xlsx", "HOST_NOT_APPROVED")


def test_other_share_is_refused():
    _expect(r"\\fileserver\payroll\finance\sales.xlsx", "SHARE_NOT_APPROVED")


def test_administrative_share_is_refused():
    _expect(
        r"\\fileserver\C$\finance\sales.xlsx",
        "SHARE_NOT_APPROVED",
        share_name="C$",
    )


@pytest.mark.parametrize(
    "path",
    [
        r"\\.\PHYSICALDRIVE0\data\finance\x.csv",
        r"\\?\C:\data\finance\x.csv",
    ],
)
def test_device_paths_are_refused(path):
    _expect(path, "INVALID_PATH")


def test_embedded_credentials_are_refused():
    _expect(r"\\user:pass@fileserver\data\finance\x.csv", "INVALID_PATH")


@pytest.mark.parametrize(
    "path",
    [
        r"\\fileserver\data\finance\*.xlsx",
        r"\\fileserver\data\finance\rep?rt.xlsx",
        r"\\fileserver\data\finance\file:stream.xlsx",
    ],
)
def test_wildcards_and_streams_are_refused(path):
    _expect(path, "INVALID_PATH")


def test_control_characters_are_refused():
    _expect("\\\\fileserver\\data\\finance\\sa\x00les.xlsx", "INVALID_PATH")


def test_local_and_relative_paths_are_refused():
    _expect("C:/data/finance/sales.xlsx", "INVALID_PATH")
    _expect("finance/sales.xlsx", "INVALID_PATH")


def test_directory_without_filename_is_refused():
    _expect(r"\\fileserver\data\finance", "INVALID_PATH")


def test_disabled_connection_is_refused():
    _expect(
        r"\\fileserver\data\finance\sales.xlsx", "CONNECTION_DISABLED", enabled=False
    )


def test_archived_connection_is_refused():
    _expect(
        r"\\fileserver\data\finance\sales.xlsx", "CONNECTION_DISABLED", archived=True
    )


def test_stored_secret_is_never_part_of_the_resolved_path():
    connection = _connection(username="svc_reader", secret_encrypted="gAAAAAtoken")
    resolved = resolve_network_path(
        r"\\fileserver\data\finance\sales.xlsx", connection
    )
    rendered = f"{resolved.unc_path}{resolved.redacted_locator}{connection.label}"
    assert "gAAAAAtoken" not in rendered
    assert "svc_reader" not in rendered
