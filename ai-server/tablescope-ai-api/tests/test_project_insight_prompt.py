"""Tests for the Project Insight best-practices reference file.

Kept free of router imports so it runs without the optional vector-store deps
(qdrant). The Project Insight endpoint must load THIS project-scoped prompt —
not the tenant-wide Business/Home Insight prompt. Run from the
``tablescope-ai-api`` directory: ``pytest -q``.
"""

from __future__ import annotations

from app.services.prompt_loader import PROMPTS_DIR, load_prompt_reference


def test_project_insight_best_practices_file_exists() -> None:
    assert (PROMPTS_DIR / "project_insight_best_practices.md").exists()


def test_project_insight_best_practices_has_key_sections() -> None:
    text = load_prompt_reference("project_insight_best_practices.md")
    assert text
    assert "Project Insight Best Practices" in text
    assert "Executive Project Summary" in text
    assert "Insight Validation Workflow" in text
    assert "Recommended Dashboards" in text


def test_project_insight_prompt_is_project_scoped_not_business() -> None:
    """The prompt must scope to ONE project and distinguish Business Insight."""
    text = load_prompt_reference("project_insight_best_practices.md")
    assert "Difference Between Business Insight and Project Insight" in text
    # V1 validation workflow: Reviewed/Acknowledged only — no Approve/Reject.
    lowered = text.lower()
    assert "reviewed" in lowered
    assert "acknowledged" in lowered
