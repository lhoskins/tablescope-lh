#!/usr/bin/env bash
# User data for the simulated customer gateway EC2 host.
#
# This host runs two containers:
#   * dperson/samba:4.18 on the host network, serving /srv/repository as the
#     "repository" share.
#   * alpine:3.18 with strongSwan installed at boot, also on the host network,
#     terminating the AWS Site-to-Site VPN.
#
# StrongSwan config (/etc/ipsec.conf and /etc/ipsec.secrets) is NOT rendered
# here because the AWS VPN connection and pre-shared keys are not known until
# after the TableScope tenant VPN is provisioned. Run
# scripts/render-vpn-config.py on this host (or copy the generated files) and
# then `systemctl restart tablescope-strongswan`.
set -euo pipefail

# Enable IP forwarding for the IPsec tunnel and for routing to the Samba bridge.
cat <<EOF > /etc/sysctl.d/99-tablescope-e2e.conf
net.ipv4.ip_forward=1
net.ipv4.conf.all.send_redirects=0
net.ipv4.conf.default.send_redirects=0
EOF
sysctl --system

# Ensure host keys exist so sshd can start. sshd itself is started by the
# tablescope-sshd unit below because Amazon Linux 2023 does not always start
# it reliably on first boot in this test harness.
/usr/bin/ssh-keygen -A || true

# Install Docker and the compose plugin.
yum update -y
yum install -y docker
systemctl enable --now docker
usermod -aG docker ec2-user

# Pull images that will be used by the compose stack.
docker pull alpine:3.18
docker pull dperson/samba:4.18

# Create the repository tree and a deterministic fixture.
mkdir -p /srv/repository
cat <<EOF > /srv/repository/sample.csv
id,name
1,test
EOF
chown -R ec2-user:ec2-user /srv/repository

cat <<EOF > /etc/environment
TABLESCOPE_REPO_ROOT=/srv/repository
TABLESCOPE_SAMBA_IP=10.250.10.229
TABLESCOPE_SAMBA_NET=10.250.20.0/24
EOF

# ---------------------------------------------------------------------------
# Container startup script. It is idempotent and will tolerate either the
# Samba or strongSwan config being missing, so the host can be rebooted safely
# before the VPN is configured.
# ---------------------------------------------------------------------------
cat <<'EOF' > /usr/local/bin/tablescope-start-containers.sh
#!/usr/bin/env bash
set -uo pipefail

systemctl start docker 2>/dev/null || true

# Samba always starts.
docker rm -f tablescope-vpn-smb-e2e-samba 2>/dev/null || true
docker run -d \
  --name tablescope-vpn-smb-e2e-samba \
  --network host \
  --restart always \
  -v /srv/repository:/share \
  dperson/samba:4.18 \
  -u "tablescope;Tablescope123!" \
  -s "repository;/share;yes;no;yes;tablescope;tablescope;tablescope" \
  -p

# StrongSwan only starts when the operator has rendered /etc/ipsec.conf.
if [[ -f /etc/ipsec.conf && -f /etc/ipsec.secrets ]]; then
  docker rm -f tablescope-vpn-smb-e2e-strongswan 2>/dev/null || true
  docker run -d \
    --name tablescope-vpn-smb-e2e-strongswan \
    --network host \
    --restart always \
    --cap-add NET_ADMIN \
    --device /dev/net/tun:/dev/net/tun \
    -v /etc/ipsec.conf:/etc/ipsec.conf:ro \
    -v /etc/ipsec.secrets:/etc/ipsec.secrets:ro \
    alpine:3.18 \
    sh -c 'apk add --no-cache strongswan && mkdir -p /var/run && ipsec start --nofork'
else
  echo "StrongSwan config not present; run render-vpn-config.py and restart tablescope-strongswan"
fi
EOF
chmod +x /usr/local/bin/tablescope-start-containers.sh

# ---------------------------------------------------------------------------
# systemd units.
# ---------------------------------------------------------------------------
cat <<'EOF' > /etc/systemd/system/tablescope-sshd.service
[Unit]
Description=TableScope VPN/SMB E2E sshd
After=network.target
Wants=network.target

[Service]
Type=simple
ExecStartPre=-/usr/bin/ssh-keygen -A
ExecStart=/usr/sbin/sshd -D
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

cat <<'EOF' > /etc/systemd/system/tablescope-samba.service
[Unit]
Description=TableScope VPN/SMB E2E Samba container
After=docker.service network.target
Wants=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/bin/tablescope-start-containers.sh

[Install]
WantedBy=multi-user.target
EOF

# Enable all units.
systemctl daemon-reload
systemctl enable --now tablescope-sshd.service
systemctl enable --now tablescope-samba.service
