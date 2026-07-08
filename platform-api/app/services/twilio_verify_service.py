"""Twilio Verify integration for SMS MFA.

Twilio Verify is the MFA primitive: it generates the OTP, sends the SMS, and
validates the entered code (handling expiry, attempt throttling, and channel
fallback). We never see or store the OTP. Credentials come from the environment
and are never logged; phone numbers are masked in any log line.

This replaces the Supabase phone-MFA factor + Send-SMS hook path, so no paid
Supabase add-on is required.
"""

from __future__ import annotations

import logging

from app.config import get_settings
from app.services.twilio_sms_service import TwilioConfigError, mask_phone

logger = logging.getLogger(__name__)


class TwilioVerifyError(RuntimeError):
    """Raised when Twilio Verify rejects or fails a request."""


class TwilioVerifyService:
    """Thin wrapper over Twilio Verify v2 using a Verify Service SID."""

    def __init__(self) -> None:
        settings = get_settings()
        if not settings.twilio_verify_configured:
            raise TwilioConfigError(
                "Twilio Verify is not configured (TWILIO_ACCOUNT_SID / "
                "TWILIO_API_KEY_SID / TWILIO_API_KEY_SECRET / "
                "TWILIO_VERIFY_SERVICE_SID)."
            )
        # Imported lazily so the dependency is only required where MFA is used.
        from twilio.rest import Client

        self.service_sid = settings.twilio_verify_service_sid
        # API key auth: Client(api_key_sid, api_key_secret, account_sid).
        self.client = Client(
            settings.twilio_api_key_sid,
            settings.twilio_api_key_secret,
            settings.twilio_account_sid,
        )

    def start_verification(self, *, to_phone: str) -> str:
        """Send an OTP via SMS. Returns the Twilio verification SID."""
        try:
            verification = self.client.verify.v2.services(
                self.service_sid
            ).verifications.create(to=to_phone, channel="sms")
        except Exception as exc:  # pragma: no cover - network/credential errors
            logger.warning("Twilio Verify start failed for %s", mask_phone(to_phone))
            raise TwilioVerifyError(str(exc)) from exc
        logger.info(
            "Twilio Verify started for %s (sid=%s, status=%s)",
            mask_phone(to_phone),
            verification.sid,
            verification.status,
        )
        return verification.sid

    def check_verification(self, *, to_phone: str, code: str) -> bool:
        """Check an OTP. Returns True only when Twilio reports ``approved``."""
        try:
            check = self.client.verify.v2.services(
                self.service_sid
            ).verification_checks.create(to=to_phone, code=code)
        except Exception as exc:  # pragma: no cover - network/credential errors
            # A 404 here means the verification expired or was already consumed;
            # treat any error as a failed check rather than leaking details.
            logger.info(
                "Twilio Verify check error for %s: %s",
                mask_phone(to_phone),
                type(exc).__name__,
            )
            return False
        return bool(getattr(check, "status", None) == "approved")
