"""Least-privileged decommission runner contract.

The application API coordinates state in PostgreSQL. The runner is a separate
process/host that performs privileged Terraform and host operations. It receives
a short-lived signed payload from the API that binds it to a single job, tenant,
and infrastructure SHA. The runner returns signed callbacks; the API verifies
the signature before accepting any state change.
"""

from __future__ import annotations

import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.config import get_settings


class RunnerAuthError(Exception):
    """Raised when a runner payload signature is invalid or expired."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _secret() -> str:
    return get_settings().decommission_runner_secret or get_settings().tablescope_secret_key


def _make_signature(*, payload_json: str, timestamp: str, secret: str) -> str:
    """Produce an HMAC-SHA256 hex signature over the canonical string."""
    mac = hmac.new(secret.encode(), digestmod="sha256")
    mac.update(timestamp.encode())
    mac.update(b".")
    mac.update(payload_json.encode())
    return mac.hexdigest()


def _now_timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


@dataclass(slots=True, frozen=True)
class RunnerPayload:
    job_id: str
    tenant_slug: str
    data_plane_tenant_id: str | None
    state_key: str
    application_sha: str
    infrastructure_sha: str
    expected_aws_ids: dict[str, str | None]
    issued_at: str
    expires_at: str
    signature: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "tenant_slug": self.tenant_slug,
            "data_plane_tenant_id": self.data_plane_tenant_id,
            "state_key": self.state_key,
            "application_sha": self.application_sha,
            "infrastructure_sha": self.infrastructure_sha,
            "expected_aws_ids": self.expected_aws_ids,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "signature": self.signature,
        }


def create_runner_payload(
    *,
    job_id: str,
    tenant_slug: str,
    data_plane_tenant_id: str | None,
    state_key: str,
    application_sha: str,
    infrastructure_sha: str,
    expected_aws_ids: dict[str, str | None] | None = None,
    ttl_seconds: int = 600,
) -> RunnerPayload:
    """Build and sign a payload for the decommission runner.

    ``expected_aws_ids`` maps resource types (e.g. ``aws_vpc``, ``aws_vpn_connection``)
    to the IDs the runner must verify have been destroyed. ``state_key`` is the
    workflow status the runner is authorised to advance (e.g. ``terraform_plan``).
    """
    now = datetime.now(UTC)
    issued_at = now.strftime("%Y%m%dT%H%M%SZ")
    expires_at = (now + timedelta(seconds=ttl_seconds)).strftime("%Y%m%dT%H%M%SZ")
    body = {
        "job_id": job_id,
        "tenant_slug": tenant_slug,
        "data_plane_tenant_id": data_plane_tenant_id,
        "state_key": state_key,
        "application_sha": application_sha,
        "infrastructure_sha": infrastructure_sha,
        "expected_aws_ids": expected_aws_ids or {},
        "issued_at": issued_at,
        "expires_at": expires_at,
    }
    payload_json = json.dumps(body, sort_keys=True, separators=(",", ":"))
    signature = _make_signature(
        payload_json=payload_json, timestamp=issued_at, secret=_secret()
    )
    return RunnerPayload(
        job_id=job_id,
        tenant_slug=tenant_slug,
        data_plane_tenant_id=data_plane_tenant_id,
        state_key=state_key,
        application_sha=application_sha,
        infrastructure_sha=infrastructure_sha,
        expected_aws_ids=expected_aws_ids or {},
        issued_at=issued_at,
        expires_at=expires_at,
        signature=signature,
    )


def verify_runner_payload(payload: dict[str, Any]) -> RunnerPayload:
    """Verify a signed runner payload and return the validated contract."""
    signature = payload.get("signature", "")
    issued_at = payload.get("issued_at", "")
    expected = {
        "job_id": payload.get("job_id"),
        "tenant_slug": payload.get("tenant_slug"),
        "data_plane_tenant_id": payload.get("data_plane_tenant_id"),
        "state_key": payload.get("state_key"),
        "application_sha": payload.get("application_sha"),
        "infrastructure_sha": payload.get("infrastructure_sha"),
        "expected_aws_ids": payload.get("expected_aws_ids", {}),
        "issued_at": issued_at,
        "expires_at": payload.get("expires_at"),
    }
    payload_json = json.dumps(expected, sort_keys=True, separators=(",", ":"))
    computed = _make_signature(
        payload_json=payload_json, timestamp=issued_at, secret=_secret()
    )
    if not hmac.compare_digest(computed, signature):
        raise RunnerAuthError("Runner payload signature mismatch.")

    expires = datetime.strptime(expected["expires_at"], "%Y%m%dT%H%M%SZ").replace(
        tzinfo=UTC
    )
    if datetime.now(UTC) > expires:
        raise RunnerAuthError("Runner payload has expired.")

    return RunnerPayload(
        job_id=expected["job_id"],
        tenant_slug=expected["tenant_slug"],
        data_plane_tenant_id=expected["data_plane_tenant_id"],
        state_key=expected["state_key"],
        application_sha=expected["application_sha"],
        infrastructure_sha=expected["infrastructure_sha"],
        expected_aws_ids=expected["expected_aws_ids"],
        issued_at=expected["issued_at"],
        expires_at=expected["expires_at"],
        signature=signature,
    )
