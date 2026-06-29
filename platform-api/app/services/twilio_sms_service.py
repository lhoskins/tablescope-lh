"""Shared helpers for Twilio-backed SMS MFA.

OTP delivery + validation is handled by Twilio Verify (see
``twilio_verify_service``); this module holds the small pieces shared across the
MFA code: phone masking and the "Twilio not configured" error. Phone numbers are
masked in any log line and never stored in full.
"""

from __future__ import annotations


def mask_phone(phone: str | None) -> str:
    """Mask a phone number for logs/storage, e.g. ``+16615551212`` -> ``+1******1212``."""
    if not phone:
        return ""
    digits = phone.strip()
    if len(digits) <= 4:
        return "*" * len(digits)
    prefix = digits[:2]
    suffix = digits[-4:]
    return f"{prefix}{'*' * (len(digits) - 6)}{suffix}"


class TwilioConfigError(RuntimeError):
    """Raised when Twilio credentials are not configured."""
