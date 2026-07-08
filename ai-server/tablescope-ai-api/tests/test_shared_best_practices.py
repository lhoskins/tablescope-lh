"""Shared best-practices docs (plan §7.2 / Devin ASK §17).

Every AI surface should reference shared policy files rather than duplicating
guidance inline. These tests pin the six §17 docs into existence, verify the
shared-block loader combines them, and assert each is actually referenced from
the router so a doc can never silently become orphaned.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.prompt_loader import (
    PROMPTS_DIR,
    load_prompt_reference,
    shared_policy_block,
)

# The six shared best-practices docs required by §17.
REQUIRED_DOCS = [
    "response_best_practices.md",
    "visualization_best_practices.md",
    "sql_generation_best_practices.md",
    "document_intelligence_best_practices.md",
    "hybrid_intelligence_best_practices.md",
    "analytical_method_best_practices.md",
]

AI_ROUTER = Path(__file__).resolve().parents[1] / "app" / "routers" / "ai.py"


@pytest.mark.parametrize("name", REQUIRED_DOCS)
def test_doc_exists_and_nonempty(name: str) -> None:
    assert (PROMPTS_DIR / name).exists(), f"missing shared doc {name}"
    text = load_prompt_reference(name)
    assert len(text.strip()) > 100, f"{name} looks empty/stub"


@pytest.mark.parametrize("name", REQUIRED_DOCS)
def test_doc_is_referenced_by_a_surface(name: str) -> None:
    # A doc that no surface loads is dead policy — guard against it.
    src = AI_ROUTER.read_text(encoding="utf-8")
    assert name in src, f"{name} is not referenced from ai.py"


def test_shared_policy_block_combines_docs() -> None:
    block = shared_policy_block(
        "response_best_practices.md", "visualization_best_practices.md"
    )
    assert block.startswith("Shared Best Practices")
    # Content from both docs is present.
    assert "response modes" in block.lower()
    assert "visualization engine" in block.lower()


def test_shared_policy_block_empty_when_all_missing() -> None:
    assert shared_policy_block("does_not_exist.md") == ""


def test_no_forced_chart_policy_present() -> None:
    # A non-negotiable rule: prose/document answers never force a chart.
    text = load_prompt_reference("response_best_practices.md")
    assert "force a chart" in text.lower() or "no forced chart" in text.lower()
