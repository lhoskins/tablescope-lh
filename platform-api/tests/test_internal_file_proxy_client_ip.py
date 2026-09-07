"""TS-ISO-010: X-Forwarded-For must never be trusted for this route.

``/internal/file-proxy`` authorizes callers purely by source IP (tenant
Docker subnet / operator CIDR allowlist / Teiid's Docker network). It is not
proxied through nginx (not under ``/api``) and has no legitimate reverse
proxy in front of it, so the old ``_client_ip`` -- which read
``X-Forwarded-For`` first and fell back to the TCP peer -- let any caller
who could reach the port directly spoof a trusted tenant CIDR and bypass
the check entirely. These tests lock in the fix: only the real TCP peer
address is ever used.
"""

from __future__ import annotations

from starlette.requests import Request

from app.routes.internal_file_proxy import _client_ip, _source_allowed


def _request(*, client_host: str | None, headers: dict[str, str] | None = None) -> Request:
    scope = {
        "type": "http",
        "headers": [
            (k.lower().encode(), v.encode()) for k, v in (headers or {}).items()
        ],
        "client": (client_host, 12345) if client_host is not None else None,
    }
    return Request(scope)


def test_client_ip_ignores_spoofed_x_forwarded_for():
    request = _request(
        client_host="203.0.113.50",
        headers={"x-forwarded-for": "10.0.0.5"},
    )

    assert _client_ip(request) == "203.0.113.50"


def test_client_ip_returns_none_when_no_client_present():
    request = _request(client_host=None)

    assert _client_ip(request) is None


def test_source_allowed_rejects_spoofed_header_previously_trusted_cidr():
    """The exact live bypass this fix closes: an attacker outside the
    tenant's Docker subnet used to be able to set X-Forwarded-For to an IP
    inside it and pass ``_source_allowed``. Now the real (untrusted) peer
    address is what's checked, so the request is rejected."""
    tenant_cidr = "10.50.0.0/24"
    attacker_request = _request(
        client_host="198.51.100.7",
        headers={"x-forwarded-for": "10.50.0.5"},
    )

    client_ip = _client_ip(attacker_request)

    assert client_ip == "198.51.100.7"
    assert _source_allowed(client_ip, tenant_cidr, []) is False


def test_source_allowed_still_accepts_real_peer_inside_tenant_cidr():
    tenant_cidr = "10.50.0.0/24"
    legitimate_request = _request(client_host="10.50.0.5")

    client_ip = _client_ip(legitimate_request)

    assert _source_allowed(client_ip, tenant_cidr, []) is True
