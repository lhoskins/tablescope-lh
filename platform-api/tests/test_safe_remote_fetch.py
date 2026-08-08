"""SSRF and content controls for the shared hardened URL fetcher.

These cover the class of attack the fetcher exists to stop: pointing a
server-side download at the cluster's own network. Every case asserts the
refusal *code*, since callers map codes onto HTTP statuses and user-safe text.
"""

from __future__ import annotations

import httpx
import pytest

from app.config import get_settings
from app.services import safe_remote_fetch as srf
from app.services.safe_remote_fetch import RemoteFetchError


def _resolver(*addresses: str):
    return lambda host, port: list(addresses)


@pytest.fixture(autouse=True)
def _clear_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ── Scheme and locator handling ──────────────────────────────────────────


def test_http_is_refused_by_default():
    with pytest.raises(RemoteFetchError) as exc:
        srf.validate_url("http://example.com/a.csv", resolver=_resolver("93.184.216.34"))
    assert exc.value.code == "INSECURE_SCHEME"


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "gopher://example.com/a",
        "ftp://example.com/a.csv",
    ],
)
def test_non_http_schemes_are_refused(url):
    with pytest.raises(RemoteFetchError) as exc:
        srf.validate_url(url, resolver=_resolver("93.184.216.34"))
    assert exc.value.code == "INVALID_SCHEME"


def test_url_userinfo_is_refused():
    with pytest.raises(RemoteFetchError) as exc:
        srf.validate_url(
            "https://user:secret@example.com/a.csv",
            resolver=_resolver("93.184.216.34"),
        )
    assert exc.value.code == "URL_USERINFO"


def test_redaction_drops_query_fragment_and_credentials():
    redacted = srf.redact_url(
        "https://user:pw@files.example.com/reports/q3.csv?sig=abc123#part"
    )
    assert redacted == "https://files.example.com/reports/q3.csv"
    assert "sig" not in redacted
    assert "pw" not in redacted


# ── Address-space controls ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.1.2.3",
        "172.16.5.5",
        "192.168.1.10",
        "169.254.169.254",  # cloud metadata
        "100.64.0.1",  # CGNAT
        "0.0.0.0",
        "::1",
        "fd00::1",
        "fe80::1",
    ],
)
def test_internal_addresses_are_refused(address):
    with pytest.raises(RemoteFetchError) as exc:
        srf.resolve_public_addresses("evil.example.com", 443, resolver=_resolver(address))
    assert exc.value.code == "BLOCKED_ADDRESS"


@pytest.mark.parametrize("host", ["localhost", "teiid", "metadata.google.internal"])
def test_internal_hostnames_are_refused(host):
    with pytest.raises(RemoteFetchError) as exc:
        srf.resolve_public_addresses(host, 443, resolver=_resolver("93.184.216.34"))
    assert exc.value.code == "BLOCKED_HOST"


def test_ip_literal_to_metadata_service_is_refused():
    with pytest.raises(RemoteFetchError) as exc:
        srf.validate_url("https://169.254.169.254/latest/meta-data/")
    assert exc.value.code == "BLOCKED_ADDRESS"


def test_split_horizon_answer_is_refused_entirely():
    """One public and one private answer is a rebinding attempt, not multi-homing."""
    with pytest.raises(RemoteFetchError) as exc:
        srf.resolve_public_addresses(
            "rebind.example.com", 443, resolver=_resolver("93.184.216.34", "127.0.0.1")
        )
    assert exc.value.code == "BLOCKED_ADDRESS"


def test_domain_allowlist_blocks_other_hosts(monkeypatch):
    monkeypatch.setenv("FILE_IMPORT_ALLOWED_URL_DOMAINS", "files.example.com")
    get_settings.cache_clear()
    assert srf.resolve_public_addresses(
        "files.example.com", 443, resolver=_resolver("93.184.216.34")
    ) == ["93.184.216.34"]
    with pytest.raises(RemoteFetchError) as exc:
        srf.resolve_public_addresses(
            "other.example.org", 443, resolver=_resolver("93.184.216.34")
        )
    assert exc.value.code == "DOMAIN_NOT_ALLOWED"


# ── Redirects, size, and content metadata ────────────────────────────────


def _transport(handler):
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_redirect_to_internal_address_is_refused():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start.csv":
            return httpx.Response(
                302, headers={"location": "https://169.254.169.254/latest/meta-data/"}
            )
        return httpx.Response(200, content=b"should never be reached")

    with pytest.raises(RemoteFetchError) as exc:
        await srf.fetch_remote_file(
            "https://files.example.com/start.csv",
            resolver=_resolver("93.184.216.34"),
            transport=_transport(handler),
        )
    assert exc.value.code == "BLOCKED_ADDRESS"


@pytest.mark.asyncio
async def test_redirect_chain_is_capped():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302, headers={"location": "https://files.example.com/next.csv"}
        )

    with pytest.raises(RemoteFetchError) as exc:
        await srf.fetch_remote_file(
            "https://files.example.com/a.csv",
            resolver=_resolver("93.184.216.34"),
            transport=_transport(handler),
        )
    assert exc.value.code == "TOO_MANY_REDIRECTS"


@pytest.mark.asyncio
async def test_declared_content_length_over_limit_is_refused_before_download():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-length": "999999"}, content=b"x" * 10
        )

    with pytest.raises(RemoteFetchError) as exc:
        await srf.fetch_remote_file(
            "https://files.example.com/big.csv",
            max_bytes=1024,
            resolver=_resolver("93.184.216.34"),
            transport=_transport(handler),
        )
    assert exc.value.code == "FILE_TOO_LARGE"


@pytest.mark.asyncio
async def test_streaming_body_over_limit_is_refused():
    """A lying (or absent) Content-Length must not defeat the cap."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 5000)

    with pytest.raises(RemoteFetchError) as exc:
        await srf.fetch_remote_file(
            "https://files.example.com/big.csv",
            max_bytes=1024,
            resolver=_resolver("93.184.216.34"),
            transport=_transport(handler),
        )
    assert exc.value.code == "FILE_TOO_LARGE"


@pytest.mark.asyncio
async def test_http_error_status_is_reported_safely():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    with pytest.raises(RemoteFetchError) as exc:
        await srf.fetch_remote_file(
            "https://files.example.com/missing.csv",
            resolver=_resolver("93.184.216.34"),
            transport=_transport(handler),
        )
    assert exc.value.code == "HTTP_ERROR"


@pytest.mark.asyncio
async def test_successful_fetch_returns_bytes_and_safe_metadata():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"a,b\n1,2\n",
            headers={
                "content-type": "text/csv; charset=utf-8",
                "etag": '"v1"',
                "last-modified": "Wed, 01 Jan 2025 00:00:00 GMT",
            },
        )

    data, metadata = await srf.fetch_remote_file(
        "https://files.example.com/reports/sales.csv?token=secret",
        resolver=_resolver("93.184.216.34"),
        transport=_transport(handler),
    )
    assert data == b"a,b\n1,2\n"
    assert metadata.filename == "sales.csv"
    assert metadata.content_type == "text/csv"
    assert metadata.url_host == "files.example.com"
    assert "secret" not in metadata.locator_redacted
    assert metadata.etag == '"v1"'


def test_content_disposition_path_is_stripped():
    headers = httpx.Headers(
        {"content-disposition": 'attachment; filename="../../etc/passwd"'}
    )
    assert (
        srf.filename_from_response("https://files.example.com/x", headers) == "passwd"
    )
