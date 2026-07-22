"""Executor registry dispatch.

Selects the right executor for a method based on ``execution_engine`` and the
``R_ANALYTICS_ENABLED`` feature gate. Keeps Python as the default and fallback.
"""

from __future__ import annotations

from typing import Any

from app.services.analytical_method_engine import method_executor
from app.services.analytical_method_engine.executors.base import ExecRequest, Executor
from app.services.analytical_method_engine.executors.python_executor import PythonExecutor
from app.services.analytical_method_engine.executors.r_executor import RExecutor
from app.services.analytical_method_engine.r_config import (
    is_r_analytics_enabled,
    r_analytics_failure_mode,
)


class ExecutorRegistry:
    """Simple registry of execution engines.

    Instances are stateless and cheap to create; they are not cached globally
    so feature-gate changes are respected on every call.
    """

    def get(self, execution_engine: str | None) -> Executor:
        engine = (execution_engine or "python").lower()
        if engine == "r" and is_r_analytics_enabled():
            return RExecutor()
        return PythonExecutor()

    def execute(
        self,
        method: dict[str, Any],
        df: Any,
        roles: dict[str, Any],
        profile: dict[str, Any],
        policies: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        request = ExecRequest(
            method_id=method.get("method_id") or "unknown",
            executor_key=method.get("executor_key") or "",
            df=df,
            roles=roles,
            profile=profile,
            policies=policies,
            max_rows=method.get("max_rows"),
            timeout_seconds=method.get("timeout_seconds"),
        )
        engine = (method.get("execution_engine") or "python").lower()
        if engine == "r" and is_r_analytics_enabled():
            r_result = RExecutor().execute(request)
            if r_result.get("status") == "ok":
                r_result["executionEngine"] = "r"
                return r_result
            if r_analytics_failure_mode() == "python_fallback" and request.executor_key in method_executor.EXECUTORS:
                py_result = PythonExecutor().execute(request)
                py_result["executionEngine"] = "python"
                py_result["fallbackFrom"] = "r"
                if py_result.get("status") == "ok":
                    py_result["quality"] = "reliable (python fallback)"
                return py_result
            # No fallback available; return the R error envelope.
            r_result["executionEngine"] = "r"
            return r_result
        result = PythonExecutor().execute(request)
        result["executionEngine"] = "python"
        return result
