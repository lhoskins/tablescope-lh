"""Validate a Terraform JSON plan for a tenant decommission.

A plan is approved only when every changed resource is either:
* inside the target tenant module, or
* a shared route keyed by the target tenant's on-prem CIDRs, or
* a shared hub resource update expected when a tenant is removed.

The validator rejects any creation, state move, provider replacement, destruction
of shared hub resources, or mutation of another tenant's resources.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_TARGET_MODULE_RE = re.compile(r'^module\.tenant\["([^"]+)"\]\.')
_SHARED_ROUTE_RE = re.compile(r'^module\.network_hub\[0\]\.aws_route\.shared_to_tgw\["([^"]+)"\]$')
_HUB_RESOURCE_RE = re.compile(r'^module\.network_hub\[0\]\.')


class PlanPolicyError(Exception):
    """Raised when a Terraform plan fails policy validation."""

    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


@dataclass(slots=True, frozen=True)
class PlanValidationResult:
    valid: bool
    proposed_destroy: list[str]
    proposed_update: list[str]
    shared_hub_would_be_destroyed: bool
    other_tenant_affected: bool
    validation_errors: list[str]


def _resource_tags(value: dict | None) -> dict:
    if not value:
        return {}
    tags = value.get("tags") or value.get("tag") or {}
    if isinstance(tags, list):
        # AWS provider occasionally normalises tags as a list of maps.
        return {t.get("key"): t.get("value") for t in tags if isinstance(t, dict)}
    return tags if isinstance(tags, dict) else {}


def validate_terraform_plan(
    plan_json: dict,
    *,
    target_tenant_id: str,
    target_onprem_cidrs: list[str],
    managed_by: str = "tablescope-tenant-dataplane",
) -> PlanValidationResult:
    """Validate that a Terraform plan only destroys the target tenant."""
    errors: list[str] = []
    destroy: list[str] = []
    update: list[str] = []
    hub_destroyed = False
    other_affected = False

    resource_changes = plan_json.get("resource_changes", [])
    if not resource_changes:
        errors.append("Plan contains no resource changes; nothing to decommission.")
        return PlanValidationResult(
            valid=False,
            proposed_destroy=[],
            proposed_update=[],
            shared_hub_would_be_destroyed=False,
            other_tenant_affected=False,
            validation_errors=errors,
        )

    target_seen = False
    expected_route_keys = {f"{target_tenant_id}-{idx}" for idx, _ in enumerate(target_onprem_cidrs)}

    for rc in resource_changes:
        address = rc.get("address", "")
        actions = rc.get("change", {}).get("actions", [])
        before = rc.get("change", {}).get("before") or {}

        if "no-op" in actions or "read" in actions:
            continue

        if "create" in actions or "replace" in actions:
            errors.append(f"Plan would create/replace resource: {address}")
            continue

        if "update" in actions:
            update.append(address)
            if _HUB_RESOURCE_RE.match(address):
                if not _SHARED_ROUTE_RE.match(address):
                    errors.append(
                        f"Plan would update shared hub resource: {address}"
                    )
                    hub_destroyed = True
            continue

        if "delete" not in actions:
            continue

        destroy.append(address)

        # Target tenant module resources are allowed to be destroyed.
        target_match = _TARGET_MODULE_RE.match(address)
        if target_match:
            tenant_in_address = target_match.group(1)
            if tenant_in_address != target_tenant_id:
                other_affected = True
                errors.append(
                    f"Plan deletes another tenant's resource: {address}"
                )
                continue
            target_seen = True
            tags = _resource_tags(before)
            if tags.get("Tenant") != target_tenant_id:
                errors.append(
                    f"Resource {address} does not have expected Tenant tag"
                )
            if tags.get("ManagedBy") != managed_by:
                errors.append(
                    f"Resource {address} does not have expected ManagedBy tag"
                )
            continue

        # Shared VPC route-table routes keyed by target tenant are allowed.
        shared_match = _SHARED_ROUTE_RE.match(address)
        if shared_match:
            key = shared_match.group(1)
            if key not in expected_route_keys:
                other_affected = True
                errors.append(
                    f"Plan removes a shared route that does not belong to target: {address}"
                )
            continue

        # Any other network_hub change is forbidden.
        if _HUB_RESOURCE_RE.match(address):
            hub_destroyed = True
            errors.append(
                f"Plan would modify the shared network hub: {address}"
            )
            continue

        # Anything outside the target module/shared routes is forbidden.
        other_affected = True
        errors.append(
            f"Plan affects an unrelated resource outside target tenant: {address}"
        )

    if not target_seen and not errors:
        errors.append("Plan does not contain any resources for the target tenant.")

    valid = len(errors) == 0
    return PlanValidationResult(
        valid=valid,
        proposed_destroy=destroy,
        proposed_update=update,
        shared_hub_would_be_destroyed=hub_destroyed,
        other_tenant_affected=other_affected,
        validation_errors=errors,
    )
