"""Deterministic analytical executors.

The registry dispatches a selected method to either the local Python executor
(scipy/statsmodels) or the remote R analytics service based on the method's
``execution_engine`` field. Both return the same normalized ``ExecResult`` shape.
"""

from __future__ import annotations

from app.services.analytical_method_engine.executors.base import ExecRequest, Executor
from app.services.analytical_method_engine.executors.python_executor import PythonExecutor
from app.services.analytical_method_engine.executors.r_executor import RExecutor
from app.services.analytical_method_engine.executors.registry import ExecutorRegistry

__all__ = ["ExecRequest", "Executor", "ExecutorRegistry", "PythonExecutor", "RExecutor"]
