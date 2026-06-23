"""Injectable wrapper around the branded transactional email system.

Services that send lifecycle email (tenant onboarding, billing webhooks, user
invites) depend on :class:`EmailService` so the send path can be replaced with a
fake in tests.  The class delegates to
:func:`app.services.email.send_transactional_email`, which renders a branded
HTML + plain-text message and delivers it over SMTP.

Magic/invite links and tokens are treated as credentials and are NEVER logged —
only the recipient address, template name, and send status are logged.
"""

from __future__ import annotations

import structlog

from app.config import get_settings

logger = structlog.get_logger("tablescope.email")


class EmailService:
    def __init__(self) -> None:
        self._settings = get_settings()

    async def send_transactional_email(
        self,
        *,
        to: str,
        template: str,
        variables: dict[str, str],
        subject: str | None = None,
        reply_to: str | None = None,
    ) -> bool:
        """Render + send a branded transactional email by template name.

        Returns True when delivered, False when email is not configured (the
        send is recorded but not delivered).
        """
        from app.services.email import send_transactional_email

        result = await send_transactional_email(
            to=to,
            template=template,
            variables=variables,
            subject=subject,
            reply_to=reply_to,
        )
        return result.delivered
