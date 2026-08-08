from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.services.knowledge_graph_lifecycle.impact_analyzer import GraphImpactAnalyzer


class LifecycleBase:
    """Mixin base that provides type declarations and a catch-all getattr."""

    session: AsyncSession
    context: RequestContext | None
    impact_analyzer: GraphImpactAnalyzer

    def __getattr__(self, name: str) -> Any:
        raise AttributeError(name)
