from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext


class ProjectContextBase:
    """Mixin base that provides type declarations and a catch-all getattr."""

    session: AsyncSession
    context: RequestContext

    def __getattr__(self, name: str) -> Any:
        raise AttributeError(name)
