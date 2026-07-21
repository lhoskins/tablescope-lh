"""Tests for the branded transactional email template system."""

from __future__ import annotations

import pytest

from app.services.email import (
    MissingTemplateVariableError,
    TemplateNotFoundError,
    render_transactional_email,
    send_transactional_email,
)
from app.services.email.templates import TEMPLATES

_SAMPLE: dict[str, str] = {
    "first_name": "Leonard",
    "confirmation_link": "https://app.tablescope.cloud/confirm?token=abc",
    "expiration_time": "24 hours",
    "workspace_name": "Acme Workspace",
    "tenant_name": "Acme Corp",
    "tenant_slug": "acme",
    "admin_email": "admin@acme.example",
    "workspace_url": "https://app.tablescope.cloud/acme",
    "password_setup_link": "https://app.tablescope.cloud/acme/set-password?token=t",
    "inviter_name": "Dana",
    "role_name": "Editor",
    "invitation_link": "https://app.tablescope.cloud/invite?token=t",
    "expiration_date": "Jun 30, 2026",
    "started_at": "Jun 23, 2026 9:20 AM",
    "vpn_information_link": "https://app.tablescope.cloud/onboarding/vpn?request=1",
    "support_contact_email": "support@tablescope.cloud",
    "account_name": "Acme Corp",
    "plan_name": "Enterprise",
    "payment_amount": "$1,200.00",
    "payment_date": "Jun 23, 2026",
    "payment_attempt_date": "Jun 23, 2026",
    "invoice_number": "INV-1",
    "invoice_link": "https://billing.tablescope.cloud/i/1",
    "billing_portal_link": "https://billing.tablescope.cloud/portal",
    "reset_link": "https://app.tablescope.cloud/reset?token=t",
    "data_source_name": "sales_data.csv",
    "project_url": "https://app.tablescope.cloud/projects/1",
    "project_name": "Boeing",
    "actor_name": "Dana",
}


@pytest.mark.parametrize("name", sorted(TEMPLATES))
def test_every_template_renders_html_and_text(name: str) -> None:
    rendered = render_transactional_email(name, _SAMPLE)
    assert rendered.subject
    assert rendered.html.startswith("<!DOCTYPE html>")
    assert "Tablescope" in rendered.html
    assert rendered.text.strip()
    # Plain text must not contain raw HTML tags from the layout.
    assert "<table" not in rendered.text


def test_missing_required_variable_raises() -> None:
    with pytest.raises(MissingTemplateVariableError):
        render_transactional_email("account_confirmation", {"first_name": "X"})


def test_unknown_template_raises() -> None:
    with pytest.raises(TemplateNotFoundError):
        render_transactional_email("does_not_exist", _SAMPLE)


def test_combined_onboarding_uses_password_cta() -> None:
    rendered = render_transactional_email(
        "workspace_ready_with_password_setup", _SAMPLE
    )
    assert rendered.subject == "Your Tablescope workspace is ready"
    assert "Create your password" in rendered.html
    assert _SAMPLE["password_setup_link"] in rendered.html
    assert "Create your password" in rendered.text
    # The combined email shows the workspace URL but does not use a login CTA.
    assert "Sign in" not in rendered.html


def test_html_escapes_injected_values() -> None:
    rendered = render_transactional_email(
        "workspace_ready",
        {
            "first_name": "<script>x</script>",
            "workspace_name": "<b>Acme</b>",
            "tenant_name": "Acme",
            "workspace_url": "https://app.tablescope.cloud/acme",
        },
    )
    assert "<script>" not in rendered.html
    assert "&lt;script&gt;" in rendered.html


def test_preview_text_present_in_html() -> None:
    rendered = render_transactional_email("account_confirmation", _SAMPLE)
    assert rendered.preview_text
    assert rendered.preview_text in rendered.html


@pytest.mark.asyncio
async def test_send_records_when_email_not_configured(monkeypatch) -> None:
    # Default test settings have no SMTP host configured.
    result = await send_transactional_email(
        to="user@example.com",
        template="account_confirmation",
        variables=_SAMPLE,
    )
    assert result.delivered is False
    assert result.recipient == "user@example.com"
    assert result.template == "account_confirmation"
