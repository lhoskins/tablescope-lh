"""Python executor wrapping the existing scipy/statsmethods implementations.

This is a thin adapter so the engine can dispatch by ``execution_engine``
without changing the numeric behavior of the existing executors.
"""

from __future__ import annotations

from typing import Any

from app.services.analytical_method_engine.executors.base import ExecRequest, Executor
from app.services.analytical_method_engine import method_executor


class PythonExecutor(Executor):
    def execute(self, request: ExecRequest) -> dict[str, Any]:
        return method_executor.execute(
            request.executor_key,
            request.df,
            request.roles,
            request.profile,
            request.policies,
        )
