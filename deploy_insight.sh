#!/bin/bash
set -e
cd /home/ubuntu/tablescope
echo "[build] start $(date)"
sudo docker compose build platform-api web-ui
echo "[up] recreate $(date)"
sudo docker compose up -d platform-api platform-api-worker web-ui
echo "[migrate] $(date)"
sleep 10
sudo docker compose exec -T platform-api alembic upgrade head || echo "MIGRATE_FAILED"
echo "[done] $(date)"
sudo docker compose ps
