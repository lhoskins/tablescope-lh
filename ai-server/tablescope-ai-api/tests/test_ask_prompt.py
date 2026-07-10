"""Tests for the prose-only ``ASK_SYSTEM_PROMPT`` used by ``ask()``.

Kept free of router imports so it runs without the optional vector-store deps
(qdrant), mirroring ``test_project_insight_prompt``. The ``ask()`` endpoint is
the prose fallback channel: it must use a prompt that never emits SQL, while the
relationship-suggestion endpoint keeps the SQL-capable ``SYSTEM_PROMPT``.
"""

from __future__ import annotations

import ast
from pathlib import Path

_AI_ROUTER = Path(__file__).resolve().parents[1] / "app" / "routers" / "ai.py"


def _constant(name: str) -> str:
    """Extract a module-level string constant from ai.py without importing it."""
    tree = ast.parse(_AI_ROUTER.read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not found in ai.py")


def test_ask_system_prompt_forbids_sql() -> None:
    prompt = _constant("ASK_SYSTEM_PROMPT")
    assert prompt
    assert "PROSE channel" in prompt
    assert "NEVER output SQL" in prompt


def test_ask_uses_ask_system_prompt_not_shared() -> None:
    """``ask()`` must call the LLM with ASK_SYSTEM_PROMPT; the relationship
    endpoint keeps the SQL-capable SYSTEM_PROMPT."""
    source = _AI_ROUTER.read_text()
    async_ask = source.index("async def ask(")
    next_def = source.index("\nasync def ", async_ask + 1)
    ask_body = source[async_ask:next_def]
    assert "system_prompt=ASK_SYSTEM_PROMPT" in ask_body
    assert "system_prompt=SYSTEM_PROMPT" not in ask_body
    # The shared SQL-capable prompt is still used elsewhere (relationships).
    assert "system_prompt=SYSTEM_PROMPT" in source
