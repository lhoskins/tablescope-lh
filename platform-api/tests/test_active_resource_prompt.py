"""Unit tests for the workspace grounding block.

These sit alongside the end-to-end canonical-turn tests deliberately. Those go
through the intent classifier, which routes some phrasings down paths that
never reach the prompt builder -- so an assertion there can pass without the
prompt ever having been built. This exercises the function directly.
"""

from app.services.conversational_analytics import _format_active_resource_prompt
from app.services.workspace_context import ActiveResourceContext


def _ctx(label: str) -> ActiveResourceContext:
    return ActiveResourceContext(
        resource_type="document",
        resource_id=abs(hash(label)) % 1000,
        label=label,
        summary=f"a document titled '{label}'",
    )


def test_no_resources_produces_no_block():
    assert _format_active_resource_prompt(None) == ""
    assert _format_active_resource_prompt([]) == ""


def test_single_resource_is_described_without_a_focus_line():
    prompt = _format_active_resource_prompt([_ctx("Incident Report")])
    assert "a document titled 'Incident Report'" in prompt
    # With one item there is nothing to disambiguate, so the extra sentence
    # would only add noise.
    assert "currently looking at" not in prompt


def test_many_resources_are_listed_as_peers_when_nothing_is_focused():
    prompt = _format_active_resource_prompt([_ctx("Report A"), _ctx("Report B")])
    assert "- a document titled 'Report A'" in prompt
    assert "- a document titled 'Report B'" in prompt
    assert "currently looking at" not in prompt


def test_focus_names_one_item_while_keeping_the_others_visible():
    focus = _ctx("Report B")
    prompt = _format_active_resource_prompt([_ctx("Report A"), focus], focus)
    # The whole set is still there for cross-referencing...
    assert "Report A" in prompt
    # ...and the model is told which one the question is likely about.
    assert "the user is currently looking at Report B." in prompt


def test_focus_line_stays_descriptive():
    """This block is prepended to the text the intent classifier reads, so
    imperative wording here changes how turns get routed. Keep it factual."""
    focus = _ctx("Report B")
    prompt = _format_active_resource_prompt([_ctx("Report A"), focus], focus)
    for imperative in ("Answer about", "You should", "Use the", "Do not"):
        assert imperative not in prompt


def test_focus_is_ignored_for_a_single_resource():
    """The one-item phrasing already says what is open; adding "and you are
    looking at it" is redundant."""
    only = _ctx("Incident Report")
    prompt = _format_active_resource_prompt([only], only)
    assert "currently looking at" not in prompt
