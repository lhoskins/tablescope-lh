# Devin: merge and deploy private S3 data-plane boundaries

**Repository:** `lhoskins/tablescope-lh`

**Feature branch:** `codex/isolated-data-plane-s3-boundary`

**Merge target:** `UX-design-03`

**Feature base:** `766c7cb4427e3ec0aec590e7971222471383ee43`

This change adds migration `0089` and changes Terraform, platform API, worker,
and web UI. Deploy it as one coordinated maintenance-window change.

## Security invariant

An organization with a `tenant_data_planes` record never falls back to the
global S3 bucket. It can read or write only after all tenant metadata is
present and a live write/head/read/delete probe proves access through the
tenant endpoint with the tenant role and CMK. This applies to both `none` and
`customer_vpn` modes.

The shared EC2 host remains a trusted control-plane boundary. The feature
isolates each customer's S3 authorization and network path; it does not defend
against root compromise of that shared host. Customers requiring that fault
boundary need tenant-resident compute.

## Merge

```bash
git fetch origin --prune
git rev-parse origin/codex/isolated-data-plane-s3-boundary
git show --stat --oneline origin/codex/isolated-data-plane-s3-boundary

git checkout UX-design-03
git pull --ff-only origin UX-design-03
git branch backup/UX-design-03-before-private-s3-20260905
git push origin backup/UX-design-03-before-private-s3-20260905

git merge --no-ff origin/codex/isolated-data-plane-s3-boundary \
  -m "Merge tenant-private S3 data-plane boundaries"
```

If `UX-design-03` moved beyond the feature base, inspect the delta and preserve
the fail-closed resolver, migration `0089`, tenant access-point endpoint URL,
and Terraform deny policies. Never restore global `S3StorageService()` in a
tenant-scoped path while resolving a conflict.

## Pre-merge validation

```bash
cd platform-api
python -m ruff check app tests/test_tenant_data_planes.py
python -m mypy app
python -m pytest -q \
  tests/test_tenant_data_planes.py \
  tests/test_chat_attachment_authorization.py \
  tests/test_file_import_ingestion.py \
  tests/test_upload_intake.py \
  tests/test_file_import_routes.py
python -m alembic heads

cd ../web-ui
npm ci --no-audit --no-fund
npm run typecheck
npm run lint
npm run build

cd ../terraform
terraform fmt -recursive -check
terraform init -backend=false
terraform validate
```

Run `terraform plan` with the production backend and reviewed tenant values.
Reject the plan if either mode lacks a bucket, CMK, access point, S3 interface
endpoint, tenant role, or the shared-to-tenant and return TGW routes.

## Deploy order

1. Export the current DB and Terraform state. Start a maintenance window for
   existing isolated tenants; migration defaults their storage to
   `unconfigured`, so the new API intentionally blocks their data operations
   until metadata is imported and validated.
2. Add every existing isolated tenant to `terraform.tfvars`. Set `vpn_mode` to
   `none` or `customer_vpn`; both receive private S3. Leave
   `storage_force_destroy = false` in production.
3. Apply Terraform before activating the new API:

   ```bash
   cd terraform
   terraform plan -out private-s3.tfplan
   terraform show private-s3.tfplan
   terraform apply private-s3.tfplan
   terraform output -json tenant_data_planes > /tmp/tenant-data-planes.json
   ```

4. Deploy the migration and services:

   ```bash
   cd ..
   git checkout UX-design-03
   git pull --ff-only origin UX-design-03
   sudo docker compose build platform-api platform-api-worker web-ui
   sudo docker compose run --rm platform-api alembic upgrade head
   sudo docker compose up -d platform-api platform-api-worker web-ui
   sudo docker compose restart nginx
   ```

5. For each tenant, import `.["TENANT"].storage` from the JSON output. The
   values are identifiers only; do not copy AWS credentials into the database.

   ```bash
   TENANT_ID=acme
   jq --arg id "$TENANT_ID" '.[$id].storage' \
     /tmp/tenant-data-planes.json > /tmp/acme-storage.json
   curl --fail-with-body -X POST \
     -H "Authorization: Bearer $TABLESCOPE_ADMIN_TOKEN" \
     -H 'Content-Type: application/json' \
     --data-binary @/tmp/acme-storage.json \
     "https://YOUR_HOST/api/tenant-data-planes/$TENANT_ID/storage-metadata"
   ```

   Import network fields to `/{tenant_id}/vpn-metadata` as usual.

6. Render/apply the tenant compose and firewall artifacts. Recreate the API and
   worker containers if necessary so their EC2 role credentials and TGW route
   are effective.
7. Run the health endpoint. It must return `storage_status: ready`; then call
   `POST /api/tenant-data-planes/{tenant_id}/provision-vdbs`. Only this final
   call sets the plane active.

## Acceptance and negative tests

For one `none` tenant and one `customer_vpn` tenant:

- Upload a file, create/redeploy a user VDB, create/redeploy a shared VDB, and
  upload/delete a chat attachment. Confirm all objects land in only that
  tenant's bucket and carry exactly that tenant's CMK ARN.
- From the runtime role, direct access to the bucket name must be denied.
- Requests through the public S3 endpoint must be denied.
- Tenant A's assumed role/access-point ARN must be denied against tenant B.
- Changing the registered endpoint, CMK, or role to another tenant must fail
  health and block VDB/upload operations; it must never use the shared bucket.
- Confirm `s3_force_private=false` is rejected by the API.

Record bucket ARN, access-point ARN, endpoint ID, role ARN, KMS ARN, object
encryption, and CloudTrail request source for each check.

## Rollback

Do not destroy tenant storage. Stop the new services, restore the prior images,
and run `alembic downgrade 0088` only after confirming no process depends on the
new columns. Removing the code re-enables legacy shared behavior, so this is an
availability rollback, not a security-equivalent rollback. Keep buckets and
CMKs; `force_destroy=false` and the 30-day KMS deletion window are intentional.

Report the merge SHA, deployed SHA, migration head, Terraform plan/apply result,
health response for every isolated tenant, and all negative-test evidence.
