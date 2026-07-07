# Letter to AWS Support — Request for One-Time Courtesy Billing Adjustment

**To:** AWS Support / AWS Billing
**Re:** Case update — request for a one-time courtesy credit / partial adjustment for unexpected June 2026 charges
**AWS Account ID:** 988823366090
**Date:** 2026-07-07
**Case reference:** [insert your existing case ID here]

---

Hello,

I'm writing to update my case and respectfully request consideration for a
one-time courtesy billing credit or partial adjustment for unexpected charges
on account **988823366090** during **June 2026**.

**What happened.** A GPU compute instance (`g6.xlarge`, instance ID
`i-0d938409d1b57ff12`, region us-west-2) was unintentionally left running
continuously (24/7). My account's spend had been very stable — approximately
**$63/month on average from January through May 2026** — but in **June 2026 it
rose to $771.91**, roughly **12 times** the normal baseline. The increase is
almost entirely attributable to the continuous runtime of this single GPU
instance, which was intended only for occasional, business-hours use.

**This was an oversight, not intended usage.** There were no automated controls
in place at the time (no start/stop schedule, no idle shutdown, no budget, and
no billing alarms), so the instance continued running and the charges accrued
without notification.

**Corrective actions already taken.** Since discovering the issue, I have
implemented and activated a comprehensive, permanent cost-governance program on
the account so this cannot recur:

1. **Scheduled GPU operation** — the instance now runs only during business
   hours (weekday 07:00–20:00 Pacific) via AWS EventBridge Scheduler, with a
   hard automatic stop every night.
2. **Automatic idle shutdown** — an AWS Lambda function stops the instance when
   it is idle (low CPU and no active requests for 60 minutes).
3. **AWS Budgets** — a monthly budget with actual thresholds at
   $50/$100/$200/$300/$500 and forecast alerts at $200/$300/$500, with email
   notifications (confirmed working).
4. **CloudWatch alarms** — alerts for the instance running outside its approved
   schedule, running more than 4 hours outside business hours, sitting idle, and
   for account estimated charges exceeding a threshold.
5. **Cost dashboards, tagging, and monthly optimization reporting** — for
   ongoing visibility and prevention.

These controls reduce the GPU's projected cost by approximately **61%** and
eliminate the conditions that caused the June overage.

**My request.** Given that (a) this was a genuine, one-time configuration
oversight, (b) my account has a long, consistent history of low, predictable
spend, and (c) I have already taken thorough corrective action to ensure it does
not happen again, I would be very grateful if AWS would consider a **one-time
courtesy credit or partial adjustment** for the anomalous June 2026 charges.

I'm happy to provide any additional detail. I have attached a "Before vs. After
Cost Governance Report" documenting the anomaly (from AWS Cost Explorer) and the
specific controls now in place. Thank you very much for your time and
consideration.

Sincerely,
Leonard Hoskins
leonard.hoskins@gmail.com
AWS Account 988823366090

---

*Attachment: Before-vs-After-Cost-Governance-Report.md*
