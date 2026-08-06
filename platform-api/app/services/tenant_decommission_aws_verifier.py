"""Verify AWS resource destruction after a Terraform apply.

This module is intentionally generic over the resource types created by the
tenant-vpc Terraform module. It polls with exponential back-off until every
expected resource is confirmed deleted or a timeout is reached.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import boto3
from botocore.exceptions import ClientError


@dataclass(slots=True, frozen=True)
class VerificationResult:
    resource_type: str
    resource_id: str
    address: str
    found: bool
    error: str | None


class AWSVerificationError(Exception):
    """Raised when expected resources are still present after verification."""

    def __init__(self, remaining: list[VerificationResult]) -> None:
        self.remaining = remaining
        super().__init__(f"{len(remaining)} resources were not destroyed.")


def _ec2() -> Any:
    return boto3.client("ec2")


def _check_vpc(vpc_id: str) -> bool:
    try:
        result = _ec2().describe_vpcs(VpcIds=[vpc_id])
        return len(result.get("Vpcs", [])) > 0
    except ClientError as exc:
        if "InvalidVpcID.NotFound" in str(exc):
            return False
        raise


def _check_subnet(subnet_id: str) -> bool:
    try:
        result = _ec2().describe_subnets(SubnetIds=[subnet_id])
        return len(result.get("Subnets", [])) > 0
    except ClientError as exc:
        if "InvalidSubnetID.NotFound" in str(exc):
            return False
        raise


def _check_customer_gateway(cgw_id: str) -> bool:
    try:
        result = _ec2().describe_customer_gateways(CustomerGatewayIds=[cgw_id])
        return len(result.get("CustomerGateways", [])) > 0
    except ClientError as exc:
        if "InvalidCustomerGatewayID.NotFound" in str(exc):
            return False
        raise


def _check_vpn_connection(vpn_id: str) -> bool:
    try:
        result = _ec2().describe_vpn_connections(VpnConnectionIds=[vpn_id])
        return len(result.get("VpnConnections", [])) > 0
    except ClientError as exc:
        if "InvalidVpnConnectionID.NotFound" in str(exc):
            return False
        raise


def _check_tgw_route_table(rt_id: str) -> bool:
    try:
        result = _ec2().describe_transit_gateway_route_tables(
            TransitGatewayRouteTableIds=[rt_id]
        )
        return len(result.get("TransitGatewayRouteTables", [])) > 0
    except ClientError as exc:
        if "InvalidTransitGatewayRouteTableID.NotFound" in str(exc):
            return False
        raise


def _check_security_group(sg_id: str) -> bool:
    try:
        result = _ec2().describe_security_groups(GroupIds=[sg_id])
        return len(result.get("SecurityGroups", [])) > 0
    except ClientError as exc:
        if "InvalidGroup.NotFound" in str(exc):
            return False
        raise


_CHECKERS = {
    "aws_vpc": _check_vpc,
    "aws_subnet": _check_subnet,
    "aws_customer_gateway": _check_customer_gateway,
    "aws_vpn_connection": _check_vpn_connection,
    "aws_ec2_transit_gateway_route_table": _check_tgw_route_table,
    "aws_security_group": _check_security_group,
}


async def verify_aws_destruction(
    expected_aws_ids: dict[str, list[tuple[str, str]]],
    *,
    max_attempts: int = 18,
    delay_seconds: float = 10.0,
) -> list[VerificationResult]:
    """Poll AWS until all resources in ``expected_aws_ids`` are gone.

    ``expected_aws_ids`` is structured as ``{resource_type: [(address, id), ...]}``.
    Returns a list of ``VerificationResult`` objects. Raises
    ``AWSVerificationError`` if any resource is still present after ``max_attempts``.
    """
    remaining = [
        (rtype, address, rid)
        for rtype, items in expected_aws_ids.items()
        for address, rid in items
    ]
    results: list[VerificationResult] = []

    for attempt in range(max_attempts):
        still_present: list[tuple[str, str, str]] = []
        for rtype, address, rid in remaining:
            checker = _CHECKERS.get(rtype)
            if checker is None:
                # Unknown resource type: skip verification, record as not found.
                results.append(
                    VerificationResult(
                        resource_type=rtype,
                        resource_id=rid,
                        address=address,
                        found=False,
                        error=None,
                    )
                )
                continue
            try:
                found = checker(rid)
            except ClientError as exc:
                results.append(
                    VerificationResult(
                        resource_type=rtype,
                        resource_id=rid,
                        address=address,
                        found=True,
                        error=str(exc),
                    )
                )
                still_present.append((rtype, address, rid))
                continue

            if found:
                still_present.append((rtype, address, rid))
            else:
                results.append(
                    VerificationResult(
                        resource_type=rtype,
                        resource_id=rid,
                        address=address,
                        found=False,
                        error=None,
                    )
                )

        if not still_present:
            return results

        remaining = still_present
        if attempt < max_attempts - 1:
            await asyncio.sleep(delay_seconds)

    # Final pass: build failure results for anything still present.
    for rtype, address, rid in remaining:
        results.append(
            VerificationResult(
                resource_type=rtype,
                resource_id=rid,
                address=address,
                found=True,
                error="Resource still present after verification timeout",
            )
        )
    raise AWSVerificationError(results)
