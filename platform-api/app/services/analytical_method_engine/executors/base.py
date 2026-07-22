"""Executor base class and request/result contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ExecRequest:
    """Normalized execution payload for every executor."""

    def __init__(
        self,
        *,
        method_id: str,
        executor_key: str,
        df: Any,
        roles: dict[str, Any],
        profile: dict[str, Any],
        policies: dict[str, Any] | None = None,
        max_rows: int | None = None,
        timeout_seconds: int | None = None,
    ) -> None:
        self.method_id = method_id
        self.executor_key = executor_key
        self.df = df
        self.roles = roles
        self.profile = profile
        self.policies = policies or {}
        self.max_rows = max_rows
        self.timeout_seconds = timeout_seconds


class Executor(ABC):
    @abstractmethod
    def execute(self, request: ExecRequest) -> dict[str, Any]:
        """Run the method and return a normalized ExecResult dict. Never raises."""
        ...
