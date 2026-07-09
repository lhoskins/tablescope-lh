"""Engine mode gating.

The Method Engine ships behind a feature flag so it can be rolled out per the
plan's staged gating:

- ``off``      — engine never runs.
- ``readonly`` — engine computes + logs envelopes but never alters responses
  (default; safe for live hosts — hybrid classification runs without gating
  rendering).
- ``hybrid``   — engine additionally attaches the envelope to hybrid responses.

Controlled by env var ``ANALYTICAL_METHOD_ENGINE_MODE``.
"""

from __future__ import annotations

import os
from enum import Enum

DEFAULT_ENGINE_MODE = "readonly"


class EngineMode(str, Enum):
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
        return EngineMode.READONLY
