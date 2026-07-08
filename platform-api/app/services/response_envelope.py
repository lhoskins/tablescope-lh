"""Shared ``ResponseEnvelope`` — one response contract across AI surfaces.

Plan §7.1 recommends, as the concrete first step of Presentation Engine
unification, a single Pydantic superset model that every mode can converge on
(mode-specific fields optional) instead of the five/six divergent, bespoke
response schemas that exist today. Endpoints can adopt it incrementally; the
frontend unification follows once endpoints emit a consistent shape.

This model carries data only — the *sections* to render for its ``mode`` come
from :mod:`app.services.presentation_engine`, the single section registry.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from app.services.presentation_engine import (
    PresentationMode,
    describe,
)

logger = logging.getLogger(__name__)


class ResponseEnvelope(BaseModel):
    """Superset of the fields across all AI response surfaces.

    Only ``mode`` and ``sections`` are always present. Every other field is
    optional and populated per mode, so a conversational answer and a dashboard
    can share one contract without inventing empty data for absent sections.
    """

    mode: str
    sections: list[str] = Field(default_factory=list)

    # Narrative / prose
    summary: str | None = None
    executive_summary: str | None = None
    answer: str | None = None
    key_points: list[str] | None = None
    key_findings: list[Any] | None = None
    key_drivers: list[Any] | None = None
    recommended_actions: list[Any] | None = None

    # Structured data
    sql: str | None = None
    columns: list[str] | None = None
    rows: list[Any] | None = None
    chart: dict[str, Any] | None = None
    method_envelope: dict[str, Any] | None = None

    # Provenance
    sources: list[Any] | None = None
    references: list[Any] | None = None
    evidence: list[Any] | None = None
    citations: list[Any] | None = None
    document_references: list[Any] | None = None

    # Routing / meta
    intent: dict[str, Any] | None = None
    status: str | None = None
    follow_ups: list[str] | None = None

    @classmethod
    def build(cls, mode: PresentationMode, **fields: Any) -> ResponseEnvelope:
        """Construct an envelope, stamping ``sections`` from the registry.

        Unknown/None fields are simply omitted; the section registry — not the
        caller — decides which sections the mode renders.
        """
        payload = {k: v for k, v in fields.items() if v is not None}
        payload["mode"] = mode.value
        payload["sections"] = describe(mode)["sections"]
        return cls(**payload)


def attach_envelope(
    response: dict[str, Any], mode: PresentationMode, **fields: Any
) -> None:
    """Additively stamp ``presentation`` + ``envelope`` on a response dict.

    Used by surfaces that keep their bespoke frontend renderer but still emit
    the shared contract (Home intelligence cards, document profiles). It never
    replaces existing keys and is *fail-closed*: a registry/model error logs and
    skips rather than breaking the surface, so a consumer that ignores the
    envelope is unaffected.
    """
    try:
        if not isinstance(response, dict):
            return
        response["presentation"] = describe(mode)
        response["envelope"] = ResponseEnvelope.build(mode, **fields).model_dump(
            exclude_none=True
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Presentation envelope stamp failed (%s): %s", mode, exc)
