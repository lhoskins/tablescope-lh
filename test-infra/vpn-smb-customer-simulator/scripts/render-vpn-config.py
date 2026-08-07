#!/usr/bin/env python3
"""Render strongSwan config from an AWS Site-to-Site VPN connection.

Supports two output formats:
  * ``ipsec``  – classic starter/stroke files (``/etc/ipsec.conf`` and
    ``/etc/ipsec.secrets``). This is the format used by the live E2E simulator
    with the ``alpine:3.18`` + ``apk add strongswan`` container.
  * ``swanctl`` – the modern vici/swanctl file written to ``/etc/swanctl``.

Pre-shared keys are written into files, never logged.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import boto3


def _get_tunnel_options(vpn_id: str, region: str) -> list[dict]:
    client = boto3.client("ec2", region_name=region)
    response = client.describe_vpn_connections(VpnConnectionIds=[vpn_id])
    connections = response.get("VpnConnections", [])
    if not connections:
        raise SystemExit(f"VPN connection {vpn_id} not found")
    return connections[0].get("Options", {}).get("TunnelOptions", [])


def _render_ipsec(
    tunnels: list[dict],
    customer_ip: str,
    customer_lan: str,
    remote_cidrs: list[str],
) -> tuple[str, str]:
    """Return (ipsec.conf, ipsec.secrets) text."""
    if len(tunnels) < 2:
        raise SystemExit("AWS VPN connection must have two tunnel options")

    config_lines = [
        "config setup",
        '    charondebug="ike 2, knl 2, cfg 2"',
        "",
    ]
    secret_lines: list[str] = []
    right_subnets = ",".join(remote_cidrs)

    for idx, tunnel in enumerate(tunnels[:2], start=1):
        aws_ip = tunnel["OutsideIpAddress"]
        psk = tunnel["PreSharedKey"]

        config_lines.append(f"conn aws-tunnel{idx}")
        config_lines.append("    type=tunnel")
        config_lines.append("    auto=start")
        config_lines.append("    keyexchange=ikev1")
        config_lines.append("    authby=secret")
        config_lines.append("    left=%defaultroute")
        config_lines.append(f"    leftid={customer_ip}")
        config_lines.append(f"    right={aws_ip}")
        config_lines.append(f"    rightid={aws_ip}")
        config_lines.append(f"    leftsubnet={customer_lan}")
        config_lines.append(f"    rightsubnet={right_subnets}")
        config_lines.append("    ike=aes256-sha256-modp2048")
        config_lines.append("    esp=aes256-sha256-modp2048")
        config_lines.append("    ikelifetime=28800s")
        config_lines.append("    lifetime=3600s")
        config_lines.append("    dpddelay=10")
        config_lines.append("    dpdtimeout=30")
        config_lines.append("    dpdaction=restart")
        config_lines.append("    keyingtries=%forever")
        config_lines.append("    closeaction=restart")
        config_lines.append("    phase2=esp")
        config_lines.append("    pfs=yes")
        config_lines.append(f"    reqid={idx}")
        config_lines.append("")

        secret_lines.append(f"{customer_ip} {aws_ip} : PSK \"{psk}\"")

    return "\n".join(config_lines) + "\n", "\n".join(secret_lines) + "\n"


def _render_swanctl(
    tunnels: list[dict],
    customer_ip: str,
    customer_lan: str,
    remote_cidrs: list[str],
) -> str:
    """Return a swanctl.conf text."""
    if len(tunnels) < 2:
        raise SystemExit("AWS VPN connection must have two tunnel options")

    config_lines = ["connections {"]
    secret_lines = ["secrets {"]

    for idx, tunnel in enumerate(tunnels[:2], start=1):
        aws_ip = tunnel["OutsideIpAddress"]
        psk = tunnel["PreSharedKey"]

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
    parser.add_argument(
        "--remote-cidrs",
        default=os.environ.get("REMOTE_CIDRS", ""),
        help="Comma-separated CIDRs to expose to the tunnel",
    )
    parser.add_argument("--format", choices=["ipsec", "swanctl"], default="ipsec")
    parser.add_argument("--output-dir", default="/etc", type=Path)
    args = parser.parse_args()

    if not args.customer_gateway_ip:
        raise SystemExit("CUSTOMER_GATEWAY_IP or --customer-gateway-ip is required")

    remote_cidrs = [c for c in args.remote_cidrs.split(",") if c] or ["0.0.0.0/0"]

    tunnels = _get_tunnel_options(args.vpn_connection_id, args.region)

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.format == "ipsec":
        ipsec_conf, ipsec_secrets = _render_ipsec(
            tunnels,
            customer_ip=args.customer_gateway_ip,
            customer_lan=args.customer_lan_cidr,
            remote_cidrs=remote_cidrs,
        )
        conf_path = output_dir / "ipsec.conf"
        secrets_path = output_dir / "ipsec.secrets"
        conf_path.write_text(ipsec_conf)
        secrets_path.write_text(ipsec_secrets)
        conf_path.chmod(0o600)
        secrets_path.chmod(0o600)
        print(f"Wrote {conf_path}")
        print(f"Wrote {secrets_path}")
    else:
        swanctl_path = output_dir / "swanctl.conf"
        swanctl_path.write_text(
            _render_swanctl(
                tunnels,
                customer_ip=args.customer_gateway_ip,
                customer_lan=args.customer_lan_cidr,
                remote_cidrs=remote_cidrs,
            )
        )
        swanctl_path.chmod(0o600)
        print(f"Wrote {swanctl_path}")

    # Write a sanitized summary (no PSKs) for the evidence bundle.
    summary = {
        "vpn_connection_id": args.vpn_connection_id,
        "format": args.format,
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
    summary_path = output_dir / "vpn-config-summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))
    summary_path.chmod(0o644)
    print(f"Wrote {summary_path}")


if __name__ == "__main__":
    main()
