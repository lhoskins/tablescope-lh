"""Phase 11 - monthly cost optimization report + before/after governance report."""
from __future__ import annotations

import datetime
from typing import Any

from . import common as C
from . import inventory as INV

# Weekday 07:00-20:00 PT => 13h x 5 = 65 running hours/week vs 168.
SCHEDULED_FRACTION = round(65.0 / 168.0, 4)  # ~0.387


def build_recommendations(inv: dict[str, Any]) -> list[dict[str, Any]]:
    recs: list[dict[str, Any]] = []
    s = INV.summarize(inv)

    for i in s["gpuRunning"]:
        full = i["MonthlyEstimateRunning"] or 0.0
        scheduled = round(full * SCHEDULED_FRACTION, 2)
        saving = round(full - scheduled, 2)
        recs.append({
            "resource": i["InstanceId"], "region": i["Region"],
            "type": i["InstanceType"],
            "recommendation": "Stop idle / schedule GPU (weekday 07:00-20:00 PT + idle shutdown)",
            "estMonthlySavings": saving, "estAnnualSavings": round(saving * 12, 2),
            "confidence": "High", "risk": "Low (AutoStop tag + manual wake available)"})

    for v in s["unattachedEbs"]:
        recs.append({
            "resource": v["VolumeId"], "region": v["Region"],
            "type": f"EBS {v['VolumeType']} {v['SizeGiB']}GiB",
            "recommendation": "Snapshot then delete unattached volume",
            "estMonthlySavings": v["MonthlyEstimate"],
            "estAnnualSavings": round(v["MonthlyEstimate"] * 12, 2),
            "confidence": "High", "risk": "Low (unattached); archive snapshot first"})

    for e in s["unattachedElasticIps"]:
        recs.append({
            "resource": e["AllocationId"] or e["PublicIp"], "region": e["Region"],
            "type": "Elastic IP (unattached)",
            "recommendation": "Release unattached Elastic IP",
            "estMonthlySavings": e["MonthlyEstimate"],
            "estAnnualSavings": round(e["MonthlyEstimate"] * 12, 2),
            "confidence": "High", "risk": "Low; re-allocatable if needed"})

    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=90)
    for region, blk in inv["regions"].items():
        for snap in blk["other"]["Snapshots"]:
            st = snap.get("StartTime")
            if isinstance(st, str):
                try:
                    st = datetime.datetime.fromisoformat(st)
                except ValueError:
                    st = None
            if st and st < cutoff:
                recs.append({
                    "resource": snap["SnapshotId"], "region": region,
                    "type": "EBS snapshot (>90 days)",
                    "recommendation": "Review/delete old snapshot",
                    "estMonthlySavings": snap["MonthlyEstimate"],
                    "estAnnualSavings": round(snap["MonthlyEstimate"] * 12, 2),
                    "confidence": "Medium", "risk": "Medium; verify no restore dependency"})

    for n in s["natGateways"]:
        recs.append({
            "resource": n["NatGatewayId"], "region": n["Region"],
            "type": "NAT Gateway",
            "recommendation": "Confirm workloads still require NAT; delete if not",
            "estMonthlySavings": n["MonthlyEstimate"],
            "estAnnualSavings": round(n["MonthlyEstimate"] * 12, 2),
            "confidence": "Low", "risk": "High if private subnets need egress"})

    # Steady-state right-sizing / commitment for always-on non-GPU prod.
    for region, blk in inv["regions"].items():
        for i in blk["ec2"]:
            if i["State"] == "running" and not i["IsGpu"] and i["MonthlyEstimateRunning"]:
                saving = round(i["MonthlyEstimateRunning"] * 0.30, 2)
                recs.append({
                    "resource": i["InstanceId"], "region": region,
                    "type": i["InstanceType"],
                    "recommendation": "Consider 1-yr Compute Savings Plan for always-on host",
                    "estMonthlySavings": saving, "estAnnualSavings": round(saving * 12, 2),
                    "confidence": "Medium", "risk": "Low; commitment reduces flexibility"})
    recs.sort(key=lambda r: -r["estMonthlySavings"])
    return recs


def recommendations_markdown(inv: dict[str, Any], recs: list[dict[str, Any]]) -> str:
    total_m = round(sum(r["estMonthlySavings"] for r in recs), 2)
    out = ["# Monthly Cost Optimization Report", "",
           f"- **Generated:** {C.now_iso()}",
           f"- **Account:** `{inv['account']}`",
           f"- **Identified monthly savings:** ${total_m:,.2f}",
           f"- **Identified annual savings:** ${round(total_m*12,2):,.2f}", "",
           "| Resource | Region | Type | Recommendation | $/mo | $/yr | Confidence | Risk |",
           "|---|---|---|---|---|---|---|---|"]
    for r in recs:
        out.append(f"| `{r['resource']}` | {r['region']} | {r['type']} | "
                   f"{r['recommendation']} | ${r['estMonthlySavings']:,.2f} | "
                   f"${r['estAnnualSavings']:,.2f} | {r['confidence']} | {r['risk']} |")
    out.append("")
    return "\n".join(out)


def _billed_history_section(billed: dict[str, Any] | None) -> list[str]:
    """Render real Cost Explorer history (the billed anomaly) when available."""
    if not billed or not billed.get("monthlyTrend"):
        return []
    trend = billed["monthlyTrend"]
    baseline_months = [m for m in trend[:-1]] or trend
    baseline = (round(sum(m["amount"] for m in baseline_months) / len(baseline_months), 2)
                if baseline_months else 0.0)
    peak = max(trend, key=lambda m: m["amount"])
    out = ["## Billed history (AWS Cost Explorer, actual)", "",
           "| Month | Actual spend (USD) |", "|---|---|"]
    for m in trend:
        flag = "  ← anomaly" if m["month"] == peak["month"] and peak["amount"] > baseline * 2 else ""
        out.append(f"| {m['month']} | ${m['amount']:,.2f}{flag} |")
    out += ["",
            f"- Typical monthly baseline (prior months): **${baseline:,.2f}/mo**",
            f"- Anomalous month **{peak['month']}**: **${peak['amount']:,.2f}** "
            f"(~{round(peak['amount'] / baseline, 1) if baseline else 0}x baseline)",
            f"- Month-to-date this month: **${billed.get('monthToDate', 0):,.2f}**, "
            f"projected **${billed.get('projectedMonth', 0):,.2f}** if left uncontrolled.", ""]
    return out


def before_after_markdown(inv: dict[str, Any], recs: list[dict[str, Any]],
                          billed: dict[str, Any] | None = None) -> str:
    s = INV.summarize(inv)
    gpu_full = round(sum((i["MonthlyEstimateRunning"] or 0) for i in s["gpuRunning"]), 2)
    gpu_after = round(gpu_full * SCHEDULED_FRACTION, 2)
    rows = [
        ("GPU running 24/7", "Scheduled (weekday 07:00-20:00 PT) + idle shutdown"),
        ("No EventBridge automation", "Automated start/stop + nightly hard-stop schedules"),
        ("No budget alerts", "AWS Budget $50/$100/$200/$300/$500 actual + forecast alerts"),
        ("No idle monitoring", "Idle-shutdown Lambda (CPU + request-aware)"),
        ("No resource inventory", "Full inventory across us-east-1/us-west-1/us-west-2"),
        ("No cost alarms", "CloudWatch alarms: off-schedule, >4h off-hours, idle, billing"),
        ("Untagged resources", "Standard cost tags applied (Environment/Owner/AutoStop/...)"),
        ("Reactive cost management", "Proactive governance + monthly optimization report"),
    ]
    out = ["# Before vs. After Cost Governance Report", "",
           f"- **Generated:** {C.now_iso()}",
           f"- **Account:** `{inv['account']}`", ""]
    out += _billed_history_section(billed)
    out += ["## Governance controls", "",
            "| Before | After |", "|---|---|"]
    for b, a in rows:
        out.append(f"| {b} | {a} |")
    out += ["", "## Quantified impact", "",
            f"- GPU spend before (24/7): **${gpu_full:,.2f}/mo**",
            f"- GPU spend after (scheduled ~38.7% uptime): **${gpu_after:,.2f}/mo**",
            f"- GPU monthly reduction: **${round(gpu_full-gpu_after,2):,.2f}** "
            f"(~{round((1-SCHEDULED_FRACTION)*100)}%)",
            f"- Total identified monthly savings (all recommendations): "
            f"**${round(sum(r['estMonthlySavings'] for r in recs),2):,.2f}**", "",
            "This artifact documents that corrective controls are permanently in "
            "place, supporting the request for a one-time courtesy billing "
            "adjustment for the unexpected June 2026 GPU charges.", ""]
    return "\n".join(out)
