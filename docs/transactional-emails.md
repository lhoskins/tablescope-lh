# Transactional Emails

Tablescope sends branded transactional email (account, workspace, billing,
tenant setup, and service-activity notices) through a single reusable template
system in `platform-api/app/services/email/`.

## How it works

Calling code never builds raw HTML. It picks a template name and passes the
variables it needs:

```python
from app.services.email import send_transactional_email

await send_transactional_email(
    to="user@example.com",
    template="workspace_ready_with_password_setup",
    variables={
        "first_name": "Leonard",
        "workspace_name": "Acme Workspace",
        "tenant_name": "Acme Corp",
        "admin_email": "admin@acme.example",
        "workspace_url": "https://app.tablescope.cloud/acme",
        "password_setup_link": "https://app.tablescope.cloud/acme/set-password?token=…",
        "expiration_time": "24 hours",
    },
)
```

Services that need to be faked in tests depend on
`app.services.email_service.EmailService` and call its
`send_transactional_email(...)` method (same arguments), which delegates to the
function above.

Every email is rendered as a **multipart message**: a plain-text body (default)
plus an HTML alternative. The HTML uses a single shared layout
(`layout.py`): light-gray background, a centered 600px white card, a logo (or
the "Tablescope" wordmark when `EMAIL_LOGO_URL` is unset), a title, body
paragraphs, an optional details table, an optional primary/secondary CTA button,
optional info bullets, an optional security note, and a footer. All CSS is
inline and table-based so it renders consistently across Gmail, Outlook, and
Apple Mail. No JavaScript, no external stylesheets.

All caller-supplied values are HTML-escaped, so workspace/tenant/user names
cannot inject markup.

## Files

- `layout.py` — `EmailContent` block model + HTML and plain-text renderers.
- `templates.py` — the `TEMPLATES` registry (subject, required vars, builder).
- `render.py` — `render_transactional_email(template, variables)` → `RenderedEmail`.
- `service.py` — `send_transactional_email(...)` (renders + sends over SMTP).

## Configuration

| Setting (env)                   | Purpose                                  |
| ------------------------------- | ---------------------------------------- |
| `SMTP_HOST` / `SMTP_PORT`       | SMTP relay (e.g. Amazon SES SMTP).       |
| `SMTP_USERNAME` / `SMTP_PASSWORD` | SMTP auth.                             |
| `SMTP_USE_TLS`                  | STARTTLS (default true).                 |
| `TABLESCOPE_EMAIL_FROM`         | From address.                            |
| `TABLESCOPE_EMAIL_REPLY_TO`     | Optional Reply-To.                       |
| `TABLESCOPE_EMAIL_LOGO_URL`     | Logo image URL (falls back to wordmark). |
| `TABLESCOPE_APP_URL`            | App base URL used in footer/links.       |
| `TABLESCOPE_SUPPORT_EMAIL`      | Support contact shown in footer.         |

When SMTP is not configured the send is **recorded** (recipient + template
logged) but not delivered, so non-prod environments never send real email.
Magic/invite links and tokens are never logged.

## Templates

Each template lists its required variables (rendering raises
`MissingTemplateVariableError` if one is missing/empty). `first_name` is always
optional — the greeting degrades to "Hello,". Several detail rows are optional
and are simply omitted when their value is absent.

| Template | Subject | Required variables |
| --- | --- | --- |
| `account_confirmation` | Welcome to Tablescope — confirm your account | `confirmation_link` |
| `workspace_ready` | Your Tablescope workspace is ready | `workspace_url` |
| `workspace_ready_with_password_setup` | Your Tablescope workspace is ready | `password_setup_link` |
| `user_invitation` | You have been invited to Tablescope | `invitation_link` |
| `tenant_provisioning_started` | Tablescope tenant provisioning started | `tenant_name` |
| `vpn_setup_information_required` | Tablescope VPN setup information required | `vpn_information_link` |
| `payment_confirmation` | Tablescope payment confirmation | `invoice_link` |
| `payment_failed` | Tablescope payment failed | `billing_portal_link` |
| `password_reset` | Reset your Tablescope password | `reset_link` |
| `subscription_cancelled` | Your Tablescope subscription was cancelled | `account_name` |
| `data_source_processing_completed` | Your Tablescope data source is ready | `workspace_url` |
| `data_source_processing_failed` | Tablescope data source processing failed | `workspace_url` |

### Combined tenant-admin onboarding

`workspace_ready_with_password_setup` is the **single** email a new tenant admin
receives. Its primary CTA is **"Create your password"** (the set-password link),
not a login link, so the admin never lands on a sign-in page before having
credentials. No separate "workspace ready" + "password setup" emails are sent.
If the admin already exists in Supabase (already has a password), the plain
`workspace_ready` email (Open workspace CTA) is sent instead.

## Previewing locally

Render every template with sample data to HTML + text files:

```bash
cd platform-api
python -m scripts.preview_emails            # writes ./email-previews/
open email-previews/index.html
```

## Adding a template

1. Add a builder function in `templates.py` returning an `EmailContent`.
2. Append an `EmailTemplate(name, subject, required_vars, build)` to
   `_TEMPLATE_LIST`.
3. Add sample values for any new variables to `scripts/preview_emails.py`.
4. Add the row to the table above.
