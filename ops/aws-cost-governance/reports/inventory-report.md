# AWS Resource Inventory Report

- **Account:** `988823366090`
- **Generated:** 2026-07-07T14:55:04Z
- **Regions scanned:** us-east-1, us-west-1, us-west-2
- **Estimated monthly cost (running state):** $744.96

## Estimated monthly cost by category

| Category | Monthly (USD) |
|---|---|
| EC2 compute | $656.71 |
| EBS volumes | $55.40 |
| NAT gateways | $32.85 |
| **Total** | **$744.96** |

## EC2 instances

| Region | Instance | Name | Type | State | GPU | Class | $/mo (running) | Missing tags |
|---|---|---|---|---|---|---|---|---|
| us-east-1 | `i-0573bbffa487688e2` | BitnamiRedashCf3f9cEc2Instance | m3.medium | stopped | no | Unknown | n/a | 0 |
| us-west-1 | `i-0399e2ee5e37a2c4f` | AMT-Pritunl | t2.micro | running | no | Production | $8.47 | 0 |
| us-west-1 | `i-0181f6033242b1d1a` | - | t2.micro | stopped | no | Unknown | $8.47 | 0 |
| us-west-1 | `i-0d1ae6093692f8889` | tablescope | t3.large | running | no | Production | $60.74 | 0 |
| us-west-2 | `i-0d938409d1b57ff12` | tablescope-ai-server | g6.xlarge | running | yes | Production | $587.50 | 0 |

## Elastic IPs

| Region | Public IP | Allocation | Associated | Unattached | $/mo |
|---|---|---|---|---|---|
| us-west-1 | 13.57.117.13 | `eipalloc-002cdf9e0f62a1329` | i-0d1ae6093692f8889 | no | $3.65 |
| us-west-1 | 52.53.137.219 | `eipalloc-0d3dee1532bb5d333` | i-0399e2ee5e37a2c4f | no | $3.65 |
| us-west-2 | 35.166.118.9 | `eipalloc-04bbf1dee5ce12ec7` | eni-08ac989df71fc83a2 | no | $3.65 |

## EBS volumes

| Region | Volume | Size | Type | State | Attached | $/mo |
|---|---|---|---|---|---|---|
| us-east-1 | `vol-0487639e64439c309` | 10 GiB | gp2 | in-use | i-0573bbffa487688e2 | $1.00 |
| us-west-1 | `vol-0eac12da6e879a57e` | 60 GiB | gp3 | in-use | i-0d1ae6093692f8889 | $4.80 |
| us-west-1 | `vol-00beb1169366e733e` | 8 GiB | gp2 | in-use | i-0399e2ee5e37a2c4f | $0.80 |
| us-west-1 | `vol-0f3f44bb11b2004a3` | 8 GiB | gp2 | in-use | i-0181f6033242b1d1a | $0.80 |
| us-west-2 | `vol-0c13835d5bf04e770` | 500 GiB | gp3 | in-use | i-0d938409d1b57ff12 | $40.00 |
| us-west-2 | `vol-0559c75ebae434742` | 100 GiB | gp3 | in-use | i-0d938409d1b57ff12 | $8.00 |

## NAT gateways

| Region | NAT Gateway | VPC | Subnet | State | $/mo (base) |
|---|---|---|---|---|---|
| us-west-2 | `nat-0a12c47e33d1a36e1` | vpc-04c3fab8e136a66d9 | subnet-06f18a3068970d5a7 | available | $32.85 |

## Other billable resources

- **global:** Route53 zones=0, S3 buckets=1

## Cleanup candidates (report-only, never auto-deleted)

- Unattached Elastic IPs: **0**
- Unattached EBS volumes: **0**
- GPU instances running: **1** `i-0d938409d1b57ff12` (g6.xlarge)
