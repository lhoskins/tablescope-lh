"""Tests for the analytical method executor registry and R fallbacks."""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from app.services.analytical_method_engine.executors import ExecRequest, ExecutorRegistry
from app.services.analytical_method_engine.executors.python_executor import PythonExecutor
from app.services.analytical_method_engine.executors.r_executor import RExecutor


def _df() -> pd.DataFrame:
    return pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0, 5.0]})


def test_registry_routes_python_by_default() -> None:
    registry = ExecutorRegistry()
    executor = registry.get("python")
    assert isinstance(executor, PythonExecutor)


def test_registry_routes_r_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("R_ANALYTICS_ENABLED", "true")
    registry = ExecutorRegistry()
    executor = registry.get("r")
    assert isinstance(executor, RExecutor)


def test_registry_falls_back_to_python_when_r_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("R_ANALYTICS_ENABLED", "false")
    registry = ExecutorRegistry()
    executor = registry.get("r")
    assert isinstance(executor, PythonExecutor)


def test_python_executor_runs_existing_describe_numeric() -> None:
    registry = ExecutorRegistry()
    request = ExecRequest(
        method_id="describe_numeric",
        executor_key="describe_numeric",
        df=_df(),
        roles={"value": "x"},
        profile={},
    )
    result = registry.get("python").execute(request)
    assert result["status"] == "ok"
    assert result["n"] == 5


def test_r_executor_returns_error_when_service_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("R_ANALYTICS_ENABLED", "true")
    monkeypatch.setenv("R_ANALYTICS_URL", "http://r-analytics:8000")

    registry = ExecutorRegistry()
    request = ExecRequest(
        method_id="r_descriptive_profile",
        executor_key="describe_numeric",
        df=_df(),
        roles={"value": "x"},
        profile={},
    )
    # Service is not running in tests, so the request should fail open.
    result = registry.get("r").execute(request)
    assert result["status"] == "error"
    assert "R analytics unavailable" in result.get("reason", "")


def test_registry_execute_picks_engine_from_method() -> None:
    registry = ExecutorRegistry()
    method = {
        "method_id": "describe_numeric",
        "executor_key": "describe_numeric",
        "execution_engine": "python",
    }
    result = registry.execute(method, _df(), {"value": "x"}, {})
    assert result["status"] == "ok"


def test_registry_execute_honors_max_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("R_ANALYTICS_ENABLED", "true")
    captured: list[dict] = []

    def _fake_post(self, url: str, *, json: dict, **kwargs: object) -> object:
        captured.append(json)

        class _Resp:
            status_code = 200
            def raise_for_status(self) -> None: ...
            def json(self) -> dict:
                return {"status": "ok", "n": len(json["rows"]), "results": {}}

        return _Resp()

    with patch("httpx.Client.post", _fake_post):
        registry = ExecutorRegistry()
        method = {
            "method_id": "r_descriptive_profile",
            "executor_key": "describe_numeric",
            "execution_engine": "r",
            "max_rows": 3,
            "timeout_seconds": 10,
        }
        df = _df()
        df = pd.concat([df, df, df], ignore_index=True)
        result = registry.execute(method, df, {"value": "x"}, {})

    assert result["status"] == "ok"
    assert result["n"] == 3
    assert captured
    assert captured[0]["max_rows"] == 3
