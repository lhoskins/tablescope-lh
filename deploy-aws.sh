#!/usr/bin/env bash
# Single-server AWS deployment script for Tablescope.
#
# Usage:
#   bash deploy-aws.sh
#
# Run once on a fresh EC2 instance (Ubuntu 22.04+) with Docker + Compose
# available. Re-runnable: idempotent — pulls latest images, applies
# migrations, restarts services.
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/etlagent/tablescope.git}"
BRANCH="${BRANCH:-feature/multi-tenant-platform-migration}"
WORK_DIR="${WORK_DIR:-$HOME/tablescope}"
TEIID_FILES="${TEIID_FILES:-/opt/wildfly/teiidfiles}"

need_root() {
    if ! sudo -n true 2>/dev/null; then
        echo "[deploy-aws] sudo required, please re-run with passwordless sudo or as root." >&2
        exit 1
    fi
}

install_prereqs() {
    if ! command -v docker >/dev/null 2>&1; then
        echo "[deploy-aws] Installing Docker"
        need_root
        sudo apt-get update -y
        sudo apt-get install -y ca-certificates curl gnupg lsb-release
        sudo install -m 0755 -d /etc/apt/keyrings
        curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
        sudo chmod a+r /etc/apt/keyrings/docker.gpg
        echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
            | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
        sudo apt-get update -y
        sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
        sudo usermod -aG docker "$USER" || true
    fi
}

prepare_shared_volumes() {
    if [ ! -d "$TEIID_FILES" ]; then
        echo "[deploy-aws] Creating $TEIID_FILES"
        sudo mkdir -p "$TEIID_FILES"
        sudo chown "$USER":"$USER" "$TEIID_FILES"
    fi
}

clone_or_pull() {
    if [ ! -d "$WORK_DIR/.git" ]; then
        echo "[deploy-aws] Cloning $REPO_URL into $WORK_DIR"
        git clone "$REPO_URL" "$WORK_DIR"
    fi
    cd "$WORK_DIR"
    git fetch --all
    git checkout "$BRANCH"
    git pull --ff-only
}

ensure_env_file() {
    if [ ! -f .env ]; then
        echo "[deploy-aws] Creating .env (generated secrets)"
        cp .env.example .env
        sed -i "s|^JWT_SECRET_KEY=.*|JWT_SECRET_KEY=$(openssl rand -hex 32)|" .env
        sed -i "s|^TEIID_API_KEY=.*|TEIID_API_KEY=$(openssl rand -hex 32)|" .env
    fi
}

deploy() {
    docker compose build
    docker compose run --rm platform-api-migrate
    docker compose up -d
    docker compose ps
}

main() {
    install_prereqs
    prepare_shared_volumes
    clone_or_pull
    ensure_env_file
    deploy
    echo "[deploy-aws] Done. Tablescope is running on:"
    echo "  Platform API : http://$(hostname -I | awk '{print $1}'):8000"
    echo "  Web UI       : http://$(hostname -I | awk '{print $1}'):3000"
}

main "$@"
