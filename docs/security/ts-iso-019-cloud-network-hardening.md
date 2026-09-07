# TS-ISO-019: Cloud Network Hardening — Standalone Implementation Plan

**Status:** Open — tenant routing and private-storage foundations exist; host exposure and unrestricted egress remain

**Severity:** Medium

**Owner:** Cloud Platform / Security / SRE / Data Plane

**Target branch:** `UX-design-03`

**Plan branch:** `codex/ts-iso-019-cloud-network-hardening`

**Depends on:** TS-ISO-012 (data-plane fallback completion), TS-ISO-014 (service identity scoping)
**Related findings:** TS-ISO-004 (PostgreSQL RLS), TS-ISO-010 (file-proxy hardening), TS-ISO-011 (cross-store deletion), TS-ISO-017 (background job reauthorization)

## 1. Objective

Move TableScope production compute behind controlled private network boundaries, eliminate direct administrative and AI-host Internet exposure, restrict ingress and egress by workload purpose, require hardened instance metadata and managed administration, and continuously prove that the shared control plane, AI plane, and tenant data planes cannot reach unintended networks or one another.

The only public production entry point should be the managed application edge on approved HTTPS ports. Application, worker, database, Teiid, Redis, AI API, model runtime, vector store, and tenant gateway workloads must use private addresses and explicit security-group, route, identity, and TLS policies. Administration must use AWS Systems Manager Session Manager with auditable access; SSH and generated private keys must not be part of the production design.

## 2. Current-state finding

Recent tenant-storage and Transit Gateway work improves isolation, but the root and AI Terraform still contain broad cloud-network defaults:

| Area | Current behavior | Remaining gap |
|---|---|---|
| Application subnet | Root Terraform selects the default VPC and a subnet with `map-public-ip-on-launch=true` when IDs are omitted | Production can silently deploy into a broad public/default network rather than an explicit environment VPC |
| Application instance | `associate_public_ip_address=true` | The shared host has direct Internet addressing instead of sitting behind a managed edge/load balancer |
| Application SSH | Port 22 uses `allowed_ssh_cidrs`, whose default is `0.0.0.0/0` | A default deployment exposes SSH globally |
| Application egress | Security group permits all protocols and destinations to `0.0.0.0/0` | A compromised application/worker can exfiltrate or scan without workload-level destination controls |
| Local SSH material | Terraform can generate an ED25519 key and write the private key to a local `.pem` file | Long-lived administrative credentials are created outside a managed, audited access plane |
| Application outputs | Terraform returns public service URLs and SSH/log-tail commands | The deployment contract normalizes direct host access even though only the reverse proxy should be public |
| AI VPC layout | A private subnet exists, but the AI EC2 instance is placed in the public subnet with a public IP | The private subnet is not actually the AI compute boundary |
| AI SSH | Port 22 defaults to `0.0.0.0/0` | The GPU/model/vector host is directly exposed for administration |
| AI API ingress | Port 8000 trusts a caller-supplied public application IP `/32` | Authorization relies on public addressing rather than private routing, security-group identity, and service identity |
| AI egress | AI security group and private route table permit general Internet egress through NAT | Model/vector workloads can contact arbitrary Internet destinations after provisioning |
| SSM readiness | Output suggests `aws ssm start-session`, but the AI instance does not attach the documented instance profile or managed SSM policy/endpoints | Removing SSH today could lock operators out because the replacement access path is incomplete |
| Instance metadata | EC2 resources have no `metadata_options`; AI idle shutdown uses unauthenticated IMDSv1-style `curl` | IMDSv2, hop limit, and metadata exposure are not enforced |
| Host container ports | Main API publishes `8000` on all host interfaces; AI API and vLLM publish `8000`/`8001` on all host interfaces | Security groups are the only barrier for services that should be local/private-only |
| Tenant data-plane egress | Tenant and S3-endpoint security groups allow all outbound traffic | Tenant workloads/endpoints lack an explicit destination/port allowlist |
| Shared-to-tenant routing | Shared subnet/TGW route tables receive routes for every tenant VPC and customer on-prem CIDR | The shared host remains able to route toward all tenant networks, which TS-ISO-012 must replace with tenant-scoped gateways |
| Network validation | CI formats the VPN test Terraform but has no general IaC security scan or reachability policy | Reintroduction of public IP, SSH, permissive egress, IMDSv1, or cross-tenant routes is not automatically blocked |

### Root cause

The original single-host deployment optimized for fast bootstrap, direct SSH, package/model downloads, and public-IP connectivity between the application and AI host. Private subnet, S3, VPN, and TGW resources were added later, but the original public administration and unrestricted outbound assumptions remained the default deployment path.

## 3. Scope and non-goals

This plan covers:

- production VPC/subnet/route/security-group topology for application, worker, AI, data, management, and tenant gateway workloads;
- public edge, private service connectivity, administration, IMDS, DNS, egress, VPC endpoints, container host bindings, and network telemetry;
- Terraform validation, IaC scanning, AWS reachability analysis, staged migration, lockout prevention, and rollback;
- network controls needed by tenant S3, VPN, workload identity, background jobs, and AI/vector services.

This plan does not claim TS-ISO-012 closure merely by tightening the shared host. Tenant VPN/data execution must still move to tenant-scoped gateways/workers. It does not replace application authorization, RLS, asset visibility, or job reauthorization. It also does not make all third-party integrations impossible; approved external dependencies receive explicit, monitored egress paths.

## 4. Network invariants

1. No production EC2 workload has a public IPv4/IPv6 address or direct Internet route.
2. Only a managed public edge accepts Internet traffic, on approved TLS ports, through an explicit edge security group and WAF policy.
3. SSH ingress and long-lived EC2 key pairs are absent; administration uses MFA-governed, logged SSM sessions.
4. Application, worker, database, Redis, Teiid, AI API, vLLM, Ollama, Qdrant, and tenant gateways use private addresses and least-privilege security-group references.
5. Default workload egress is denied; every allowed destination, protocol, port, DNS name/category, and owner is documented and monitored.
6. Customer VPN and tenant VPC traffic terminates in a tenant-scoped gateway that cannot reach another tenant or the general shared runtime.
7. AI/vector/model workloads have no routine Internet egress after build/provisioning and cannot reach tenant/customer networks directly.
8. Instance metadata requires IMDSv2, has hop limit `1`, and is disabled entirely when a workload does not need it.
9. AWS credentials are delivered through least-privilege instance/task identities and private AWS endpoints, never static host environment keys.
10. Container-only services are not published on all host interfaces; host and Docker policy reinforce the cloud boundary.
11. Terraform cannot default a production environment into the default VPC, public subnet, open SSH, public IP, or all-egress configuration.
12. Continuous reachability, flow-log, configuration, and IaC tests prove the intended paths and forbidden paths after every change.

## 5. Target architecture

### 5.1 Environment VPC and subnet tiers

Create or require an explicit production VPC with at least two Availability Zones and distinct subnet tiers:

| Tier | Public route | Intended workloads |
|---|---:|---|
| Public edge | Internet Gateway | ALB/NLB only; NAT/egress components only where approved |
| Private application | No direct IGW | web/API, schedulers, general workers, tenant-gateway control clients |
| Private data | No direct IGW; tightly restricted routes | PostgreSQL, Redis, Teiid/shared data services where retained |
| Private AI | No direct IGW; no tenant routes | AI API, model runtime, vector store, AI worker |
| Private management/endpoints | No direct IGW | SSM and AWS interface endpoints, resolver, logging/monitoring endpoints |
| Tenant execution | Per-tenant route domain | TS-ISO-012 gateway/worker and that tenant's approved S3/VPN destinations |

The application edge terminates TLS with ACM and applies WAF/rate controls. Port 80 exists only at the managed edge for an HTTPS redirect if required; certificate issuance/renewal must not require inbound traffic to an EC2 host. The edge forwards to private application targets using a security-group reference and health-check port only.

Production variables must require explicit VPC and subnet IDs or create the reviewed topology. Remove the default-VPC/public-subnet discovery fallback. Tag every resource with environment, service, owner, data classification, and tenant where applicable.

### 5.2 Public edge and application ingress

- Use an Internet-facing ALB for the browser/API edge with TLS 1.2+ policy, ACM certificate, access logs, deletion protection, WAF, and approved DNS.
- Edge security group accepts `443` from the intended audience; optional `80` only redirects to `443`.
- Application security group accepts the target port only from the ALB security group, not a public CIDR.
- Separate application, worker, data, and management security groups; do not reuse one broad host group.
- Health-check endpoints return no secrets or dependency details and are reachable only from the ALB/monitoring identity.
- Remove Terraform outputs for public host IP, raw API/UI ports, SSH commands, and direct log-tail access.

If the single-host deployment is retained temporarily, bind platform API and Teiid management ports to loopback or an internal Docker network and expose only nginx to the private ALB target. It remains a transition state, not the final workload separation.

### 5.3 Private application-to-AI connectivity

Place the AI EC2 instance in the private AI subnet with `associate_public_ip_address=false`. Connect application and AI networks using one reviewed private pattern:

1. same environment VPC with isolated subnet/route/security-group tiers;
2. PrivateLink endpoint service for a separately owned AI VPC; or
3. tightly controlled TGW/peering routes without transitive tenant/customer reach.

PrivateLink is preferred when the AI plane remains a separate VPC because it exposes only the AI service, not general VPC reachability.

- AI API ingress uses the application/gateway security-group or endpoint identity on the exact port.
- TS-ISO-014 mTLS/workload tokens remain mandatory; network location alone is not authentication.
- Bind AI API to the private service interface. Do not publish vLLM, Ollama, or Qdrant to the EC2 host; use isolated Docker networks and explicit service-to-service ports.
- AI route tables must not learn tenant VPC or customer on-prem CIDRs.
- Application callbacks from AI use a private internal endpoint with exact security-group and service-identity policy, not the public application URL.

### 5.4 Managed administration and patching

Remove port 22 rules, EC2 key-pair requirements, generated `tls_private_key`/`local_file` resources, and SSH outputs after SSM validation.

Each managed instance receives a least-privilege instance profile with `AmazonSSMManagedInstanceCore`-equivalent permissions scoped through reviewed policies. Private interface endpoints include at least:

```text
ssm
ssmmessages
ec2messages (where required by the regional agent contract)
logs
kms
secretsmanager
```

Endpoint security groups accept `443` only from managed workload subnets/security groups. SSM sessions require federated human identity, MFA/step-up, least-privilege IAM, reason/ticket tags, session time limits, and CloudTrail/session logging to encrypted destinations. Disable SSH daemon or firewall port 22 at the host after cutover.

Use SSM Patch Manager or an approved immutable-image replacement process. Patch baselines, maintenance windows, vulnerability scans, and reboot policy must be documented and tested for GPU drivers and model workloads.

### 5.5 IMDS and instance identity

Set EC2 metadata options explicitly:

```hcl
metadata_options {
  http_endpoint               = "enabled"
  http_tokens                 = "required"
  http_put_response_hop_limit = 1
  instance_metadata_tags      = "disabled"
}
```

Disable the metadata endpoint when an instance has no instance-profile requirement. Update AI idle-stop logic to obtain and refresh an IMDSv2 token or, preferably, move stop scheduling/idle decisions to an external EventBridge/Lambda/SSM automation whose IAM policy targets only the exact AI instance tags/ARNs.

Container workloads must not be able to reach IMDS unless explicitly required. Enforce hop limit, host firewall rules, and runtime credential delivery appropriate to the eventual orchestrator. Do not pass AWS access keys through `docker-compose.yml`; use scoped role credentials and SDK resolution.

### 5.6 Egress policy

Build a workload-by-destination egress matrix before removing general NAT access:

| Workload | Approved destination classes |
|---|---|
| Application API | AWS private endpoints, identity provider, Stripe, email/SMS, approved connector APIs, observability |
| General worker | Queue/database/private AI, approved connector APIs required by its job capability |
| AI API/worker | private application callback, model/vector services, logs/metrics, approved artifact store |
| Data services | only explicit application/worker clients, backup/monitoring endpoints, DNS/NTP |
| Tenant gateway | one tenant's Teiid/S3/VPN CIDRs, control channel, DNS/NTP and approved endpoints |

Prefer VPC endpoints for S3, ECR API/DKR, CloudWatch Logs, KMS, Secrets Manager, STS, SSM, and other AWS services in use. Apply endpoint policies that constrain accounts, roles, buckets, access points, keys, repositories, and actions.

For required third-party APIs, route through an egress proxy or AWS Network Firewall with domain/IP policy, TLS/SNI controls where supportable, DNS logging, per-workload source identity, and alerting. Because several providers use changing addresses, maintain provider domain categories with automated validation rather than embedding permissive CIDRs.

The production runtime must not install packages, clone arbitrary branches, pull mutable container tags, or download models directly from the Internet during boot. Build signed AMIs/images in a controlled build account/pipeline, pin digests, scan them, store them in private ECR/S3/model vault, and deploy immutable artifacts. Any temporary migration egress is time-bound, source-specific, approved, monitored, and removed after image/model staging.

DNS uses Route 53 Resolver and approved conditional forwarding. Deny direct external DNS, DNS-over-HTTPS, SMTP except the approved relay, and IPv6 egress unless equivalent IPv6 policy is implemented.

### 5.7 Tenant network and Transit Gateway hardening

Keep the existing TGW defaults that disable automatic attachment acceptance, association, and propagation. Strengthen the design in coordination with TS-ISO-012:

- remove shared application/worker subnet routes to every tenant/customer network after tenant-gateway migration;
- associate each tenant attachment and VPN with only that tenant's route table;
- expose a narrow control channel from the shared application to the tenant gateway, not general tenant VPC or customer CIDR routes;
- allow the gateway only that tenant's approved on-prem CIDRs, Teiid, private S3 endpoint/access point, DNS/NTP, and control endpoint;
- deny other tenant CIDRs, shared data/control services, AI subnets, instance metadata, management ports, and Internet by default;
- validate tenant VPC and customer CIDR overlap before plan/apply. Continue the documented no-overlap rule until an architecture with isolated route domains can prove overlapping customer CIDRs safely;
- disable source/destination checking only on an explicitly approved routing appliance and never on general workloads;
- record the expected route/security policy hash in the tenant binding and revalidate it before activation and jobs.

Security-group egress on tenant and S3-endpoint groups must be reduced to the exact required endpoints and response paths. Network ACLs may provide subnet-level defense in depth but must not replace stateful security-group and route policy.

### 5.8 Host and container network defense

- Bind host-published internal ports to `127.0.0.1` during the single-host transition or remove publishing entirely in favor of internal Docker networks.
- Publish only nginx/edge target ports; API `8000`, Teiid `8095/35442/9990`, PostgreSQL, Redis, PgBouncer, R analytics, AI API, vLLM, Ollama, and Qdrant remain private.
- Separate front-end, application, data, observability, and tenant-gateway Docker networks; attach a service only to networks it needs.
- Remove shared control-plane membership in tenant Docker/VPN networks per TS-ISO-012.
- Drop Linux capabilities, run non-root, use read-only filesystems where supported, block inter-container communication by default, and apply host `DOCKER-USER` policy before containers start.
- Deny containers access to the Docker socket, host network, privileged mode, management interfaces, and metadata service unless a documented exception is enforced.
- Treat `ipc: host` for vLLM as a reviewed GPU/runtime exception and verify it does not create a network or host-namespace escape path.

### 5.9 IAM and endpoint coupling

Network restrictions and IAM must reinforce each other:

- scope the shared runtime's `sts:AssumeRole` to roles in the current AWS account and require tenant/environment tags, external/session tags, source identity, and approved endpoint conditions;
- tenant storage roles remain restricted to their access point, KMS key, and VPC endpoint;
- worker, AI, SSM, image pull, logging, backup, scheduler, and tenant gateway roles are distinct;
- EventBridge start/stop policies target only the approved AI instance/ASG tags and cannot manage arbitrary EC2 instances;
- use KMS/Secrets Manager endpoint policies and resource policies to deny access outside approved VPC endpoints where operationally safe;
- block creation/use of static AWS keys in production deployment configuration.

TS-ISO-014 authorizes the workload at the application layer. Security groups, endpoint policies, IAM roles, TLS identities, and application claims must agree on environment and tenant; a mismatch fails closed.

### 5.10 Telemetry and continuous verification

Enable and centralize:

- VPC Flow Logs for edge, application, data, AI, management, TGW, and tenant subnet interfaces;
- TGW Flow Logs and route-table change events;
- ALB/WAF access/security logs;
- Route 53 Resolver query logs;
- CloudTrail organization/account events, GuardDuty, Security Hub, AWS Config, Inspector, and IAM Access Analyzer;
- Network Firewall/egress proxy logs and rejected-connection metrics;
- SSM session/audit logs encrypted under a security-owned key.

Alert on public IP assignment, SSH rule creation, `0.0.0.0/0` or `::/0` workload egress, IMDSv1 allowance, unexpected NAT bytes, denied cross-tenant paths, metadata access, public S3/KMS changes, unapproved TGW propagation, anomalous DNS, and AI/model Internet attempts.

Use AWS Reachability Analyzer for required and forbidden paths, Network Access Analyzer scopes for public exposure, and automated packet probes from representative application, AI, and tenant gateway instances.

## 6. Implementation work breakdown

### Phase A — Inventory, policy, and lockout-safe prerequisites

1. Inventory VPCs, subnets, routes, security groups, ENIs, public IPs, NAT/IGW paths, TGW/VPN attachments, VPC endpoints, DNS, host ports, IAM roles, and actual flow logs.
2. Classify every inbound and outbound flow by source workload, destination, port, protocol, owner, environment, tenant, and business requirement.
3. Create explicit production variables/checks that prohibit default VPC/public subnet/open SSH/public instance IP/unrestricted egress.
4. Deploy and verify SSM instance profiles, agents, endpoints, DNS, KMS, session logging, and federated MFA access before changing SSH.
5. Add IMDSv2 metadata options and update/remove IMDSv1-dependent idle automation.

### Phase B — Private application edge

1. Create public edge subnets, ALB, ACM certificate, WAF, logging, and edge security group.
2. Create private application/data subnets and workload-specific route/security groups.
3. Deploy a new private application target from a signed immutable image; keep the current host unchanged during validation.
4. Route canary DNS/traffic through the ALB and verify application, auth, billing, connectors, email/SMS, storage, AI, and observability.
5. Drain the public application host, remove its public IP/SSH/key path, and delete obsolete public/raw outputs.

### Phase C — Private AI plane

1. Attach the approved AI instance profile and establish SSM/monitoring endpoints.
2. Build a replacement AI instance in the private AI subnet with no public IP and IMDSv2 required.
3. Establish PrivateLink or reviewed private routing plus SG-to-SG/mTLS access from the application.
4. Pre-stage pinned model/container/driver artifacts privately and remove routine AI Internet/NAT access.
5. Remove AI SSH, public IP, public-IP ingress variable, public output, and host-published internal model/vector ports.

### Phase D — Egress and tenant route segmentation

1. Add private AWS endpoints and least-privilege endpoint policies.
2. Introduce workload-specific egress proxy/firewall rules in observe mode and build the approved domain/destination inventory.
3. Enforce application, worker, data, AI, management, and gateway egress allowlists separately.
4. Migrate tenant execution through TS-ISO-012 gateways, then remove shared routes to tenant/customer networks.
5. Restrict tenant/S3-endpoint SG egress and validate TGW association/propagation, overlap rules, and route policy hashes.

### Phase E — Host, CI, and continuous enforcement

1. Remove unnecessary host port publishing and segment Docker networks/capabilities.
2. Add Terraform format/validate/plan plus Checkov/tfsec-equivalent, policy-as-code, secret, and container/IaC scans to CI.
3. Add AWS Config/Security Hub controls and automated Reachability/Network Access Analyzer assertions.
4. Enable flow/DNS/TGW/WAF/SSM logging, retention, alerts, and incident runbooks.
5. Run public-exposure, cross-tenant, AI egress, IMDS, SSM lockout, failover, patching, and rollback drills before closing the finding.

## 7. Expected file changes

| Area | Expected files |
|---|---|
| Root network/compute | `terraform/main.tf`, `variables.tf`, `outputs.tf`, environment tfvars/examples, new VPC/ALB/WAF/private-compute modules |
| AI network/compute | `terraform/ai-server/main.tf`, `variables.tf`, `outputs.tf`, user data/image pipeline, private connectivity module |
| Tenant network | `terraform/modules/network-hub/*`, `modules/tenant-vpc/*`, `tenants.tf`, tenant variables/outputs |
| IAM/endpoints | workload instance profiles/policies, SSM/VPC endpoint modules and policies, KMS/Secrets/STS/S3 restrictions |
| Egress/DNS | firewall/proxy, NAT where retained, Route 53 Resolver rules/logging, endpoint and workload egress matrices |
| Public edge | ALB listeners/targets, ACM, WAF, access logs, DNS records, health-check configuration |
| Runtime | `docker-compose.yml`, `ai-server/docker-compose.yml`, nginx/internal callbacks, host firewall and hardening scripts |
| Build/patch | signed AMI/container/model artifact pipeline, pinned digests, SSM Patch Manager/immutable replacement automation |
| Observability | VPC/TGW Flow Logs, CloudTrail, Config, GuardDuty, Security Hub, Inspector, Access Analyzer, alerts/dashboards |
| CI/tests/docs | Terraform/IaC policy workflow, reachability assertions, packet probes, migration, access, incident, deployment, and rollback runbooks |

Exact resources, paths, module boundaries, account structure, state backend, and current AWS inventory must be confirmed before implementation. Do not infer production resources solely from Terraform state or repository defaults.

## 8. Terraform and policy-as-code requirements

Production plans must fail when they contain:

- an EC2 public IP or public-subnet application/AI/data workload;
- port 22 ingress or any administrative port from CIDR ranges;
- `0.0.0.0/0` or `::/0` workload egress without a named, reviewed edge/egress resource exception;
- missing/optional IMDSv2 enforcement;
- default VPC/subnet discovery;
- generated private SSH keys or outputs containing keys/direct host commands;
- an AI/model/vector port exposed to public or general VPC sources;
- automatic TGW association/propagation or cross-tenant/shared-customer routes;
- wildcard endpoint, IAM assume-role, S3, or KMS policy broader than the approved tagged resources;
- unencrypted/short-retention flow, load-balancer, DNS, SSM, or audit logs;
- mutable/unpinned production image/model sources.

Use a remote encrypted Terraform backend with locking, versioning, least-privilege CI roles, plan review, environment separation, and no secrets in state inputs when a managed secret reference can be used. Require a reviewed plan artifact and policy results before apply. Protect production applies with environment approval and record the exact plan digest.

## 9. Test and validation plan

### Public exposure and administration

- Network Access Analyzer finds only the approved ALB listeners publicly reachable.
- No EC2 ENI has a public IP; direct application, AI, database, Redis, Teiid, Qdrant, Ollama, vLLM, or management-port probes fail.
- Security groups, NACLs, routes, and host firewalls contain no port 22 ingress.
- SSM works from approved federated MFA roles, logs sessions, enforces timeouts, and denies unapproved identities.
- Loss of Internet/NAT does not break SSM, logging, secret retrieval, image start, health checks, or emergency access.

### Required private paths

- ALB reaches only healthy private application targets on the approved port.
- Application reaches database/Redis/Teiid/private AI only on exact ports and identities.
- AI callback reaches only the private application endpoint and cannot initiate arbitrary application/data connections.
- Each workload reaches only its required AWS VPC endpoints under its own IAM and endpoint policy.
- DNS, NTP, logs, metrics, backup, and patch flows work through approved paths.

### Forbidden reachability

- Application/worker cannot directly reach tenant Teiid/VPN/customer CIDRs after gateway migration.
- Tenant A gateway cannot reach Tenant B VPC, S3 endpoint, Teiid, customer CIDRs, control/data services, AI subnet, or Internet.
- AI cannot reach tenant/customer networks, metadata from containers, arbitrary Internet hosts, or internal databases/vector ports outside its policy.
- Database/Redis/Teiid cannot initiate general Internet egress.
- IPv6 cannot bypass the IPv4 policy.
- TGW route-table association/propagation and overlapping-CIDR checks fail unsafe configurations before apply.

### IMDS, identity, and egress

- IMDSv1 requests fail; IMDSv2 works only where required, with hop limit `1` and no instance tags.
- Containers cannot retrieve host instance credentials unless explicitly designed and tested.
- Static AWS keys are absent from instance files, Compose environments, logs, user data, Terraform state, and CI output.
- Approved third-party APIs work through the egress policy; unapproved domains/IPs/protocols are denied and alerted.
- AI boot/restart succeeds from private pinned artifacts with no Internet model/package downloads.
- Role, endpoint, KMS, S3, and network policies all reject a tenant/environment mismatch.

### Operational and failure tests

- Replace instances from signed images, rotate certificates/identities, patch GPU/application hosts, and restore from backup without public access.
- Endpoint, firewall, DNS, PrivateLink, ALB, or one-AZ failure follows the documented degraded/fail-closed behavior.
- Flow/DNS/WAF/TGW/SSM logs arrive encrypted with expected tenant/workload attribution and retention.
- Detection alerts fire for attempted public IP, open SSH, all-egress, IMDSv1, cross-tenant route, anomalous DNS, and AI Internet access.
- Terraform drift and out-of-band security-group/route changes are detected and reconciled through reviewed code.

## 10. Deployment sequence

1. Snapshot the current AWS inventory, Terraform state/plan, route and security-group tables, IAM/endpoint policies, public exposure, flow logs, DNS, container ports, image digests, and recovery access.
2. Enable telemetry and deploy private SSM/Logs/KMS/Secrets endpoints plus instance profiles. Prove Session Manager and recovery from a clean operator session before removing any access path.
3. Enforce IMDSv2 and update idle-stop/instance automation on canaries; confirm no container or host dependency breaks.
4. Build the private ALB/application topology in parallel, deploy signed images, validate all application flows, and shift traffic gradually by DNS/target weight.
5. Drain and terminate the public application instance only after private health, SSM, backup, observability, and rollback tests pass.
6. Build the replacement private AI host, pre-stage pinned models/images, establish private SG-to-SG/PrivateLink plus TS-ISO-014 identity, and canary AI traffic.
7. Remove the AI public IP, SSH rule/key resources, public-app-IP trust, public callback, general NAT egress, and host-published internal AI ports.
8. Enforce workload-specific AWS endpoint and third-party egress policies in observed waves; investigate denials rather than restoring all-egress.
9. Complete TS-ISO-012 tenant gateway migration, remove shared-to-tenant/customer routes, and enforce per-tenant gateway/TGW/endpoint policy.
10. Enable blocking CI/policy-as-code and continuous reachability/configuration controls; run incident, lockout, patch, AZ-failure, cross-tenant, egress, and rollback drills.

Use replacement infrastructure and weighted cutover rather than mutating the only reachable host in place. Do not remove SSH until SSM and its private dependencies have been independently proven; once removed, do not restore it as routine rollback.

## 11. Rollback

- Roll back traffic to the last known-good private target/image through the ALB; retain private addressing, SSM, IMDSv2, logging, and least-privilege security groups.
- If PrivateLink/private AI connectivity fails, disable AI-dependent features or route to a previously validated private endpoint. Do not expose the AI host publicly.
- If an egress rule blocks a required dependency, add a time-bound, source/destination/port-specific reviewed exception with monitoring; do not restore unrestricted outbound access.
- If SSM fails after cutover, recover through a pretested private break-glass automation or instance replacement. Do not add `0.0.0.0/0` SSH or distribute a long-lived key.
- Preserve TGW tenant isolation and S3 endpoint policies through rollback. A tenant gateway failure makes that tenant data path unavailable rather than rerouting through the shared host.
- Never roll back IMDSv2, public-IP prohibition, SSH removal, audit logs, or a detected compromised identity/key.

## 12. Acceptance criteria

- [ ] Only the managed HTTPS edge is publicly reachable; production application, worker, data, AI, model, vector, and tenant gateway instances have no public addresses.
- [ ] Port 22, EC2 key pairs, generated private keys, and direct-host SSH/log outputs are removed from production Terraform.
- [ ] SSM administration, MFA/step-up, private endpoints, session logging, patching, and break-glass recovery are tested before SSH removal.
- [ ] IMDSv2 is required with hop limit `1` or metadata is disabled; containers cannot obtain unintended instance credentials.
- [ ] Application-to-AI and AI callbacks use private routing, exact SG/endpoint identity, TLS, and TS-ISO-014 workload authorization.
- [ ] API, Teiid, database, Redis, Qdrant, Ollama, vLLM, and management ports are not published to public/general host interfaces.
- [ ] Workload egress is default-deny and limited to approved AWS endpoints, third-party APIs, tenant destinations, ports, and purposes.
- [ ] AI/model/vector workloads restart and operate from pinned private artifacts without general Internet access.
- [ ] Shared application/worker routes to tenant/customer networks are removed after TS-ISO-012 gateway migration; tenant route tables remain mutually isolated.
- [ ] Tenant and endpoint security groups, TGW policies, IAM roles, endpoint policies, and application claims agree on tenant/environment and fail closed on mismatch.
- [ ] Terraform/IaC policy blocks public IPs, open SSH, unrestricted egress, IMDSv1, default VPC fallback, unsafe TGW routes, and mutable artifacts.
- [ ] Flow/DNS/TGW/ALB/WAF/SSM/CloudTrail/Config/GuardDuty/Security Hub telemetry and alerts are enabled, encrypted, retained, and tested.
- [ ] Required-path and forbidden-path Reachability/Network Access Analyzer plus live packet tests pass in a production-like environment.
- [ ] Public-host, SSM lockout, egress dependency, AI connectivity, cross-tenant routing, patching, failover, and rollback drills succeed without weakening the boundary.

TS-ISO-019 must remain open until the public application/AI host and SSH paths are removed, unrestricted workload egress is eliminated, IMDSv2/SSM/private connectivity are enforced, shared tenant routes are retired through TS-ISO-012, and automated cloud reachability/configuration evidence passes.

## Validation addendum

Independent re-verification against `origin/UX-design-03` (`966abba6`), reading `terraform/main.tf`, `terraform/variables.tf`, `terraform/outputs.tf`, `terraform/ai-server/main.tf`, `terraform/ai-server/variables.tf`, `terraform/ai-server/outputs.tf`, `terraform/ai-server/user-data-ai.sh.tpl`, `terraform/tenants.tf`, `terraform/modules/network-hub/main.tf`, `terraform/modules/tenant-vpc/main.tf`, `docker-compose.yml`, `ai-server/docker-compose.yml`, `.github/workflows/vpn-smb-e2e.yml`, and `scripts/vpn-smb-e2e/run.sh` as text (no `terraform plan`/`apply` run) — 17 current-state claims in Section 2 checked individually.

**16 of 17 claims are ACCURATE**, including the default-VPC/public-subnet fallback (`main.tf:24-46`), `associate_public_ip_address = true` on the app instance (`main.tf:194`), SSH default `0.0.0.0/0` on both instances (`main.tf:104-110`/`variables.tf:61-65`, `ai-server/main.tf:151-157`/`ai-server/variables.tf:110-114`), all-protocol/`0.0.0.0/0` egress on both security groups (`main.tf:136-141`, `ai-server/main.tf:159-165`), the ED25519 `tls_private_key` + `local_file` `.pem` write pattern in both root and AI Terraform, SSH/log-tail command outputs (`outputs.tf`), the AI instance sitting in the **public** subnet despite a private subnet existing (`ai-server/main.tf:32-39` vs. `201-208`), the `app_server_ip` hardcoded default (`13.57.117.13`) trusted as a bare `/32` ingress CIDR (`ai-server/main.tf:142-148`, `ai-server/variables.tf:55-59`), all-egress + NAT route for the AI private subnet, the SSM output present but no `iam_instance_profile` ever attached with an explicit code comment admitting the IAM role must be created manually (`ai-server/main.tf:170-176, 201-233`), the complete absence of any `metadata_options` block on either instance (IMDSv2 unenforced), the plain unauthenticated `curl http://169.254.169.254/...` in the idle-check cron script (`user-data-ai.sh.tpl:128-129`), unbound Docker port publishing on `8000`/`8001` in both compose files, all-egress tenant/S3-endpoint security groups (`modules/tenant-vpc/main.tf`), and the shared-subnet/TGW routes propagated to every tenant VPC and on-prem CIDR (`tenants.tf` + `modules/network-hub/main.tf` + `modules/tenant-vpc/main.tf`).

**Claim 17 needed a correction.** The plan states CI "formats" the VPN test Terraform in addition to running it. In fact `.github/workflows/vpn-smb-e2e.yml` and `scripts/vpn-smb-e2e/run.sh` run only `terraform init`, `terraform plan -out=tfplan`, and `terraform apply tfplan` (`run.sh:57-63,66-67`) — there is no `terraform fmt` or `terraform validate` step anywhere in the workflow. The second half of the claim — that no IaC security scanner (tfsec, checkov, or similar) exists in any workflow — is confirmed accurate; a repo-wide search finds no such tool referenced outside unrelated binary jars under `wildfly/`.

**Corrected wording for Section 2, claim 17:** "CI runs Terraform `init`/`plan`/`apply` for the VPN test infrastructure but performs no `terraform fmt`/`validate` step and no IaC security scan" — not "CI formats the VPN test Terraform." This makes the gap slightly larger than originally stated: there is no automated formatting or static validation at all on this Terraform, not just no security-specific scan.
