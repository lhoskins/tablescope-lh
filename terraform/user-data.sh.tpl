#!/usr/bin/env bash
# Cloud-init user-data script for Tablescope EC2 instance.
# Runs once on first boot as root.
set -euo pipefail
exec > >(tee /var/log/tablescope-deploy.log) 2>&1

echo "[tablescope] Starting deployment — $(date)"

# ── 1. System updates ──────────────────────────────────────────────
apt-get update -y
apt-get upgrade -y

# ── 2. Install Docker ──────────────────────────────────────────────
apt-get install -y ca-certificates curl gnupg lsb-release
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Let ubuntu user run docker without sudo
usermod -aG docker ubuntu

# ── 3. Shared volumes ─────────────────────────────────────────────
mkdir -p /opt/wildfly/teiidfiles
chown ubuntu:ubuntu /opt/wildfly/teiidfiles

mkdir -p /opt/redash-8.0.0-7/apps/tsTest/src
chown ubuntu:ubuntu /opt/redash-8.0.0-7/apps/tsTest/src

# ── 4. Clone repository ───────────────────────────────────────────
WORK_DIR=/home/ubuntu/tablescope
sudo -u ubuntu git clone "${repo_url}" "$WORK_DIR"
cd "$WORK_DIR"
sudo -u ubuntu git checkout "${branch}"

# ── 5. Create .env with generated secrets ──────────────────────────
sudo -u ubuntu cp .env.example .env
sudo -u ubuntu sed -i "s|^JWT_SECRET_KEY=.*|JWT_SECRET_KEY=$(openssl rand -hex 32)|" .env
sudo -u ubuntu sed -i "s|^TEIID_API_KEY=.*|TEIID_API_KEY=$(openssl rand -hex 32)|" .env
sudo -u ubuntu sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(openssl rand -hex 16)|" .env

# ── 6. Build and start services ───────────────────────────────────
cd "$WORK_DIR"
sudo -u ubuntu docker compose build
sudo -u ubuntu docker compose run --rm platform-api-migrate
sudo -u ubuntu docker compose up -d

# ── 7. Completion marker ──────────────────────────────────────────
echo "[tablescope] Deployment complete — $(date)" | tee /home/ubuntu/tablescope-ready.txt
