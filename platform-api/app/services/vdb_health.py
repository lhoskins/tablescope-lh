"""VDB health checking utilities."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def check_vdb_health(vdb_id: str) -> str:
    """Check VDB health status. Returns 'deployed', 'inactive', or 'unknown'."""
    # For now, this is a pass-through; VDB health is tracked in the DB
    # Future: could ping Teiid Admin API to verify VDB is actually deployed
    return "unknown"
