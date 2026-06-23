"""Transactional email template registry.

Each template declares its subject, required variables, and a builder that maps
validated variables to an :class:`EmailContent` block structure.  Calling code
never builds raw HTML — it passes a template name + variables to
:func:`app.services.email.send_transactional_email`.

``required_vars`` are the variables a template cannot render meaningfully
without (typically the actionable link + primary identifier); rendering raises
:class:`MissingTemplateVariableError` when one is absent.  ``first_name`` is
always optional (the greeting degrades to "Hello,") and several detail fields
are optional — detail rows are only shown when a value is supplied.

To add a new transactional email: add an :class:`EmailTemplate` entry to
``TEMPLATES`` below.  See ``docs/transactional-emails.md``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.services.email.layout import CallToAction, EmailContent


class TemplateNotFoundError(KeyError):
    """Raised when an unknown template name is requested."""


class MissingTemplateVariableError(ValueError):
    """Raised when a template is rendered without a required variable."""


@dataclass(slots=True)
class EmailTemplate:
    name: str
    subject: str
    required_vars: tuple[str, ...]
    build: Callable[[dict[str, str]], EmailContent]


def _greeting(variables: dict[str, str]) -> str:
    name = (variables.get("first_name") or "").strip()
    return f"Hello {name}," if name else "Hello,"


def _opt_details(
    variables: dict[str, str],
    pairs: list[tuple[str, str]],
    *,
    extra: list[tuple[str, str]] | None = None,
) -> list[tuple[str, str]]:
    """Build a detail table, skipping rows whose value is empty/missing.

    ``extra`` rows hold literal (non-variable) values and are always appended.
    """
    out: list[tuple[str, str]] = []
    for label, key in pairs:
        value = str(variables.get(key, "")).strip()
        if value:
            out.append((label, value))
    if extra:
        out.extend(extra)
    return out


def _account_confirmation(v: dict[str, str]) -> EmailContent:
    expiry = (v.get("expiration_time") or "24 hours").strip()
    return EmailContent(
        title="Welcome to Tablescope",
        preview_text="Confirm your email address to finish setting up your "
        "Tablescope account.",
        greeting=_greeting(v),
        paragraphs=[
            "Thanks for creating a Tablescope account. Please confirm your "
            "email address to finish setting up your account.",
        ],
        cta=CallToAction("Confirm your account", v["confirmation_link"]),
        security_note=f"This link will expire in {expiry}.",
        fallback_note="If you did not create a Tablescope account, you can "
        "safely ignore this email.",
    )


def _workspace_ready(v: dict[str, str]) -> EmailContent:
    return EmailContent(
        title="Your Tablescope workspace is ready",
        preview_text="Your Tablescope workspace has been provisioned and is "
        "ready to use.",
        greeting=_greeting(v),
        paragraphs=[
            "Your Tablescope workspace has been provisioned and is ready to use.",
        ],
        details=_opt_details(
            v,
            [("Workspace", "workspace_name"), ("Tenant", "tenant_name")],
            extra=[("Status", "Ready")],
        ),
        cta=CallToAction("Open workspace", v["workspace_url"]),
    )


def _workspace_ready_password_setup(v: dict[str, str]) -> EmailContent:
    expiry = (v.get("expiration_time") or "24 hours").strip()
    return EmailContent(
        title="Your Tablescope workspace is ready",
        preview_text="Create your password to access your new Tablescope "
        "workspace.",
        greeting=_greeting(v),
        paragraphs=[
            "Your Tablescope workspace has been provisioned and is ready.",
            "To access your workspace, please create a password for your "
            "tenant admin account.",
        ],
        details=_opt_details(
            v,
            [
                ("Workspace", "workspace_name"),
                ("Tenant", "tenant_name"),
                ("Admin account", "admin_email"),
                ("Workspace URL", "workspace_url"),
            ],
            extra=[("Status", "Ready")],
        ),
        cta=CallToAction("Create your password", v["password_setup_link"]),
        security_note=f"This password setup link will expire in {expiry}.",
        fallback_note="If you were not expecting this Tablescope workspace, "
        "please ignore this email or contact Tablescope support.",
    )


def _user_invitation(v: dict[str, str]) -> EmailContent:
    inviter = (v.get("inviter_name") or "A Tablescope administrator").strip()
    workspace = (v.get("workspace_name") or "a Tablescope workspace").strip()
    role = (v.get("role_name") or "team member").strip()
    return EmailContent(
        title="You have been invited to Tablescope",
        preview_text="Accept your invitation to join a Tablescope workspace.",
        greeting=_greeting(v),
        paragraphs=[
            f"{inviter} invited you to join the {workspace} workspace on "
            f"Tablescope as a {role}.",
        ],
        details=_opt_details(
            v,
            [
                ("Workspace", "workspace_name"),
                ("Invited by", "inviter_name"),
                ("Role", "role_name"),
                ("Expiration date", "expiration_date"),
            ],
        ),
        cta=CallToAction("Accept invitation", v["invitation_link"]),
        fallback_note="If you were not expecting this invitation, you can "
        "ignore this email.",
    )


def _tenant_provisioning_started(v: dict[str, str]) -> EmailContent:
    cta = (
        CallToAction("View setup status", v["workspace_url"])
        if v.get("workspace_url")
        else None
    )
    return EmailContent(
        title="Tablescope tenant provisioning started",
        preview_text="We have started setting up your Tablescope tenant.",
        greeting=_greeting(v),
        paragraphs=[
            "We have started preparing your Tablescope workspace, including "
            "database isolation, user access, and required application "
            "settings. We will let you know as soon as it is ready.",
        ],
        details=_opt_details(
            v,
            [
                ("Tenant name", "tenant_name"),
                ("Tenant slug", "tenant_slug"),
                ("Started", "started_at"),
            ],
            extra=[("Status", "Provisioning")],
        ),
        cta=cta,
    )


def _vpn_setup_information_required(v: dict[str, str]) -> EmailContent:
    support = v.get("support_contact_email")
    return EmailContent(
        title="Tablescope VPN setup information required",
        preview_text="We need additional network details to complete your VPN "
        "setup.",
        greeting=_greeting(v),
        paragraphs=[
            "To complete your secure private connectivity, we need a few "
            "network details from your team.",
        ],
        details=_opt_details(
            v,
            [("Tenant", "tenant_name")],
            extra=[
                ("Request type", "VPN configuration"),
                ("Status", "Information required"),
            ],
        ),
        cta=CallToAction("Provide VPN information", v["vpn_information_link"]),
        info_lines=[
            "Customer VPN gateway public IP address",
            "Customer network CIDR ranges",
            "Preferred IKE version",
            "Encryption and hashing requirements, if applicable",
            "Pre-shared key preference, if managed by your team",
            "Technical contact name and email",
            "Preferred maintenance window",
        ],
        fallback_note=(
            f"Questions? Contact us at {support}." if support else None
        ),
    )


def _payment_confirmation(v: dict[str, str]) -> EmailContent:
    secondary = (
        CallToAction("Open workspace", v["workspace_url"])
        if v.get("workspace_url")
        else None
    )
    return EmailContent(
        title="Tablescope payment confirmation",
        preview_text="Your Tablescope payment was received successfully.",
        greeting=_greeting(v),
        paragraphs=[
            "Your Tablescope payment was received successfully. Thank you.",
        ],
        details=_opt_details(
            v,
            [
                ("Account", "account_name"),
                ("Plan", "plan_name"),
                ("Amount", "payment_amount"),
                ("Invoice", "invoice_number"),
                ("Payment date", "payment_date"),
            ],
        ),
        cta=CallToAction("View invoice", v["invoice_link"]),
        secondary_cta=secondary,
    )


def _payment_failed(v: dict[str, str]) -> EmailContent:
    return EmailContent(
        title="Tablescope payment failed",
        preview_text="We were unable to process your Tablescope payment.",
        greeting=_greeting(v),
        paragraphs=[
            "We were unable to process your latest Tablescope payment. Please "
            "update your payment method to avoid any interruption to your "
            "service.",
        ],
        details=_opt_details(
            v,
            [
                ("Account", "account_name"),
                ("Plan", "plan_name"),
                ("Amount", "payment_amount"),
                ("Attempt date", "payment_attempt_date"),
            ],
            extra=[("Status", "Payment failed")],
        ),
        cta=CallToAction("Update payment method", v["billing_portal_link"]),
    )


def _password_reset(v: dict[str, str]) -> EmailContent:
    expiry = (v.get("expiration_time") or "1 hour").strip()
    return EmailContent(
        title="Reset your Tablescope password",
        preview_text="Reset the password for your Tablescope account.",
        greeting=_greeting(v),
        paragraphs=[
            "We received a request to reset the password for your Tablescope "
            "account. Click the button below to choose a new password.",
        ],
        cta=CallToAction("Reset your password", v["reset_link"]),
        security_note=f"This link will expire in {expiry}.",
        fallback_note="If you did not request a password reset, you can safely "
        "ignore this email — your password will not change.",
    )


def _subscription_cancelled(v: dict[str, str]) -> EmailContent:
    account = (v.get("account_name") or "your account").strip()
    return EmailContent(
        title="Your Tablescope subscription was cancelled",
        preview_text="Your Tablescope subscription has been cancelled.",
        greeting=_greeting(v),
        paragraphs=[
            f"Your Tablescope subscription for {account} has been cancelled. "
            "Your workspace has been suspended, but your data is retained.",
        ],
        details=_opt_details(
            v,
            [("Account", "account_name")],
            extra=[("Status", "Cancelled")],
        ),
        fallback_note="Contact Tablescope support if you would like to "
        "reactivate your subscription.",
    )


def _data_source_processing_completed(v: dict[str, str]) -> EmailContent:
    name = (v.get("data_source_name") or "your data source").strip()
    return EmailContent(
        title="Data source processing completed",
        preview_text="Your Tablescope data source is ready to use.",
        greeting=_greeting(v),
        paragraphs=[
            f'Processing for the data source "{name}" has completed '
            "successfully and it is now ready to use.",
        ],
        details=_opt_details(
            v,
            [
                ("Workspace", "workspace_name"),
                ("Data source", "data_source_name"),
            ],
            extra=[("Status", "Completed")],
        ),
        cta=CallToAction("Open workspace", v["workspace_url"]),
    )


def _data_source_processing_failed(v: dict[str, str]) -> EmailContent:
    name = (v.get("data_source_name") or "your data source").strip()
    return EmailContent(
        title="Data source processing failed",
        preview_text="We were unable to finish processing your data source.",
        greeting=_greeting(v),
        paragraphs=[
            f'We were unable to finish processing the data source "{name}". '
            "Please review the source and try again.",
        ],
        details=_opt_details(
            v,
            [
                ("Workspace", "workspace_name"),
                ("Data source", "data_source_name"),
            ],
            extra=[("Status", "Failed")],
        ),
        cta=CallToAction("Open workspace", v["workspace_url"]),
    )


_TEMPLATE_LIST: tuple[EmailTemplate, ...] = (
    EmailTemplate(
        "account_confirmation",
        "Welcome to Tablescope — confirm your account",
        ("confirmation_link",),
        _account_confirmation,
    ),
    EmailTemplate(
        "workspace_ready",
        "Your Tablescope workspace is ready",
        ("workspace_url",),
        _workspace_ready,
    ),
    EmailTemplate(
        "workspace_ready_with_password_setup",
        "Your Tablescope workspace is ready",
        ("password_setup_link",),
        _workspace_ready_password_setup,
    ),
    EmailTemplate(
        "user_invitation",
        "You have been invited to Tablescope",
        ("invitation_link",),
        _user_invitation,
    ),
    EmailTemplate(
        "tenant_provisioning_started",
        "Tablescope tenant provisioning started",
        ("tenant_name",),
        _tenant_provisioning_started,
    ),
    EmailTemplate(
        "vpn_setup_information_required",
        "Tablescope VPN setup information required",
        ("vpn_information_link",),
        _vpn_setup_information_required,
    ),
    EmailTemplate(
        "payment_confirmation",
        "Tablescope payment confirmation",
        ("invoice_link",),
        _payment_confirmation,
    ),
    EmailTemplate(
        "payment_failed",
        "Tablescope payment failed",
        ("billing_portal_link",),
        _payment_failed,
    ),
    EmailTemplate(
        "password_reset",
        "Reset your Tablescope password",
        ("reset_link",),
        _password_reset,
    ),
    EmailTemplate(
        "subscription_cancelled",
        "Your Tablescope subscription was cancelled",
        ("account_name",),
        _subscription_cancelled,
    ),
    EmailTemplate(
        "data_source_processing_completed",
        "Your Tablescope data source is ready",
        ("workspace_url",),
        _data_source_processing_completed,
    ),
    EmailTemplate(
        "data_source_processing_failed",
        "Tablescope data source processing failed",
        ("workspace_url",),
        _data_source_processing_failed,
    ),
)

TEMPLATES: dict[str, EmailTemplate] = {t.name: t for t in _TEMPLATE_LIST}


def get_template(name: str) -> EmailTemplate:
    try:
        return TEMPLATES[name]
    except KeyError as exc:
        raise TemplateNotFoundError(name) from exc


def build_content(name: str, variables: dict[str, str]) -> EmailContent:
    """Validate required variables and build the template's content blocks."""
    template = get_template(name)
    missing = [
        key
        for key in template.required_vars
        if not str(variables.get(key, "")).strip()
    ]
    if missing:
        raise MissingTemplateVariableError(
            f"Template '{name}' is missing required variables: "
            f"{', '.join(sorted(missing))}"
        )
    return template.build(variables)
