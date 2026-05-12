"""Filesystem layout tests for CustomerFolderService."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.customer_folders import CustomerFolderError, CustomerFolderService


def test_ensure_tenant_folders(tmp_path: Path) -> None:
    service = CustomerFolderService(base_path=str(tmp_path))
    layout = service.ensure_tenant_folders("acme")
    assert layout.shared_data.exists()
    assert layout.shared_uploads.exists()
    assert layout.users_root.exists()


def test_ensure_user_folders(tmp_path: Path) -> None:
    service = CustomerFolderService(base_path=str(tmp_path))
    layout = service.ensure_user_folders("acme", "ext-alice")
    assert layout.user_data("ext-alice").exists()
    assert layout.user_uploads("ext-alice").exists()


def test_write_and_list_upload(tmp_path: Path) -> None:
    service = CustomerFolderService(base_path=str(tmp_path))
    service.write_upload(
        tenant_slug="acme",
        user_external_id="ext-alice",
        filename="sales.xlsx",
        content=b"binary-content",
    )
    files = service.list_user_files("acme", "ext-alice")
    # write_upload places into /uploads, not /data, so list_user_files (data)
    # should be empty here.
    assert files == []
    upload = (
        tmp_path
        / "acme"
        / "users"
        / "ext-alice"
        / "uploads"
        / "sales.xlsx"
    )
    assert upload.read_bytes() == b"binary-content"


def test_copy_to_shared_requires_source(tmp_path: Path) -> None:
    service = CustomerFolderService(base_path=str(tmp_path))
    service.ensure_user_folders("acme", "ext-alice")
    with pytest.raises(CustomerFolderError):
        service.copy_user_data_to_shared(
            tenant_slug="acme",
            user_external_id="ext-alice",
            filenames=["missing.xlsx"],
        )
