"""Unit tests for the UNC/SMB repository connector."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
import smbclient

from app.connectors.repositories import get_repository_connector
from app.connectors.repositories.unc import UNCRepositoryConnector

pytestmark = pytest.mark.anyio


@dataclass
class _FakeStat:
    st_size: int = 0
    st_ino: int = 12345
    st_mtime: float = 1704067200.0
    st_ctime: float = 1704067200.0


@dataclass
class _FakeDirEntry:
    name: str
    is_dir_flag: bool = False
    is_file_flag: bool = True
    is_symlink_flag: bool = False
    stat_value: _FakeStat | None = None

    def is_dir(self) -> bool:
        return self.is_dir_flag

    def is_file(self) -> bool:
        return self.is_file_flag

    def is_symlink(self) -> bool:
        return self.is_symlink_flag

    def stat(self, *, follow_symlinks: bool = True) -> _FakeStat:
        return self.stat_value or _FakeStat()

    def inode(self) -> int:
        return (self.stat_value or _FakeStat()).st_ino


class _FakeFile:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self, size: int | None = None) -> bytes:
        if size is None or size < 0:
            return self._data
        return self._data[:size]

    def __enter__(self) -> _FakeFile:
        return self

    def __exit__(self, *args: Any) -> None:
        pass


@pytest.fixture
def connector() -> UNCRepositoryConnector:
    return get_repository_connector("unc")


@pytest.fixture(autouse=True)
def _patch_smbclient(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch out all live SMB/socket calls for every test in this module."""

    monkeypatch.setattr(
        "smbclient.register_session",
        lambda server, **kwargs: None,
    )
    monkeypatch.setattr(
        "smbclient.delete_session",
        lambda server: None,
    )
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("127.0.0.1", 0))],
    )


def test_connector_is_registered() -> None:
    assert get_repository_connector("unc").connector_type == "unc"


async def test_validate_config_accepts_valid_unc(connector: UNCRepositoryConnector) -> None:
    await connector.validate_config(
        {
            "rootPath": r"\\server\share\Reports",
            "allowedExtensions": ["pdf", "docx"],
            "recursive": True,
            "maxFileSizeBytes": 10_000_000,
        }
    )


@pytest.mark.parametrize(
    "config,expected_substring",
    [
        ({"rootPath": "C:\\Reports"}, "Local drive"),
        ({"rootPath": "smb://server/share"}, "URI schemes"),
        ({"rootPath": "\\\\server"}, "share"),
        ({"rootPath": "\\\\server\\share\\..\\other"}, "traversal"),
        ({"rootPath": r"\\?\\UNC\server\share"}, "Extended UNC"),
        ({"rootPath": "\\\\server\\share", "allowedExtensions": "pdf"}, "list of strings"),
        ({"rootPath": "\\\\server\\share", "maxFileSizeBytes": -1}, "non-negative"),
    ],
)
async def test_validate_config_rejects_invalid_input(
    connector: UNCRepositoryConnector,
    config: dict[str, Any],
    expected_substring: str,
) -> None:
    from app.connectors.repositories.base import RepositoryConnectorError

    with pytest.raises(RepositoryConnectorError) as exc:
        await connector.validate_config(config)
    assert expected_substring in str(exc.value)


async def test_test_connection_success(
    connector: UNCRepositoryConnector,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_scandir(path: str) -> list[Any]:
        return [
            _FakeDirEntry("Q1", is_dir_flag=True, is_file_flag=False),
            _FakeDirEntry("report.pdf", is_dir_flag=False, is_file_flag=True),
        ]

    monkeypatch.setattr(smbclient.path, "isdir", lambda path: True)
    monkeypatch.setattr(smbclient, "scandir", _fake_scandir)

    result = await connector.test_connection(
        {"rootPath": r"\\server\share\Reports"},
        {"username": "u", "password": "p"},
    )

    assert result.success is True
    assert result.sample == {"itemsVisible": 2}
    check_names = {c.name for c in result.checks}
    assert check_names == {"configuration", "dns_resolution", "authentication", "root_access", "directory_listing"}


async def test_test_connection_authentication_failure(
    connector: UNCRepositoryConnector,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from smbprotocol.exceptions import SMBAuthenticationError

    def _raise(*args: Any, **kwargs: Any) -> None:
        raise SMBAuthenticationError("Bad creds")

    monkeypatch.setattr("smbclient.register_session", _raise)

    result = await connector.test_connection(
        {"rootPath": r"\\server\share"},
        {"username": "u", "password": "p"},
    )

    assert result.success is False
    auth_check = next(c for c in result.checks if c.name == "authentication")
    assert auth_check.status == "failed"
    assert "Authentication" in auth_check.message


async def test_list_items_enumerates_files_and_directories(
    connector: UNCRepositoryConnector,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fs: dict[str, list[Any]] = {
        r"\\server\share\Reports": [
            _FakeDirEntry("2024", is_dir_flag=True, is_file_flag=False),
            _FakeDirEntry("summary.pdf", is_dir_flag=False, is_file_flag=True, stat_value=_FakeStat(st_size=1024, st_ino=1, st_mtime=1704067200.0)),
        ],
        r"\\server\share\Reports\2024": [
            _FakeDirEntry("Q1.pdf", is_dir_flag=False, is_file_flag=True, stat_value=_FakeStat(st_size=2048, st_ino=2, st_mtime=1704067200.0)),
        ],
    }

    monkeypatch.setattr(
        smbclient,
        "scandir",
        lambda path: fs.get(path, []),
    )

    page1 = await connector.list_items(
        {"rootPath": r"\\server\share\Reports", "recursive": True},
        {"username": "u", "password": "p"},
        page_size=2,
    )
    assert page1.has_more is True
    assert len(page1.items) == 2

    page2 = await connector.list_items(
        {"rootPath": r"\\server\share\Reports", "recursive": True},
        {"username": "u", "password": "p"},
        checkpoint=page1.checkpoint,
        page_size=10,
    )
    assert page2.has_more is False
    paths = {item.relative_path for item in page2.items}
    assert "2024/Q1.pdf" in paths


async def test_list_items_respects_allowed_extensions(
    connector: UNCRepositoryConnector,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smbclient,
        "scandir",
        lambda path: [
            _FakeDirEntry("report.pdf", is_dir_flag=False, is_file_flag=True, stat_value=_FakeStat(st_size=100, st_ino=1, st_mtime=1704067200.0)),
            _FakeDirEntry("notes.txt", is_dir_flag=False, is_file_flag=True, stat_value=_FakeStat(st_size=100, st_ino=2, st_mtime=1704067200.0)),
            _FakeDirEntry("data.tmp", is_dir_flag=False, is_file_flag=True, stat_value=_FakeStat(st_size=100, st_ino=3, st_mtime=1704067200.0)),
        ],
    )

    page = await connector.list_items(
        {
            "rootPath": r"\\server\share",
            "allowedExtensions": [".pdf", "txt"],
            "excludePatterns": ["**/*.tmp"],
        },
        {"username": "u", "password": "p"},
        page_size=50,
    )

    names = {item.name for item in page.items}
    assert names == {"report.pdf", "notes.txt"}
    assert "data.tmp" not in names


async def test_list_items_rejects_path_escape_attempt(
    connector: UNCRepositoryConnector,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bad_entry = _FakeDirEntry("..\\..\\etc", is_dir_flag=False, is_file_flag=True, stat_value=_FakeStat(st_size=100, st_ino=99, st_mtime=1704067200.0))
    monkeypatch.setattr(smbclient, "scandir", lambda path: [bad_entry])

    page = await connector.list_items(
        {"rootPath": r"\\server\share"},
        {"username": "u", "password": "p"},
        page_size=50,
    )
    assert page.items == []


async def test_read_item_returns_bytes(
    connector: UNCRepositoryConnector,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smbclient,
        "open_file",
        lambda path, **kwargs: _FakeFile(b"hello repository"),
    )

    data = await connector.read_item(
        {"rootPath": r"\\server\share"},
        {"username": "u", "password": "p"},
        "report.pdf",
    )
    assert data == b"hello repository"
