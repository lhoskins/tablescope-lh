"""Tests for the Presentation Engine registry + shared ResponseEnvelope.

The registry is the single source of truth for which sections each mode
renders (plan §7.1 / Devin ASK §11). These tests pin the section sets to the
spec, assert the envelope stamps them, and cover the ask-and-run mode mapping.
"""

from __future__ import annotations

import pytest

from app.services.presentation_engine import (
    SECTIONS_BY_MODE,
    PresentationMode,
    Section,
    describe,
    mode_for_ask_and_run,
    sections_for,
)
from app.services.response_envelope import ResponseEnvelope

# ── Registry ──────────────────────────────────────────────────────────────

def test_every_mode_has_sections() -> None:
    for mode in PresentationMode:
        assert sections_for(mode), f"{mode} has no sections"


def test_registry_matches_spec_exactly() -> None:
    # Pinned to plan §7.1 — a drift here is a deliberate spec change.
    assert SECTIONS_BY_MODE[PresentationMode.STRUCTURED] == (
        Section.SUMMARY, Section.CHART, Section.GRID, Section.SHOW_SQL,
        Section.SAVE_QUERY, Section.CREATE_DASHBOARD, Section.FOLLOW_UPS,
    )
    assert SECTIONS_BY_MODE[PresentationMode.HYBRID] == (
        Section.EXECUTIVE_SUMMARY, Section.CHART, Section.GRID,
        Section.METHOD_ENVELOPE, Section.KEY_DRIVERS,
        Section.RECOMMENDED_ACTIONS, Section.SOURCES, Section.SHOW_SQL,
    )
    assert SECTIONS_BY_MODE[PresentationMode.CONVERSATIONAL] == (
        Section.PROSE_ANSWER, Section.KEY_POINTS, Section.REFERENCES,
        Section.FOLLOW_UPS,
    )
    assert SECTIONS_BY_MODE[PresentationMode.DOCUMENT] == (
        Section.SUMMARY, Section.FINDINGS, Section.EVIDENCE,
        Section.DOCUMENT_REFERENCES, Section.FOLLOW_UPS,
    )
    assert SECTIONS_BY_MODE[PresentationMode.DASHBOARD] == (
        Section.EXECUTIVE_SUMMARY, Section.KEY_FINDINGS,
        Section.RECOMMENDED_ACTIONS, Section.CHART_CARDS, Section.SHOW_DATA,
        Section.SAVE,
    )


def test_conversational_and_document_have_no_forced_chart() -> None:
    # ASK §11: prose / document modes never force a chart or SQL section.
    for mode in (PresentationMode.CONVERSATIONAL, PresentationMode.DOCUMENT):
        secs = sections_for(mode)
        assert Section.CHART not in secs
        assert Section.CHART_CARDS not in secs
    assert Section.SHOW_SQL not in sections_for(PresentationMode.DOCUMENT)


def test_hybrid_carries_method_envelope() -> None:
    # The method envelope only surfaces on the hybrid analytical surface.
    assert Section.METHOD_ENVELOPE in sections_for(PresentationMode.HYBRID)
    assert Section.METHOD_ENVELOPE not in sections_for(
        PresentationMode.STRUCTURED
    )


def test_describe_shape() -> None:
    d = describe(PresentationMode.STRUCTURED)
    assert d["mode"] == "structured"
    assert d["sections"] == [s.value for s in sections_for(
        PresentationMode.STRUCTURED
    )]
    assert all(isinstance(s, str) for s in d["sections"])


# ── ask-and-run mode mapping ──────────────────────────────────────────────

def test_mode_for_ask_and_run_prose() -> None:
    assert mode_for_ask_and_run(
        answer_type="text", has_method_envelope=False
    ) is PresentationMode.CONVERSATIONAL


def test_mode_for_ask_and_run_hybrid_when_envelope() -> None:
    assert mode_for_ask_and_run(
        answer_type="data", has_method_envelope=True
    ) is PresentationMode.HYBRID


def test_mode_for_ask_and_run_structured_default() -> None:
    assert mode_for_ask_and_run(
        answer_type="data", has_method_envelope=False
    ) is PresentationMode.STRUCTURED
    # A prose answer wins over an (impossible) envelope flag.
    assert mode_for_ask_and_run(
        answer_type="text", has_method_envelope=True
    ) is PresentationMode.CONVERSATIONAL


# ── ResponseEnvelope ──────────────────────────────────────────────────────

def test_envelope_build_stamps_sections_and_omits_none() -> None:
    env = ResponseEnvelope.build(
        PresentationMode.STRUCTURED,
        summary="Sales grew 12%",
        sql="SELECT ...",
        answer=None,  # dropped
    )
    assert env.mode == "structured"
    assert env.sections == [s.value for s in sections_for(
        PresentationMode.STRUCTURED
    )]
    assert env.summary == "Sales grew 12%"
    assert env.sql == "SELECT ..."
    assert env.answer is None


@pytest.mark.parametrize("mode", list(PresentationMode))
def test_envelope_sections_match_registry_for_every_mode(
    mode: PresentationMode,
) -> None:
    env = ResponseEnvelope.build(mode)
    assert env.sections == [s.value for s in sections_for(mode)]
