#!/usr/bin/env bash
# TableScope VPN/SMB E2E orchestrator.
# Usage:
#   run.sh <create|test|destroy|full> [run-id]
#
# Environment variables:
#   AWS_REGION           - target region (default us-west-1)
#   AWS_ROLE_ARN         - OIDC role for Terraform / AWS CLI
#   TABLESCOPE_API       - base URL of the TableScope platform API
#   TABLESCOPE_API_KEY   - admin API key for tenant creation
#   TABLESCOPE_REPO      - path to the tablescope-lh checkout
#   TERRAFORM_STATE_BUCKET - S3 bucket for the simulator Terraform state
#   TERRAFORM_STATE_KEY  - state key prefix
#   REMOTE_CIDRS         - comma-separated CIDRs the customer should route to
#
# This script is intended for workflow_dispatch / staging-environment runs.
# It always attempts teardown on failure unless the mode is `create`.

set -euo pipefail

MODE="${1:-full}"
RUN_ID="${2:-$(date +%s)}"
: "${AWS_REGION:=us-west-1}"
: "${TABLESCOPE_REPO:=$(git rev-parse --show-toplevel 2>/dev/null || echo .)}"
: "${SIMULATOR_DIR:=$TABLESCOPE_REPO/test-infra/vpn-smb-customer-simulator}"
: "${TERRAFORM_STATE_BUCKET:=}"
: "${TERRAFORM_STATE_KEY:=vpn-smb-e2e/${RUN_ID}.tfstate}"
: "${REMOTE_CIDRS:=0.0.0.0/0}"

SIM_IP_FILE="/tmp/tablescope-vpn-smb-e2e-sim-ip-${RUN_ID}"
VPN_ID_FILE="/tmp/tablescope-vpn-smb-e2e-vpn-id-${RUN_ID}"
EVIDENCE_DIR="${TABLESCOPE_REPO}/artifacts/vpn-smb-e2e/${RUN_ID}"

cleanup_on_error() {
  if [[ "$MODE" != "create" ]]; then
    echo "Failure detected; attempting teardown..."
    destroy || true
  fi
}

trap cleanup_on_error ERR

log() {
  echo "[vpn-smb-e2e] $*"
}

_run_terraform() {
  local cmd=$1
  shift
  cd "${SIMULATOR_DIR}/terraform"
  local backend_args=()
  if [[ -n "$TERRAFORM_STATE_BUCKET" ]]; then
    backend_args+=(
      -backend-config="bucket=${TERRAFORM_STATE_BUCKET}"
      -backend-config="key=${TERRAFORM_STATE_KEY}"
      -backend-config="region=${AWS_REGION}"
      -backend-config="encrypt=true"
    )
  fi
  terraform init "${backend_args[@]}"
  terraform "${cmd}" "$@" -var="run_id=${RUN_ID}" -var="allowed_vpn_cidrs=${ALLOWED_VPN_CIDRS:-[]}" -var="aws_region=${AWS_REGION}"
}

create_simulator() {
  log "Creating customer simulator (run_id=${RUN_ID})"
  _run_terraform plan -out=tfplan
  _run_terraform apply tfplan

  terraform output -raw customer_gateway_public_ip > "$SIM_IP_FILE"
  log "Customer gateway EIP: $(cat "$SIM_IP_FILE")"
}

provision_tablescope_vpn() {
  local sim_ip
  sim_ip=$(cat "$SIM_IP_FILE")
  log "Provisioning TableScope test tenant VPN through ${TABLESCOPE_API:-api}"

  # TODO: call TableScope tenant provisioning / Terraform workflow.
  # The expected sequence is:
  # 1. Create tenant `vpn-smb-e2e` with `customer_vpn` tier.
  # 2. Add the tenant to the canonical Terraform `tenants` map with
  #    customer_gateway_ip = sim_ip and customer_onprem_cidrs = 10.250.10.0/24.
  # 3. Run `terraform plan -out=...` and `terraform apply` with the saved plan.
  # 4. Capture the resulting `vpn_connection_id` in $VPN_ID_FILE.

  # Placeholder until the platform provisioning endpoint is wired.
  : > "$VPN_ID_FILE"
  log "TableScope VPN placeholder created"
}

configure_simulator() {
  local sim_ip vpn_id
  sim_ip=$(cat "$SIM_IP_FILE")
  vpn_id=$(cat "$VPN_ID_FILE")

  log "Copying fixtures and rendering VPN config on ${sim_ip}"

  python3 "${SIMULATOR_DIR}/scripts/generate-fixtures.py" \
    --output "${SIMULATOR_DIR}/fixtures"

  # Render strongSwan config locally if a VPN id is available.
  if [[ -n "$vpn_id" ]]; then
    CUSTOMER_GATEWAY_IP="$sim_ip" \
    CUSTOMER_LAN_CIDR="10.250.10.0/24" \
    REMOTE_CIDRS="$REMOTE_CIDRS" \
    python3 "${SIMULATOR_DIR}/scripts/render-vpn-config.py" \
      --vpn-connection-id "$vpn_id" \
      --region "$AWS_REGION" \
      --output-dir "${SIMULATOR_DIR}/compose/strongswan"
  fi

  # SCP/rsync fixtures and compose files to the gateway host, then start.
  # (The actual EC2 instance may not have a key pair; use SSM Run Command.)
  log "Deploying compose stack to simulator"
  # aws ssm send-command ...
}

run_tests() {
  mkdir -p "$EVIDENCE_DIR"
  log "Running platform security and integration tests"
  cd "${TABLESCOPE_REPO}/platform-api"
  pytest tests/security/test_smb_tenant_network_isolation.py tests/integration/test_smb_repository_import.py -q \
    --junitxml="$EVIDENCE_DIR/junit.xml" || true

  if [[ -n "${PLAYWRIGHT_E2E:-}" ]]; then
    log "Running browser E2E tests"
    cd "${TABLESCOPE_REPO}/web-ui"
    npx playwright test e2e/data-source-builder-network-import.spec.ts \
      --reporter=junit,"$EVIDENCE_DIR/playwright-junit.xml" || true
  fi
}

collect_evidence() {
  mkdir -p "$EVIDENCE_DIR"
  log "Collecting evidence to $EVIDENCE_DIR"
  # aws ec2 describe-vpn-connections, route tables, security groups, etc.
  # Copy sanitized strongswan-status and samba logs from the gateway host.
  # The full list is in docs/testing/vpn-smb-repository-e2e.md.
}

destroy() {
  log "Destroying simulator (run_id=${RUN_ID})"
  cd "${SIMULATOR_DIR}/terraform"
  terraform destroy -auto-approve -var="run_id=${RUN_ID}" \
    -var="allowed_vpn_cidrs=${ALLOWED_VPN_CIDRS:-[]}" \
    -var="aws_region=${AWS_REGION}" || true

  # TODO: destroy TableScope test tenant VPN via Terraform / platform API.
  rm -f "$SIM_IP_FILE" "$VPN_ID_FILE"
}

main() {
  case "$MODE" in
    create)
      create_simulator
      provision_tablescope_vpn
      configure_simulator
      ;;
    test)
      run_tests
      collect_evidence
      ;;
    destroy)
      destroy
      ;;
    full)
      create_simulator
      provision_tablescope_vpn
      configure_simulator
      run_tests
      collect_evidence
      destroy
      ;;
    *)
      echo "Unknown mode: $MODE" >&2
      exit 1
      ;;
  esac
  log "Done"
}

main "$@"
