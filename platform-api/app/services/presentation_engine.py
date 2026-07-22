"""Presentation Engine — one section-per-mode registry (plan §7.1 / ASK §11).

Until now each AI surface returned its own bespoke response schema, and each
decided ad hoc which of {summary, chart, grid, Show SQL, method envelope, key
drivers, recommended actions, sources, findings, citations, follow-ups} to
render. There was no shared notion of a "response mode" anywhere in the repo.

This module is the single source of truth for **which sections belong to which
mode**. It is a pure, deterministic registry — no LLM, no business logic, no
charting decisions (charting is already unified via ``InsightChartBlock`` /
``WidgetRenderer``). It governs response *assembly* only.
"""

from __future__ import annotations

from enum import StrEnum


class PresentationMode(StrEnum):
    """The five (really six) response surfaces, collapsed to a shared vocabulary."""

    CONVERSATIONAL = "conversational"  # /ask prose
    STRUCTURED = "structured"  # executed SQL result
    HYBRID = "hybrid"  # ask-and-run: data + method envelope + drivers
    DOCUMENT = "document"  # document / family intelligence
    DASHBOARD = "dashboard"  # generated dashboard modal


class Section(StrEnum):
    """Every renderable section across all modes (superset)."""

    SUMMARY = "summary"
    EXECUTIVE_SUMMARY = "executive_summary"
    PROSE_ANSWER = "prose_answer"
    CHART = "chart"
    CHART_CARDS = "chart_cards"
    GRID = "grid"
    SHOW_SQL = "show_sql"
    SHOW_DATA = "show_data"
    SAVE_QUERY = "save_query"
    SAVE = "save"
    CREATE_DASHBOARD = "create_dashboard"
    METHOD_ENVELOPE = "method_envelope"
    KEY_DRIVERS = "key_drivers"
    KEY_FINDINGS = "key_findings"
    KEY_POINTS = "key_points"
    RECOMMENDED_ACTIONS = "recommended_actions"
    SOURCES = "sources"
    REFERENCES = "references"
    FINDINGS = "findings"
    EVIDENCE = "evidence"
    DOCUMENT_REFERENCES = "document_references"
    FOLLOW_UPS = "follow_ups"


# The one registry. Order is the intended render order for each mode.
# Mirrors plan §7.1 / Devin ASK §11 exactly.
SECTIONS_BY_MODE: dict[PresentationMode, tuple[Section, ...]] = {
    PresentationMode.STRUCTURED: (
        Section.SUMMARY,
        Section.CHART,
        Section.GRID,
        Section.SHOW_SQL,
        Section.SAVE_QUERY,
        Section.CREATE_DASHBOARD,
        Section.FOLLOW_UPS,
    ),
    PresentationMode.HYBRID: (
        Section.EXECUTIVE_SUMMARY,
        Section.CHART,
        Section.GRID,
        Section.METHOD_ENVELOPE,
        Section.KEY_DRIVERS,
        Section.RECOMMENDED_ACTIONS,
        Section.SOURCES,
        Section.SHOW_SQL,
    ),
    PresentationMode.CONVERSATIONAL: (
        Section.PROSE_ANSWER,
        Section.KEY_POINTS,
        Section.REFERENCES,
        Section.FOLLOW_UPS,
    ),
    PresentationMode.DOCUMENT: (
        Section.SUMMARY,
        Section.FINDINGS,
        Section.EVIDENCE,
        Section.DOCUMENT_REFERENCES,
        Section.FOLLOW_UPS,
    ),
    PresentationMode.DASHBOARD: (
        Section.EXECUTIVE_SUMMARY,
        Section.KEY_FINDINGS,
        Section.RECOMMENDED_ACTIONS,
        Section.CHART_CARDS,
        Section.SHOW_DATA,
        Section.SAVE,
    ),
}


def sections_for(mode: PresentationMode) -> tuple[Section, ...]:
    """Return the ordered section set for a mode (empty tuple if unknown)."""
    return SECTIONS_BY_MODE.get(mode, ())


def describe(mode: PresentationMode) -> dict[str, object]:
    """A JSON-ready ``{mode, sections}`` descriptor for the frontend.

    This is the shape endpoints attach so the UI can render the correct section
    set from one contract instead of sniffing each surface's bespoke schema.
    """
    return {
        "mode": mode.value,
        "sections": [s.value for s in sections_for(mode)],
    }


def mode_for_ask_and_run(
    *, answer_type: str | None, has_method_envelope: bool
) -> PresentationMode:
    """Map an ask-and-run outcome onto a presentation mode.

    - a prose fallback answer -> conversational,
    - an executed result carrying a method envelope -> hybrid,
    - a plain executed result -> structured.
    """
    if answer_type == "text":
        return PresentationMode.CONVERSATIONAL
    if has_method_envelope:
        return PresentationMode.HYBRID
    return PresentationMode.STRUCTURED
