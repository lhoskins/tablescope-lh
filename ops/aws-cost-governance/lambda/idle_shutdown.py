"""Idle-shutdown watchdog for cost-controlled EC2 instances.

Runs on a short EventBridge schedule (e.g. every 15 min). For each running
instance tagged AutoStop=True it checks:

  * average CPU over the last IDLE_MINUTES is below CPU_THRESHOLD, and
  * the app-published custom metric `Tablescope/AI ActiveRequests` (sum) is
    zero over the same window (treated as zero if the metric is absent).

Only when BOTH hold does it stop the instance. Anything tagged
IdleShutdown=Disabled is skipped. Conservative by construction: missing data
never triggers a shutdown.
"""
import datetime
import os

import boto3

try:
    from zoneinfo import ZoneInfo
    _PT = ZoneInfo("America/Los_Angeles")
except Exception:  # pragma: no cover - fallback if tz db missing
    _PT = datetime.timezone(datetime.timedelta(hours=-7))

CPU_THRESHOLD = float(os.environ.get("CPU_THRESHOLD", "5"))
IDLE_MINUTES = int(os.environ.get("IDLE_MINUTES", "60"))
REQUEST_NAMESPACE = os.environ.get("REQUEST_NAMESPACE", "Tablescope/AI")
REQUEST_METRIC = os.environ.get("REQUEST_METRIC", "ActiveRequests")
COST_NAMESPACE = "Tablescope/Cost"
# Approved on-hours: Mon-Fri 07:00-20:00 Pacific.
ON_START_HOUR = 7
ON_END_HOUR = 20


def _off_schedule_now() -> bool:
    now = datetime.datetime.now(_PT)
    if now.weekday() >= 5:  # Sat/Sun
        return True
    return not (ON_START_HOUR <= now.hour < ON_END_HOUR)


def _avg_cpu(cw, instance_id, start, end):
    r = cw.get_metric_statistics(
        Namespace="AWS/EC2", MetricName="CPUUtilization",
        Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
        StartTime=start, EndTime=end, Period=300, Statistics=["Average"])
    pts = r.get("Datapoints", [])
    if not pts:
        return None
    return sum(p["Average"] for p in pts) / len(pts)


def _sum_requests(cw, instance_id, start, end):
    r = cw.get_metric_statistics(
        Namespace=REQUEST_NAMESPACE, MetricName=REQUEST_METRIC,
        Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
        StartTime=start, EndTime=end, Period=300, Statistics=["Sum"])
    pts = r.get("Datapoints", [])
    return sum(p["Sum"] for p in pts) if pts else 0.0


def handler(event, context):
    region = os.environ.get("TARGET_REGION") or context.invoked_function_arn.split(":")[3]
    ec2 = boto3.client("ec2", region_name=region)
    cw = boto3.client("cloudwatch", region_name=region)
    end = datetime.datetime.utcnow()
    start = end - datetime.timedelta(minutes=IDLE_MINUTES)

    resp = ec2.describe_instances(Filters=[
        {"Name": "tag:AutoStop", "Values": ["True", "true"]},
        {"Name": "instance-state-name", "Values": ["running"]},
    ])
    off_schedule = _off_schedule_now()
    decisions = []
    to_stop = []
    metric_data = []
    for r in resp["Reservations"]:
        for inst in r["Instances"]:
            iid = inst["InstanceId"]
            tags = {t["Key"]: t["Value"] for t in inst.get("Tags", [])}
            # Publish an off-schedule signal so a CloudWatch alarm can fire
            # when a cost-controlled instance is up outside approved hours.
            metric_data.append({
                "MetricName": "GPURunningOffSchedule",
                "Dimensions": [{"Name": "InstanceId", "Value": iid}],
                "Value": 1.0 if off_schedule else 0.0,
                "Unit": "Count",
            })
            if tags.get("IdleShutdown") == "Disabled":
                decisions.append({"id": iid, "decision": "skip", "reason": "IdleShutdown=Disabled"})
                continue
            cpu = _avg_cpu(cw, iid, start, end)
            reqs = _sum_requests(cw, iid, start, end)
            # No CPU datapoints yet -> not enough evidence, never stop.
            if cpu is None:
                decisions.append({"id": iid, "decision": "keep", "reason": "no CPU data"})
                continue
            if cpu < CPU_THRESHOLD and reqs == 0:
                to_stop.append(iid)
                decisions.append({"id": iid, "decision": "stop",
                                  "cpu": round(cpu, 2), "requests": reqs})
            else:
                decisions.append({"id": iid, "decision": "keep",
                                  "cpu": round(cpu, 2), "requests": reqs})
    if metric_data:
        cw.put_metric_data(Namespace=COST_NAMESPACE, MetricData=metric_data)
    if to_stop:
        ec2.stop_instances(InstanceIds=to_stop)
    return {"region": region, "stopped": to_stop, "decisions": decisions,
            "offSchedule": off_schedule,
            "cpuThreshold": CPU_THRESHOLD, "idleMinutes": IDLE_MINUTES}
