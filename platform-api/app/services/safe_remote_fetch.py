"""Hardened server-side fetcher for user-supplied URLs.

Every server-side fetch of a URL a *user* controls must go through
:func:`fetch_remote_file` (or :func:`stream_remote_file`).  It is the single
place that enforces the SSRF controls:

* HTTPS only unless an operator explicitly enables plain HTTP;
* URL user-info (``user:password@host``) rejected;
* DNS resolved up front and every resulting address checked against private,
  loopback, link-local, multicast, reserved, documentation, and
  cloud-metadata ranges for both IPv4 and IPv6;
* the connection is pinned to the vetted address, so a second resolution
  cannot rebind the hostname to an internal target between check and connect;
* every redirect hop revalidated the same way, capped at five hops;
* optional host-suffix allowlist;
* early ``Content-Length`` rejection plus a hard byte cap while streaming;
* bounded connect/read/total timeouts, capped concurrency, per-host rate
  limiting, and no automatic retry of permanent failures.

Only redacted locators (scheme, host, path filename) are ever logged or
returned — query strings and fragments can carry signed credentials.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from email.message import Message
from urllib.parse import unquote, urlparse, urlunparse

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

#: Hostnames that must never be fetched even if they resolve publicly. These
#: are the in-cluster service names and the cloud metadata endpoints.
BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "ip6-localhost",
        "metadata",
        "metadata.google.internal",
        "metadata.goog",
        "instance-data",
        "teiid",
        "redis",
        "db",
        "postgres",
        "postgresql",
        "platform-api",
        "platform-api-worker",
        "web-ui",
        "ai-server",
        "ollama",
        "clamav",
        "nginx",
        "r-analytics",
        "wildfly",
    }
)

#: Extra IPv4 ranges beyond the ones ``ipaddress`` already classifies.
_EXTRA_BLOCKED_V4 = (
    ipaddress.ip_network("169.254.0.0/16"),  # link-local + AWS/Azure metadata
    ipaddress.ip_network("100.64.0.0/10"),  # carrier-grade NAT
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("198.18.0.0/15"),  # benchmarking
    ipaddress.ip_network("192.88.99.0/24"),  # 6to4 relay anycast
)
_EXTRA_BLOCKED_V6 = (
    ipaddress.ip_network("fc00::/7"),  # unique local
    ipaddress.ip_network("fe80::/10"),  # link-local
    ipaddress.ip_network("::ffff:0:0/96"),  # IPv4-mapped
    ipaddress.ip_network("64:ff9b::/96"),  # NAT64
    ipaddress.ip_network("2002::/16"),  # 6to4
)

MAX_HOST_CONCURRENCY = 2
HOST_RATE_LIMIT_SECONDS = 0.5


class RemoteFetchError(Exception):
    """A fetch was refused or failed. ``code`` is a safe error category."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(slots=True)
class FetchedMetadata:
    """Safe response metadata for a completed fetch."""

    url_host: str
    locator_redacted: str
    filename: str | None
    content_type: str | None
    content_length: int | None
    etag: str | None
    last_modified: str | None


@dataclass(slots=True)
class _HostThrottle:
    semaphore: asyncio.Semaphore = field(
        default_factory=lambda: asyncio.Semaphore(MAX_HOST_CONCURRENCY)
    )
    last_request: float = 0.0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


_host_throttles: dict[str, _HostThrottle] = {}
_global_semaphore: asyncio.Semaphore | None = None
_global_semaphore_size = 0


def _global_gate() -> asyncio.Semaphore:
    global _global_semaphore, _global_semaphore_size
    limit = max(1, get_settings().file_import_max_concurrent_fetches)
    if _global_semaphore is None or _global_semaphore_size != limit:
        _global_semaphore = asyncio.Semaphore(limit)
        _global_semaphore_size = limit
    return _global_semaphore


@asynccontextmanager
async def _throttle(host: str) -> AsyncIterator[None]:
    throttle = _host_throttles.setdefault(host, _HostThrottle())
    async with _global_gate(), throttle.semaphore:
        async with throttle.lock:
            elapsed = time.monotonic() - throttle.last_request
            if elapsed < HOST_RATE_LIMIT_SECONDS:
                await asyncio.sleep(HOST_RATE_LIMIT_SECONDS - elapsed)
            throttle.last_request = time.monotonic()
        yield


# ── URL validation ───────────────────────────────────────────────────────


def redact_url(url: str) -> str:
    """Return ``scheme://host/path`` — no user-info, query, or fragment."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return "(unparseable url)"
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    return urlunparse((parsed.scheme, host, parsed.path, "", "", ""))


def _is_blocked_address(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        return True
    extra = _EXTRA_BLOCKED_V4 if ip.version == 4 else _EXTRA_BLOCKED_V6
    return any(ip in network for network in extra)


def _host_allowed(host: str) -> bool:
    allowlist = get_settings().file_import_url_domain_allowlist
    if not allowlist:
        return True
    host = host.lower()
    return any(host == d or host.endswith(f".{d}") for d in allowlist)


def resolve_public_addresses(
    host: str,
    port: int,
    *,
    resolver: Callable[[str, int], list[str]] | None = None,
) -> list[str]:
    """Resolve ``host`` and return its addresses, rejecting internal targets.

    Raises :class:`RemoteFetchError` when the host is blocked by name, fails
    to resolve, or resolves to *any* non-public address — an all-or-nothing
    check, since a host that returns one public and one private address is a
    rebinding attempt, not a legitimate multi-homed server.
    """
    lowered = host.lower().rstrip(".")
    if lowered in BLOCKED_HOSTNAMES or lowered.endswith(".localhost"):
        raise RemoteFetchError("BLOCKED_HOST", "That host is not permitted.")
    if not _host_allowed(lowered):
        raise RemoteFetchError(
            "DOMAIN_NOT_ALLOWED",
            "That domain is not on this tenant's approved list.",
        )

    literal = _parse_ip_literal(lowered)
    if literal is not None:
        if _is_blocked_address(literal):
            raise RemoteFetchError(
                "BLOCKED_ADDRESS", "That address range is not permitted."
            )
        return [str(literal)]

    if resolver is not None:
        addresses = resolver(lowered, port)
    else:
        try:
            infos = socket.getaddrinfo(lowered, port, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise RemoteFetchError(
                "DNS_FAILURE", "The host name could not be resolved."
            ) from exc
        addresses = [info[4][0] for info in infos]

    if not addresses:
        raise RemoteFetchError("DNS_FAILURE", "The host name could not be resolved.")

    for address in addresses:
        try:
            parsed_ip = ipaddress.ip_address(address.split("%", 1)[0])
        except ValueError as exc:
            raise RemoteFetchError("DNS_FAILURE", "Unusable DNS result.") from exc
        if _is_blocked_address(parsed_ip):
            raise RemoteFetchError(
                "BLOCKED_ADDRESS", "That address range is not permitted."
            )
    return addresses


def _parse_ip_literal(
    host: str,
) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    candidate = host[1:-1] if host.startswith("[") and host.endswith("]") else host
    try:
        return ipaddress.ip_address(candidate)
    except ValueError:
        return None


def validate_url(
    url: str,
    *,
    resolver: Callable[[str, int], list[str]] | None = None,
) -> tuple[str, int, list[str]]:
    """Validate one URL (no redirect following). Returns (host, port, addrs)."""
    settings = get_settings()
    try:
        parsed = urlparse(url)
    except ValueError as exc:
        raise RemoteFetchError("INVALID_URL", "That URL could not be parsed.") from exc

    if parsed.scheme not in ("http", "https"):
        raise RemoteFetchError("INVALID_SCHEME", "Only https:// URLs are supported.")
    if parsed.scheme == "http" and not settings.file_import_allow_http:
        raise RemoteFetchError(
            "INSECURE_SCHEME",
            "Plain http:// is disabled. Use an https:// URL.",
        )
    if parsed.username or parsed.password or "@" in (parsed.netloc.split("]")[-1]):
        raise RemoteFetchError(
            "URL_USERINFO", "URLs with embedded credentials are not accepted."
        )
    host = parsed.hostname
    if not host:
        raise RemoteFetchError("INVALID_URL", "That URL has no host.")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise RemoteFetchError("INVALID_URL", "That URL has an invalid port.") from exc

    addresses = resolve_public_addresses(host, port, resolver=resolver)
    return host, port, addresses


def filename_from_response(url: str, headers: httpx.Headers) -> str | None:
    """Derive a filename from Content-Disposition, else from the URL path."""
    disposition = headers.get("content-disposition")
    if disposition:
        message = Message()
        message["content-disposition"] = disposition
        candidate = message.get_filename()
        if candidate:
            # Strip any directory component a hostile server may have sent.
            return unquote(candidate).replace("\\", "/").rsplit("/", 1)[-1]
    path = urlparse(url).path
    if path and not path.endswith("/"):
        return unquote(path.rsplit("/", 1)[-1]) or None
    return None


# ── Fetching ─────────────────────────────────────────────────────────────


def _build_transport(
    pinned: dict[str, str],
) -> httpx.AsyncHTTPTransport:
    """Transport that connects only to addresses already vetted for a host."""

    class _PinnedTransport(httpx.AsyncHTTPTransport):
        async def handle_async_request(
            self, request: httpx.Request
        ) -> httpx.Response:
            host = request.url.host
            address = pinned.get(host)
            if address is None:
                raise RemoteFetchError(
                    "BLOCKED_HOST", "Connection to an unvetted host was refused."
                )
            # Re-point the socket at the vetted address while keeping the
            # original Host header and TLS SNI, so a second DNS lookup cannot
            # swap in an internal target after validation.
            request.extensions = {
                **request.extensions,
                "sni_hostname": host,
            }
            pinned_url = request.url.copy_with(host=address)
            request.url = pinned_url
            request.headers["Host"] = host
            return await super().handle_async_request(request)

    return _PinnedTransport(retries=0)


@asynccontextmanager
async def stream_remote_file(
    url: str,
    *,
    max_bytes: int | None = None,
    resolver: Callable[[str, int], list[str]] | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> AsyncIterator[tuple[httpx.Response, FetchedMetadata]]:
    """Open a validated, redirect-checked streaming GET.

    Redirects are followed manually so each hop is revalidated. The caller
    consumes ``response.aiter_bytes()`` and must still enforce the byte cap
    (:func:`fetch_remote_file` does this).
    """
    settings = get_settings()
    limit = max_bytes or settings.file_import_max_bytes
    host, port, addresses = validate_url(url, resolver=resolver)

    pinned = {host: addresses[0]}
    client_transport = transport or _build_transport(pinned)
    timeout = httpx.Timeout(
        settings.file_import_read_timeout_seconds,
        connect=settings.file_import_connect_timeout_seconds,
        pool=settings.file_import_connect_timeout_seconds,
    )

    async with _throttle(host):
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,
            transport=client_transport,
            headers={"User-Agent": BROWSER_UA, "Accept": "*/*"},
        ) as client:
            current = url
            for _ in range(settings.file_import_max_redirects + 1):
                request = client.build_request("GET", current)
                try:
                    response = await client.send(request, stream=True)
                except RemoteFetchError:
                    raise
                except httpx.TimeoutException as exc:
                    raise RemoteFetchError(
                        "TIMEOUT", "The source did not respond in time."
                    ) from exc
                except httpx.HTTPError as exc:
                    logger.info(
                        "remote fetch transport error for %s: %s",
                        redact_url(current),
                        type(exc).__name__,
                    )
                    raise RemoteFetchError(
                        "HOST_UNREACHABLE", "The source could not be reached."
                    ) from exc

                if response.is_redirect:
                    location = response.headers.get("location", "")
                    await response.aclose()
                    if not location:
                        raise RemoteFetchError(
                            "BAD_REDIRECT", "The source sent an invalid redirect."
                        )
                    current = str(httpx.URL(current).join(location))
                    next_host, next_port, next_addresses = validate_url(
                        current, resolver=resolver
                    )
                    pinned[next_host] = next_addresses[0]
                    continue

                if response.status_code >= 400:
                    status = response.status_code
                    await response.aclose()
                    raise RemoteFetchError(
                        "HTTP_ERROR", f"The source returned HTTP {status}."
                    )

                declared = response.headers.get("content-length")
                if declared and declared.isdigit() and int(declared) > limit:
                    await response.aclose()
                    raise RemoteFetchError(
                        "FILE_TOO_LARGE",
                        f"That file exceeds the {limit // (1024 * 1024)}MB limit.",
                    )

                metadata = FetchedMetadata(
                    url_host=httpx.URL(current).host,
                    locator_redacted=redact_url(current),
                    filename=filename_from_response(current, response.headers),
                    content_type=(
                        response.headers.get("content-type", "")
                        .split(";")[0]
                        .strip()
                        .lower()
                        or None
                    ),
                    content_length=int(declared) if declared and declared.isdigit()
                    else None,
                    etag=response.headers.get("etag"),
                    last_modified=response.headers.get("last-modified"),
                )
                try:
                    yield response, metadata
                finally:
                    await response.aclose()
                return

            raise RemoteFetchError(
                "TOO_MANY_REDIRECTS", "The source redirected too many times."
            )


async def fetch_remote_file(
    url: str,
    *,
    max_bytes: int | None = None,
    resolver: Callable[[str, int], list[str]] | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    sink: Callable[[bytes], None] | None = None,
) -> tuple[bytes, FetchedMetadata]:
    """Fetch a URL into memory (or into ``sink``) with the byte cap enforced.

    When ``sink`` is provided the chunks are handed to it and the returned
    bytes object is empty, so large files never have to be buffered.
    """
    settings = get_settings()
    limit = max_bytes or settings.file_import_max_bytes
    chunks: list[bytes] = []
    total = 0
    try:
        # A source that trickles bytes forever never trips the per-read
        # timeout, so the whole transfer is bounded as well.
        async with asyncio.timeout(settings.file_import_total_timeout_seconds):
            async with stream_remote_file(
                url, max_bytes=limit, resolver=resolver, transport=transport
            ) as (response, metadata):
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > limit:
                        raise RemoteFetchError(
                            "FILE_TOO_LARGE",
                            f"That file exceeds the {limit // (1024 * 1024)}MB limit.",
                        )
                    if sink is not None:
                        sink(chunk)
                    else:
                        chunks.append(chunk)
    except (TimeoutError, httpx.TimeoutException) as exc:
        raise RemoteFetchError(
            "TIMEOUT", "The download did not complete in time."
        ) from exc
    metadata.content_length = total
    return b"".join(chunks), metadata
