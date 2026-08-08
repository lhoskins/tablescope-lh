#!/bin/bash
set -e
cd /home/ubuntu/tablescope
echo "[build] start $(date)"
sudo docker compose build teiid
sudo docker compose build --no-cache platform-api web-ui
echo "[up] recreate $(date)"
sudo docker compose up -d teiid platform-api platform-api-worker web-ui
echo "[migrate] $(date)"
sleep 8
sudo docker compose exec -T platform-api alembic upgrade head || echo "MIGRATE_FAILED"
echo "[done] $(date)"
sudo docker compose ps
