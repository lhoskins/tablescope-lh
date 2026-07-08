"""Phase 9 - CloudWatch alarms + SNS notifications.

Creates an SNS topic (email subscription) and alarms for:
  * GPU running outside the approved schedule (any datapoint)
  * GPU running >4h continuously outside business hours
  * GPU idle (low CPU for 60 min)
  * Account estimated charges over a threshold (billing metric, us-east-1)

Alarms are notify-only (SNS -> email); they do not stop instances. The
idle_shutdown Lambda owns the actual stop action.
"""
from __future__ import annotations

from typing import Any

from botocore.exceptions import ClientError

from . import common as C

TOPIC_NAME = "tablescope-cost-alerts"
COST_NAMESPACE = "Tablescope/Cost"


def ensure_topic(region: str) -> str | None:
    """Create/subscribe the alert topic. Returns None if SNS is unavailable
    (e.g. the caller lacks SNS permissions); alarms are then created without
    notification actions but still evaluate state in-console."""
    try:
        sns = C.client("sns", region)
        arn = sns.create_topic(Name=TOPIC_NAME)["TopicArn"]
        existing = {s["Endpoint"] for s in
                    sns.list_subscriptions_by_topic(TopicArn=arn).get("Subscriptions", [])}
        if C.NOTIFY_EMAIL not in existing:
            sns.subscribe(TopicArn=arn, Protocol="email", Endpoint=C.NOTIFY_EMAIL)
        return arn
    except ClientError:
        return None


def _put(cw, topic_arn, **kw):
    kw.setdefault("ActionsEnabled", bool(topic_arn))
    if topic_arn:
        kw["AlarmActions"] = [topic_arn]
        kw["OKActions"] = [topic_arn]
    cw.put_metric_alarm(**kw)


def apply(region: str, gpu_instance_ids: list[str], dry_run: bool = True) -> dict[str, Any]:
    plan: dict[str, Any] = {
        "region": region,
        "topic": TOPIC_NAME,
        "gpuInstances": gpu_instance_ids,
        "alarms": [],
        "action": "dry-run",
    }
    alarm_names = []
    for iid in gpu_instance_ids:
        alarm_names += [
            f"tablescope-gpu-offschedule-{iid}",
            f"tablescope-gpu-offschedule-4h-{iid}",
            f"tablescope-gpu-idle-{iid}",
        ]
    alarm_names.append("tablescope-estimated-charges")
    plan["alarms"] = alarm_names
    if dry_run:
        return plan

    topic_arn = ensure_topic(region)
    plan["notificationsEnabled"] = bool(topic_arn)
    if not topic_arn:
        plan["notificationWarning"] = (
            "SNS unavailable (missing permissions); alarms created without "
            "notification actions. Attach an SNS topic to enable email alerts.")
    cw = C.client("cloudwatch", region)
    for iid in gpu_instance_ids:
        dim = [{"Name": "InstanceId", "Value": iid}]
        _put(cw, topic_arn,
             AlarmName=f"tablescope-gpu-offschedule-{iid}",
             AlarmDescription="GPU instance running outside approved schedule",
             Namespace=COST_NAMESPACE, MetricName="GPURunningOffSchedule",
             Dimensions=dim, Statistic="Maximum", Period=900,
             EvaluationPeriods=1, Threshold=1, ComparisonOperator="GreaterThanOrEqualToThreshold",
             TreatMissingData="notBreaching")
        _put(cw, topic_arn,
             AlarmName=f"tablescope-gpu-offschedule-4h-{iid}",
             AlarmDescription="GPU running >4h continuously outside business hours",
             Namespace=COST_NAMESPACE, MetricName="GPURunningOffSchedule",
             Dimensions=dim, Statistic="Minimum", Period=900,
             EvaluationPeriods=16, Threshold=1, ComparisonOperator="GreaterThanOrEqualToThreshold",
             TreatMissingData="notBreaching")
        _put(cw, topic_arn,
             AlarmName=f"tablescope-gpu-idle-{iid}",
             AlarmDescription="GPU idle: CPU < 5% for 60 minutes",
             Namespace="AWS/EC2", MetricName="CPUUtilization",
             Dimensions=dim, Statistic="Average", Period=300,
             EvaluationPeriods=12, Threshold=5, ComparisonOperator="LessThanThreshold",
             TreatMissingData="notBreaching")

    # Billing metric lives only in us-east-1.
    try:
        cwb = C.client("cloudwatch", "us-east-1")
        topic_use1 = ensure_topic("us-east-1")
        _put(cwb, topic_use1,
             AlarmName="tablescope-estimated-charges",
             AlarmDescription="Account estimated charges over $200 this month",
             Namespace="AWS/Billing", MetricName="EstimatedCharges",
             Dimensions=[{"Name": "Currency", "Value": "USD"}],
             Statistic="Maximum", Period=21600, EvaluationPeriods=1,
             Threshold=200, ComparisonOperator="GreaterThanThreshold",
             TreatMissingData="notBreaching")
    except ClientError as e:
        plan["billingAlarmWarning"] = str(e)

    plan["action"] = "created"
    plan["topicArn"] = topic_arn
    return plan
