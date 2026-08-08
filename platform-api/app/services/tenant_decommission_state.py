"""Tenant decommission state machine definitions and transition rules."""

from __future__ import annotations


class DecommissionError(Exception):
    """Raised when a decommission operation cannot proceed."""

    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


# ---------------------------------------------------------------------------
# Terminal states
# ---------------------------------------------------------------------------
STATUS_COMPLETED = "completed"
STATUS_CANCELLED = "cancelled"

# ---------------------------------------------------------------------------
# Failure states (resumable)
# ---------------------------------------------------------------------------
STATUS_PREFLIGHT_BLOCKED = "preflight_blocked"
STATUS_TERRAFORM_PLAN_REJECTED = "terraform_plan_rejected"
STATUS_TERRAFORM_APPLY_FAILED = "terraform_apply_failed"
STATUS_AWS_VERIFICATION_FAILED = "aws_verification_failed"
STATUS_RUNTIME_CLEANUP_FAILED = "runtime_cleanup_failed"
STATUS_DATA_CLEANUP_FAILED = "data_cleanup_failed"

# ---------------------------------------------------------------------------
# In-progress states
# ---------------------------------------------------------------------------
STATUS_REQUESTED = "requested"
STATUS_PREFLIGHT_RUNNING = "preflight_running"
STATUS_TENANT_FROZEN = "tenant_frozen"
STATUS_TERRAFORM_PLAN_RUNNING = "terraform_plan_running"
STATUS_AWAITING_APPROVAL = "awaiting_approval"
STATUS_TERRAFORM_APPLY_RUNNING = "terraform_apply_running"
STATUS_AWS_VERIFICATION_RUNNING = "aws_verification_running"
STATUS_AWS_DESTROYED = "aws_destroyed"
STATUS_RUNTIME_CLEANUP_RUNNING = "runtime_cleanup_running"
STATUS_DATA_CLEANUP_RUNNING = "data_cleanup_running"

NON_RESUMABLE_STATES = {STATUS_COMPLETED, STATUS_CANCELLED}

_VALID_TRANSITIONS: dict[str, set[str]] = {
    STATUS_REQUESTED: {STATUS_PREFLIGHT_RUNNING, STATUS_PREFLIGHT_BLOCKED, STATUS_CANCELLED},
    STATUS_PREFLIGHT_RUNNING: {STATUS_TENANT_FROZEN, STATUS_PREFLIGHT_BLOCKED},
    STATUS_PREFLIGHT_BLOCKED: {STATUS_CANCELLED, STATUS_REQUESTED},
    STATUS_TENANT_FROZEN: {STATUS_TERRAFORM_PLAN_RUNNING, STATUS_AWAITING_APPROVAL, STATUS_CANCELLED},
    STATUS_TERRAFORM_PLAN_RUNNING: {STATUS_AWAITING_APPROVAL, STATUS_TERRAFORM_PLAN_REJECTED},
    STATUS_TERRAFORM_PLAN_REJECTED: {STATUS_TERRAFORM_PLAN_RUNNING, STATUS_CANCELLED},
    STATUS_AWAITING_APPROVAL: {STATUS_TERRAFORM_APPLY_RUNNING, STATUS_CANCELLED},
    STATUS_TERRAFORM_APPLY_RUNNING: {STATUS_AWS_VERIFICATION_RUNNING, STATUS_TERRAFORM_APPLY_FAILED},
    STATUS_TERRAFORM_APPLY_FAILED: {STATUS_TERRAFORM_APPLY_RUNNING, STATUS_CANCELLED},
    STATUS_AWS_VERIFICATION_RUNNING: {STATUS_AWS_DESTROYED, STATUS_AWS_VERIFICATION_FAILED},
    STATUS_AWS_VERIFICATION_FAILED: {STATUS_AWS_VERIFICATION_RUNNING, STATUS_CANCELLED},
    STATUS_AWS_DESTROYED: {STATUS_RUNTIME_CLEANUP_RUNNING, STATUS_DATA_CLEANUP_RUNNING},
    STATUS_RUNTIME_CLEANUP_RUNNING: {STATUS_DATA_CLEANUP_RUNNING, STATUS_RUNTIME_CLEANUP_FAILED},
    STATUS_RUNTIME_CLEANUP_FAILED: {STATUS_RUNTIME_CLEANUP_RUNNING},
    STATUS_DATA_CLEANUP_RUNNING: {STATUS_COMPLETED, STATUS_DATA_CLEANUP_FAILED},
    STATUS_DATA_CLEANUP_FAILED: {STATUS_DATA_CLEANUP_RUNNING},
    # Special transitions from any pre-apply state to cancelled.
    STATUS_CANCELLED: set(),
    STATUS_COMPLETED: set(),
}


def can_transition(from_status: str, to_status: str) -> bool:
    """Return True if ``to_status`` is a legal next state for ``from_status``."""
    if from_status == to_status:
        return True
    if to_status == STATUS_CANCELLED:
        return from_status not in {
            STATUS_TERRAFORM_APPLY_RUNNING,
            STATUS_AWS_VERIFICATION_RUNNING,
            STATUS_AWS_DESTROYED,
            STATUS_RUNTIME_CLEANUP_RUNNING,
            STATUS_DATA_CLEANUP_RUNNING,
            STATUS_TERRAFORM_APPLY_FAILED,
            STATUS_AWS_VERIFICATION_FAILED,
            STATUS_RUNTIME_CLEANUP_FAILED,
            STATUS_DATA_CLEANUP_FAILED,
            STATUS_COMPLETED,
            STATUS_CANCELLED,
        }
    return to_status in _VALID_TRANSITIONS.get(from_status, set())
