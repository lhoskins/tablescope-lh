"""Multi-factor-authentication policy.

Twilio SMS (via Twilio Verify) is the primary MFA method. Owner / Admin / DB
Admin roles must complete an SMS challenge (assurance level ``aal2``) before they
can reach any tenant data or admin API; Members may enable MFA optionally.

Enforcement reads the ``aal`` claim on the first-party token. That claim is set
when an SMS code is verified (``/api/mfa/phone/verify`` mints an ``aal2`` token)
and re-derived at ``/auth/exchange`` from the user's verified-phone record while
its window is open (see :mod:`app.services.mfa_phone_service`). A missing ``aal``
claim is treated as ``aal1`` (not satisfied).
"""

from __future__ import annotations

# Roles for which SMS MFA is mandatory. Stored normalized (lowercase, spaces
# collapsed to underscores) so "DB Admin", "db admin" and "db_admin" all match.
ADMIN_MFA_ROLES = {
    "owner",
    "admin",
    "dbadmin",
    "db_admin",
    "root_admin",
    "tenant_admin",
}

AAL2 = "aal2"

# Preferred factor type surfaced to the client when MFA is required.
PREFERRED_FACTOR_TYPE = "phone"


def normalize_role(role: str | None) -> str:
    return (role or "").strip().lower().replace(" ", "_")


def role_requires_mfa(role: str | None) -> bool:
    """True when the role must complete SMS MFA before tenant access."""
    return normalize_role(role) in ADMIN_MFA_ROLES


def session_has_mfa(aal: str | None) -> bool:
    """True when the session has been upgraded to assurance level aal2."""
    return aal == AAL2


def mfa_required_for_request(role: str | None, aal: str | None) -> bool:
    """True when this caller's role demands MFA but the session lacks aal2."""
    return role_requires_mfa(role) and not session_has_mfa(aal)
