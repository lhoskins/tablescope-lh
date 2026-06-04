"""Tests for the multi-tenant data-plane control plane."""

from __future__ import annotations

import pytest

from app.services.tenant_compose_service import TenantComposeService
from app.services.tenant_firewall_service import (
    TenantFirewallService,
    TenantFirewallSpec,
)
from app.services.tenant_layout import (
    InvalidTenantId,
    compute_layout,
    validate_tenant_id,
)

# --- Layout -----------------------------------------------------------------


def test_layout_matches_plan_worked_example() -> None:
    a = compute_layout("acme", 1)
    assert a.docker_subnet_cidr == "172.30.10.0/24"
    assert a.teiid_container_ip == "172.30.10.10"
    assert a.host_servlet_port == 18095
    assert a.host_pg_port == 15442
    assert a.host_mgmt_port == 19990
    assert a.teiid_servlet_url == "http://127.0.0.1:18095"
    assert a.firewall_chain == "TABLESCOPE-TENANT-ACME"

    b = compute_layout("globex", 2)
    assert b.docker_subnet_cidr == "172.30.20.0/24"
    assert b.host_servlet_port == 28095
    assert b.host_pg_port == 25442
    assert b.host_mgmt_port == 29990


def test_validate_tenant_id_rejects_unsafe() -> None:
    assert validate_tenant_id("Acme") == "acme"
    for bad in ["", "-acme", "acme-", "ac me", "a/b", "a" * 60, "../x"]:
        with pytest.raises(InvalidTenantId):
            validate_tenant_id(bad)


# --- Compose isolation ------------------------------------------------------


def test_compose_enforces_isolation_rules() -> None:
    layout = compute_layout("acme", 1)
    content = TenantComposeService(teiid_image="tablescope-teiid:latest").render(layout)

    # Fixed network + subnet + IP for this tenant only.
    assert "tenant_acme_net" in content
    assert "subnet: 172.30.10.0/24" in content
    assert "ipv4_address: 172.30.10.10" in content
    # Localhost-bound ports only.
    assert "127.0.0.1:18095:8080" in content
    assert "127.0.0.1:15442:35432" in content
    # Tenant-specific VDB dir, not shared.
    assert "/opt/tablescope/tenants/acme/vdb:/opt/wildfly/teiidfiles/customers" in content
    # Per-tenant API key via env reference (never a literal secret).
    assert "${TENANT_ACME_TEIID_API_KEY}" in content
    # The Docker socket is never mounted; no privileged escalation.
    assert "/var/run/docker.sock" not in content
    assert "privileged: true" not in content
    assert "no-new-privileges:true" in content


# --- Firewall cross-tenant deny --------------------------------------------


def test_firewall_blocks_cross_tenant_and_allows_own_onprem() -> None:
    acme = TenantFirewallSpec(
        tenant_id="acme",
        docker_subnet_cidr="172.30.10.0/24",
        chain="TABLESCOPE-TENANT-ACME",
        allowed_onprem_cidrs=["10.10.0.0/16"],
    )
    globex = TenantFirewallSpec(
        tenant_id="globex",
        docker_subnet_cidr="172.30.20.0/24",
        chain="TABLESCOPE-TENANT-GLOBEX",
        allowed_onprem_cidrs=["10.20.0.0/16"],
    )
    svc = TenantFirewallService()
    script = svc.render_script([acme, globex])

    # Jump is hooked into DOCKER-USER (before Docker's own ACCEPT rules), not
    # appended to FORWARD where it would be preempted.
    assert "iptables -I DOCKER-USER -s 172.30.10.0/24 -j TABLESCOPE-TENANT-ACME" in script
    assert "-A FORWARD -s 172.30.10.0/24 -j TABLESCOPE-TENANT-ACME" not in script
    # Acme can reach its own on-prem.
    assert "iptables -A TABLESCOPE-TENANT-ACME -d 10.10.0.0/16 -j ACCEPT" in script
    # Acme blocked from Globex's Docker subnet and on-prem.
    assert "iptables -A TABLESCOPE-TENANT-ACME -d 172.30.20.0/24 -j DROP" in script
    assert "iptables -A TABLESCOPE-TENANT-ACME -d 10.20.0.0/16 -j DROP" in script
    # Metadata endpoint blocked.
    assert "iptables -A TABLESCOPE-TENANT-ACME -d 169.254.169.254/32 -j DROP" in script
    # Default deny at end of chain.
    assert "iptables -A TABLESCOPE-TENANT-ACME -j DROP" in script
    # systemd unit references the apply script.
    unit = svc.render_systemd_unit()
    assert "tablescope-apply-tenant-firewall.sh" in unit


# --- API --------------------------------------------------------------------


async def test_create_list_get_and_artifacts(client, service_headers) -> None:
    resp = await client.post(
        "/api/tenant-data-planes",
        json={
            "tenant_id": "acme",
            "tenant_name": "Acme Co",
            "allowed_onprem_cidrs": ["10.10.0.0/16"],
        },
        headers=service_headers,
    )
    assert resp.status_code == 201, resp.text
    plane = resp.json()
    assert plane["tenant_id"] == "acme"
    assert plane["docker_subnet_cidr"] == "172.30.10.0/24"
    assert plane["teiid_pg_port"] == 15442
    assert plane["status"] == "provisioning"

    # Second tenant gets the next deterministic index/subnet.
    resp = await client.post(
        "/api/tenant-data-planes",
        json={
            "tenant_id": "globex",
            "tenant_name": "Globex",
            "allowed_onprem_cidrs": ["10.20.0.0/16"],
        },
        headers=service_headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["docker_subnet_cidr"] == "172.30.20.0/24"

    # Duplicate rejected.
    dup = await client.post(
        "/api/tenant-data-planes",
        json={"tenant_id": "acme", "tenant_name": "x", "allowed_onprem_cidrs": []},
        headers=service_headers,
    )
    assert dup.status_code == 409

    # Invalid tenant id rejected.
    bad = await client.post(
        "/api/tenant-data-planes",
        json={"tenant_id": "Bad Name", "tenant_name": "x", "allowed_onprem_cidrs": []},
        headers=service_headers,
    )
    assert bad.status_code == 422

    # List shows both.
    listing = await client.get("/api/tenant-data-planes", headers=service_headers)
    assert listing.status_code == 200
    assert {t["tenant_id"] for t in listing.json()} == {"acme", "globex"}

    # Compose preview.
    compose = await client.get("/api/tenant-data-planes/acme/compose", headers=service_headers)
    assert compose.status_code == 200
    assert "tenant_acme_net" in compose.json()["compose_content"]

    # Firewall script across tenants enforces cross-tenant deny.
    fw = await client.get("/api/tenant-data-planes/firewall-script", headers=service_headers)
    assert fw.status_code == 200
    script = fw.json()["script"]
    assert "TABLESCOPE-TENANT-ACME -d 172.30.20.0/24 -j DROP" in script


async def test_vpn_metadata_and_onboarding(client, service_headers) -> None:
    await client.post(
        "/api/tenant-data-planes",
        json={"tenant_id": "acme", "tenant_name": "Acme", "allowed_onprem_cidrs": ["10.10.0.0/16"]},
        headers=service_headers,
    )
    meta = await client.post(
        "/api/tenant-data-planes/acme/vpn-metadata",
        json={
            "tenant_vpc_id": "vpc-abc",
            "vpn_connection_id": "vpn-123",
            "vpn_tunnel1_address": "203.0.113.1",
            "vpn_tunnel2_address": "203.0.113.2",
            "customer_gateway_id": "cgw-9",
        },
        headers=service_headers,
    )
    assert meta.status_code == 200, meta.text
    assert meta.json()["tenant_vpc_id"] == "vpc-abc"

    pkg = await client.get(
        "/api/tenant-data-planes/acme/onboarding-package", headers=service_headers
    )
    assert pkg.status_code == 200
    body = pkg.json()
    assert body["aws_tunnel_outside_ips"] == ["203.0.113.1", "203.0.113.2"]
    assert body["allowed_onprem_cidrs"] == ["10.10.0.0/16"]


async def test_health_endpoint_reports_dimensions(client, service_headers) -> None:
    await client.post(
        "/api/tenant-data-planes",
        json={"tenant_id": "acme", "tenant_name": "Acme", "allowed_onprem_cidrs": []},
        headers=service_headers,
    )
    resp = await client.post("/api/tenant-data-planes/acme/health", json={}, headers=service_headers)
    assert resp.status_code == 200, resp.text
    report = resp.json()
    for key in ("vpn_status", "teiid_status", "firewall_status", "vdb_path_status"):
        assert key in report
    # No VPN configured yet.
    assert report["vpn_status"] == "not_configured"


async def test_resolver_uses_incluster_address(db_session) -> None:
    from app.models.tenant_data_plane import TenantDataPlane
    from app.services.tenant_teiid_resolver import TenantTeiidResolver

    db_session.add(
        TenantDataPlane(
            tenant_id="acme",
            tenant_name="Acme",
            docker_network_name="tenant_acme_net",
            docker_subnet_cidr="172.30.10.0/24",
            teiid_container_name="tenant-acme-teiid",
            teiid_container_ip="172.30.10.10",
            teiid_servlet_url="http://127.0.0.1:18095",
            teiid_pg_host="127.0.0.1",
            teiid_pg_port=15442,
            teiid_mgmt_port=19990,
            vdb_host_path="/opt/tablescope/tenants/acme/vdb",
            allowed_onprem_cidrs=[],
            blocked_cidrs=[],
        )
    )
    await db_session.commit()

    ep = await TenantTeiidResolver(db_session).resolve("acme")
    # In-cluster default: reach the tenant container over the tenant network,
    # not the host's 127.0.0.1-bound ports.
    assert ep.is_dedicated is True
    assert ep.servlet_url == "http://172.30.10.10:8080"
    assert ep.pg_host == "172.30.10.10"
    assert ep.pg_port == 35432

    # Unknown tenant falls back to the global (dev/single-tenant) endpoint.
    fallback = await TenantTeiidResolver(db_session).resolve("nope")
    assert fallback.is_dedicated is False


async def test_requires_auth(client) -> None:
    resp = await client.get("/api/tenant-data-planes")
    assert resp.status_code == 401
