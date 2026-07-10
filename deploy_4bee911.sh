#!/usr/bin/env bash
set -uo pipefail
cd /home/ubuntu/tablescope
BRANCH="devin/1781979035-scope-relationship-builder"
echo "== APP DEPLOY START $(date) =="
git fetch origin "$BRANCH" 2>&1 | tail -2
git checkout "$BRANCH" 2>&1 | tail -1
git reset --hard "origin/$BRANCH" 2>&1 | tail -1
echo "== HEAD =="; git rev-parse --short HEAD
echo "== build platform-api + web-ui =="
sudo docker compose build platform-api web-ui 2>&1 | tail -15
echo "== recreate =="
sudo docker compose up -d platform-api platform-api-worker web-ui 2>&1 | tail -10
sleep 8
echo "== alembic upgrade head =="
sudo docker compose exec -T platform-api alembic upgrade head 2>&1 | tail -5
echo "== alembic current =="
sudo docker compose exec -T platform-api alembic current 2>&1 | tail -3
echo "== APP DEPLOY DONE $(date) =="
