#!/usr/bin/env bash
# Attaches the Tablescope control-plane containers to every per-tenant Docker
# network so the (containerized) platform API/worker can reach each tenant Teiid
# over the tenant network. Idempotent; safe to re-run.
#
# Install to /usr/local/sbin/ and run via the companion systemd unit
# (deploy/tablescope-control-plane-netattach.service) so the attachment is
# re-established on boot / after Docker restarts.
set -uo pipefail
CONTROL_PLANE=(tablescope-platform-api-1 tablescope-platform-api-worker-1)
for net in $(docker network ls --filter "name=tenant_" --format "{{.Name}}"); do
  for c in "${CONTROL_PLANE[@]}"; do
    docker network connect "$net" "$c" 2>/dev/null && echo "connected $c -> $net" || true
  done
done
