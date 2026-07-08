"""Render every transactional email template to local HTML + text files.

Dev-only preview: renders all registered templates with sample data into an
output directory so you can open them in a browser.  Sends no real email.

Usage:
    python -m scripts.preview_emails [output_dir]

Defaults to ./email-previews.
"""

from __future__ import annotations

import sys
from pathlib import Path

from app.services.email.render import render_transactional_email
from app.services.email.templates import TEMPLATES

# Representative sample data covering every required variable across templates.
SAMPLE_VARS: dict[str, str] = {
    "first_name": "Leonard",
    "confirmation_link": "https://app.tablescope.cloud/auth/confirm?token=sample",
    "expiration_time": "24 hours",
    "workspace_name": "Acme Analytics Workspace",
    "tenant_name": "Acme Corporation",
    "tenant_slug": "acme",
    "admin_email": "leonard@acme.example",
    "workspace_url": "https://app.tablescope.cloud/acme",
    "password_setup_link": "https://app.tablescope.cloud/acme/set-password?token=sample",
    "inviter_name": "Dana Reyes",
    "role_name": "Editor",
    "invitation_link": "https://app.tablescope.cloud/invite?token=sample",
    "expiration_date": "Jun 30, 2026",
    "started_at": "Jun 23, 2026 9:20 AM",
    "vpn_information_link": "https://app.tablescope.cloud/onboarding/vpn?request=42",
    "support_contact_email": "support@tablescope.cloud",
    "account_name": "Acme Corporation",
    "plan_name": "Enterprise",
    "payment_amount": "$1,200.00",
    "payment_date": "Jun 23, 2026",
    "payment_attempt_date": "Jun 23, 2026",
    "invoice_number": "INV-000123",
    "invoice_link": "https://billing.tablescope.cloud/invoices/INV-000123",
    "billing_portal_link": "https://billing.tablescope.cloud/portal",
    "reset_link": "https://app.tablescope.cloud/auth/reset?token=sample",
    "data_source_name": "sales_data.csv",
}


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("email-previews")
    out_dir.mkdir(parents=True, exist_ok=True)

    index: list[str] = ["<h1>Tablescope email previews</h1><ul>"]
    for name in sorted(TEMPLATES):
        rendered = render_transactional_email(name, SAMPLE_VARS)
        (out_dir / f"{name}.html").write_text(rendered.html, encoding="utf-8")
        (out_dir / f"{name}.txt").write_text(rendered.text, encoding="utf-8")
        index.append(
            f'<li><a href="{name}.html">{name}</a> — '
            f"<em>{rendered.subject}</em></li>"
        )
        print(f"rendered {name} -> {out_dir / f'{name}.html'}")
    index.append("</ul>")
    (out_dir / "index.html").write_text("".join(index), encoding="utf-8")
    print(f"\nOpen {out_dir / 'index.html'} in a browser.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
