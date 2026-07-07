# Tablescope AWS Cost Governance

Tooling that implements the AWS Cost Governance & Remediation Plan across
`us-east-1`, `us-west-1`, `us-west-2`. Full design and operating guide:
[`docs/aws-cost-governance.md`](../../docs/aws-cost-governance.md).

## Layout

```
awscost/        package: inventory, tagging, budgets, alarms, dashboard,
                optimize, schedule (phase modules)
lambda/         Lambda sources: scheduled_stopstart, idle_shutdown, manual_wake
iam/            IAM policy the automation identity needs
reports/        generated artifacts (inventory, optimization, before/after, ...)
tests/          unit tests (pure logic, no AWS)
cli.py          entrypoint (dry-run by default; --apply to write)
```

## Quick start

```
pip install -r requirements.txt
python cli.py inventory            # read-only report
python cli.py all --apply          # provision everything except enabling schedules
python cli.py schedule enable      # activate GPU start/stop (approval gate)
```

## Safety

- Every command is **dry-run** unless `--apply` is passed.
- Tagging is **additive** (never overwrites existing tag values).
- Elastic IP / EBS / NAT are **report-only** — never auto-deleted.
- EC2 schedules deploy **DISABLED**; `schedule enable` is the explicit gate.
- Only instances tagged `AutoStop=True` are ever stopped/started.

## Provisioning status (as run by `devin-terraform`)

`devin-terraform` currently has **EC2 + CloudWatch** permissions only, so the
following are live now: resource inventory, Phase 3 tagging (15 resources),
Phase 9 CloudWatch alarms (4, notify-actions pending SNS), Phase 10 CloudWatch
dashboard. Budgets (Phase 8), the Lambda + EventBridge schedules (Phase 4), SNS
alert notifications, and the Cost Explorer dashboard require the additional
permissions in [`iam/cost-governance-policy.json`](iam/cost-governance-policy.json);
attach that policy (or run `all --apply` from an admin identity) to finish
provisioning.
```
aws iam put-user-policy --user-name devin-terraform \
  --policy-name tablescope-cost-governance \
  --policy-document file://iam/cost-governance-policy.json
```
