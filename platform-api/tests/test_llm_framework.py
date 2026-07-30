"""Tests for the LLM Framework service layer."""

from __future__ import annotations

import pytest

from app.models.llm_framework import ROUTING_CAPABILITIES
from app.services.llm_framework import (
    CAPABILITIES,
    InvalidCapabilityError,
    validate_routing_capability,
)


def test_routing_capabilities_excludes_embed() -> None:
    assert "embed" not in ROUTING_CAPABILITIES
    assert "embedding" not in ROUTING_CAPABILITIES


def test_service_capabilities_match_model() -> None:
    assert sorted(CAPABILITIES) == sorted(ROUTING_CAPABILITIES)


async def test_validate_routing_capability_accepts_routable() -> None:
    assert await validate_routing_capability("sql_generation") == "sql_generation"


async def test_validate_routing_capability_rejects_embed() -> None:
    with pytest.raises(InvalidCapabilityError) as exc:
        await validate_routing_capability("embed")
    assert "re-index" in str(exc.value).lower() or "embedding" in str(exc.value).lower()


async def test_validate_routing_capability_rejects_unknown() -> None:
    with pytest.raises(InvalidCapabilityError) as exc:
        await validate_routing_capability("code")
    assert "not a routable capability" in str(exc.value)
