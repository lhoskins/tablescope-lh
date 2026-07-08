"""Shared helpers for the Tablescope AWS cost-governance tooling.

Everything here is intentionally dependency-light (boto3 + stdlib) so the
package can run from a laptop, a CI job, or a Lambda layer without extra
infrastructure.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import boto3

# --- Account-wide configuration -----------------------------------------

# Regions AWS Support flagged plus any the account has opted into. Phase 1
# always scans at least these three; discover_active_regions() may widen it.
DEFAULT_REGIONS = ["us-east-1", "us-west-1", "us-west-2"]

# Directory where generated JSON/markdown artifacts are written.
REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"

# Standard tag keys the governance policy requires on every managed resource.
REQUIRED_TAG_KEYS = [
    "Environment",
    "Owner",
    "Application",
    "CostCenter",
    "Project",
    "TablescopeRole",
    "CostControl",
    "AutoStop",
    "ManagedBy",
]

# The GPU/AI instances that must not run 24/7. Matched by tag or name.
AI_GPU_ROLE = "AI-GPU"

# Notification email for budgets / alarms. Overridable via env.
NOTIFY_EMAIL = os.environ.get("COST_NOTIFY_EMAIL", "leonard.hoskins@gmail.com")
SNS_TOPIC_ENV = "COST_SNS_TOPIC_ARN"

# --- Rough on-demand price book (USD) -----------------------------------
# Deliberately conservative monthly estimates; good enough for cost triage,
# not billing. 730 hours/month.
HOURS_PER_MONTH = 730.0

# Per-hour on-demand price for common instance families (us-west-2 list price).
EC2_HOURLY = {
    "t2.micro": 0.0116, "t2.small": 0.023, "t2.medium": 0.0464,
    "t2.large": 0.0928, "t2.xlarge": 0.1856,
    "t3.micro": 0.0104, "t3.small": 0.0208, "t3.medium": 0.0416,
    "t3.large": 0.0832, "t3.xlarge": 0.1664, "t3.2xlarge": 0.3328,
    "t3a.medium": 0.0376, "t3a.large": 0.0752,
    "m5.large": 0.096, "m5.xlarge": 0.192, "m5.2xlarge": 0.384,
    "m6i.large": 0.096, "m6i.xlarge": 0.192,
    "c5.large": 0.085, "c5.xlarge": 0.17,
    "r5.large": 0.126, "r5.xlarge": 0.252,
    # GPU families (the expensive ones this whole exercise is about)
    "g4dn.xlarge": 0.526, "g4dn.2xlarge": 0.752, "g4dn.4xlarge": 1.204,
    "g5.xlarge": 1.006, "g5.2xlarge": 1.212, "g5.4xlarge": 1.624,
    "g6.xlarge": 0.8048, "g6.2xlarge": 0.9776, "g6.4xlarge": 1.323,
    "g6.8xlarge": 2.014, "g6.12xlarge": 3.911,
    "p3.2xlarge": 3.06, "p3.8xlarge": 12.24,
    "p4d.24xlarge": 32.7726,
}

# EBS $/GB-month by volume type.
EBS_GB_MONTH = {
    "gp3": 0.08, "gp2": 0.10, "io1": 0.125, "io2": 0.125,
    "st1": 0.045, "sc1": 0.015, "standard": 0.05,
}
SNAPSHOT_GB_MONTH = 0.05
# Public IPv4 (incl. idle Elastic IP) is billed at $0.005/hr since 2024-02.
EIP_MONTH = round(0.005 * HOURS_PER_MONTH, 2)          # ~$3.65
NAT_GATEWAY_MONTH = round(0.045 * HOURS_PER_MONTH, 2)  # ~$32.85 (excl. data)


def session() -> boto3.session.Session:
    return boto3.session.Session()


def client(service: str, region: str | None = None):
    return session().client(service, region_name=region)


def discover_active_regions() -> list[str]:
    """All regions that are opted-in for the account (superset of defaults)."""
    ec2 = client("ec2", "us-east-1")
    resp = ec2.describe_regions(
        Filters=[{"Name": "opt-in-status",
                  "Values": ["opt-in-not-required", "opted-in"]}]
    )
    regions = sorted(r["RegionName"] for r in resp["Regions"])
    # Guarantee the flagged regions are present even if the call is scoped.
    for r in DEFAULT_REGIONS:
        if r not in regions:
            regions.append(r)
    return regions


def tags_to_dict(tag_list: Iterable[dict[str, str]] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for t in tag_list or []:
        key = t.get("Key") or t.get("key")
        val = t.get("Value") or t.get("value")
        if key is not None:
            out[key] = val
    return out


def name_of(tags: dict[str, str]) -> str:
    return tags.get("Name", "")


def ec2_monthly(instance_type: str) -> float | None:
    price = EC2_HOURLY.get(instance_type)
    return round(price * HOURS_PER_MONTH, 2) if price is not None else None


def ebs_monthly(volume_type: str, size_gb: int) -> float:
    return round(EBS_GB_MONTH.get(volume_type, 0.10) * size_gb, 2)


def snapshot_monthly(size_gb: int) -> float:
    return round(SNAPSHOT_GB_MONTH * size_gb, 2)


def now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def utcstamp() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d-%H%M%S")


def write_json(name: str, payload: Any) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / name
    path.write_text(json.dumps(payload, indent=2, default=str))
    return path


def write_text(name: str, text: str) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / name
    path.write_text(text)
    return path


def is_gpu_type(instance_type: str) -> bool:
    return instance_type.split(".")[0] in {
        "g4dn", "g5", "g5g", "g6", "p2", "p3", "p4d", "p5", "inf1", "inf2",
    }


@dataclass
class Money:
    """Small accumulator for monthly cost totals by category."""
    by_category: dict[str, float] = field(default_factory=dict)

    def add(self, category: str, amount: float | None) -> None:
        if amount:
            self.by_category[category] = round(
                self.by_category.get(category, 0.0) + amount, 2)

    @property
    def total(self) -> float:
        return round(sum(self.by_category.values()), 2)
