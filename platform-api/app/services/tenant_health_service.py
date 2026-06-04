"""Per-tenant data-plane health checks (plan Phase 8).

Reports, best-effort, on the dimensions the plan calls out: VPN tunnel status,
Teiid container/health endpoint, VDB directory presence, firewall application,
and optional on-prem connectivity probes.

Checks that require host/root visibility (firewall chains, VDB path on the host)
or AWS credentials (VPN tunnel state) degrade gracefully to an ``unknown``
status with an explanatory message rather than failing the whole report.
"""

from __future__ import annotations

import asyncio
import os
import socket
import subprocess
from dataclasses import asdict, dataclass, field

import httpx

from app.models.tenant_data_plane import TenantDataPlane
from app.services.tenant_layout import compute_layout


@dataclass(slots=True)
class ConnectivityTest:
    target: str
    status: str  # reachable | unreachable | skipped
    detail: str | None = None


@dataclass(slots=True)
class TenantHealthReport:
    tenant_id: str
    vpn_status: str
    teiid_status: str
    firewall_status: str
    vdb_path_status: str
    connectivity_tests: list[ConnectivityTest] = field(default_factory=list)
    messages: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


class TenantHealthService:
    def __init__(self, *, timeout: float = 3.0) -> None:
        self._timeout = timeout

    async def check(
        self,
        plane: TenantDataPlane,
        *,
        connectivity_targets: list[str] | None = None,
    ) -> TenantHealthReport:
        report = TenantHealthReport(
            tenant_id=plane.tenant_id,
            vpn_status="unknown",
            teiid_status="unknown",
            firewall_status="unknown",
            vdb_path_status="unknown",
        )

        await asyncio.gather(
            self._check_vpn(plane, report),
            self._check_teiid(plane, report),
        )
        self._check_vdb_path(plane, report)
        self._check_firewall(plane, report)

        for target in connectivity_targets or []:
            report.connectivity_tests.append(await self._probe_tcp(target))

        return report

    async def _check_vpn(self, plane: TenantDataPlane, report: TenantHealthReport) -> None:
        if not plane.vpn_connection_id:
            report.vpn_status = "not_configured"
            return
        try:
            status = await asyncio.to_thread(self._describe_vpn, plane.vpn_connection_id)
            report.vpn_status = status
        except Exception as exc:
            report.vpn_status = "unknown"
            report.messages["vpn"] = f"could not query VPN: {exc}"

    @staticmethod
    def _describe_vpn(vpn_connection_id: str) -> str:
        import boto3  # imported lazily so tests/dev without AWS still load

        client = boto3.client("ec2")
        resp = client.describe_vpn_connections(VpnConnectionIds=[vpn_connection_id])
        conns = resp.get("VpnConnections", [])
        if not conns:
            return "missing"
        telemetry = conns[0].get("VgwTelemetry", [])
        states = [t.get("Status") for t in telemetry]
        if states and any(s == "UP" for s in states):
            return "up"
        if states:
            return "down"
        return conns[0].get("State", "unknown")

    async def _check_teiid(self, plane: TenantDataPlane, report: TenantHealthReport) -> None:
        # WildFly management/health endpoint.
        url = f"http://{plane.teiid_pg_host}:{plane.teiid_mgmt_port}/health"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(url)
            report.teiid_status = "healthy" if resp.status_code < 500 else "unhealthy"
        except Exception as exc:
            report.teiid_status = "unreachable"
            report.messages["teiid"] = f"{url}: {exc}"

    def _check_vdb_path(self, plane: TenantDataPlane, report: TenantHealthReport) -> None:
        try:
            report.vdb_path_status = "ok" if os.path.isdir(plane.vdb_host_path) else "missing"
        except OSError as exc:
            report.vdb_path_status = "unknown"
            report.messages["vdb_path"] = str(exc)

    def _check_firewall(self, plane: TenantDataPlane, report: TenantHealthReport) -> None:
        chain = compute_layout(plane.tenant_id, int(plane.docker_subnet_cidr.split(".")[2]) // 10).firewall_chain
        try:
            result = subprocess.run(
                ["iptables", "-S", chain],
                capture_output=True,
                text=True,
                timeout=self._timeout,
            )
            report.firewall_status = "applied" if result.returncode == 0 else "not_applied"
        except FileNotFoundError:
            report.firewall_status = "unknown"
            report.messages["firewall"] = "iptables not available in this context"
        except Exception as exc:
            report.firewall_status = "unknown"
            report.messages["firewall"] = str(exc)

    async def _probe_tcp(self, target: str) -> ConnectivityTest:
        host, _, port_s = target.partition(":")
        if not port_s:
            return ConnectivityTest(target=target, status="skipped", detail="expected host:port")
        try:
            port = int(port_s)
        except ValueError:
            return ConnectivityTest(target=target, status="skipped", detail="invalid port")
        try:
            fut = asyncio.open_connection(host, port)
            reader, writer = await asyncio.wait_for(fut, timeout=self._timeout)
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            return ConnectivityTest(target=target, status="reachable")
        except (TimeoutError, OSError, socket.gaierror) as exc:
            return ConnectivityTest(target=target, status="unreachable", detail=str(exc))
