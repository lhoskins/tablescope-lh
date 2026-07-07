# AWS Cost Governance & Remediation

This document describes the permanent cost-governance controls implemented for
the Tablescope AWS account (`988823366090`) across **us-east-1, us-west-1,
us-west-2**. It is the reference for how spend is discovered, controlled,
monitored, and reported, and it is the corrective-action record submitted to AWS
Support in support of a one-time courtesy billing adjustment for the unexpected
June 2026 EC2 GPU charges.

All tooling lives in [`ops/aws-cost-governance/`](../ops/aws-cost-governance/).
It is dependency-light (boto3 + stdlib), safe-by-default (every write is a
dry-run unless `--apply` is passed), and **never deletes resources
automatically**.

## Root cause of the unexpected charges

The `tablescope-ai-server` GPU instance (`g6.xlarge`, us-west-2) was running
**24/7**. At the on-demand rate (~$0.8048/hr) that is **~$587/mo** for a
workload that is only needed during business hours. There were no schedules,
no idle shutdown, no budgets, and no alarms, so the spend accrued silently.

## Architecture

```
                         ops/aws-cost-governance/cli.py
                                     |
   +----------------+----------------+----------------+----------------+
   |                |                |                |                |
 inventory        tagging          budgets          alarms         schedule
 (Phase 1-2)      (Phase 3)        (Phase 8)        (Phase 9)      (Phase 4)
   |                |                |                |                |
 EC2/EBS/EIP/     create_tags     AWS Budgets     CloudWatch      Lambda x3
 NAT/ELB/...      (additive)      (actual+fcst)   alarms + SNS    + EventBridge
                                                                   Scheduler
                                     |
                                dashboard (Phase 10)  optimize (Phase 11)
                                CloudWatch dashboard  recommendations +
                                + Cost Explorer       before/after report
```

## Standard tags (Phase 3)

Every managed resource carries: `Environment`, `Owner`, `Application`,
`CostCenter`, `Project`, `TablescopeRole`, `CostControl`, `AutoStop`,
`ManagedBy`. Tagging is **additive** — existing values are never overwritten.
`AutoStop=True` is the switch the automation keys off; only the AI-GPU instance
carries it. Production hosts (app, VPN) are `AutoStop=False`.

## EC2 governance (Phase 4)

Three Lambda functions in [`lambda/`](../ops/aws-cost-governance/lambda/):

| Function | Trigger | Behaviour |
|---|---|---|
| `scheduled_stopstart` | EventBridge Scheduler | Starts/stops all `AutoStop=True` instances |
| `idle_shutdown` | rate(15 min) | Stops instance when CPU < 5% **and** no AI requests for 60 min; also emits the `GPURunningOffSchedule` metric |
| `manual_wake` | Function URL / invoke | Admin start + status-ok wait + optional HTTP health check |

EventBridge Scheduler schedules (timezone `America/Los_Angeles`):

| Schedule | Cron | Purpose |
|---|---|---|
| `tablescope-gpu-start` | `cron(0 7 ? * MON-FRI *)` | Start 07:00 PT weekdays |
| `tablescope-gpu-stop` | `cron(0 20 ? * MON-FRI *)` | Stop 20:00 PT weekdays |
| `tablescope-gpu-nightly-stop` | `cron(0 21 * * ? *)` | Hard nightly stop (every day) |
| `tablescope-idle-shutdown` | `rate(15 minutes)` | Idle watchdog |

**Safety gate:** schedules are created **DISABLED** (`schedule deploy`). They
are activated only with an explicit `schedule enable`, so provisioning never
powers off a live instance without approval.

Only instances tagged `AutoStop=True` are ever affected. Tag any instance with
`IdleShutdown=Disabled` to exempt it from the idle watchdog.

### Manual wake-up

```
aws lambda invoke --function-name tablescope-manual-wake \
  --payload '{"health_url":"https://app.tablescope.cloud/health"}' out.json
```

Returns `{state, health_check, ai_ready, allow_requests}` so a UI can drive
Start → Health Check → AI Ready → Allow Requests.

## Elastic IP / EBS / NAT governance (Phases 5-7)

**Report-only. Nothing is deleted automatically.** The inventory flags:
unattached Elastic IPs, unattached ("available") EBS volumes, snapshots older
than 90 days, and NAT gateways (with a "confirm still required" recommendation).
Acting on any of these is a manual, approved step.

## AWS Budgets (Phase 8)

A single monthly cost budget `tablescope-monthly-cost-governance` (limit $500)
carries **actual** thresholds at $50 / $100 / $200 / $300 / $500 and
**forecast** thresholds at $200 / $300 / $500 (expressed as percentages of the
$500 limit). Notifications go to the account owner email and, if
`COST_SNS_TOPIC_ARN` is set, an SNS topic.

## CloudWatch monitoring (Phase 9)

| Alarm | Condition |
|---|---|
| `tablescope-gpu-offschedule-<id>` | `GPURunningOffSchedule >= 1` (running outside approved hours) |
| `tablescope-gpu-offschedule-4h-<id>` | Off-schedule for 16×15min = 4h continuously |
| `tablescope-gpu-idle-<id>` | CPU < 5% for 60 min |
| `tablescope-estimated-charges` | Account `EstimatedCharges` > $200 (us-east-1) |

Alarms notify via the `tablescope-cost-alerts` SNS topic (email). They are
notify-only; the `idle_shutdown` Lambda owns the stop action.

## Cost dashboard (Phase 10)

- **CloudWatch dashboard** `Tablescope-Cost-Governance`: estimated charges, GPU
  CPU, and off-schedule signal.
- **Cost Explorer report** (`reports/cost-dashboard.md`): month-to-date,
  projected month, top 10 cost drivers, monthly trend, daily spend. Falls back
  to inventory-based estimates if Cost Explorer access is unavailable.

## Monthly optimization report (Phase 11)

`cli.py optimize` produces `reports/optimization-report.md` (recommendations
with estimated monthly/annual savings, confidence, and risk) and
`reports/before-after-report.md` (the AWS Support artifact). Run monthly (it can
be wired to the same EventBridge Scheduler).

## Usage

```
cd ops/aws-cost-governance
pip install -r requirements.txt

python cli.py inventory              # Phase 1-2 report (read-only)
python cli.py tag --apply            # Phase 3
python cli.py budgets --apply        # Phase 8
python cli.py alarms --apply         # Phase 9
python cli.py dashboard --apply      # Phase 10
python cli.py optimize               # Phase 11 + before/after
python cli.py schedule deploy --apply   # Phase 4 (schedules DISABLED)
python cli.py schedule enable           # activate GPU start/stop
python cli.py all --apply               # everything except enabling schedules
```

Every command defaults to **dry-run**; `--apply` performs writes.

## Required IAM permissions

The automation identity needs the actions in
[`iam/cost-governance-policy.json`](../ops/aws-cost-governance/iam/cost-governance-policy.json):
EC2 (describe/tag/start/stop), CloudWatch (alarms/dashboards), Cost Explorer
(read), Budgets, SNS, Lambda, EventBridge Scheduler, and scoped IAM
create-role/pass-role for the two `tablescope-cost-*` roles.

## Recovery & maintenance

- **Instance stopped unexpectedly?** `aws lambda invoke --function-name
  tablescope-manual-wake ...`, or start it in the console; re-tag
  `IdleShutdown=Disabled` to pin it up.
- **Disable all automation:** `python cli.py schedule disable`.
- **Monthly checklist:** run `cli.py inventory` and `cli.py optimize`, review
  unknown/unattached resources, confirm budgets/alarms exist, act on
  recommendations with explicit approval.
