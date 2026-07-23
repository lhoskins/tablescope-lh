"""Multi-source, multi-entity insight generation.

Typed planning contract, deterministic relationship/cardinality validation,
grain-safe SQL generation, and governed method-bundle execution for comparing
named business entities across safely joinable source tables.
"""

from __future__ import annotations

from app.services.multi_entity_insights.planner import (
    MultiEntityPlanner,
    generate_multi_entity_insights,
    is_multi_entity_eligible,
)

__all__ = [
    "MultiEntityPlanner",
    "generate_multi_entity_insights",
    "is_multi_entity_eligible",
]
