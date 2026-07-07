"""Phase 10 - AWS cost dashboard.

Pulls spend from the Cost Explorer API (current + projected month, by service,
daily, monthly trend, top drivers) and renders a markdown dashboard. Also
publishes a CloudWatch dashboard so the same signals are visible in-console.
"""
from __future__ import annotations

import datetime
import json
from typing import Any

from botocore.exceptions import ClientError

from . import common as C

DASHBOARD_NAME = "Tablescope-Cost-Governance"


def _month_bounds(today: datetime.date) -> tuple[str, str]:
    first = today.replace(day=1)
    if today.month == 12:
        nxt = today.replace(year=today.year + 1, month=1, day=1)
    else:
        nxt = today.replace(month=today.month + 1, day=1)
    return first.isoformat(), nxt.isoformat()


def collect(ce=None) -> dict[str, Any]:
    ce = ce or C.client("ce", "us-east-1")
    try:
        return _collect_ce(ce)
    except ClientError as e:
        if e.response["Error"]["Code"] not in ("AccessDeniedException",
                                               "AccessDenied"):
            raise
        return _collect_degraded(str(e))


def _collect_degraded(reason: str) -> dict[str, Any]:
    """Cost Explorer unavailable: fall back to inventory-based estimates."""
    from . import inventory as INV
    inv = INV.run(C.DEFAULT_REGIONS)
    est = inv["costEstimateMonthly"]
    services = [{"service": k, "amount": v}
                for k, v in sorted(est["byCategory"].items(), key=lambda kv: -kv[1])]
    return {
        "generatedAt": C.now_iso(),
        "source": "inventory-estimate (Cost Explorer access denied)",
        "note": reason,
        "monthToDate": est["total"],
        "projectedMonth": est["total"],
        "byService": services,
        "topDrivers": services[:10],
        "daily": [],
        "monthlyTrend": [],
    }


def _collect_ce(ce) -> dict[str, Any]:
    today = datetime.date.today()
    m_start, m_end = _month_bounds(today)
    tomorrow = (today + datetime.timedelta(days=1)).isoformat()

    by_service = ce.get_cost_and_usage(
        TimePeriod={"Start": m_start, "End": tomorrow},
        Granularity="MONTHLY", Metrics=["UnblendedCost"],
        GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}])
    services = []
    for grp in by_service["ResultsByTime"][0]["Groups"]:
        amt = float(grp["Metrics"]["UnblendedCost"]["Amount"])
        if amt > 0:
            services.append({"service": grp["Keys"][0], "amount": round(amt, 2)})
    services.sort(key=lambda s: -s["amount"])
    month_total = round(sum(s["amount"] for s in services), 2)

    forecast = None
    try:
        fc = ce.get_cost_forecast(
            TimePeriod={"Start": tomorrow, "End": m_end},
            Metric="UNBLENDED_COST", Granularity="MONTHLY")
        forecast = round(month_total + float(fc["Total"]["Amount"]), 2)
    except ClientError:
        forecast = month_total  # too early in month to forecast

    daily = []
    d_start = (today - datetime.timedelta(days=30)).isoformat()
    dd = ce.get_cost_and_usage(
        TimePeriod={"Start": d_start, "End": tomorrow},
        Granularity="DAILY", Metrics=["UnblendedCost"])
    for r in dd["ResultsByTime"]:
        daily.append({"date": r["TimePeriod"]["Start"],
                      "amount": round(float(r["Total"]["UnblendedCost"]["Amount"]), 2)})

    trend = []
    t_start = (today.replace(day=1) - datetime.timedelta(days=175)).replace(day=1).isoformat()
    tt = ce.get_cost_and_usage(
        TimePeriod={"Start": t_start, "End": m_start},
        Granularity="MONTHLY", Metrics=["UnblendedCost"])
    for r in tt["ResultsByTime"]:
        trend.append({"month": r["TimePeriod"]["Start"][:7],
                      "amount": round(float(r["Total"]["UnblendedCost"]["Amount"]), 2)})

    return {
        "generatedAt": C.now_iso(),
        "monthToDate": month_total,
        "projectedMonth": forecast,
        "byService": services,
        "topDrivers": services[:10],
        "daily": daily,
        "monthlyTrend": trend,
    }


def markdown(data: dict[str, Any]) -> str:
    out = ["# AWS Cost Dashboard", "",
           f"- **Generated:** {data['generatedAt']}",
           f"- **Month-to-date spend:** ${data['monthToDate']:,.2f}",
           f"- **Projected month-end:** ${data['projectedMonth']:,.2f}", "",
           "## Top cost drivers (month-to-date)", "",
           "| # | Service | MTD (USD) |", "|---|---|---|"]
    for n, s in enumerate(data["topDrivers"], 1):
        out.append(f"| {n} | {s['service']} | ${s['amount']:,.2f} |")
    out += ["", "## Monthly trend", "", "| Month | Spend (USD) |", "|---|---|"]
    for m in data["monthlyTrend"]:
        out.append(f"| {m['month']} | ${m['amount']:,.2f} |")
    out += ["", "## Daily spend (last 30 days)", "", "| Date | Spend (USD) |", "|---|---|"]
    for d in data["daily"]:
        out.append(f"| {d['date']} | ${d['amount']:,.2f} |")
    out.append("")
    return "\n".join(out)


def put_cloudwatch_dashboard(region: str, gpu_instance_ids: list[str],
                             dry_run: bool = True) -> dict[str, Any]:
    widgets = [
        {"type": "metric", "x": 0, "y": 0, "width": 12, "height": 6,
         "properties": {"title": "Estimated Charges (USD)", "region": "us-east-1",
                        "metrics": [["AWS/Billing", "EstimatedCharges", "Currency", "USD"]],
                        "period": 21600, "stat": "Maximum", "view": "timeSeries"}},
    ]
    y = 6
    for iid in gpu_instance_ids:
        widgets.append({"type": "metric", "x": 0, "y": y, "width": 12, "height": 6,
                        "properties": {"title": f"GPU CPU % - {iid}", "region": region,
                                       "metrics": [["AWS/EC2", "CPUUtilization", "InstanceId", iid]],
                                       "period": 300, "stat": "Average", "view": "timeSeries"}})
        widgets.append({"type": "metric", "x": 12, "y": y, "width": 12, "height": 6,
                        "properties": {"title": f"GPU Off-Schedule - {iid}", "region": region,
                                       "metrics": [["Tablescope/Cost", "GPURunningOffSchedule", "InstanceId", iid]],
                                       "period": 900, "stat": "Maximum", "view": "timeSeries"}})
        y += 6
    body = {"widgets": widgets}
    if dry_run:
        return {"action": "dry-run", "dashboard": DASHBOARD_NAME, "widgets": len(widgets)}
    cw = C.client("cloudwatch", region)
    cw.put_dashboard(DashboardName=DASHBOARD_NAME, DashboardBody=json.dumps(body))
    return {"action": "created", "dashboard": DASHBOARD_NAME, "widgets": len(widgets)}
