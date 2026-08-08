"""R analytics feature gates.

Orthogonal to EngineMode. R is disabled by default and must be explicitly
enabled in the deployment environment.
"""

from __future__ import annotations

import os

DEFAULT_R_ANALYTICS_ENABLED = "true"
DEFAULT_R_ANALYTICS_URL = "http://r-analytics:8000"
DEFAULT_R_ANALYTICS_TIMEOUT_SECONDS = "30"
DEFAULT_R_ANALYTICS_FAILURE_MODE = "python_fallback"  # "error" or "python_fallback"


def r_analytics_failure_mode() -> str:
    return (os.getenv("R_ANALYTICS_FAILURE_MODE") or DEFAULT_R_ANALYTICS_FAILURE_MODE).strip().lower()


def is_r_analytics_enabled() -> bool:
    raw = (os.getenv("R_ANALYTICS_ENABLED") or DEFAULT_R_ANALYTICS_ENABLED).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def r_analytics_url() -> str:
    return (os.getenv("R_ANALYTICS_URL") or DEFAULT_R_ANALYTICS_URL).strip()


def r_analytics_timeout_seconds() -> int:
    try:
        return int(os.getenv("R_ANALYTICS_TIMEOUT_SECONDS") or DEFAULT_R_ANALYTICS_TIMEOUT_SECONDS)
    except ValueError:
        return 30
