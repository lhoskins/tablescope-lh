"""Twilio SMS delivery for MFA codes.

Sends through the Twilio **Messaging Service SID** (not a single from-number).
Credentials come from the environment and are never logged; the OTP body is
never logged. Phone numbers are masked in any log line.
"""

from __future__ import annotations

import logging

from app.config import get_settings

logger = logging.getLogger(__name__)


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


class TwilioSmsError(RuntimeError):
    """Raised when Twilio rejects or fails to send a message."""


class TwilioSmsService:
    """Thin wrapper over the Twilio REST client using a Messaging Service SID."""

    def __init__(self) -> None:
        settings = get_settings()
        if not settings.twilio_configured:
            raise TwilioConfigError(
                "Twilio is not configured (TWILIO_ACCOUNT_SID / TWILIO_API_KEY_SID "
                "/ TWILIO_API_KEY_SECRET / TWILIO_MESSAGING_SERVICE_SID)."
            )
        # Imported lazily so the dependency is only required where SMS is used.
        from twilio.rest import Client

        self.messaging_service_sid = settings.twilio_messaging_service_sid
        # API key auth: Client(api_key_sid, api_key_secret, account_sid).
        self.client = Client(
            settings.twilio_api_key_sid,
            settings.twilio_api_key_secret,
            settings.twilio_account_sid,
        )

    def send_mfa_code(self, *, to_phone: str, message: str) -> str:
        """Send the SMS and return the Twilio message SID. Never logs the body."""
        try:
            msg = self.client.messages.create(
                messaging_service_sid=self.messaging_service_sid,
                to=to_phone,
                body=message,
            )
        except Exception as exc:  # pragma: no cover - network/credential errors
            # Mask the destination; never include the OTP body or credentials.
            logger.warning("Twilio send failed to %s", mask_phone(to_phone))
            raise TwilioSmsError(str(exc)) from exc
        logger.info("Twilio MFA SMS sent to %s (sid=%s)", mask_phone(to_phone), msg.sid)
        return msg.sid
