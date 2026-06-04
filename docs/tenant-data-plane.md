# Tenant VPN / Data-Plane Architecture

Cost-conscious enterprise isolation tier: **one shared EC2 host** runs the
control plane and every tenant's Teiid container, while each tenant gets its
own VPC, Site-to-Site VPN, Docker network/subnet, VDB directory, secrets, and
host-firewall egress policy. Stronger than Docker-only separation, much cheaper
than one EC2 per tenant.

```
 customer on-prem ── IPsec VPN ── tenant VPC ─┐
                                              ├─ Transit Gateway ─ shared services VPC ─ EC2 host
 customer on-prem ── IPsec VPN ── tenant VPC ─┘                                          ├─ control plane (web/api/worker/pg/redis)
                                                                                         ├─ tenant-acme-teiid  (172.30.10.0/24, ports 18095/15442/19990 @127.0.0.1)
                                                                                         └─ tenant-globex-teiid(172.30.20.0/24, ports 28095/25442/29990 @127.0.0.1)
```

## Key decisions (isolation vs. cost)

- **Transit Gateway, not VPC peering.** Traffic from a customer's on-prem network
  enters AWS through the tenant VPN and must reach the shared services VPC where
  the EC2 host lives. VPC peering does not support that transitive (edge-to-edge)
  routing through a VPN attachment; a TGW does. One shared TGW serves all tenants.
- **Static VPN routes, not BGP.** Simpler and no extra cost; BGP is available per
  tenant via `customer_bgp_asn` / `vpn_routing_type = "dynamic"` if needed later.
- **Per-tenant Teiid bound to `127.0.0.1` only.** Never published publicly; the
  platform API reaches each tenant's Teiid over localhost on deterministic ports.
- **Secrets as references, never plaintext.** `tenant_secret_refs` stores a
  reference; the Teiid API key is injected into the tenant container via an env
  var (`TENANT_<ID>_TEIID_API_KEY`). No plaintext in compose, DB, or logs.
- **Host firewall enforces egress.** Docker isolation alone is insufficient, so a
  per-tenant `iptables` chain (`TABLESCOPE-TENANT-<ID>`) allows only that tenant's
  on-prem CIDRs, denies other tenants' subnets/CIDRs and the metadata endpoint,
  and defaults to deny. Persisted via a systemd unit so it survives reboots.

## Deterministic layout

All host-facing values derive from a 1-based tenant index (`app/services/tenant_layout.py`),
so compose / firewall / resolver can never drift:

| index | docker subnet     | teiid IP      | servlet | pg wire | mgmt  |
|-------|-------------------|---------------|---------|---------|-------|
| 1     | `172.30.10.0/24`  | `172.30.10.10`| 18095   | 15442   | 19990 |
| 2     | `172.30.20.0/24`  | `172.30.20.10`| 28095   | 25442   | 29990 |

Paths: `/opt/tablescope/tenants/<tenant_id>/{vdb,logs,secrets,mounts,compose}`.

## Components

| Layer | Location |
|-------|----------|
| Terraform TGW hub | `terraform/modules/network-hub` |
| Terraform per-tenant VPC + VPN | `terraform/modules/tenant-vpc` |
| Terraform orchestration | `terraform/tenants.tf`, `tenant-variables.tf`, `tenant-outputs.tf` |
| Registry tables | `tenant_data_planes`, `tenant_secret_refs` (migration `0011`) |
| Provisioning / layout / compose / firewall / resolver / health | `platform-api/app/services/tenant_*.py` |
| Admin API | `platform-api/app/routes/tenant_data_planes.py` (`/api/tenant-data-planes`, super-admin) |

## Onboarding a tenant

1. **Register the data plane** (allocates index, subnet, ports, paths):
   ```
   POST /api/tenant-data-planes
   { "tenant_id": "acme", "tenant_name": "Acme Co", "allowed_onprem_cidrs": ["10.10.0.0/16"] }
   ```
2. **Provision AWS** — add the tenant to `terraform.tfvars` `tenants` map (see
   `terraform.tfvars.example`) and `terraform apply`. Each VPN bills ~$0.05/hr.
3. **Attach VPN metadata** from the Terraform outputs:
   ```
   POST /api/tenant-data-planes/acme/vpn-metadata
   { "tenant_vpc_id": "...", "vpn_connection_id": "...", "vpn_tunnel1_address": "...", ... }
   ```
4. **Render + apply the container** on the EC2 host:
   `POST /api/tenant-data-planes/acme/provision-container` returns the compose
   file + directory list; create the dirs, write the compose, set the API key
   env var, `docker compose -f <file> up -d`.
5. **Apply host firewall** — `GET /api/tenant-data-planes/firewall-script` returns
   the idempotent script + systemd unit; install and enable on the host.
6. **Hand the customer their config** — `GET /api/tenant-data-planes/acme/onboarding-package`.
7. **Verify** — `POST /api/tenant-data-planes/acme/health` reports VPN, Teiid,
   firewall, VDB-path, and optional on-prem connectivity probes.

## Backward compatibility

With an empty Terraform `tenants` map no tenant infra is created and the existing
single-host deployment is untouched. The Teiid resolver falls back to the global
settings when a tenant has no data plane, so existing single-tenant / dev-mode
data-source creation keeps working.
