"""Central transactional email send path.

Sends a multipart (plain-text + HTML) message over SMTP when configured;
otherwise records intent (recipient + template) without delivering.  Sensitive
links and tokens are NEVER logged — only recipient address, template name, and
send status.
"""

from __future__ import annotations

import smtplib
from dataclasses import dataclass
from email.message import EmailMessage

import structlog
from anyio import to_thread

from app.config import get_settings
from app.services.email.render import render_transactional_email

logger = structlog.get_logger("tablescope.email")


@dataclass(slots=True)
class EmailSendResult:
    template: str
    recipient: str
    delivered: bool


async def send_transactional_email(
    *,
    to: str,
    template: str,
    variables: dict[str, str],
    subject: str | None = None,
    reply_to: str | None = None,
) -> EmailSendResult:
    """Render + send a branded transactional email.

    Returns an :class:`EmailSendResult`; ``delivered`` is False when email is
    not configured (the send is recorded but not delivered).
    """
    settings = get_settings()
    rendered = render_transactional_email(template, variables, subject=subject)

    if not settings.email_configured:
        logger.info(
            "email_recorded_not_sent", recipient=to, template=template
        )
        return EmailSendResult(template=template, recipient=to, delivered=False)

    msg = EmailMessage()
    msg["From"] = settings.email_from
    msg["To"] = to
    msg["Subject"] = rendered.subject
    resolved_reply_to = reply_to or settings.email_reply_to
    if resolved_reply_to:
        msg["Reply-To"] = resolved_reply_to
    # Plain text is the default body; HTML is the preferred alternative.
    msg.set_content(rendered.text)
    msg.add_alternative(rendered.html, subtype="html")

    def _send() -> None:
        with smtplib.SMTP(
            settings.smtp_host, settings.smtp_port, timeout=20
        ) as server:
            if settings.smtp_use_tls:
                server.starttls()
            if settings.smtp_username:
                server.login(settings.smtp_username, settings.smtp_password)
            server.send_message(msg)

    await to_thread.run_sync(_send)
    logger.info("email_sent", recipient=to, template=template)
    return EmailSendResult(template=template, recipient=to, delivered=True)
