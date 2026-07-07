"""Phase 3 - Resource tagging.

Adds the required standard tags where they are *missing*. Never overwrites a
tag that already has a value, so human-set metadata is preserved. Dry-run by
default; pass apply=True to write.
"""
from __future__ import annotations

from typing import Any

from . import common as C


def _role_for(name: str, is_gpu: bool, classification: str) -> tuple[str, str]:
    """Return (TablescopeRole, AutoStop) defaults for a resource."""
    low = name.lower()
    if is_gpu or "ai" in low:
        return "AI-GPU", "True"
    if "pritunl" in low or "vpn" in low:
        return "VPN", "False"
    if "tablescope" in low or "app" in low:
        return "App", "False"
    if classification in {"Development", "Test", "Temporary"}:
        return "NonProd", "True"
    return "Unclassified", "False"


def desired_tags(name: str, is_gpu: bool, classification: str) -> dict[str, str]:
    role, autostop = _role_for(name, is_gpu, classification)
    env = classification if classification != "Unknown" else "Unknown"
    return {
        "Environment": env,
        "Owner": C.NOTIFY_EMAIL,
        "Application": "Tablescope",
        "CostCenter": "Tablescope",
        "Project": "Tablescope",
        "TablescopeRole": role,
        "CostControl": "Enabled",
        "AutoStop": autostop,
        "ManagedBy": "Devin",
    }


def _missing(existing: dict[str, str], desired: dict[str, str]) -> dict[str, str]:
    return {k: v for k, v in desired.items() if not existing.get(k)}


def plan_from_inventory(inv: dict[str, Any]) -> list[dict[str, Any]]:
    plans: list[dict[str, Any]] = []
    for region, blk in inv["regions"].items():
        for i in blk["ec2"]:
            add = _missing(i["Tags"], desired_tags(
                i["Name"], i["IsGpu"], i["Classification"]))
            if add:
                plans.append({"region": region, "id": i["InstanceId"],
                              "kind": "instance", "add": add})
        for v in blk["ebs"]:
            add = _missing(v["Tags"], desired_tags(
                "", False, v["Classification"]))
            if add:
                plans.append({"region": region, "id": v["VolumeId"],
                              "kind": "volume", "add": add})
        for e in blk["elasticIps"]:
            if not e["AllocationId"]:
                continue
            add = _missing(e["Tags"], desired_tags("", False, "Unknown"))
            if add:
                plans.append({"region": region, "id": e["AllocationId"],
                              "kind": "eip", "add": add})
        for n in blk["natGateways"]:
            add = _missing(n["Tags"], desired_tags("", False, "Production"))
            if add:
                plans.append({"region": region, "id": n["NatGatewayId"],
                              "kind": "nat", "add": add})
    return plans


def apply(inv: dict[str, Any], apply: bool = False) -> dict[str, Any]:
    plans = plan_from_inventory(inv)
    applied = 0
    for p in plans:
        if apply:
            ec2 = C.client("ec2", p["region"])
            ec2.create_tags(
                Resources=[p["id"]],
                Tags=[{"Key": k, "Value": v} for k, v in p["add"].items()])
            applied += 1
    return {
        "action": "applied" if apply else "dry-run",
        "resourcesToTag": len(plans),
        "resourcesTagged": applied,
        "plans": plans,
    }
