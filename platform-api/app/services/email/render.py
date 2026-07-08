"""Render a registered template + variables into HTML and plain text."""

from __future__ import annotations

from dataclasses import dataclass

from app.config import get_settings
from app.services.email.layout import render_html, render_text
from app.services.email.templates import build_content, get_template


@dataclass(slots=True)
class RenderedEmail:
    template: str
    subject: str
    html: str
    text: str
    preview_text: str


def render_transactional_email(
    template: str,
    variables: dict[str, str],
    *,
    subject: str | None = None,
) -> RenderedEmail:
    """Render ``template`` with ``variables`` into a :class:`RenderedEmail`.

    Raises ``MissingTemplateVariableError`` when a required variable is absent
    and ``TemplateNotFoundError`` for an unknown template.
    """
    settings = get_settings()
    content = build_content(template, variables)
    html = render_html(
        content,
        logo_url=settings.email_logo_url,
        app_url=settings.app_base_url,
    )
    text = render_text(content, app_url=settings.app_base_url)
    return RenderedEmail(
        template=template,
        subject=subject or get_template(template).subject,
        html=html,
        text=text,
        preview_text=content.preview_text,
    )
