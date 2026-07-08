"""Phase 4 - EC2 cost governance: Lambda + EventBridge Scheduler deploy.

Deploys three Lambda functions (scheduled start/stop, idle watchdog, manual
wake) and the EventBridge schedules that drive them. Schedules are created
DISABLED by default so provisioning never powers off a live instance without
an explicit `enable`. Idempotent create-or-update throughout.
"""
from __future__ import annotations

import io
import json
import time
import zipfile
from pathlib import Path
from typing import Any

from botocore.exceptions import ClientError

from . import common as C

LAMBDA_DIR = Path(__file__).resolve().parent.parent / "lambda"
ROLE_NAME = "tablescope-cost-lambda-role"
SCHED_ROLE_NAME = "tablescope-cost-scheduler-role"
SCHEDULE_GROUP = "tablescope-cost-governance"
TZ = "America/Los_Angeles"

FUNCTIONS = {
    "tablescope-scheduled-stopstart": "scheduled_stopstart.handler",
    "tablescope-idle-shutdown": "idle_shutdown.handler",
    "tablescope-manual-wake": "manual_wake.handler",
}

LAMBDA_POLICY = {
    "Version": "2012-10-17",
    "Statement": [
        {"Effect": "Allow",
         "Action": ["ec2:DescribeInstances", "ec2:DescribeInstanceStatus",
                    "ec2:StartInstances", "ec2:StopInstances",
                    "cloudwatch:GetMetricStatistics", "cloudwatch:GetMetricData",
                    "cloudwatch:PutMetricData",
                    "logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
         "Resource": "*"},
    ],
}


def _zip(src_name: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("lambda_function.py", (LAMBDA_DIR / src_name).read_text())
    return buf.getvalue()


def _ensure_lambda_role(iam) -> str:
    trust = {"Version": "2012-10-17", "Statement": [{
        "Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"},
        "Action": "sts:AssumeRole"}]}
    try:
        arn = iam.create_role(
            RoleName=ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(trust),
            Description="Tablescope cost-governance Lambda execution role",
        )["Role"]["Arn"]
        time.sleep(10)  # allow role to propagate
    except ClientError as e:
        if e.response["Error"]["Code"] != "EntityAlreadyExists":
            raise
        arn = iam.get_role(RoleName=ROLE_NAME)["Role"]["Arn"]
    iam.put_role_policy(RoleName=ROLE_NAME, PolicyName="cost-lambda-inline",
                        PolicyDocument=json.dumps(LAMBDA_POLICY))
    return arn


def _ensure_scheduler_role(iam, account: str, region: str) -> str:
    trust = {"Version": "2012-10-17", "Statement": [{
        "Effect": "Allow", "Principal": {"Service": "scheduler.amazonaws.com"},
        "Action": "sts:AssumeRole"}]}
    try:
        arn = iam.create_role(
            RoleName=SCHED_ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(trust),
            Description="Tablescope cost-governance EventBridge Scheduler role",
        )["Role"]["Arn"]
        time.sleep(10)
    except ClientError as e:
        if e.response["Error"]["Code"] != "EntityAlreadyExists":
            raise
        arn = iam.get_role(RoleName=SCHED_ROLE_NAME)["Role"]["Arn"]
    policy = {"Version": "2012-10-17", "Statement": [{
        "Effect": "Allow", "Action": "lambda:InvokeFunction",
        "Resource": f"arn:aws:lambda:{region}:{account}:function:tablescope-*"}]}
    iam.put_role_policy(RoleName=SCHED_ROLE_NAME, PolicyName="invoke-cost-lambdas",
                        PolicyDocument=json.dumps(policy))
    return arn


def _deploy_function(lam, name: str, handler: str, role_arn: str,
                     region: str) -> str:
    src = handler.split(".")[0] + ".py"
    code = _zip(src)
    env = {"Variables": {"TARGET_REGION": region}}
    try:
        arn = lam.create_function(
            FunctionName=name, Runtime="python3.12", Role=role_arn,
            Handler="lambda_function.handler", Code={"ZipFile": code},
            Timeout=300, MemorySize=128, Environment=env,
            Description="Tablescope cost governance",
        )["FunctionArn"]
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceConflictException":
            raise
        lam.update_function_code(FunctionName=name, ZipFile=code)
        lam.get_waiter("function_updated").wait(FunctionName=name)
        lam.update_function_configuration(
            FunctionName=name, Timeout=300, Environment=env)
        arn = lam.get_function(FunctionName=name)["Configuration"]["FunctionArn"]
    return arn


def _ensure_group(sched) -> None:
    try:
        sched.create_schedule_group(Name=SCHEDULE_GROUP)
    except ClientError as e:
        if e.response["Error"]["Code"] != "ConflictException":
            raise


def _put_schedule(sched, name: str, cron: str, target_arn: str,
                  role_arn: str, payload: dict, enabled: bool) -> None:
    kwargs = dict(
        Name=name, GroupName=SCHEDULE_GROUP,
        ScheduleExpression=cron, ScheduleExpressionTimezone=TZ,
        FlexibleTimeWindow={"Mode": "OFF"},
        State="ENABLED" if enabled else "DISABLED",
        Target={"Arn": target_arn, "RoleArn": role_arn,
                "Input": json.dumps(payload)},
    )
    try:
        sched.create_schedule(**kwargs)
    except ClientError as e:
        if e.response["Error"]["Code"] != "ConflictException":
            raise
        sched.update_schedule(**kwargs)


def deploy(region: str, enabled: bool = False, dry_run: bool = True) -> dict[str, Any]:
    account = C.client("sts").get_caller_identity()["Account"]
    plan = {
        "region": region,
        "functions": list(FUNCTIONS),
        "schedules": {
            "tablescope-gpu-start": "cron(0 7 ? * MON-FRI *)  # 07:00 PT weekdays",
            "tablescope-gpu-stop": "cron(0 20 ? * MON-FRI *)  # 20:00 PT weekdays",
            "tablescope-gpu-nightly-stop": "cron(0 21 * * ? *)  # 21:00 PT daily hard stop",
            "tablescope-idle-shutdown": "rate(15 minutes)",
        },
        "schedulesEnabled": enabled,
        "action": "dry-run",
    }
    if dry_run:
        return plan

    iam = C.client("iam")
    lam = C.client("lambda", region)
    sched = C.client("scheduler", region)

    role_arn = _ensure_lambda_role(iam)
    sched_role_arn = _ensure_scheduler_role(iam, account, region)
    fn_arns = {name: _deploy_function(lam, name, handler, role_arn, region)
               for name, handler in FUNCTIONS.items()}
    _ensure_group(sched)

    stopstart = fn_arns["tablescope-scheduled-stopstart"]
    idle = fn_arns["tablescope-idle-shutdown"]
    _put_schedule(sched, "tablescope-gpu-start", "cron(0 7 ? * MON-FRI *)",
                  stopstart, sched_role_arn, {"action": "start"}, enabled)
    _put_schedule(sched, "tablescope-gpu-stop", "cron(0 20 ? * MON-FRI *)",
                  stopstart, sched_role_arn, {"action": "stop"}, enabled)
    _put_schedule(sched, "tablescope-gpu-nightly-stop", "cron(0 21 * * ? *)",
                  stopstart, sched_role_arn, {"action": "stop"}, enabled)
    _put_schedule(sched, "tablescope-idle-shutdown", "rate(15 minutes)",
                  idle, sched_role_arn, {}, enabled)

    plan["action"] = "deployed"
    plan["functionArns"] = fn_arns
    return plan


def set_enabled(region: str, enabled: bool) -> dict[str, Any]:
    """Flip all governance schedules on/off (the confirmation gate)."""
    sched = C.client("scheduler", region)
    changed = []
    for name in ["tablescope-gpu-start", "tablescope-gpu-stop",
                 "tablescope-gpu-nightly-stop", "tablescope-idle-shutdown"]:
        cur = sched.get_schedule(GroupName=SCHEDULE_GROUP, Name=name)
        sched.update_schedule(
            Name=name, GroupName=SCHEDULE_GROUP,
            ScheduleExpression=cur["ScheduleExpression"],
            ScheduleExpressionTimezone=cur.get("ScheduleExpressionTimezone", TZ),
            FlexibleTimeWindow=cur["FlexibleTimeWindow"],
            State="ENABLED" if enabled else "DISABLED",
            Target=cur["Target"])
        changed.append(name)
    return {"region": region, "enabled": enabled, "schedules": changed}
