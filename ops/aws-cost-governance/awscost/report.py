"""Render the inventory + cost data into markdown deliverables."""
from __future__ import annotations

from typing import Any

from . import inventory as INV


def _fmt_money(v: float | None) -> str:
    return f"${v:,.2f}" if v is not None else "n/a"


def inventory_markdown(inv: dict[str, Any]) -> str:
    s = INV.summarize(inv)
    out: list[str] = []
    out.append("# AWS Resource Inventory Report")
    out.append("")
    out.append(f"- **Account:** `{inv['account']}`")
    out.append(f"- **Generated:** {inv['generatedAt']}")
    out.append(f"- **Regions scanned:** {', '.join(inv['regionsScanned'])}")
    out.append(f"- **Estimated monthly cost (running state):** "
               f"{_fmt_money(inv['costEstimateMonthly']['total'])}")
    out.append("")
    out.append("## Estimated monthly cost by category")
    out.append("")
    out.append("| Category | Monthly (USD) |")
    out.append("|---|---|")
    for k, v in sorted(inv["costEstimateMonthly"]["byCategory"].items(),
                       key=lambda kv: -kv[1]):
        out.append(f"| {k} | {_fmt_money(v)} |")
    out.append(f"| **Total** | **{_fmt_money(inv['costEstimateMonthly']['total'])}** |")
    out.append("")

    out.append("## EC2 instances")
    out.append("")
    out.append("| Region | Instance | Name | Type | State | GPU | Class | $/mo (running) | Missing tags |")
    out.append("|---|---|---|---|---|---|---|---|---|")
    for region, blk in inv["regions"].items():
        for i in blk["ec2"]:
            out.append(
                f"| {i['Region']} | `{i['InstanceId']}` | {i['Name'] or '-'} | "
                f"{i['InstanceType']} | {i['State']} | {'yes' if i['IsGpu'] else 'no'} | "
                f"{i['Classification']} | {_fmt_money(i['MonthlyEstimateRunning'])} | "
                f"{len(i['MissingTags'])} |")
    out.append("")

    out.append("## Elastic IPs")
    out.append("")
    eips = [e for r in inv["regions"].values() for e in r["elasticIps"]]
    if eips:
        out.append("| Region | Public IP | Allocation | Associated | Unattached | $/mo |")
        out.append("|---|---|---|---|---|---|")
        for e in eips:
            out.append(f"| {e['Region']} | {e['PublicIp']} | `{e['AllocationId']}` | "
                       f"{e['AssociatedInstance'] or e['AssociatedEni'] or '-'} | "
                       f"{'YES' if e['Unattached'] else 'no'} | {_fmt_money(e['MonthlyEstimate'])} |")
    else:
        out.append("_No Elastic IPs allocated._")
    out.append("")

    out.append("## EBS volumes")
    out.append("")
    vols = [v for r in inv["regions"].values() for v in r["ebs"]]
    if vols:
        out.append("| Region | Volume | Size | Type | State | Attached | $/mo |")
        out.append("|---|---|---|---|---|---|---|")
        for v in vols:
            out.append(f"| {v['Region']} | `{v['VolumeId']}` | {v['SizeGiB']} GiB | "
                       f"{v['VolumeType']} | {v['State']} | "
                       f"{','.join(v['AttachedTo']) or 'UNATTACHED'} | {_fmt_money(v['MonthlyEstimate'])} |")
    else:
        out.append("_No EBS volumes._")
    out.append("")

    out.append("## NAT gateways")
    out.append("")
    if s["natGateways"]:
        out.append("| Region | NAT Gateway | VPC | Subnet | State | $/mo (base) |")
        out.append("|---|---|---|---|---|---|")
        for n in s["natGateways"]:
            out.append(f"| {n['Region']} | `{n['NatGatewayId']}` | {n['Vpc']} | "
                       f"{n['Subnet']} | {n['State']} | {_fmt_money(n['MonthlyEstimate'])} |")
    else:
        out.append("_No NAT gateways._")
    out.append("")

    out.append("## Other billable resources")
    out.append("")
    for region, blk in inv["regions"].items():
        o = blk["other"]
        counts = {k: len(v) for k, v in o.items()}
        if any(counts.values()):
            out.append(f"- **{region}:** " + ", ".join(
                f"{k}={c}" for k, c in counts.items() if c))
    g = inv["global"]
    out.append(f"- **global:** Route53 zones={len(g['Route53HostedZones'])}, "
               f"S3 buckets={len(g['S3Buckets'])}")
    out.append("")

    out.append("## Cleanup candidates (report-only, never auto-deleted)")
    out.append("")
    out.append(f"- Unattached Elastic IPs: **{len(s['unattachedElasticIps'])}**")
    out.append(f"- Unattached EBS volumes: **{len(s['unattachedEbs'])}**")
    out.append(f"- GPU instances running: **{len(s['gpuRunning'])}** "
               + (", ".join(f"`{i['InstanceId']}` ({i['InstanceType']})" for i in s["gpuRunning"]) or ""))
    out.append("")
    return "\n".join(out)
