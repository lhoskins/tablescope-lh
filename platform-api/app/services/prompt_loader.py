"""Load shared prompt-reference files bundled with the platform API.

Reference files (e.g. ``home_insight_best_practices.md``) live under
``app/prompts`` and encode generation policy in one editable place rather
than scattered inline strings.
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
