#!/usr/bin/env bash
# Cloud-init user-data for Tablescope AI Server (g6.xlarge GPU).
# Installs Docker + NVIDIA runtime, mounts data EBS, deploys AI stack.
set -euo pipefail
exec > >(tee /var/log/tablescope-ai-deploy.log) 2>&1

echo "[tablescope-ai] Starting deployment — $(date)"

# ── 1. System updates ─────────────────────────────────────────────
apt-get update -y
apt-get upgrade -y

# ── 2. Install Docker ─────────────────────────────────────────────
apt-get install -y ca-certificates curl gnupg lsb-release jq awscli
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
usermod -aG docker ubuntu

# ── 3. Install NVIDIA drivers + container toolkit ─────────────────
# NVIDIA driver
apt-get install -y linux-headers-$(uname -r)
curl -fsSL https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2204/x86_64/cuda-keyring_1.1-1_all.deb -o /tmp/cuda-keyring.deb
dpkg -i /tmp/cuda-keyring.deb
apt-get update -y
apt-get install -y cuda-drivers

# NVIDIA Container Toolkit
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
apt-get update -y
apt-get install -y nvidia-container-toolkit
nvidia-ctk runtime configure --runtime=docker
systemctl restart docker

# ── 4. Mount 500 GB encrypted data volume ─────────────────────────
DATA_DEV="/dev/xvdf"
MOUNT_POINT="/mnt/tablescope-ai"

# Wait for the EBS volume to attach
for i in $(seq 1 30); do
  if [ -b "$DATA_DEV" ]; then break; fi
  echo "Waiting for $DATA_DEV..."
  sleep 5
done

# Format only if not already formatted
if ! blkid "$DATA_DEV" &>/dev/null; then
  mkfs.ext4 "$DATA_DEV"
fi

mkdir -p "$MOUNT_POINT"
mount "$DATA_DEV" "$MOUNT_POINT"

# Persist in fstab
UUID=$(blkid -s UUID -o value "$DATA_DEV")
echo "UUID=$UUID $MOUNT_POINT ext4 defaults,nofail 0 2" >> /etc/fstab

# Create directory structure
mkdir -p "$MOUNT_POINT"/{ollama,qdrant,models,embeddings,logs,audit,runtime,temp,backups}
chown -R ubuntu:ubuntu "$MOUNT_POINT"

# ── 5. Clone repository ───────────────────────────────────────────
WORK_DIR=/home/ubuntu/tablescope
sudo -u ubuntu git clone "${repo_url}" "$WORK_DIR"
cd "$WORK_DIR"
sudo -u ubuntu git checkout "${branch}"

# ── 6. Create AI server .env ──────────────────────────────────────
cat > "$WORK_DIR/ai-server/.env" <<EOF
OLLAMA_URL=http://ollama:11434
QDRANT_URL=http://qdrant:6333
TABLESCOPE_APP_URL=${app_base_url}
AI_SIGNING_SECRET=${ai_signing_secret}
IDLE_TIMEOUT_MINUTES=${idle_timeout_minutes}
DATA_MOUNT=/mnt/tablescope-ai
EOF
chown ubuntu:ubuntu "$WORK_DIR/ai-server/.env"

# ── 7. Build and start AI services ────────────────────────────────
cd "$WORK_DIR/ai-server"
sudo -u ubuntu docker compose build
sudo -u ubuntu docker compose up -d

# ── 8. Pull initial Ollama models ─────────────────────────────────
echo "[tablescope-ai] Pulling Ollama models..."
# Wait for Ollama to be ready
for i in $(seq 1 60); do
  if docker compose exec -T ollama ollama list &>/dev/null; then break; fi
  echo "Waiting for Ollama..."
  sleep 5
done

docker compose exec -T ollama ollama pull qwen2.5-coder:7b
docker compose exec -T ollama ollama pull llama3.1:8b
docker compose exec -T ollama ollama pull nomic-embed-text

# ── 9. Install idle monitor cron ──────────────────────────────────
cat > /usr/local/bin/tablescope-ai-idle-check.sh <<'IDLE_SCRIPT'
#!/bin/bash
IDLE_LIMIT=$((${idle_timeout_minutes} * 60))
ACTIVITY_FILE="/mnt/tablescope-ai/runtime/last_activity.json"

if [ ! -f "$ACTIVITY_FILE" ]; then
  exit 0
fi

LAST_SEC=$(python3 -c "
import json, datetime
d = json.load(open('$ACTIVITY_FILE'))
ts = d.get('last_activity_utc', '')
if not ts:
    print(0)
else:
    last = datetime.datetime.fromisoformat(ts.rstrip('Z')).replace(tzinfo=datetime.timezone.utc)
    now = datetime.datetime.now(datetime.timezone.utc)
    print(int((now - last).total_seconds()))
")

if [ "$LAST_SEC" -gt "$IDLE_LIMIT" ]; then
  INSTANCE_ID=$(curl -s http://169.254.169.254/latest/meta-data/instance-id)
  REGION=$(curl -s http://169.254.169.254/latest/meta-data/placement/region)
  aws ec2 stop-instances --instance-ids "$INSTANCE_ID" --region "$REGION"
  echo "$(date -u) Auto-stopped after $${LAST_SEC}s idle" >> /mnt/tablescope-ai/logs/idle-shutdown.log
fi
IDLE_SCRIPT
chmod +x /usr/local/bin/tablescope-ai-idle-check.sh

# Run idle check every 5 minutes
echo "*/5 * * * * root /usr/local/bin/tablescope-ai-idle-check.sh" > /etc/cron.d/tablescope-ai-idle

# ── 10. Verify GPU ────────────────────────────────────────────────
echo "[tablescope-ai] Verifying GPU..."
nvidia-smi || echo "WARNING: nvidia-smi failed — GPU may need reboot"

# ── 11. Completion marker ─────────────────────────────────────────
echo "[tablescope-ai] Deployment complete — $(date)" | tee /home/ubuntu/tablescope-ai-ready.txt
