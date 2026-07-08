# Monthly Cost Optimization Report

- **Generated:** 2026-07-07T15:37:55Z
- **Account:** `988823366090`
- **Identified monthly savings:** $413.81
- **Identified annual savings:** $4,965.72

| Resource | Region | Type | Recommendation | $/mo | $/yr | Confidence | Risk |
|---|---|---|---|---|---|---|---|
| `i-0d938409d1b57ff12` | us-west-2 | g6.xlarge | Stop idle / schedule GPU (weekday 07:00-20:00 PT + idle shutdown) | $360.20 | $4,322.40 | High | Low (AutoStop tag + manual wake available) |
| `nat-0a12c47e33d1a36e1` | us-west-2 | NAT Gateway | Confirm workloads still require NAT; delete if not | $32.85 | $394.20 | Low | High if private subnets need egress |
| `i-0d1ae6093692f8889` | us-west-1 | t3.large | Consider 1-yr Compute Savings Plan for always-on host | $18.22 | $218.64 | Medium | Low; commitment reduces flexibility |
| `i-0399e2ee5e37a2c4f` | us-west-1 | t2.micro | Consider 1-yr Compute Savings Plan for always-on host | $2.54 | $30.48 | Medium | Low; commitment reduces flexibility |
