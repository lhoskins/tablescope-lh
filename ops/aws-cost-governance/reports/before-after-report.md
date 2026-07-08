# Before vs. After Cost Governance Report

- **Generated:** 2026-07-07T15:37:56Z
- **Account:** `988823366090`

## Billed history (AWS Cost Explorer, actual)

| Month | Actual spend (USD) |
|---|---|
| 2026-01 | $61.54 |
| 2026-02 | $55.87 |
| 2026-03 | $61.55 |
| 2026-04 | $59.66 |
| 2026-05 | $78.09 |
| 2026-06 | $771.91  ← anomaly |

- Typical monthly baseline (prior months): **$63.34/mo**
- Anomalous month **2026-06**: **$771.91** (~12.2x baseline)
- Month-to-date this month: **$182.93**, projected **$1,104.58** if left uncontrolled.

## Governance controls

| Before | After |
|---|---|
| GPU running 24/7 | Scheduled (weekday 07:00-20:00 PT) + idle shutdown |
| No EventBridge automation | Automated start/stop + nightly hard-stop schedules |
| No budget alerts | AWS Budget $50/$100/$200/$300/$500 actual + forecast alerts |
| No idle monitoring | Idle-shutdown Lambda (CPU + request-aware) |
| No resource inventory | Full inventory across us-east-1/us-west-1/us-west-2 |
| No cost alarms | CloudWatch alarms: off-schedule, >4h off-hours, idle, billing |
| Untagged resources | Standard cost tags applied (Environment/Owner/AutoStop/...) |
| Reactive cost management | Proactive governance + monthly optimization report |

## Quantified impact

- GPU spend before (24/7): **$587.50/mo**
- GPU spend after (scheduled ~38.7% uptime): **$227.30/mo**
- GPU monthly reduction: **$360.20** (~61%)
- Total identified monthly savings (all recommendations): **$413.81**

This artifact documents that corrective controls are permanently in place, supporting the request for a one-time courtesy billing adjustment for the unexpected June 2026 GPU charges.
