# Before vs. After Cost Governance Report

- **Generated:** 2026-07-07T14:55:23Z
- **Account:** `988823366090`

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
