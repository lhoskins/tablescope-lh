"""Email-safe HTML + plain-text layout primitives.

Renders a single reusable branded layout (gray background, white card, logo,
title, body, optional details table, optional CTA button, footer) using
table-based HTML and inline CSS so it renders consistently across Gmail,
Outlook, and Apple Mail.  No JavaScript, no external stylesheets.

All caller-supplied values are HTML-escaped by default so user/workspace/tenant
names cannot inject markup into rendered emails.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from html import escape

# Brand palette (kept inline per email-client rules).
_BG = "#F6F7F9"
_CARD = "#FFFFFF"
_BORDER = "#E5E7EB"
_TEXT = "#111827"
_MUTED = "#6B7280"
_BRAND = "#4F46E5"
_BRAND_TEXT = "#FFFFFF"
_FONT = "Arial, Helvetica, sans-serif"


@dataclass(slots=True)
class CallToAction:
    label: str
    url: str


@dataclass(slots=True)
class EmailContent:
    """Structured, transport-agnostic description of a transactional email."""

    title: str
    preview_text: str
    greeting: str | None = None
    paragraphs: list[str] = field(default_factory=list)
    details: list[tuple[str, str]] = field(default_factory=list)
    cta: CallToAction | None = None
    secondary_cta: CallToAction | None = None
    info_lines: list[str] = field(default_factory=list)
    security_note: str | None = None
    fallback_note: str | None = None


def _esc(value: str) -> str:
    return escape(str(value), quote=True)


def render_footer_html(*, app_url: str) -> str:
    return (
        f'<tr><td style="padding:24px 32px 32px 32px;">'
        f'<hr style="border:none;border-top:1px solid {_BORDER};margin:0 0 16px 0;" />'
        f'<p style="margin:0;font-family:{_FONT};font-size:13px;'
        f'line-height:20px;color:{_MUTED};">'
        f'<strong style="color:{_TEXT};">Tablescope</strong><br />'
        f'<a href="{_esc(app_url)}" style="color:{_BRAND};text-decoration:none;">'
        f"{_esc(app_url)}</a></p>"
        f'<p style="margin:12px 0 0 0;font-family:{_FONT};font-size:12px;'
        f'line-height:18px;color:{_MUTED};">'
        "This is a transactional email related to your Tablescope account, "
        "workspace, billing, tenant setup, or service activity."
        "</p></td></tr>"
    )


def _logo_html(*, logo_url: str) -> str:
    if logo_url:
        return (
            f'<img src="{_esc(logo_url)}" alt="Tablescope" height="32" '
            f'style="display:block;border:0;outline:none;height:32px;" />'
        )
    return (
        f'<span style="font-family:{_FONT};font-size:22px;font-weight:700;'
        f'color:{_TEXT};">Tablescope</span>'
    )


def _button_html(cta: CallToAction, *, primary: bool) -> str:
    bg = _BRAND if primary else _CARD
    color = _BRAND_TEXT if primary else _BRAND
    border = _BRAND
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" '
        f'style="margin:0 0 4px 0;"><tr><td '
        f'style="border-radius:8px;background:{bg};">'
        f'<a href="{_esc(cta.url)}" target="_blank" '
        f'style="display:inline-block;padding:12px 24px;font-family:{_FONT};'
        f'font-size:15px;font-weight:600;color:{color};text-decoration:none;'
        f'border:1px solid {border};border-radius:8px;">{_esc(cta.label)}</a>'
        f"</td></tr></table>"
    )


def _details_html(details: list[tuple[str, str]]) -> str:
    rows = "".join(
        f'<tr>'
        f'<td style="padding:8px 0;font-family:{_FONT};font-size:13px;'
        f'color:{_MUTED};white-space:nowrap;vertical-align:top;">{_esc(label)}</td>'
        f'<td style="padding:8px 0 8px 16px;font-family:{_FONT};font-size:13px;'
        f'color:{_TEXT};text-align:right;word-break:break-word;">'
        f"{_esc(value)}</td></tr>"
        for label, value in details
    )
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" width="100%" '
        f'style="margin:8px 0 20px 0;border-top:1px solid {_BORDER};'
        f'border-bottom:1px solid {_BORDER};">{rows}</table>'
    )


def render_html(content: EmailContent, *, logo_url: str, app_url: str) -> str:
    """Render the full branded HTML document for an email."""
    blocks: list[str] = []

    # Hidden preview text (shown in inbox list previews).
    blocks.append(
        f'<div style="display:none;max-height:0;overflow:hidden;opacity:0;">'
        f"{_esc(content.preview_text)}</div>"
    )

    blocks.append(
        f'<tr><td style="padding:32px 32px 0 32px;">'
        f"{_logo_html(logo_url=logo_url)}</td></tr>"
    )

    body: list[str] = [
        f'<h1 style="margin:24px 0 16px 0;font-family:{_FONT};font-size:22px;'
        f'line-height:28px;font-weight:700;color:{_TEXT};">'
        f"{_esc(content.title)}</h1>"
    ]
    if content.greeting:
        body.append(
            f'<p style="margin:0 0 16px 0;font-family:{_FONT};font-size:15px;'
            f'line-height:24px;color:{_TEXT};">{_esc(content.greeting)}</p>'
        )
    for para in content.paragraphs:
        body.append(
            f'<p style="margin:0 0 16px 0;font-family:{_FONT};font-size:15px;'
            f'line-height:24px;color:{_TEXT};">{_esc(para)}</p>'
        )
    if content.details:
        body.append(_details_html(content.details))
    if content.cta:
        body.append(_button_html(content.cta, primary=True))
    if content.secondary_cta:
        body.append(_button_html(content.secondary_cta, primary=False))
    if content.info_lines:
        items = "".join(
            f'<li style="margin:0 0 6px 0;">{_esc(line)}</li>'
            for line in content.info_lines
        )
        body.append(
            f'<ul style="margin:8px 0 16px 20px;padding:0;font-family:{_FONT};'
            f'font-size:14px;line-height:22px;color:{_TEXT};">{items}</ul>'
        )
    if content.security_note:
        body.append(
            f'<p style="margin:16px 0 0 0;font-family:{_FONT};font-size:13px;'
            f'line-height:20px;color:{_MUTED};">{_esc(content.security_note)}</p>'
        )
    if content.fallback_note:
        body.append(
            f'<p style="margin:8px 0 0 0;font-family:{_FONT};font-size:13px;'
            f'line-height:20px;color:{_MUTED};">{_esc(content.fallback_note)}</p>'
        )

    blocks.append(
        f'<tr><td style="padding:0 32px 8px 32px;">{"".join(body)}</td></tr>'
    )
    blocks.append(render_footer_html(app_url=app_url))

    card = (
        f'<table role="presentation" cellpadding="0" cellspacing="0" width="600" '
        f'style="width:600px;max-width:600px;background:{_CARD};'
        f'border:1px solid {_BORDER};border-radius:12px;">{"".join(blocks)}</table>'
    )

    return (
        "<!DOCTYPE html><html><head>"
        '<meta charset="utf-8" />'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0" />'
        f"<title>{_esc(content.title)}</title></head>"
        f'<body style="margin:0;padding:0;background:{_BG};">'
        f'<table role="presentation" cellpadding="0" cellspacing="0" width="100%" '
        f'style="background:{_BG};padding:24px 12px;"><tr><td align="center">'
        f"{card}</td></tr></table></body></html>"
    )


def render_text(content: EmailContent, *, app_url: str) -> str:
    """Render the plain-text fallback for an email."""
    lines: list[str] = [content.title, ""]
    if content.greeting:
        lines.extend([content.greeting, ""])
    for para in content.paragraphs:
        lines.extend([para, ""])
    if content.details:
        for label, value in content.details:
            lines.append(f"{label}: {value}")
        lines.append("")
    if content.cta:
        lines.extend([f"{content.cta.label}:", content.cta.url, ""])
    if content.secondary_cta:
        lines.extend(
            [f"{content.secondary_cta.label}:", content.secondary_cta.url, ""]
        )
    if content.info_lines:
        for line in content.info_lines:
            lines.append(f"- {line}")
        lines.append("")
    if content.security_note:
        lines.extend([content.security_note, ""])
    if content.fallback_note:
        lines.extend([content.fallback_note, ""])
    lines.extend(["—", "Tablescope", app_url])
    return "\n".join(lines).strip() + "\n"
