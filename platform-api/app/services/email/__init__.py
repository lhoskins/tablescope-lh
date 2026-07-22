"""Branded transactional email system.

Calling code passes a template name + variables to
:func:`send_transactional_email`; it never builds raw HTML.  See
``docs/transactional-emails.md`` for the full template catalog and usage.
"""

from __future__ import annotations

from app.services.email.render import RenderedEmail, render_transactional_email
from app.services.email.service import EmailSendResult, send_transactional_email
from app.services.email.templates import (
    TEMPLATES,
    MissingTemplateVariableError,
    TemplateNotFoundError,
    build_content,
    get_template,
)

__all__ = [
    "TEMPLATES",
    "EmailSendResult",
    "MissingTemplateVariableError",
    "RenderedEmail",
    "TemplateNotFoundError",
    "build_content",
    "get_template",
    "render_transactional_email",
    "send_transactional_email",
]
