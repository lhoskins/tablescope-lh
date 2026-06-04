"""Filesystem layout tests for CustomerFolderService."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.customer_folders import (
    CustomerFolderError,
    CustomerFolderService,
    UnsafeFilenameError,
)


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


@pytest.mark.parametrize(
    "filename, expected_basename",
    [
        ("../etc/passwd", "passwd"),
        ("../../shared/data/evil.csv", "evil.csv"),
        ("/etc/passwd", "passwd"),
        ("..\\windows\\system32\\evil.dat", "evil.dat"),
    ],
)
def test_write_upload_sanitizes_traversal_to_basename(
    tmp_path: Path, filename: str, expected_basename: str
) -> None:
    """Traversal attempts get normalized to their basename and stay inside uploads."""
    service = CustomerFolderService(base_path=str(tmp_path))
    target = service.write_upload(
        tenant_slug="acme",
        user_external_id="ext-alice",
        filename=filename,
        content=b"x",
    )
    expected_parent = (
        tmp_path / "acme" / "users" / "ext-alice" / "uploads"
    ).resolve()
    assert target.resolve().is_relative_to(expected_parent)
    assert target.name == expected_basename
    # Belt-and-suspenders: nothing ended up outside the uploads dir.
    assert not (tmp_path.parent / "passwd").exists()
    assert not Path("/etc/passwd_unsafe_test").exists()


@pytest.mark.parametrize(
    "filename",
    [".", "..", "", "with\x00nul.csv"],
)
def test_write_upload_rejects_invalid_filenames(
    tmp_path: Path, filename: str
) -> None:
    service = CustomerFolderService(base_path=str(tmp_path))
    with pytest.raises(UnsafeFilenameError):
        service.write_upload(
            tenant_slug="acme",
            user_external_id="ext-alice",
            filename=filename,
            content=b"x",
        )


def test_copy_to_shared_sanitizes_traversal(tmp_path: Path) -> None:
    """Traversal filenames in share requests get reduced to basenames.

    The sanitized basename is then looked up inside the user's own data
    folder — if it doesn't exist there, the call fails cleanly without
    ever touching paths outside the tenant root.
    """
    service = CustomerFolderService(base_path=str(tmp_path))
    layout = service.ensure_user_folders("acme", "ext-alice")
    # Plant a legitimate user file so the sanitized name resolves.
    (layout.user_data("ext-alice") / "evil.csv").write_bytes(b"real")

    copied = service.copy_user_data_to_shared(
        tenant_slug="acme",
        user_external_id="ext-alice",
        filenames=["../../shared/data/evil.csv"],
    )
    assert len(copied) == 1
    assert copied[0].resolve().is_relative_to(layout.shared_data.resolve())
    assert copied[0].name == "evil.csv"
