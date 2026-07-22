"""Tests for the analytical method executor registry and R fallbacks."""

from __future__ import annotations

import json as jsonlib
from unittest.mock import patch

import httpx
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


def test_registry_execute_routes_to_r_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("R_ANALYTICS_ENABLED", "true")
    captured: list[dict] = []

    def _fake_post(self, url: str, *, json: dict, **kwargs: object) -> object:
        captured.append(json)

        class _Resp:
            status_code = 200
            def raise_for_status(self) -> None: ...
            def json(self) -> dict:
                return {"status": "ok", "n": 5, "results": {"mean": 3.0}}

        return _Resp()

    with patch("httpx.Client.post", _fake_post):
        registry = ExecutorRegistry()
        method = {
            "method_id": "r_descriptive_profile",
            "executor_key": "describe_numeric",
            "execution_engine": "r",
        }
        result = registry.execute(method, _df(), {"value": "x"}, {})

    assert result["status"] == "ok"
    assert result["results"]["mean"] == 3.0
    assert captured[0]["method_id"] == "r_descriptive_profile"
    assert captured[0]["executor_key"] == "describe_numeric"
    assert captured[0]["columns"] == ["x"]
    assert captured[0]["roles"] == {"value": "x"}
    assert captured[0]["profile"] == {}
    assert captured[0]["policies"] == {}


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
    assert len(captured[0]["rows"]) == 3


def test_r_executor_returns_unchanged_success_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("R_ANALYTICS_ENABLED", "true")

    def _fake_post(self, url: str, *, json: dict, **kwargs: object) -> object:
        class _Resp:
            status_code = 200
            def raise_for_status(self) -> None: ...
            def json(self) -> dict:
                return {
                    "status": "ok",
                    "n": 5,
                    "results": {"mean": 3.0},
                    "assumptions": ["a"],
                    "caveats": ["c"],
                    "warnings": ["w"],
                    "quality": "reliable",
                }

        return _Resp()

    with patch("httpx.Client.post", _fake_post):
        registry = ExecutorRegistry()
        result = registry.get("r").execute(
            ExecRequest(
                method_id="r_descriptive_profile",
                executor_key="describe_numeric",
                df=_df(),
                roles={"value": "x"},
                profile={"hash": "h"},
            )
        )

    assert result["status"] == "ok"
    assert result["n"] == 5
    assert result["results"]["mean"] == 3.0
    assert result["quality"] == "reliable"


def test_r_executor_captures_payload_no_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("R_ANALYTICS_ENABLED", "true")
    captured: dict = {}

    def _fake_post(self, url: str, *, json: dict, **kwargs: object) -> object:
        captured.update(json)

        class _Resp:
            status_code = 200
            def raise_for_status(self) -> None: ...
            def json(self) -> dict:
                return {"status": "ok", "n": 1, "results": {}}

        return _Resp()

    with patch("httpx.Client.post", _fake_post):
        ExecutorRegistry().get("r").execute(
            ExecRequest(
                method_id="r_descriptive_profile",
                executor_key="describe_numeric",
                df=pd.DataFrame({"x": [1.0]}),
                roles={"value": "x"},
                profile={"hash": "h"},
                policies={"allowed": True},
            )
        )

    # No database/credential shaped keys leak through the executor contract.
    forbidden_keys = {"database_url", "db_password", "tenant_id", "secret", "token", "api_key"}
    for key in captured.keys():
        assert key.lower() not in forbidden_keys, f"Unexpected key in R payload: {key}"
    assert captured["method_id"] == "r_descriptive_profile"
    assert captured["rows"] == [{"x": 1.0}]


def test_r_executor_caps_rows_at_ten_thousand(monkeypatch: pytest.MonkeyPatch) -> None:
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
        df = pd.DataFrame({"x": [float(i) for i in range(12000)]})
        ExecutorRegistry().get("r").execute(
            ExecRequest(
                method_id="r_descriptive_profile",
                executor_key="describe_numeric",
                df=df,
                roles={"value": "x"},
                profile={},
            )
        )

    assert len(captured[0]["rows"]) == 10_000


def test_r_executor_returns_error_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("R_ANALYTICS_ENABLED", "true")

    def _fake_post(self, url: str, *, json: dict, **kwargs: object) -> object:
        raise httpx.TimeoutException("Request timed out")

    with patch("httpx.Client.post", _fake_post):
        result = ExecutorRegistry().get("r").execute(
            ExecRequest(
                method_id="r_descriptive_profile",
                executor_key="describe_numeric",
                df=_df(),
                roles={"value": "x"},
                profile={},
            )
        )

    assert result["status"] == "error"
    assert "R analytics unavailable" in result.get("reason", "")
    assert "Request timed out" in result.get("reason", "")


def test_r_executor_returns_error_on_http_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("R_ANALYTICS_ENABLED", "true")

    def _fake_post(self, url: str, *, json: dict, **kwargs: object) -> object:
        class _Resp:
            status_code = 500
            def raise_for_status(self) -> None:
                raise RuntimeError("Internal Server Error")
            def json(self) -> dict:
                return {}

        return _Resp()

    with patch("httpx.Client.post", _fake_post):
        result = ExecutorRegistry().get("r").execute(
            ExecRequest(
                method_id="r_descriptive_profile",
                executor_key="describe_numeric",
                df=_df(),
                roles={"value": "x"},
                profile={},
            )
        )

    assert result["status"] == "error"
    assert "Internal Server Error" in result.get("reason", "")


def test_r_executor_returns_error_on_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("R_ANALYTICS_ENABLED", "true")

    def _fake_post(self, url: str, *, json: dict, **kwargs: object) -> object:
        class _Resp:
            status_code = 200
            def raise_for_status(self) -> None: ...
            def json(self) -> dict:
                raise jsonlib.JSONDecodeError("bad json", "", 0)

        return _Resp()

    with patch("httpx.Client.post", _fake_post):
        result = ExecutorRegistry().get("r").execute(
            ExecRequest(
                method_id="r_descriptive_profile",
                executor_key="describe_numeric",
                df=_df(),
                roles={"value": "x"},
                profile={},
            )
        )

    assert result["status"] == "error"


def test_enabled_but_unavailable_with_error_mode_does_not_claim_python_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("R_ANALYTICS_ENABLED", "true")
    monkeypatch.setenv("R_ANALYTICS_FAILURE_MODE", "error")

    def _fake_post(self, url: str, *, json: dict, **kwargs: object) -> object:
        raise RuntimeError("Connection refused")

    with patch("httpx.Client.post", _fake_post):
        result = ExecutorRegistry().execute(
            {
                "method_id": "r_descriptive_profile",
                "executor_key": "describe_numeric",
                "execution_engine": "r",
            },
            _df(),
            {"value": "x"},
            {},
        )

    assert result["status"] == "error"
    assert "R analytics unavailable" in result.get("reason", "")
    assert "python" not in result.get("reason", "").lower()


def test_enabled_but_unavailable_python_fallback_for_set_a(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("R_ANALYTICS_ENABLED", "true")
    monkeypatch.setenv("R_ANALYTICS_FAILURE_MODE", "python_fallback")

    def _fake_post(self, url: str, *, json: dict, **kwargs: object) -> object:
        raise RuntimeError("Connection refused")

    with patch("httpx.Client.post", _fake_post):
        result = ExecutorRegistry().execute(
            {
                "method_id": "describe_numeric",
                "executor_key": "describe_numeric",
                "execution_engine": "r",
            },
            _df(),
            {"value": "x"},
            {},
        )

    assert result["status"] == "ok"
    assert result.get("executionEngine") == "python"
    assert result.get("fallbackFrom") == "r"
