"""Branded transactional email for billing/provisioning lifecycle.

Sends via SMTP when configured; otherwise records intent (recipient + template)
without delivering. Magic/invite links are treated as credentials and are NEVER
logged — only the recipient address and template name are logged.
"""

from __future__ import annotations

import smtplib
from dataclasses import dataclass
from email.message import EmailMessage

import structlog
from anyio import to_thread

from app.config import get_settings

logger = structlog.get_logger("tablescope.email")


@dataclass(slots=True)
class EmailMessageSpec:
    to: str
    subject: str
    body: str


def _footer() -> str:
    s = get_settings()
    return f"\n\n—\nTablescope • Need help? {s.support_email}\n"


def render_root_admin_invite(
    *, company_name: str, tier_display: str, invite_link: str | None, login_url: str
) -> EmailMessageSpec:
    cta = (
        f"Accept your invite and set up access:\n{invite_link}\n"
        if invite_link
        else f"Sign in to get started:\n{login_url}\n"
    )
    body = (
        f"Welcome to Tablescope, and thanks for choosing the {tier_display} plan "
        f"for {company_name}.\n\n"
        f"You've been added as the root administrator of your new workspace.\n\n"
        f"{cta}"
        f"{_footer()}"
    )
    return EmailMessageSpec(to="", subject="You're invited to Tablescope", body=body)


def render_user_invite(
    *, company_name: str, role: str, invite_link: str | None, login_url: str
) -> EmailMessageSpec:
    cta = (
        f"Set up your account and choose a password:\n{invite_link}\n"
        if invite_link
        else f"Sign in to get started:\n{login_url}\n"
    )
    body = (
        f"You've been added to the {company_name} workspace on Tablescope "
        f"as a {role}.\n\n"
        f"{cta}"
        f"{_footer()}"
    )
    return EmailMessageSpec(
        to="", subject="Set up your Tablescope account", body=body
    )


def render_tenant_ready(*, company_name: str, login_url: str) -> EmailMessageSpec:
    body = (
        f"Your Tablescope workspace for {company_name} is ready.\n\n"
        f"Sign in here:\n{login_url}\n"
        f"{_footer()}"
    )
    return EmailMessageSpec(to="", subject="Your Tablescope workspace is ready", body=body)


def render_vpn_info_required(*, company_name: str, onboarding_url: str) -> EmailMessageSpec:
    body = (
        f"Your isolated data plane for {company_name} is provisioned. To finish "
        f"connecting your on-prem network over site-to-site VPN, we need a few "
        f"network details.\n\n"
        f"Complete VPN onboarding here:\n{onboarding_url}\n"
        f"{_footer()}"
    )
    return EmailMessageSpec(
        to="", subject="Action needed: VPN onboarding for Tablescope", body=body
    )


def render_payment_failed(*, company_name: str) -> EmailMessageSpec:
    body = (
        f"We were unable to process the latest payment for {company_name}'s "
        f"Tablescope subscription. Please update your payment method to avoid "
        f"interruption.\n"
        f"{_footer()}"
    )
    return EmailMessageSpec(to="", subject="Payment failed for Tablescope", body=body)


def render_subscription_cancelled(*, company_name: str) -> EmailMessageSpec:
    body = (
        f"Your Tablescope subscription for {company_name} has been cancelled. "
        f"Your workspace has been suspended but your data is retained. Contact "
        f"support to reactivate.\n"
        f"{_footer()}"
    )
    return EmailMessageSpec(to="", subject="Your Tablescope subscription was cancelled", body=body)


class EmailService:
    def __init__(self) -> None:
        self._settings = get_settings()

    async def send(self, spec: EmailMessageSpec, *, to: str, template: str) -> bool:
        """Send an email. Returns True if delivered, False if only recorded.

        Never logs the email body (it may contain invite/magic links).
        """
        s = self._settings
        if not s.email_configured:
            logger.info(
                "email_recorded_not_sent", recipient=to, template=template
            )
            return False

        msg = EmailMessage()
        msg["From"] = s.email_from
        msg["To"] = to
        msg["Subject"] = spec.subject
        msg.set_content(spec.body)

        def _send() -> None:
            with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=20) as server:
                if s.smtp_use_tls:
                    server.starttls()
                if s.smtp_username:
                    server.login(s.smtp_username, s.smtp_password)
                server.send_message(msg)

        await to_thread.run_sync(_send)
        logger.info("email_sent", recipient=to, template=template)
        return True
