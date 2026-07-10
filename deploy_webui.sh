#!/bin/bash
set -e
cd /home/ubuntu/tablescope
echo "[build web-ui] $(date)"
sudo docker compose build web-ui
echo "[up web-ui] $(date)"
sudo docker compose up -d web-ui
sleep 6
echo "[restart nginx] $(date)"
sudo docker compose restart nginx
echo "[done] $(date)"
sudo docker compose ps --format "{{.Name}} {{.Status}}" | grep -E "web-ui|nginx"
