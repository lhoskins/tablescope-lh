# Before vs. After Cost Governance Report

**AWS Account:** 988823366090
**Prepared:** 2026-07-07
**Regions in scope:** us-east-1, us-west-1, us-west-2
**Prepared by:** Tablescope Cloud Operations

---

## 1. Executive summary

An unmanaged GPU compute instance (`g6.xlarge`) ran continuously (24/7) in
`us-west-2`, driving account spend from a historical baseline of **~$63/month**
to **$771.91 in June 2026 — roughly 12× normal**. The instance had no schedule,
no idle shutdown, no budget, and no cost alarms, so the charge accrued silently.

A complete cost-governance program has since been designed, deployed, and
**activated** across all enabled regions. Controls now enforce business-hours-only
GPU operation, automatic idle shutdown, budgets with actual + forecast alerting,
CloudWatch alarms, standardized cost tagging, and continuous inventory and
optimization reporting. The GPU's projected monthly cost drops from
**~$587.50 to ~$227.30 (≈61% reduction)**; total identified savings across all
recommendations are **$413.81/month (~$4,965.72/year)**.

---

## 2. The billed anomaly (AWS Cost Explorer — actual)

| Month | Actual spend (USD) |
|---|---|
| 2026-01 | $61.54 |
| 2026-02 | $55.87 |
| 2026-03 | $61.55 |
| 2026-04 | $59.66 |
| 2026-05 | $78.09 |
| **2026-06** | **$771.91  ← anomaly** |

- **Typical monthly baseline (Jan–May 2026):** $63.34/month
- **Anomalous month (June 2026):** $771.91 — **≈12.2× baseline**
- **Current month-to-date:** $182.93; **projected month-end if uncontrolled:** $1,104.58

### June cost drivers (root cause)

The overage is concentrated in EC2 compute — the continuously-running
`g6.xlarge` GPU instance (`i-0d938409d1b57ff12`, us-west-2):

| Service (month-to-date sample) | USD |
|---|---|
| Amazon EC2 – Compute | $135.30 |
| Amazon VPC (NAT gateway) | $29.86 |
| EC2 – Other (EBS, etc.) | $17.77 |

---

## 3. Before vs. After

| Area | Before | After (implemented & live) |
|---|---|---|
| GPU runtime | Running 24/7 (168 hrs/week) | Scheduled weekday 07:00–20:00 PT + hard nightly stop (≈65 hrs/week) |
| Idle handling | None | Idle-shutdown Lambda (CPU <5% + no active requests for 60 min → stop) |
| Start/stop automation | Manual / none | EventBridge Scheduler: start, stop, nightly hard-stop |
| Manual recovery | Ad hoc console start | `tablescope-manual-wake` Lambda (start + health check) |
| Budgets | None | AWS Budget $500 with actual ($50/$100/$200/$300/$500) + forecast ($200/$300/$500) alerts |
| Alarms | None | CloudWatch: off-schedule, >4h off-hours, idle, estimated-charges |
| Cost visibility | None | CloudWatch dashboard + Cost Explorer report (MTD, projected, top drivers, trend, daily) |
| Tagging | Inconsistent / missing | Standardized cost tags on all resources (Environment, Owner, AutoStop, CostCenter, …) |
| Inventory | None | Full multi-region inventory (EC2/EBS/EIP/NAT/…) with classification |
| Optimization | Reactive | Monthly optimization report with confidence/risk scoring |
| Cost posture | Reactive, no guardrails | Proactive, automated, alerting governance |

---

## 4. Quantified impact

| Metric | Value |
|---|---|
| GPU spend before (24/7) | **$587.50 / month** |
| GPU spend after (scheduled, ~38.7% uptime) | **$227.30 / month** |
| GPU monthly reduction | **$360.20 / month (~61%)** |
| Total identified monthly savings (all recommendations) | **$413.81 / month** |
| Total identified annual savings | **$4,965.72 / year** |

### Additional recommendations (report-only, no auto-delete)

| Resource | Recommendation | Est. $/mo | Confidence | Risk |
|---|---|---|---|---|
| `i-0d938409d1b57ff12` (g6.xlarge) | Schedule GPU + idle shutdown | $360.20 | High | Low (AutoStop + manual wake) |
| `nat-0a12c47e33d1a36e1` (NAT GW) | Confirm still required; remove if not | $32.85 | Low | High if private subnets need egress |
| `i-0d1ae6093692f8889` (t3.large) | 1-yr Compute Savings Plan (always-on) | $18.22 | Medium | Low |
| `i-0399e2ee5e37a2c4f` (t2.micro) | 1-yr Compute Savings Plan (always-on) | $2.54 | Medium | Low |

---

## 5. Controls implemented (all live)

**EC2 GPU governance (EventBridge Scheduler, timezone America/Los_Angeles):**

| Schedule | Expression | Purpose |
|---|---|---|
| `tablescope-gpu-start` | `cron(0 7 ? * MON-FRI *)` | Start 07:00 PT weekdays |
| `tablescope-gpu-stop` | `cron(0 20 ? * MON-FRI *)` | Stop 20:00 PT weekdays |
| `tablescope-gpu-nightly-stop` | `cron(0 21 * * ? *)` | Hard nightly stop, every day |
| `tablescope-idle-shutdown` | `rate(15 minutes)` | Idle watchdog (CPU + request-aware) |

**Budgets:** `tablescope-monthly-cost-governance` ($500 limit) — actual thresholds
$50/$100/$200/$300/$500 and forecast thresholds $200/$300/$500; email delivery
confirmed operational.

**CloudWatch alarms:** GPU running off-schedule; off-schedule >4h continuously;
GPU idle (<5% CPU for 60 min); account estimated charges > $200.

**Dashboards:** CloudWatch `Tablescope-Cost-Governance` (estimated charges, GPU
CPU, off-schedule signal) and a Cost Explorer report.

**Tagging & inventory:** standardized cost tags applied to all resources; full
multi-region inventory and monthly optimization report.

**Safety guarantees:** no resource is ever auto-deleted (Elastic IP / EBS / NAT
are report-only); only instances explicitly tagged `AutoStop=True` are ever
stopped/started; a manual-wake path is always available.

---

## 6. Conclusion

The root cause of the June 2026 overage — an always-on GPU with no cost
controls — has been eliminated and replaced with permanent, automated
governance. The account is now protected by schedules, idle shutdown, budgets,
alarms, and continuous reporting, reducing GPU spend by ~61% and preventing
recurrence. This report accompanies a request to AWS for a one-time courtesy
billing adjustment for the unexpected June 2026 charges.
