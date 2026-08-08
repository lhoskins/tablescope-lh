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
    assert a.firewall_chain == "TS-TENANT-ACME"

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
        chain="TS-TENANT-ACME",
        allowed_onprem_cidrs=["10.10.0.0/16"],
    )
    globex = TenantFirewallSpec(
        tenant_id="globex",
        docker_subnet_cidr="172.30.20.0/24",
        chain="TS-TENANT-GLOBEX",
        allowed_onprem_cidrs=["10.20.0.0/16"],
    )
    svc = TenantFirewallService()
    script = svc.render_script([acme, globex])

    # Jump is hooked into DOCKER-USER (before Docker's own ACCEPT rules), not
    # appended to FORWARD where it would be preempted.
    assert "iptables -I DOCKER-USER -s 172.30.10.0/24 -j TS-TENANT-ACME" in script
    assert "-A FORWARD -s 172.30.10.0/24 -j TS-TENANT-ACME" not in script
    # Acme can reach its own on-prem.
    assert "iptables -A TS-TENANT-ACME -d 10.10.0.0/16 -j ACCEPT" in script
    # Acme blocked from Globex's Docker subnet and on-prem.
    assert "iptables -A TS-TENANT-ACME -d 172.30.20.0/24 -j DROP" in script
    assert "iptables -A TS-TENANT-ACME -d 10.20.0.0/16 -j DROP" in script
    # Metadata endpoint blocked.
    assert "iptables -A TS-TENANT-ACME -d 169.254.169.254/32 -j DROP" in script
    # Default deny at end of chain.
    assert "iptables -A TS-TENANT-ACME -j DROP" in script
    # Applied-marker so the containerized control plane can confirm application.
    assert "/etc/tablescope/tenant-firewall.d/acme.applied" in script
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
    # Defaults to the no-VPN (container-only) tier.
    assert plane["vpn_mode"] == "none"

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
    assert "TS-TENANT-ACME -d 172.30.20.0/24 -j DROP" in script


async def test_vpn_mode_selection(client, service_headers) -> None:
    # Customer-VPN tier is accepted and persisted.
    resp = await client.post(
        "/api/tenant-data-planes",
        json={
            "tenant_id": "acme",
            "tenant_name": "Acme",
            "vpn_mode": "customer_vpn",
            "allowed_onprem_cidrs": ["10.10.0.0/16"],
        },
        headers=service_headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["vpn_mode"] == "customer_vpn"

    # Invalid mode rejected.
    bad = await client.post(
        "/api/tenant-data-planes",
        json={"tenant_id": "globex", "tenant_name": "G", "vpn_mode": "wat", "allowed_onprem_cidrs": []},
        headers=service_headers,
    )
    assert bad.status_code == 422

    # No-VPN tenant reports vpn_status not_applicable in health.
    await client.post(
        "/api/tenant-data-planes",
        json={"tenant_id": "novpn", "tenant_name": "No VPN", "vpn_mode": "none", "allowed_onprem_cidrs": []},
        headers=service_headers,
    )
    health = await client.post(
        "/api/tenant-data-planes/novpn/health", json={}, headers=service_headers
    )
    assert health.status_code == 200
    assert health.json()["vpn_status"] == "not_applicable"


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
        json={
            "tenant_id": "acme",
            "tenant_name": "Acme",
            "vpn_mode": "customer_vpn",
            "allowed_onprem_cidrs": [],
        },
        headers=service_headers,
    )
    resp = await client.post("/api/tenant-data-planes/acme/health", json={}, headers=service_headers)
    assert resp.status_code == 200, resp.text
    report = resp.json()
    for key in ("vpn_status", "teiid_status", "firewall_status", "vdb_path_status"):
        assert key in report
    # Customer-VPN tier but no VPN metadata attached yet.
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


async def test_resolve_for_org_binds_app_tenant_to_data_plane(db_session) -> None:
    from app.models.tenant import Tenant
    from app.models.tenant_data_plane import TenantDataPlane
    from app.services.tenant_teiid_resolver import TenantTeiidResolver

    tenant = Tenant(slug="acme", name="Acme")
    db_session.add(tenant)
    await db_session.flush()

    db_session.add(
        TenantDataPlane(
            tenant_id="acme",
            tenant_name="Acme",
            org_tenant_id=tenant.id,
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

    resolver = TenantTeiidResolver(db_session)
    # Bound app tenant -> dedicated container endpoint.
    ep = await resolver.resolve_for_org(tenant.id)
    assert ep.is_dedicated is True
    assert ep.servlet_url == "http://172.30.10.10:8080"

    # Unbound / unknown org tenant -> shared global fallback.
    fallback = await resolver.resolve_for_org(999999)
    assert fallback.is_dedicated is False
    none_ep = await resolver.resolve_for_org(None)
    assert none_ep.is_dedicated is False


async def test_create_app_tenant_requires_admin_credentials(client, service_headers) -> None:
    resp = await client.post(
        "/api/tenant-data-planes",
        headers=service_headers,
        json={
            "tenant_id": "needsadmin",
            "tenant_name": "Needs Admin",
            "vpn_mode": "none",
            "create_app_tenant": True,
        },
    )
    assert resp.status_code == 422
    assert "admin" in resp.json()["detail"].lower()


async def test_bind_app_tenant_to_existing_data_plane(client, service_headers) -> None:
    # Provision a data plane with no app tenant bound.
    resp = await client.post(
        "/api/tenant-data-planes",
        json={"tenant_id": "acme", "tenant_name": "Acme Co", "allowed_onprem_cidrs": []},
        headers=service_headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["org_tenant_id"] is None

    # Validation: must supply either an existing id or a new slug.
    bad = await client.post(
        "/api/tenant-data-planes/acme/bind-app-tenant",
        json={},
        headers=service_headers,
    )
    assert bad.status_code == 422

    # Bind by creating a new app tenant + root admin.
    bound = await client.post(
        "/api/tenant-data-planes/acme/bind-app-tenant",
        json={
            "new_tenant_slug": "acme",
            "new_tenant_name": "Acme Co",
            "admin_email": "admin@acme.com",
            "admin_password": "s3cret-pw",
        },
        headers=service_headers,
    )
    assert bound.status_code == 200, bound.text
    org_id = bound.json()["org_tenant_id"]
    assert org_id is not None

    # The data plane now reports the binding (resolver routing of a bound
    # org tenant to its dedicated container is covered separately).
    got = await client.get("/api/tenant-data-planes/acme", headers=service_headers)
    assert got.json()["org_tenant_id"] == org_id

    # Re-binding via a duplicate slug is rejected.
    dup = await client.post(
        "/api/tenant-data-planes/acme/bind-app-tenant",
        json={
            "new_tenant_slug": "acme",
            "admin_email": "x@acme.com",
            "admin_password": "pw123456",
        },
        headers=service_headers,
    )
    assert dup.status_code == 409


async def test_bind_new_app_tenant_requires_credentials(client, service_headers) -> None:
    resp = await client.post(
        "/api/tenant-data-planes",
        json={"tenant_id": "acme", "tenant_name": "Acme", "allowed_onprem_cidrs": []},
        headers=service_headers,
    )
    assert resp.status_code == 201, resp.text
    bad = await client.post(
        "/api/tenant-data-planes/acme/bind-app-tenant",
        json={"new_tenant_slug": "acme"},
        headers=service_headers,
    )
    assert bad.status_code == 422
    assert "admin" in bad.json()["detail"].lower()


async def test_delete_data_plane_cascades_app_tenant(client, service_headers) -> None:
    # Provision a plane and bind a freshly created app tenant + admin user.
    resp = await client.post(
        "/api/tenant-data-planes",
        json={"tenant_id": "acme", "tenant_name": "Acme Co", "allowed_onprem_cidrs": ["10.10.0.0/16"]},
        headers=service_headers,
    )
    assert resp.status_code == 201, resp.text
    bound = await client.post(
        "/api/tenant-data-planes/acme/bind-app-tenant",
        json={
            "new_tenant_slug": "acme",
            "new_tenant_name": "Acme Co",
            "admin_email": "admin@acme.com",
            "admin_password": "s3cret-pw",
        },
        headers=service_headers,
    )
    assert bound.status_code == 200, bound.text
    org_id = bound.json()["org_tenant_id"]

    # Delete the data plane (default cascades the bound app tenant).
    deleted = await client.delete(
        "/api/tenant-data-planes/acme", headers=service_headers
    )
    assert deleted.status_code == 200, deleted.text
    body = deleted.json()
    assert body["org_tenant_id"] == org_id
    assert body["app_tenant_deleted"] is True
    assert body["deleted_rows"]["users"] >= 1
    assert body["deleted_rows"]["tenants"] == 1
    # Teardown script targets this tenant's isolated container + network + dir.
    assert "tenant-acme-teiid" in body["teardown_script"]
    assert "tenant_acme_net" in body["teardown_script"]
    assert "/opt/tablescope/tenants/acme" in body["teardown_script"]

    # Plane is gone, and so is the app tenant (login impossible).
    gone = await client.get("/api/tenant-data-planes/acme", headers=service_headers)
    assert gone.status_code == 404


async def test_delete_data_plane_can_keep_app_tenant(client, service_headers) -> None:
    resp = await client.post(
        "/api/tenant-data-planes",
        json={"tenant_id": "acme", "tenant_name": "Acme Co", "allowed_onprem_cidrs": []},
        headers=service_headers,
    )
    assert resp.status_code == 201, resp.text
    bound = await client.post(
        "/api/tenant-data-planes/acme/bind-app-tenant",
        json={
            "new_tenant_slug": "acme",
            "admin_email": "admin@acme.com",
            "admin_password": "s3cret-pw",
        },
        headers=service_headers,
    )
    assert bound.status_code == 200, bound.text

    deleted = await client.delete(
        "/api/tenant-data-planes/acme?delete_app_tenant=false",
        headers=service_headers,
    )
    assert deleted.status_code == 200, deleted.text
    body = deleted.json()
    assert body["app_tenant_deleted"] is False
    assert body["deleted_rows"] == {}


async def test_delete_missing_data_plane_404(client, service_headers) -> None:
    resp = await client.delete(
        "/api/tenant-data-planes/nope", headers=service_headers
    )
    assert resp.status_code == 404


async def test_requires_auth(client) -> None:
    resp = await client.get("/api/tenant-data-planes")
    assert resp.status_code == 401
