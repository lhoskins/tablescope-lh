#!/usr/bin/env bash
set -uo pipefail
cd /home/ubuntu/tablescope
echo "=== $(date) build platform-api + web-ui ==="
docker compose build platform-api web-ui
echo "=== recreate platform-api + worker + web-ui ==="
docker compose up -d platform-api platform-api-worker web-ui
echo "=== alembic upgrade head ==="
docker compose exec -T platform-api alembic upgrade head
echo "=== alembic current ==="
docker compose exec -T platform-api alembic current
echo "=== DONE $(date) ==="
