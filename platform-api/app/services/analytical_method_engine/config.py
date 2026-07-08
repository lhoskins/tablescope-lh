"""Engine mode gating.

The Method Engine ships behind a feature flag so it can be rolled out per the
plan's staged gating:

- ``off``      — engine never runs (default; safe for live hosts).
- ``readonly`` — engine computes + logs envelopes but never alters responses.
- ``hybrid``   — engine additionally attaches the envelope to hybrid responses.

Controlled by env var ``ANALYTICAL_METHOD_ENGINE_MODE``.
"""

from __future__ import annotations

import os
from enum import Enum


class EngineMode(str, Enum):
    OFF = "off"
    READONLY = "readonly"
    HYBRID = "hybrid"


def get_engine_mode() -> EngineMode:
    raw = (os.getenv("ANALYTICAL_METHOD_ENGINE_MODE") or "off").strip().lower()
    try:
        return EngineMode(raw)
    except ValueError:
        return EngineMode.OFF
