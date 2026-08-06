#!/usr/bin/env bash
# User data for the simulated customer gateway EC2 host.
set -euo pipefail

# Enable IP forwarding for the IPsec tunnel and for routing to the Samba bridge.
cat <<EOF > /etc/sysctl.d/99-tablescope-e2e.conf
net.ipv4.ip_forward=1
net.ipv4.conf.all.send_redirects=0
net.ipv4.conf.default.send_redirects=0
EOF
sysctl --system

# Install Docker and docker compose plugin.
yum update -y
yum install -y docker
systemctl enable --now docker
usermod -aG docker ec2-user

# Pull images that will be used by the compose stack.
docker pull ghcr.io/strongswan/strongswan:5.9
docker pull dperson/samba:4.18

# Create the repository tree. The compose file mounts this read-only into Samba.
mkdir -p /srv/repository
cat <<EOF > /etc/environment
TABLESCOPE_REPO_ROOT=/srv/repository
TABLESCOPE_SAMBA_IP=10.250.20.20
TABLESCOPE_SAMBA_NET=10.250.20.0/24
EOF
