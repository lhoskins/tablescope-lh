"""Common helpers shared by demo dataset and document generators."""
from __future__ import annotations

from . import config as C

_PROJECT = {d.key: d.project for d in C.DEPARTMENTS}

def _seasonal(month: int) -> float:
    """A mild seasonal multiplier (summer dip, year-end push)."""
    return 1.0 + 0.06 * [0, 1, 2, 1, 0, -1, -2, -2, 0, 1, 2, 3][month - 1] / 3.0

_SYNTHETIC = (
    "> **Synthetic demo content.** All names, financials, employees, suppliers, "
    "and events in this document are fictional and generated for Tablescope "
    "demonstrations only.\n"
)
