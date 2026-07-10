#!/usr/bin/env bash
set -e
cd /home/ubuntu/tablescope
BRANCH="devin/1781979035-scope-relationship-builder"

echo "== DEPLOY scopes START $(date) =="
echo "== before =="
git rev-parse --short HEAD

git fetch origin "$BRANCH" 2>&1 | tail -2
git checkout "$BRANCH" 2>&1 | tail -1
git reset --hard "origin/$BRANCH" 2>&1 | tail -1
echo "== after =="
git rev-parse --short HEAD

echo "== rebuild platform-api + web-ui =="
sudo docker compose build platform-api web-ui 2>&1 | tail -8

echo "== restart services =="
sudo docker compose up -d platform-api platform-api-worker web-ui 2>&1 | tail -8

echo "== run alembic migration (head) =="
sleep 8
sudo docker compose exec -T platform-api alembic upgrade head 2>&1 | tail -12

echo "== reload nginx (re-resolve recreated web-ui upstream) =="
sudo docker compose exec -T nginx nginx -s reload 2>&1 | tail -3 || echo "NGINX_RELOAD_SKIPPED"

echo "== status =="
sudo docker compose ps --format "table {{.Name}}\t{{.Status}}"

echo "== health =="
curl -s -o /dev/null -w "platform-api /health/live: %{http_code}\n" http://localhost:8000/health/live || true
curl -s -o /dev/null -w "app / : %{http_code}\n" http://localhost/ || true

echo "== DONE $(date) =="
