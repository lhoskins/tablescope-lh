"""Engine mode gating.

The Method Engine ships behind a feature flag so it can be rolled out per the
plan's staged gating:

- ``off``      — engine never runs (code default; safe for tests/local).
- ``readonly`` — engine computes + logs envelopes but never alters responses.
- ``hybrid``   — engine additionally attaches the envelope to hybrid responses.

Controlled by env var ``ANALYTICAL_METHOD_ENGINE_MODE``. Production sets this to
``hybrid`` in the deployment environment; the code default stays ``off`` so
tests and local runs never execute the engine unless they opt in explicitly.
"""

from __future__ import annotations

import os
from enum import StrEnum

DEFAULT_ENGINE_MODE = "off"


class EngineMode(StrEnum):
    OFF = "off"
    READONLY = "readonly"
    HYBRID = "hybrid"


def get_engine_mode() -> EngineMode:
    raw = (
        os.getenv("ANALYTICAL_METHOD_ENGINE_MODE") or DEFAULT_ENGINE_MODE
    ).strip().lower()
    try:
        return EngineMode(raw)
    except ValueError:
        return EngineMode.OFF
