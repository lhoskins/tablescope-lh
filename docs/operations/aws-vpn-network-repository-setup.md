# AWS VPN + Network Repository Setup

This guide covers everything required to make a **customer-managed file repository** reachable from TableScope over an **AWS Site-to-Site VPN** and to expose it in the Data Source Builder as a live, queryable SMB network repository.

It is split into:

1. [What the TableScope UI gives you](#1-tablescope-ui-configuration)
2. [AWS-side prerequisites](#2-aws-side-prerequisites)
3. [Customer / on-premises gateway prerequisites](#3-customer--on-premises-gateway-prerequisites)
4. [Non-UI TableScope configuration](#4-non-ui-tablescope-configuration)
5. [Live / persistent behavior](#5-live--persistent-behavior)
6. [Troubleshooting checklist](#6-troubleshooting-checklist)

---

## 1. TableScope UI configuration

### Settings → Repositories → Allowed SMB hosts

Add the hostname or IP address of each SMB server you want to allow. You can also give it a friendly name so users see `Customer repo VM` instead of `10.250.10.229`.

| Field | Example | Purpose |
|---|---|---|
| Friendly name | `Customer repo VM` | Display label in the builder |
| Host | `10.250.10.229` | SMB server IP or DNS name |

The host must match the server part of the UNC path used later (`\\10.250.10.229\repository\...`).

### Settings → Repositories → Network file connections

Create a connection that tells TableScope how to authenticate to the share:

| Field | Example |
|---|---|
| Name | `VPN SMB Repository` |
| Protocol | `smb` |
| Host | `10.250.10.229` |
| Port | `445` |
| Share | `repository` |
| Domain | (blank, or `WORKGROUP`) |
| Username | `tablescope` |
| Password | `Tablescope123!` |

Save the connection and use **Test access** to confirm that TableScope can open the share. The test goes through the full VPN/SMB egress path, so it is a good end-to-end smoke test.

### Data Source Builder → Network Repositories

In the Data Source Builder, choose the **Network Repositories** category, select the saved connection, and click **Browse**. The file picker lists the share contents. Pick a CSV/Excel file and import it. The file is not staged as a snapshot; it becomes a **live source** that the tenant Teiid reads at query time through `/internal/file-proxy`.

---

## 2. AWS-side prerequisites

### Required AWS resources

| Resource | Purpose |
|---|---|
| Customer Gateway | The public IP of the customer's VPN gateway (`54.177.197.34` in the E2E example) |
| Transit Gateway (TGW) | TableScope's shared TGW that the tenant VPC and the VPN attach to |
| Site-to-Site VPN Connection | Two tunnels between AWS VGW and the customer gateway |
| TGW VPN Attachment | Attachment that the VPN is bound to inside the TGW |
| TGW route tables | At minimum: one shared route table, one per-tenant route table |
| Security groups / NACLs | Allow `TCP/445` and `TCP/22` from the tenant source range to the customer LAN |
| IAM role for platform-api | If TableScope auto-provisions the VPN, the platform worker needs `ec2:CreateVpnConnection`, `ec2:CreateCustomerGateway`, `ec2:CreateTransitGatewayVpcAttachment`, `ec2:CreateTransitGatewayRoute`, `ec2:Describe*`, etc. |

### Critical routing detail

The **shared TGW route table** must have a static route for the customer on-premises CIDR pointing at the **VPN attachment**, not `blackhole`.

Example (live E2E values):

```bash
aws ec2 create-transit-gateway-route \
  --transit-gateway-route-table-id tgw-rtb-0f8d4e7c849d3b137 \
  --destination-cidr-block 10.250.0.0/16 \
  --transit-gateway-attachment-id tgw-attach-03577ca399cc436cd
```

If this route is `blackhole`, IKE/phase-1 may still show `UP`, but **no TCP/ICMP/SMB traffic crosses the tunnel**.

### Required CIDRs

| Network | Example CIDR | Notes |
|---|---|---|
| TableScope shared VPC | `172.31.0.0/16` | Where the platform EC2 instance lives |
| Tenant Docker subnet | `172.30.20.0/24` | One per tenant data plane; the SMB socket binds to an IP in this range and is MASQUERADEd to the host |
| Customer LAN / SMB subnet | `10.250.0.0/16` | Must be allowed in `tenant_data_planes.allowed_onprem_cidrs` and in the TGW route table |

The customer gateway (strongSwan) must declare `rightsubnet` to include both `172.31.0.0/16` **and** the tenant Docker range (`172.30.0.0/16` or the specific tenant subnet). If the phase-2 selector does not cover the source IP after Docker MASQUERADE, the packets are dropped by the VPN gateway.

---

## 3. Customer / on-premises gateway prerequisites

### Gateway host

- A Linux host with `iptables` MASQUERADE enabled for packets leaving toward the SMB server.
- IP forwarding enabled (`net.ipv4.ip_forward=1`).
- `send_redirects` disabled (`net.ipv4.conf.all.send_redirects=0`).

### strongSwan / ipsec.conf example (IKEv1)

```text
config setup
    charondebug="ike 2, knl 2, cfg 2"

conn aws-tunnel1
    type=tunnel
    auto=start
    keyexchange=ikev1
    authby=secret
    left=%defaultroute
    leftid=<CUSTOMER_GATEWAY_PUBLIC_IP>
    right=<AWS_TUNNEL_1_OUTSIDE_IP>
    rightid=<AWS_TUNNEL_1_OUTSIDE_IP>
    leftsubnet=10.250.0.0/16
    rightsubnet=172.31.0.0/16,172.30.0.0/16
    ike=aes256-sha256-modp2048
    esp=aes256-sha256-modp2048
    ikelifetime=28800s
    lifetime=3600s
    dpddelay=10
    dpdtimeout=30
    dpdaction=restart
    keyingtries=%forever
    closeaction=restart
    phase2=esp
    pfs=yes
    reqid=1
```

Repeat for `aws-tunnel2` with the second AWS outside IP.

`/etc/ipsec.secrets`:

```text
<CUSTOMER_GATEWAY_IP> <AWS_TUNNEL_1_OUTSIDE_IP> : PSK "<TUNNEL_1_PSK>"
<CUSTOMER_GATEWAY_IP> <AWS_TUNNEL_2_OUTSIDE_IP> : PSK "<TUNNEL_2_PSK>"
```

The `rightsubnet` must include every CIDR that TableScope traffic may appear from. Because the `platform-api`/`platform-api-worker` containers bind their SMB socket to the tenant Docker subnet and the host then MASQUERADEs them, the source IP seen by the customer gateway is the TableScope EC2 host IP (`172.31.x.x`). Keep `172.30.0.0/16` in `rightsubnet` anyway, because direct container-to-tunnel routing and future changes may use it.

### SMB server

- Runs SMB2/SMB3 on `TCP/445`.
- Accepts the TableScope service account (e.g. `tablescope` / `Tablescope123!`).
- Has the repository data under a share such as `repository`.
- If using `dperson/samba`, a working launch form is:

```bash
docker run -d --name samba --network host \
  -v /srv/repository:/share \
  dperson/samba:4.18 \
  -u "tablescope;Tablescope123!" \
  -s "repository;/share;yes;no;yes;tablescope;tablescope;tablescope" \
  -p
```

### Gateway routing from tunnel to SMB

If the SMB server is not on the gateway host itself, the gateway must route `10.250.0.0/16` traffic to the SMB host and SNAT/MASQUERADE return traffic. In the E2E simulator, the Samba container runs with `network_mode: host`, so its IP is the gateway host IP and no extra forwarding is needed.

---

## 4. Non-UI TableScope configuration

The following cannot be done from the Settings UI and must be in place before network imports work.

### 4.1 Environment variables on `platform-api` and `platform-api-worker`

In `/home/ubuntu/tablescope/.env` (or the runtime environment):

```bash
FILE_IMPORT_NETWORK_ENABLED=true
FILE_IMPORT_ALLOWED_SMB_HOSTS=10.250.10.229
FILE_IMPORT_NETWORK_SOURCE_CIDRS=172.30.0.0/16
```

- `FILE_IMPORT_NETWORK_ENABLED=true` turns on network imports globally.
- `FILE_IMPORT_ALLOWED_SMB_HOSTS` is a deployment-level fallback allowlist. It is merged with the per-tenant hosts in **Settings → Repositories → Allowed SMB hosts**.
- `FILE_IMPORT_NETWORK_SOURCE_CIDRS` is an operator bypass for `/internal/file-proxy` source-IP validation. The tenant Docker subnet is checked first, but this CIDR covers the MASQUERADEd host IP if the proxy is ever reached from a non-container path.

### 4.2 Docker network attachment

`platform-api` and `platform-api-worker` must be attached to the per-tenant Docker network (e.g. `tenant_vpn-smb-e2e_net`) in `docker-compose.yml`:

```yaml
services:
  platform-api:
    networks:
      - default
      - tenant_vpn-smb-e2e_net
  platform-api-worker:
    networks:
      - default
      - tenant_vpn-smb-e2e_net

networks:
  tenant_vpn-smb-e2e_net:
    external: true
```

This is required for `tenant_network_source_ip.py` to find an IP in the tenant Docker subnet so the SMB socket can be bound to it.

### 4.3 Tenant data-plane record

The `tenant_data_planes` row for the tenant must have:

- `allowed_onprem_cidrs = ["10.250.0.0/16"]`
- `docker_subnet_cidr = "172.30.20.0/24"`

The Docker subnet CIDR is used to select the source IP. The on-prem CIDRs are used by the host `DOCKER-USER` `iptables` chain to decide which destinations each tenant's traffic is allowed to reach.

### 4.4 Host `iptables` / `DOCKER-USER` MASQUERADE

The TableScope EC2 host must MASQUERADE traffic from the tenant Docker subnet so the customer gateway sees a source IP in `172.31.0.0/16`. A representative rule is:

```bash
iptables -t nat -A POSTROUTING -s 172.30.20.0/24 ! -o docker0 -j MASQUERADE
```

The per-tenant `DOCKER-USER` chain should allow outbound `TCP/445` to `10.250.0.0/16` for source subnet `172.30.20.0/24` and drop everything else from that subnet to non-approved CIDRs.

### 4.5 WildFly / remote-file resource adapter

The tenant Teiid container needs the `remote-file` Java resource adapter configured in `standalone-teiid.xml` with `ProxyBaseUrl` pointing at `http://platform-api:8000/internal/file-proxy`:

```xml
<resource-adapter id="remote-file">
  <module slot="main" id="cloud.tablescope.remote-file"/>
  <connection-definitions>
    <connection-definition class-name="cloud.tablescope.remote.RemoteFileManagedConnectionFactory" ...>
      <config-property name="ProxyBaseUrl">http://platform-api:8000/internal/file-proxy</config-property>
    </connection-definition>
  </connection-definitions>
</resource-adapter>
```

The `platform-api` DNS name resolves inside the tenant Docker network.

### 4.6 Teiid VDB and `UserVDB` row

For each tenant user, there must be a `UserVDB` row pointing at the tenant's Teiid container. If a tenant was created before the VPN/SMB feature landed, run a finalization import or call the provisioning path so the platform creates the row (`vdb_id`, `vdb_host`, `vdb_port`). Without this row, the Data Source Builder shows **"No VDB configured"** even though the VDB file exists.

### 4.7 `FileSourceMeta` live-source parameters

When a network import is finalized, the platform should create a `FileSourceMeta` row with `live_source_params` containing the durable locator:

```json
{
  "type": "network_path",
  "connection_id": 1,
  "path": "//10.250.10.229/repository/sample.csv"
}
```

The `path` must be a full `//host/share/file` locator (or `smb://` / `\\` equivalent). A bare filename is not enough because the proxy resolves it against the saved `network_file_connection`.

The network connection must have `require_signing = true` for the `smbprotocol` library to authenticate successfully against a default `dperson/samba` server.

### 4.8 TableScope host source/dest check

On the TableScope EC2 instance, **source/destination check must be disabled** if `platform-api` containers are routing through the host and being MASQUERADEd.

---

## 5. Live / persistent behavior

With the live `remote-file` resource adapter, the file is **not** downloaded once and staged. Instead:

1. The tenant Teiid VDB view calls `RemoteCSVSourceModel.getTextFiles('remote://ds:<file_source_meta_id>')`.
2. The resource adapter issues `GET /internal/file-proxy?data_source_id=<id>`.
3. `platform-api` looks up `FileSourceMeta.live_source_params` and streams the file from the SMB share.
4. The SMB socket is bound to the tenant Docker-network IP (`172.30.20.2`).
5. The host MASQUERADEs the packet to `172.31.15.57` and sends it through the VPN tunnel.
6. The customer gateway decrypts it and forwards it to the Samba server.

This means modifying `\\10.250.10.229\repository\sample.csv` and re-running `SELECT * FROM "sample_CSV"` returns the new data immediately, without re-importing.

### Verified example

```text
SELECT * FROM "sample_CSV" LIMIT 5
-- returns ('1', 'test')

# On the simulator:
echo -e 'id,name\n1,alpha\n2,beta' > /srv/repository/sample.csv

SELECT * FROM "sample_CSV" LIMIT 5
-- returns ('1', 'alpha'), ('2', 'beta')
```

---

## 6. Troubleshooting checklist

| Symptom | Likely cause | Fix |
|---|---|---|
| `nc -vz 10.250.10.229 445` times out from `platform-api` | VPN tunnel down or TGW route blackhole | Check `aws ec2 describe-vpn-connections` for `VgwTelemetry` state; ensure TGW route for `10.250.0.0/16` points to the VPN attachment and is `active` |
| `smbclient` works from host but `smbprotocol` returns `STATUS_ACCESS_DENIED` | `require_signing=false` in `network_file_connections` | Set `require_signing=true` on the connection |
| `Live source not found` from Teiid | `FileSourceMeta` row missing or `live_source_params` is wrong | Re-finalize or insert `FileSourceMeta` with full `//host/share/file` locator |
| `No VDB configured` in the builder | Missing `UserVDB` row for tenant/user | Run a finalization import or provision the user VDB |
| `Forbidden` from `/internal/file-proxy` | Caller IP not in tenant Docker subnet or `FILE_IMPORT_NETWORK_SOURCE_CIDRS` | Attach `platform-api`/`worker` to the tenant network; verify `request.client.host` is `172.30.20.x` |
| Query returns old data after file changed | Import was a staged snapshot, not a live source | Re-import through the Network Repositories path |
| SMB host not listed in builder | Not in allowed hosts list | Add it in **Settings → Repositories → Allowed SMB hosts** or `FILE_IMPORT_ALLOWED_SMB_HOSTS` |
| strongSwan shows `UP` but no traffic | `rightsubnet` does not cover `172.30.0.0/16` | Add `172.30.0.0/16` to `rightsubnet` on both tunnels |

---

## Summary: what is needed in addition to the TableScope UI?

- AWS: Customer Gateway, Site-to-Site VPN, Transit Gateway, route tables, security groups, and correct TGW routes.
- Customer gateway: strongSwan configured with the right `leftsubnet`/`rightsubnet` and a reachable SMB share.
- TableScope host: Docker network attachment for `platform-api`/`worker`, `iptables` MASQUERADE + `DOCKER-USER` tenant chain, and source/dest check disabled.
- TableScope env: `FILE_IMPORT_NETWORK_ENABLED=true`, `FILE_IMPORT_ALLOWED_SMB_HOSTS`, and `FILE_IMPORT_NETWORK_SOURCE_CIDRS`.
- Tenant record: `allowed_onprem_cidrs` and `docker_subnet_cidr`.
- Teiid: `remote-file` resource adapter installed and `UserVDB` row created against the tenant container.
- Data integrity: `FileSourceMeta` created with a full `//host/share/file` `live_source_params` and `network_file_connections.require_signing=true`.
