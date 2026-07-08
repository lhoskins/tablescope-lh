"""Load shared prompt-reference files bundled with the AI server.

Reference files (e.g. ``dashboard_best_practices.md``) live under
``app/prompts`` and are injected into the relevant LLM prompts so the
generation policy lives in one editable place rather than inline strings.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"


@lru_cache(maxsize=16)
def load_prompt_reference(name: str) -> str:
    """Return the text of a prompt reference file, or "" if it is missing."""
    path = PROMPTS_DIR / name
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")
