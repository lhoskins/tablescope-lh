#!/usr/bin/env python3
"""Tablescope AWS cost-governance CLI.

Examples:
    python cli.py inventory
    python cli.py tag --apply
    python cli.py budgets --apply
    python cli.py alarms --apply
    python cli.py dashboard --apply
    python cli.py optimize
    python cli.py schedule deploy               # deploys Lambdas + DISABLED schedules
    python cli.py schedule enable               # turns the GPU schedules ON
    python cli.py schedule disable
    python cli.py all --apply                   # everything except enabling schedules
"""
from __future__ import annotations

import argparse
import json

from awscost import alarms, budgets, common, dashboard, inventory, optimize, report, schedule, tagging

GPU_REGION = "us-west-2"


def _load_or_scan(regions):
    inv = inventory.run(regions)
    common.write_json("inventory.json", inv)
    return inv


def _gpu_ids(inv):
    return [i["InstanceId"] for r in inv["regions"].values()
            for i in r["ec2"] if i["IsGpu"] and i["State"] == "running"]


def cmd_inventory(args):
    inv = _load_or_scan(args.regions)
    md = report.inventory_markdown(inv)
    common.write_text("inventory-report.md", md)
    print(md)


def cmd_tag(args):
    inv = _load_or_scan(args.regions)
    res = tagging.apply(inv, apply=args.apply)
    print(json.dumps(res, indent=2, default=str))


def cmd_budgets(args):
    print(json.dumps(budgets.apply(dry_run=not args.apply), indent=2))


def cmd_alarms(args):
    inv = _load_or_scan(args.regions)
    res = alarms.apply(GPU_REGION, _gpu_ids(inv), dry_run=not args.apply)
    print(json.dumps(res, indent=2, default=str))


def cmd_dashboard(args):
    data = dashboard.collect()
    common.write_json("cost-dashboard.json", data)
    common.write_text("cost-dashboard.md", dashboard.markdown(data))
    inv = _load_or_scan(args.regions)
    res = dashboard.put_cloudwatch_dashboard(GPU_REGION, _gpu_ids(inv), dry_run=not args.apply)
    print(json.dumps({"cloudwatch": res, "monthToDate": data["monthToDate"],
                      "projected": data["projectedMonth"]}, indent=2, default=str))


def cmd_optimize(args):
    inv = _load_or_scan(args.regions)
    recs = optimize.build_recommendations(inv)
    common.write_json("optimization.json", recs)
    common.write_text("optimization-report.md", optimize.recommendations_markdown(inv, recs))
    common.write_text("before-after-report.md", optimize.before_after_markdown(inv, recs))
    print(optimize.recommendations_markdown(inv, recs))


def cmd_schedule(args):
    if args.subcommand == "deploy":
        print(json.dumps(schedule.deploy(GPU_REGION, enabled=False,
                                         dry_run=not args.apply), indent=2, default=str))
    elif args.subcommand == "enable":
        print(json.dumps(schedule.set_enabled(GPU_REGION, True), indent=2))
    elif args.subcommand == "disable":
        print(json.dumps(schedule.set_enabled(GPU_REGION, False), indent=2))


def cmd_all(args):
    inv = _load_or_scan(args.regions)
    common.write_text("inventory-report.md", report.inventory_markdown(inv))
    print("tagging:", tagging.apply(inv, apply=args.apply)["action"])
    print("budgets:", budgets.apply(dry_run=not args.apply)["action"])
    print("alarms:", alarms.apply(GPU_REGION, _gpu_ids(inv), dry_run=not args.apply)["action"])
    data = dashboard.collect()
    common.write_json("cost-dashboard.json", data)
    common.write_text("cost-dashboard.md", dashboard.markdown(data))
    print("dashboard:", dashboard.put_cloudwatch_dashboard(
        GPU_REGION, _gpu_ids(inv), dry_run=not args.apply)["action"])
    recs = optimize.build_recommendations(inv)
    common.write_text("optimization-report.md", optimize.recommendations_markdown(inv, recs))
    common.write_text("before-after-report.md", optimize.before_after_markdown(inv, recs))
    print("schedule(deploy, DISABLED):",
          schedule.deploy(GPU_REGION, enabled=False, dry_run=not args.apply)["action"])
    print("NOTE: run `schedule enable` to activate GPU start/stop.")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--regions", nargs="+", default=common.DEFAULT_REGIONS)
    sub = ap.add_subparsers(dest="cmd", required=True)

    for name in ["inventory", "tag", "budgets", "alarms", "dashboard", "optimize", "all"]:
        p = sub.add_parser(name)
        p.add_argument("--apply", action="store_true",
                       help="perform writes (default is dry-run/report-only)")
    sp = sub.add_parser("schedule")
    sp.add_argument("subcommand", choices=["deploy", "enable", "disable"])
    sp.add_argument("--apply", action="store_true")

    args = ap.parse_args()
    {"inventory": cmd_inventory, "tag": cmd_tag, "budgets": cmd_budgets,
     "alarms": cmd_alarms, "dashboard": cmd_dashboard, "optimize": cmd_optimize,
     "schedule": cmd_schedule, "all": cmd_all}[args.cmd](args)


if __name__ == "__main__":
    main()
