"""Phase 1 (discovery) + Phase 2 (classification) resource inventory.

Read-only: nothing here mutates the account. Produces a structured JSON
inventory plus a human-readable markdown report used by every later phase.
"""
from __future__ import annotations

from typing import Any

from botocore.exceptions import ClientError, EndpointConnectionError

from . import common as C


# --- Phase 2 classification ---------------------------------------------

def classify(tags: dict[str, str], name: str, state: str = "") -> str:
    """Best-effort classification. Unknown is never auto-deleted downstream."""
    env = (tags.get("Environment") or "").lower()
    # An explicit Environment tag is authoritative.
    if env:
        return {"production": "Production", "prod": "Production",
                "development": "Development", "dev": "Development",
                "temporary": "Temporary", "temp": "Temporary",
                "test": "Test", "qa": "Test", "staging": "Test"}.get(
            env, "Unknown")
    # No Environment tag: infer from the instance name only.
    hay = name.lower()
    if any(k in hay for k in ("prod", "tablescope", "ai-server", "app-host",
                              "pritunl", "vpn")):
        return "Production"
    if any(k in hay for k in ("dev", "sandbox")):
        return "Development"
    if any(k in hay for k in ("test", "temp", "scratch", "probe")):
        return "Test"
    return "Unknown"


def _safe(fn, default):
    try:
        return fn()
    except (ClientError, EndpointConnectionError):
        return default


# --- Per-region collectors ----------------------------------------------

def collect_ec2(region: str, money: C.Money) -> list[dict[str, Any]]:
    ec2 = C.client("ec2", region)
    rows: list[dict[str, Any]] = []
    for res in _safe(lambda: ec2.describe_instances()["Reservations"], []):
        for inst in res["Instances"]:
            tags = C.tags_to_dict(inst.get("Tags"))
            itype = inst["InstanceType"]
            state = inst["State"]["Name"]
            est = C.ec2_monthly(itype)
            # Only running instances accrue compute cost.
            if state == "running":
                money.add("EC2 compute", est)
            rows.append({
                "InstanceId": inst["InstanceId"],
                "Name": C.name_of(tags),
                "Region": region,
                "InstanceType": itype,
                "State": state,
                "LaunchTime": inst.get("LaunchTime"),
                "PublicIp": inst.get("PublicIpAddress", ""),
                "PrivateIp": inst.get("PrivateIpAddress", ""),
                "IamRole": (inst.get("IamInstanceProfile") or {}).get("Arn", ""),
                "SecurityGroups": [g["GroupName"] for g in inst.get("SecurityGroups", [])],
                "LaunchTemplate": (inst.get("LaunchTemplate") or {}).get("LaunchTemplateName", ""),
                "IsGpu": C.is_gpu_type(itype),
                "MonthlyEstimateRunning": est,
                "Classification": classify(tags, C.name_of(tags), state),
                "Tags": tags,
                "MissingTags": [k for k in C.REQUIRED_TAG_KEYS if k not in tags],
            })
    return rows


def collect_ebs(region: str, money: C.Money) -> list[dict[str, Any]]:
    ec2 = C.client("ec2", region)
    rows = []
    for v in _safe(lambda: ec2.describe_volumes()["Volumes"], []):
        tags = C.tags_to_dict(v.get("Tags"))
        cost = C.ebs_monthly(v["VolumeType"], v["Size"])
        money.add("EBS volumes", cost)
        attached = [a["InstanceId"] for a in v.get("Attachments", [])]
        rows.append({
            "VolumeId": v["VolumeId"],
            "Region": region,
            "SizeGiB": v["Size"],
            "VolumeType": v["VolumeType"],
            "State": v["State"],
            "AttachedTo": attached,
            "Unattached": v["State"] == "available",
            "CreateTime": v.get("CreateTime"),
            "MonthlyEstimate": cost,
            "Classification": classify(tags, C.name_of(tags)),
            "Tags": tags,
        })
    return rows


def collect_eip(region: str) -> list[dict[str, Any]]:
    ec2 = C.client("ec2", region)
    rows = []
    for a in _safe(lambda: ec2.describe_addresses()["Addresses"], []):
        tags = C.tags_to_dict(a.get("Tags"))
        unattached = "AssociationId" not in a
        rows.append({
            "AllocationId": a.get("AllocationId", ""),
            "PublicIp": a.get("PublicIp", ""),
            "Region": region,
            "AssociatedInstance": a.get("InstanceId", ""),
            "AssociatedEni": a.get("NetworkInterfaceId", ""),
            "Unattached": unattached,
            # Idle EIPs are the classic silent cost; attached public IPv4 is
            # also billed now but tied to a running workload.
            "MonthlyEstimate": C.EIP_MONTH,
            "Tags": tags,
        })
    return rows


def collect_nat(region: str, money: C.Money) -> list[dict[str, Any]]:
    ec2 = C.client("ec2", region)
    rows = []
    for n in _safe(lambda: ec2.describe_nat_gateways()["NatGateways"], []):
        if n.get("State") in {"deleted", "deleting", "failed"}:
            continue
        tags = C.tags_to_dict(n.get("Tags"))
        money.add("NAT gateways", C.NAT_GATEWAY_MONTH)
        rows.append({
            "NatGatewayId": n["NatGatewayId"],
            "Region": region,
            "Vpc": n.get("VpcId", ""),
            "Subnet": n.get("SubnetId", ""),
            "State": n.get("State"),
            "MonthlyEstimate": C.NAT_GATEWAY_MONTH,
            "Tags": tags,
        })
    return rows


def collect_other(region: str, money: C.Money) -> dict[str, Any]:
    ec2 = C.client("ec2", region)
    # Load balancers (ALB/NLB + classic)
    elbv2 = C.client("elbv2", region)
    lbs = [{"Name": lb["LoadBalancerName"], "Type": lb.get("Type"),
            "Region": region, "Dns": lb.get("DNSName")}
           for lb in _safe(lambda: elbv2.describe_load_balancers()["LoadBalancers"], [])]
    elb = C.client("elb", region)
    lbs += [{"Name": lb["LoadBalancerName"], "Type": "classic", "Region": region}
            for lb in _safe(lambda: elb.describe_load_balancers()["LoadBalancerDescriptions"], [])]
    money.add("Load balancers", round(len(lbs) * 0.0225 * C.HOURS_PER_MONTH, 2))

    endpoints = [{"Id": e["VpcEndpointId"], "Service": e.get("ServiceName"),
                  "Type": e.get("VpcEndpointType"), "Region": region}
                 for e in _safe(lambda: ec2.describe_vpc_endpoints()["VpcEndpoints"], [])]

    snaps = []
    for s in _safe(lambda: ec2.describe_snapshots(OwnerIds=["self"])["Snapshots"], []):
        cost = C.snapshot_monthly(s.get("VolumeSize", 0))
        money.add("Snapshots", cost)
        snaps.append({"SnapshotId": s["SnapshotId"], "Region": region,
                      "SizeGiB": s.get("VolumeSize"), "StartTime": s.get("StartTime"),
                      "MonthlyEstimate": cost})

    amis = [{"ImageId": i["ImageId"], "Name": i.get("Name", ""), "Region": region,
             "CreationDate": i.get("CreationDate")}
            for i in _safe(lambda: ec2.describe_images(Owners=["self"])["Images"], [])]

    logs = C.client("logs", region)
    log_groups = [{"Name": g["logGroupName"], "Region": region,
                   "RetentionDays": g.get("retentionInDays", "never-expire"),
                   "StoredBytes": g.get("storedBytes", 0)}
                  for g in _safe(lambda: logs.describe_log_groups()["logGroups"], [])]

    lam = C.client("lambda", region)
    fns = [{"Name": f["FunctionName"], "Region": region, "Runtime": f.get("Runtime")}
           for f in _safe(lambda: lam.list_functions()["Functions"], [])]

    rds = C.client("rds", region)
    dbs = [{"Id": d["DBInstanceIdentifier"], "Class": d.get("DBInstanceClass"),
            "Engine": d.get("Engine"), "Region": region, "Status": d.get("DBInstanceStatus")}
           for d in _safe(lambda: rds.describe_db_instances()["DBInstances"], [])]

    return {"LoadBalancers": lbs, "VpcEndpoints": endpoints, "Snapshots": snaps,
            "Amis": amis, "CloudWatchLogGroups": log_groups, "Lambda": fns, "Rds": dbs}


def collect_global(money: C.Money) -> dict[str, Any]:
    r53 = C.client("route53", "us-east-1")
    zones = []
    for z in _safe(lambda: r53.list_hosted_zones()["HostedZones"], []):
        money.add("Route53 zones", 0.50)
        zones.append({"Id": z["Id"], "Name": z["Name"],
                      "RecordCount": z.get("ResourceRecordSetCount")})
    s3 = C.client("s3", "us-east-1")
    buckets = [{"Name": b["Name"], "Created": b["CreationDate"]}
               for b in _safe(lambda: s3.list_buckets()["Buckets"], [])]
    return {"Route53HostedZones": zones, "S3Buckets": buckets}


# --- Orchestration -------------------------------------------------------

def run(regions: list[str] | None = None) -> dict[str, Any]:
    regions = regions or C.DEFAULT_REGIONS
    money = C.Money()
    inv: dict[str, Any] = {
        "generatedAt": C.now_iso(),
        "account": C.client("sts").get_caller_identity()["Account"],
        "regionsScanned": regions,
        "regions": {},
        "global": collect_global(money),
    }
    for region in regions:
        inv["regions"][region] = {
            "ec2": collect_ec2(region, money),
            "ebs": collect_ebs(region, money),
            "elasticIps": collect_eip(region),
            "natGateways": collect_nat(region, money),
            "other": collect_other(region, money),
        }
    inv["costEstimateMonthly"] = {
        "byCategory": money.by_category,
        "total": money.total,
    }
    return inv


def summarize(inv: dict[str, Any]) -> dict[str, Any]:
    running, gpu_running, unattached_eip, unattached_ebs, nat = [], [], [], [], []
    for region, blk in inv["regions"].items():
        for i in blk["ec2"]:
            if i["State"] == "running":
                running.append(i)
                if i["IsGpu"]:
                    gpu_running.append(i)
        unattached_eip += [e for e in blk["elasticIps"] if e["Unattached"]]
        unattached_ebs += [v for v in blk["ebs"] if v["Unattached"]]
        nat += blk["natGateways"]
    return {
        "runningInstances": running,
        "gpuRunning": gpu_running,
        "unattachedElasticIps": unattached_eip,
        "unattachedEbs": unattached_ebs,
        "natGateways": nat,
    }
