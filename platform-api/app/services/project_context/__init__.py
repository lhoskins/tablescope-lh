"""Project business context service.

Handles CRUD, ordering, optimistic concurrency, relationship validation,
audit logging, and AI context building for project goals, metrics, targets,
and risks.
"""

from __future__ import annotations

from .core import CoreMixin, ProjectContextConcurrencyError
from .goals import GoalsMixin
from .metrics import MetricsMixin
from .reads import ReadsMixin
from .risks import RisksMixin
from .targets import TargetsMixin, _default_comparison


class ProjectContextService(
    GoalsMixin,
    MetricsMixin,
    RisksMixin,
    CoreMixin,
    TargetsMixin,
    ReadsMixin,
):
    """CRUD, validation, ordering, and audit for project business context."""
    pass

__all__ = ["ProjectContextService", "ProjectContextConcurrencyError", "_default_comparison"]
