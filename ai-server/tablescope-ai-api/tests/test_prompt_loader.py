"""Tests for the prompt reference loader and bundled reference files.

Run from the ``tablescope-ai-api`` directory: ``pytest -q``.
"""

from __future__ import annotations

from app.services.prompt_loader import PROMPTS_DIR, load_prompt_reference


def test_dashboard_best_practices_file_exists() -> None:
    assert (PROMPTS_DIR / "dashboard_best_practices.md").exists()


def test_load_prompt_reference_returns_content() -> None:
    text = load_prompt_reference("dashboard_best_practices.md")
    assert text
    assert "Tablescope AI Dashboard Best Practices" in text
    # Key policy sections the dashboard prompt relies on.
    assert "Insight-First Dashboard Policy" in text
    assert "Widget Validation Policy" in text
    assert "Dashboard Save Policy" in text


def test_load_prompt_reference_missing_returns_empty() -> None:
    assert load_prompt_reference("does_not_exist.md") == ""
