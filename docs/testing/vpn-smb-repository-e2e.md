# VPN/UNC/SMB Repository E2E Validation

This document describes the repeatable staging environment and test workflow for
validating TableScope's **Isolated Data Plane + Customer VPN** tier against a
simulated on-premises SMB repository.

For the operator-facing setup guide (AWS VPN, customer gateway, SMB share, and the
non-UI configuration required beyond the TableScope Settings UI), see
[`docs/operations/aws-vpn-network-repository-setup.md`](../operations/aws-vpn-network-repository-setup.md).

## Base reference

- Repository: `lhoskins/tablescope-lh`
- Integration branch: `devin/r-echarts-e2e-validation`
- Working branch: `devin/vpn-smb-repository-e2e-validation`
- Test tenant: `vpn-smb-e2e` (disposable)
- Control tenant: `vpn-smb-control`
- AWS account: non-production / staging only

## What is validated

1. A tenant can be provisioned with an isolated data plane and a customer-managed
   AWS Site-to-Site VPN.
2. A simulated customer network can be built in a **separate, non-peered VPC**.
3. An SMB2/SMB3 repository is reachable only through the VPN tunnel.
4. The repository can be registered as a tenant-scoped `network_file_connection`.
5. Structured and unstructured files can be imported through the existing Data
   Source Builder (`/data-sources/imports/network`).
6. Imports follow the standard quarantine → malware scan → profile → staging
   pipeline.
7. Only governed file/profile content reaches the AI pipeline. SMB credentials,
   full UNC paths, and unrestricted network locators are kept out of browser and
   AI context.
8. Tenant, project, data-plane, Teiid, file, AI-context, and audit isolation are
   preserved.
9. Failures (routing, VPN, SMB, malware, profile, AI, isolation) produce safe
   errors with actionable evidence.

## Architecture

```text
┌─────────────────────────────────────────────────────────────────────┐
│  TableScope shared / tenant VPC            │   Simulated customer VPC │
│  (existing VPC + Transit Gateway)          │   (test-infra/vpn-smb-   │
│                                            │    customer-simulator)    │
│  platform-api-worker ──[tenant network]───►│   Customer VPN gateway   │
│  with tenant source IP binding             │   (strongSwan host)      │
│                                            │           │              │
│  DOCKER-USER tenant chain                  │           ▼              │
│  (allow tenant on-prem CIDRs only)         │   Samba container        │
│                                            │   10.250.20.20:445      │
└─────────────────────────────────────────────────────────────────────┘
                              AWS Site-to-Site VPN
```

### Tenant-bound network egress (Gate C)

The shared `platform-api-worker` reads network files on behalf of all tenants.
To prevent one tenant's worker from opening TCP 445 to another tenant's SMB
host, the SMB socket is bound to the worker's IP inside the requesting tenant's
Docker network. The host's `DOCKER-USER` per-tenant `iptables` chain can then
match by source subnet and only allow the on-prem CIDRs approved for that
tenant.

Implementation:

- `platform-api/app/services/tenant_network_source_ip.py` resolves the worker
  IP inside `TenantDataPlane.docker_subnet_cidr`.
- `platform-api/app/services/smb_gateway.py` binds the SMB socket to that IP
  by patching `socket.create_connection` with a per-thread source address.
- `platform-api/app/services/file_ingestion/acquisition.py` and
  `platform-api/app/routes/file_imports.py` pass the resolved source IP to the
  gateway.

## Test infrastructure

```
test-infra/vpn-smb-customer-simulator/
├── terraform/          # AWS VPC, subnet, IGW, EIP, EC2, SG, flow logs
├── compose/            # strongSwan + Samba Docker Compose, SMB config
├── fixtures/           # Deterministic test files
├── scripts/            # generate-fixtures.py, render-vpn-config.py, gateway user data
└── README.md           # Quickstart for the simulator
```

### Creating the simulator locally

```bash
# 1. Generate fixtures (no malware sample is committed).
python3 test-infra/vpn-smb-customer-simulator/scripts/generate-fixtures.py \
  --output test-infra/vpn-smb-customer-simulator/fixtures

# 2. Deploy the simulator VPC/EC2 (requires AWS credentials).
./scripts/vpn-smb-e2e/run.sh create "$(date +%s)"

# 3. After the TableScope tenant VPN is provisioned, render strongSwan config.
CUSTOMER_GATEWAY_IP="<sim EIP>" \
REMOTE_CIDRS="<TableScope shared VPC CIDR>,<test tenant VPC CIDR>" \
python3 test-infra/vpn-smb-customer-simulator/scripts/render-vpn-config.py \
  --vpn-connection-id "<vpn-xxx>" \
  --output-dir test-infra/vpn-smb-customer-simulator/compose/strongswan
```

## GitHub Actions workflow

`.github/workflows/vpn-smb-e2e.yml` provides a `workflow_dispatch` job with
`create`, `test`, `destroy`, and `full` modes.

Required secrets (add to `staging-vpn-smb-e2e` environment):

- `AWS_VPN_SMB_E2E_ROLE_ARN` — OIDC role for the workflow.
- `VPN_SMB_E2E_STATE_BUCKET` — S3 bucket for the simulator Terraform state.
- `TABLESCOPE_STAGING_API` / `TABLESCOPE_STAGING_API_KEY` — for provisioning.

Do **not** store pre-shared keys, SMB passwords, or generated customer-gateway
configuration in workflow logs or artifacts. The strongSwan config file is
written with `0600` and is never uploaded.

## Test layers

| Layer | File | What it checks |
|---|---|---|
| Security/isolation | `platform-api/tests/security/test_smb_tenant_network_isolation.py` | Source-IP binding, tenant network lookup, firewall posture. |
| Integration | `platform-api/tests/integration/test_smb_repository_import.py` | `acquire_network_path` passes the tenant source IP to the SMB gateway. |
| E2E (live) | `platform-api/tests/e2e/test_vpn_smb_repository.py` | Full VPN + SMB + import + Teiid query (skipped unless `VPN_SMB_E2E_API_URL` is set). |
| Browser (live) | `web-ui/e2e/data-source-builder-network-import.spec.ts` | Data Source Builder network import UI (skipped unless `VPN_SMB_E2E_API_URL` is set). |

## Running the validation locally

```bash
cd platform-api
ruff check app tests
mypy app
pytest -q

# Optional: run only the SMB isolation/integration tests.
pytest tests/security/test_smb_tenant_network_isolation.py \
       tests/integration/test_smb_repository_import.py -q
```

## Evidence bundle

Each workflow run produces `artifacts/vpn-smb-e2e/<run-id>/` containing:

- `environment.json` — run id, region, tenant/project ids.
- `terraform-plan.txt` / `terraform-plan.json` — simulator plan output.
- `aws-vpn-status.json` — `describe-vpn-connections` output.
- `route-tables.json`, `security-groups.json`, `flow-log-summary.json`.
- `strongswan-status.txt` — sanitized `swanctl --stats`.
- `samba-sanitized-status.txt` — `smbstatus` and logs with credentials redacted.
- `tablescope-health.json` — platform and Teiid health.
- `import-jobs.json` — file import job records and outcomes.
- `fixture-manifest.json` — expected file list, sizes, and SHA-256 hashes.
- `ai-audit-summary.json` — confirms no credentials/locators in AI context.
- `isolation-results.json` — cross-tenant/control denial checks.
- `screenshots/` — browser E2E evidence.
- `junit/` — pytest and Playwright JUnit XML.
- `report.md` — PASS / CONDITIONAL PASS / FAIL summary.

## Definition of done

- [x] Disposable isolated test tenant with `customer_vpn`.
- [x] Simulated customer gateway (IKEv2/IPsec) and SMB repository.
- [ ] At least one tunnel supports functional test and both pass failover.
- [ ] SMB3 reachable only through VPN by the correct tenant-bound path.
- [ ] Public / AI / control / other-tenant SMB access denied.
- [ ] Approved UNC path passes **Test access** and imports.
- [ ] Structured fixtures become correct data sources / Teiid objects.
- [ ] Documents become project documents without fake tables.
- [ ] Quarantine, validation, malware, hashing, profiling, and AI/catalog
      steps are evidenced.
- [ ] Credentials and unrestricted locators never reach browser or AI.
- [ ] Project Ask Anything works with grounded file content.
- [ ] Cross-tenant / cross-project retrieval returns no data.
- [ ] Failures fail safely with no duplicates or orphans.
- [ ] Automated report lists every test ID.
- [ ] Disposable infrastructure is destroyed.
- [ ] Targeted tests, full suites, Terraform validation, and browser tests
      pass.

## Risk summary

- **HIGH**: The live AWS Site-to-Site VPN workflow has not been executed yet.
  Do not point production TableScope at the simulator until the staging gates
  above are green.
- **MEDIUM**: AWS hourly VPN charges. The workflow includes an `always()`
  teardown step and TTL tags.
- **LOW**: Terraform state lock and least-privilege role reuse the existing
  TableScope Terraform conventions.
