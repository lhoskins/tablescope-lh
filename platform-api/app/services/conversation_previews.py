"""Safe plain-text previews for stored AI Assistant conversation turns.

Overview surfaces show a question and a short result preview. Stored
assistant messages are Markdown, and results may only exist as a chart or
table, so the text is reduced to sanitized plain text here rather than in
a second, partial sanitizer in the UI.
"""

from __future__ import annotations

import re
from typing import Any

QUESTION_PREVIEW_LIMIT = 160
RESULT_PREVIEW_LIMIT = 220
NO_RESULT_PREVIEW = "Open conversation to view the result"

_CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`([^`]*)`")
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE)
_BLOCKQUOTE_RE = re.compile(r"^\s{0,3}>\s?", re.MULTILINE)
_LIST_BULLET_RE = re.compile(r"^\s{0,3}([*+-]|\d+\.)\s+", re.MULTILINE)
_TABLE_DIVIDER_RE = re.compile(r"^\s*\|?[\s:|-]+\|[\s:|-]*$", re.MULTILINE)
_EMPHASIS_RE = re.compile(r"(\*{1,3}|_{1,3}|~{2})(?=\S)(.*?)(?<=\S)\1", re.DOTALL)
_WHITESPACE_RE = re.compile(r"\s+")


def to_plain_text(value: str | None) -> str:
    """Reduce stored Markdown/HTML to a single line of safe plain text."""
    if not value:
        return ""
    text = _CODE_FENCE_RE.sub(" ", value)
    text = _IMAGE_RE.sub(" ", text)
    text = _LINK_RE.sub(r"\1", text)
    text = _HTML_TAG_RE.sub(" ", text)
    text = _TABLE_DIVIDER_RE.sub(" ", text)
    text = _HEADING_RE.sub("", text)
    text = _BLOCKQUOTE_RE.sub("", text)
    text = _LIST_BULLET_RE.sub("", text)
    text = _INLINE_CODE_RE.sub(r"\1", text)
    text = _EMPHASIS_RE.sub(r"\2", text)
    text = text.replace("|", " ")
    return _WHITESPACE_RE.sub(" ", text).strip()


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def question_preview(user_message: str | None, title: str | None = None) -> str:
    """Prefer the turn's own question; fall back to the stored title."""
    text = to_plain_text(user_message) or to_plain_text(title)
    return truncate(text, QUESTION_PREVIEW_LIMIT)


def _explanation_text(explanation: Any) -> str:
    if isinstance(explanation, str):
        return to_plain_text(explanation)
    if isinstance(explanation, dict):
        for key in ("summary", "narrative", "text", "explanation"):
            candidate = explanation.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return to_plain_text(candidate)
    return ""


def result_preview(
    assistant_message: str | None,
    explanation: Any = None,
    chart_config: Any = None,
) -> str:
    """Safe one-or-two-line result preview.

    Never derives text from SQL, tool traces, or raw result rows — only from
    the narrative fields the assistant already stored for display.
    """
    text = to_plain_text(assistant_message) or _explanation_text(explanation)
    if not text and isinstance(chart_config, dict):
        title = chart_config.get("title")
        if isinstance(title, str) and title.strip():
            text = to_plain_text(title)
    if not text:
        return NO_RESULT_PREVIEW
    return truncate(text, RESULT_PREVIEW_LIMIT)


def result_type(chart_config: Any, result_cache: Any) -> str:
    if isinstance(chart_config, dict) and chart_config.get("type"):
        return "chart"
    if isinstance(result_cache, dict) and result_cache.get("columns"):
        return "table"
    return "text"
