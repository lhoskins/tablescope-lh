"""Tests for the Knowledge Graph insight reference file.

Kept free of router imports so it runs without the optional vector-store deps
(qdrant). Run from the ``tablescope-ai-api`` directory: ``pytest -q``.
"""

from __future__ import annotations

from app.services.prompt_loader import PROMPTS_DIR, load_prompt_reference


def test_kg_best_practices_file_exists() -> None:
    assert (PROMPTS_DIR / "knowledge_graph_insight_best_practices.md").exists()


def test_kg_best_practices_has_key_sections() -> None:
    text = load_prompt_reference("knowledge_graph_insight_best_practices.md")
    assert text
    assert "Knowledge Graph Insight Best Practices" in text
    assert "Graph Lenses" in text
    assert "Relationship Types" in text
