#!/usr/bin/env python3
"""Render strongSwan swanctl config from an AWS Site-to-Site VPN connection.

Reads the VPN connection, extracts tunnel options, and writes a swanctl
configuration that establishes two route-based IKEv2/IPsec tunnels to AWS.
Pre-shared keys are written into files, never logged.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import boto3


def _get_tunnel_options(vpn_id: str, region: str) -> list[dict]:
    client = boto3.client("ec2", region_name=region)
    response = client.describe_vpn_connections(VpnConnectionIds=[vpn_id])
    connections = response.get("VpnConnections", [])
    if not connections:
        raise SystemExit(f"VPN connection {vpn_id} not found")
    return connections[0].get("Options", {}).get("TunnelOptions", [])


def _render_swanctl(tunnels: list[dict], customer_ip: str, customer_lan: str, remote_cidrs: list[str]) -> str:
    if len(tunnels) < 2:
        raise SystemExit("AWS VPN connection must have two tunnel options")

    config_lines = ["connections {"]
    secret_lines = ["secrets {"]

    for idx, tunnel in enumerate(tunnels[:2], start=1):
        aws_ip = tunnel["OutsideIpAddress"]
        psk = tunnel["PreSharedKey"]
        inside_cidr = tunnel.get("TunnelInsideCidr", "169.254.x.x/30")
        # Use the AWS endpoint IP as the remote id.

        config_lines.append(f"  aws-tunnel-{idx} {{")
        config_lines.append(f"    local_addrs = {customer_ip}")
        config_lines.append(f"    remote_addrs = {aws_ip}")
        config_lines.append("    version = 2")
        config_lines.append("    proposals = aes256-sha256-modp2048, aes256-sha256-modp1024, default")
        config_lines.append("    rekey_time = 1h")
        config_lines.append("    dpd_delay = 10")
        config_lines.append("    dpd_timeout = 30")
        config_lines.append("    dpd_action = restart")
        config_lines.append("    local-1 {")
        config_lines.append("      auth = psk")
        config_lines.append(f"      id = {customer_ip}")
        config_lines.append("    }")
        config_lines.append("    remote-1 {")
        config_lines.append("      auth = psk")
        config_lines.append(f"      id = {aws_ip}")
        config_lines.append("    }")
        config_lines.append("    children {")
        config_lines.append("      net-net {")
        config_lines.append(f"        local_ts = {customer_lan}")
        config_lines.append(f"        remote_ts = {','.join(remote_cidrs)}")
        config_lines.append("        esp_proposals = aes256-sha256")
        config_lines.append("        start_action = start")
        config_lines.append("        dpd_action = restart")
        config_lines.append("      }")
        config_lines.append("    }")
        config_lines.append("  }")

        secret_lines.append(f"  ike-aws-tunnel-{idx} {{")
        secret_lines.append("    secret-1 {")
        secret_lines.append("      type = IKE")
        secret_lines.append(f"      id-1 = \"{customer_ip}\"")
        secret_lines.append(f"      id-2 = \"{aws_ip}\"")
        # The PSK value is sensitive; this file is written with 0600.
        secret_lines.append(f"      data = \"{psk}\"")
        secret_lines.append("    }")
        secret_lines.append("  }")

    config_lines.append("}")
    secret_lines.append("}")

    return "\n".join(config_lines + ["", ""] + secret_lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vpn-connection-id", required=True)
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", "us-west-1"))
    parser.add_argument("--customer-gateway-ip", default=os.environ.get("CUSTOMER_GATEWAY_IP"))
    parser.add_argument("--customer-lan-cidr", default=os.environ.get("CUSTOMER_LAN_CIDR", "10.250.10.0/24"))
    parser.add_argument("--remote-cidrs", default=os.environ.get("REMOTE_CIDRS", ""), help="Comma-separated CIDRs to expose to the tunnel")
    parser.add_argument("--output-dir", default="/etc/swanctl", type=Path)
    args = parser.parse_args()

    if not args.customer_gateway_ip:
        raise SystemExit("CUSTOMER_GATEWAY_IP or --customer-gateway-ip is required")

    remote_cidrs = [c for c in args.remote_cidrs.split(",") if c] or ["0.0.0.0/0"]

    tunnels = _get_tunnel_options(args.vpn_connection_id, args.region)
    rendered = _render_swanctl(
        tunnels,
        customer_ip=args.customer_gateway_ip,
        customer_lan=args.customer_lan_cidr,
        remote_cidrs=remote_cidrs,
    )

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    config_path = output_dir / "swanctl.conf"
    config_path.write_text(rendered)
    # strongSwan reads the config as root; restrict read/write to owner.
    config_path.chmod(0o600)

    # Write a sanitized summary (no PSKs) for the evidence bundle.
    summary = {
        "vpn_connection_id": args.vpn_connection_id,
        "tunnels": [
            {
                "tunnel_index": i + 1,
                "outside_ip": t["OutsideIpAddress"],
                "inside_cidr": t.get("TunnelInsideCidr"),
            }
            for i, t in enumerate(tunnels[:2])
        ],
        "customer_gateway_ip": args.customer_gateway_ip,
        "customer_lan_cidr": args.customer_lan_cidr,
        "remote_cidrs": remote_cidrs,
    }
    summary_path = output_dir / "swanctl-summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))
    summary_path.chmod(0o644)

    print(f"Wrote strongSwan config to {config_path}")
    print(f"Wrote sanitized summary to {summary_path}")


if __name__ == "__main__":
    main()
