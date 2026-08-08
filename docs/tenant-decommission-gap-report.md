# Tenant Decommission — Current-State Gap Report

## Repository / branches
- Repository: `lhoskins/tablescope-lh`
- Base integration branch: `devin/r-echarts-e2e-validation` (includes VPN/data-plane code)
- Working branch: `devin/orchestrated-tenant-decommission-terraform`
- Deployed SHA (current branch): `33cd0158` (`devin/canonical-insight-conversations`, not yet merged to integration)
- Decommission branch base SHA: `6cca9ea1` (`devin/r-echarts-e2e-validation`)

## What already exists
1. **Tenant data-plane registry** (`platform-api/app/models/tenant_data_plane.py`)
   - `TenantDataPlane` with AWS/VPC/VPN/Docker/network/firewall metadata.
   - `TenantSecretRef` stores secret references only.
   - `status`, `last_health_status`, `last_health_message` already present.
2. **Tenant layout/compose/firewall services**
   - `TenantLayout` in `app/services/tenant_layout.py` gives deterministic Docker network, container name, ports, paths, firewall chain.
   - `TenantComposeService` renders per-tenant compose files.
   - `TenantFirewallService` renders combined iptables script.
3. **Tenant provisioning/deletion**
   - `TenantProvisioningService` creates planes.
   - `tenant_data_planes_crud.py` has a synchronous `DELETE /api/tenant-data-planes/{tenant_id}` that:
     - calls `purge_app_tenant()` to delete DB rows,
     - deletes folders,
     - deletes `TenantDataPlane`,
     - returns a host teardown script.
   - This is **not** the orchestrated workflow the plan requires (no Terraform, no plan policy, no audit tombstone, no freeze, no approval).
4. **Tenant deletion service** (`tenant_deletion_service.py`)
   - Explicit dependency-ordered tenant data purge.
   - `undeploy_tenant_vdbs()` and `delete_tenant_folders()` helpers.
   - Used by both `tenants_crud.delete_tenant` and `tenant_data_planes_crud.delete_data_plane`.
5. **Authorization**
   - `require_human_platform_admin()` / `require_platform_admin()` in `app/auth/rbac.py`.
   - `require_role(Role.ADMIN)` plus `is_super_admin` check for data-plane admin endpoints.
   - `RequestContext` carries `tenant_id`, `user_id`, `role`, `permissions`, `aal`.
6. **Middleware**
   - `AuthMiddleware` sets `request.state.context`.
   - `require_membership` re-checks user/tenant active state on every request.
   - No tenant lifecycle status beyond `is_active`; no `decommissioning`/`decommissioned` states.
7. **Terraform**
   - `terraform/tenants.tf` uses `module.tenant` with `for_each = var.tenants`.
   - `module.network_hub` count is `length(var.tenants) > 0 ? 1 : 0` — deleting the last tenant would destroy the hub.
   - `terraform/modules/tenant-vpc/main.tf` creates VPC, subnet, route table/association, SG, customer gateway, VPN, TGW route table/association, routes.
   - No backend block in `main.tf`; state backend is not committed (likely `backend.tf` or env-configured in CI).
8. **Tests/CI**
   - `pytest` and `ruff`/`mypy` pass.
   - No existing decommission workflow tests.

## Gaps to implement
1. **Database**
   - `tenant_decommission_jobs` and `tenant_decommission_events` tables.
   - `Tenant.lifecycle_status`, `activity_blocked_at`, `decommission_job_id`, `decommissioned_at`.
   - `TenantDataPlane.decommission_job_id` or status extension.
2. **Freeze / activity guard**
   - Middleware or dependency that returns `423 Locked` for decommissioning tenants except status/export/decommission endpoints.
3. **State machine / admin API**
   - `POST .../decommission/preview`
   - `POST .../decommission` (request)
   - `GET/approve/retry/cancel/unfreeze` endpoints
   - Idempotency, two-person approval, typed confirmation, protected-tenant deny list.
4. **Preview / inventory**
   - Count users, projects, data sources, documents, dashboards, actions, queued jobs, AWS IDs, container/network/firewall paths, secrets, vector/catalog namespaces, billing/subscription status.
5. **Terraform orchestration**
   - Structured tenant-map update (remove target key only).
   - Saved plan generation, SHA-256, JSON summary.
   - Plan policy validator (allowed target module deletes/updates; reject shared hub destruction, other-tenant changes, creates, provider drift).
   - Approval with hash verification.
   - Exact `terraform apply <plan>` execution by a privileged runner.
6. **AWS verification**
   - Poll AWS for absence of target VPC, subnet, route tables, SG, CGW, VPN, VPN attachment, TGW route table/association, routes.
   - Verify shared TGW still exists and other tenants healthy.
   - Verify `terraform plan` no changes and state list clean.
7. **Runtime / host cleanup**
   - Stop/remove tenant container, disconnect platform API/worker from tenant network, remove network, remove compose file, remove VDB/log/mount/secret directories, regenerate firewall excluding target tenant, reload firewall.
8. **Secrets cleanup**
   - Revoke/delete tenant-specific secret references after real secret deletion.
9. **Data cleanup**
   - Reuse/extend `purge_app_tenant` with checkpoint counts and ordering.
   - External stores: Redis keys, S3 prefixes, vector collections, file quarantine.
10. **Audit tombstone**
    - Minimal immutable decommission record outside tenant cascade.
11. **Runner / CI**
    - Least-privileged runner script/GitHub Actions workflow with signed payloads.
12. **Admin UI**
    - Preview, progress, approval, retry/cancel, sanitized report.

## First controlled run (`acme`)
- Do **not** apply until unit/integration/fixture tests and a disposable staging tenant decommission succeed.
- The preview endpoint can be run against `acme` to report planned resource changes and blockers.
