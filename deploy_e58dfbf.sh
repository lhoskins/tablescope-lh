#!/usr/bin/env bash
set -uo pipefail
cd /home/ubuntu/tablescope
echo "=== $(date) fetch+checkout ==="
git fetch origin devin/1781979035-scope-relationship-builder
git checkout devin/1781979035-scope-relationship-builder
git pull --ff-only origin devin/1781979035-scope-relationship-builder
echo "=== HEAD ==="; git rev-parse --short HEAD
echo "=== $(date) build platform-api + web-ui ==="
sudo docker compose build platform-api web-ui
echo "=== recreate ==="
sudo docker compose up -d platform-api platform-api-worker web-ui
echo "=== alembic upgrade head ==="
sleep 8
sudo docker compose exec -T platform-api alembic upgrade head
echo "=== alembic current ==="
sudo docker compose exec -T platform-api alembic current
echo "=== DONE $(date) ==="
