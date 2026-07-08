"""Tests for the resolver-guidance hint injected into SQL generation prompts."""

from app.services.llm_client import _resolver_hint


def test_hint_empty_when_no_guidance():
    assert _resolver_hint(None, None) == ""
    assert _resolver_hint([], []) == ""


def test_hint_lists_preferred_sources_and_columns():
    hint = _resolver_hint(
        ["SUP_Quality_Inspections_CSV"], ["SupplierID", "DefectRate"]
    )
    assert "SUP_Quality_Inspections_CSV" in hint
    assert "SupplierID" in hint
    assert "DefectRate" in hint
    # Must allow fallback to another authorized source, never force a bad match.
    assert "cannot answer" in hint.lower()


def test_hint_with_sources_only():
    hint = _resolver_hint(["A_CSV"], None)
    assert "A_CSV" in hint
    assert "Relevant columns" not in hint
