"""Admin-only manual wake-up for the AI GPU instance.

Exposed via a Lambda Function URL (IAM-auth) or direct invoke. Starts the
target instance, waits for it to reach `running` + status-ok, then performs an
optional HTTP health check. Returns a state machine style status so a UI can
drive the Start -> Health Check -> AI Ready -> Allow Requests flow.

Payload: {"instance_id": "i-...", "health_url": "https://.../health"}
If instance_id is omitted, the single AutoStop=True + TablescopeRole=AI-GPU
instance is used.
"""
import os
import time
import urllib.request

import boto3

HEALTH_TIMEOUT = int(os.environ.get("HEALTH_TIMEOUT", "180"))


def _resolve_instance(ec2, explicit):
    if explicit:
        return explicit
    resp = ec2.describe_instances(Filters=[
        {"Name": "tag:AutoStop", "Values": ["True", "true"]},
        {"Name": "tag:TablescopeRole", "Values": ["AI-GPU"]},
    ])
    ids = [i["InstanceId"] for r in resp["Reservations"] for i in r["Instances"]]
    if len(ids) != 1:
        raise ValueError(f"expected exactly one AI-GPU instance, found {ids}")
    return ids[0]


def _health_ok(url):
    if not url:
        return None
    deadline = time.time() + HEALTH_TIMEOUT
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                if 200 <= r.status < 300:
                    return True
        except Exception:
            pass
        time.sleep(10)
    return False


def handler(event, context):
    event = event or {}
    region = os.environ.get("TARGET_REGION") or context.invoked_function_arn.split(":")[3]
    ec2 = boto3.client("ec2", region_name=region)
    iid = _resolve_instance(ec2, event.get("instance_id"))

    ec2.start_instances(InstanceIds=[iid])
    ec2.get_waiter("instance_running").wait(
        InstanceIds=[iid], WaiterConfig={"Delay": 10, "MaxAttempts": 18})
    ec2.get_waiter("instance_status_ok").wait(
        InstanceIds=[iid], WaiterConfig={"Delay": 15, "MaxAttempts": 20})

    health = _health_ok(event.get("health_url"))
    ai_ready = health is not False  # None (no check) or True both allow
    return {
        "instance_id": iid,
        "region": region,
        "state": "running",
        "health_check": {"skipped": health is None, "passed": bool(health)},
        "ai_ready": ai_ready,
        "allow_requests": ai_ready,
    }
