"""Scheduled start/stop for cost-controlled EC2 instances.

Invoked by EventBridge Scheduler with a payload of {"action": "start"|"stop"}.
Only ever touches instances tagged AutoStop=True, so it can never stop a
production host that has opted out. Region defaults to the Lambda's own region
but can be overridden with TARGET_REGION.
"""
import os

import boto3


def _target_ids(ec2, states):
    resp = ec2.describe_instances(Filters=[
        {"Name": "tag:AutoStop", "Values": ["True", "true"]},
        {"Name": "instance-state-name", "Values": states},
    ])
    return [i["InstanceId"] for r in resp["Reservations"] for i in r["Instances"]]


def handler(event, context):
    event = event or {}
    action = str(event.get("action", "stop")).lower()
    region = os.environ.get("TARGET_REGION") or context.invoked_function_arn.split(":")[3]
    ec2 = boto3.client("ec2", region_name=region)

    if action == "start":
        ids = _target_ids(ec2, ["stopped"])
        if ids:
            ec2.start_instances(InstanceIds=ids)
    else:
        action = "stop"
        ids = _target_ids(ec2, ["running", "pending"])
        if ids:
            ec2.stop_instances(InstanceIds=ids)

    return {"action": action, "region": region, "instances": ids,
            "message": "no AutoStop targets" if not ids else "ok"}
