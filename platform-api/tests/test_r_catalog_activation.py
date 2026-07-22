"""Tests for the R-first catalog activation and curated R method sets."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.models.analytical_method_catalog import AnalyticalMethod
from app.services.analytical_method_engine import method_executor
from app.services.analytical_method_engine.catalog_admin import implementation_available
from scripts.convert_analytical_catalog import EXECUTABLE, EXECUTABLE_R, build


def test_catalog_contains_set_a_and_set_b() -> None:
    catalog = build()
    executable = [m for m in catalog["methods"] if m["is_executable"]]
    set_a_ids = {e["method_id"] for e in EXECUTABLE}
    set_b_ids = {e["method_id"] for e in EXECUTABLE_R}
    executable_ids = {m["method_id"] for m in executable}
    assert catalog["version"] == "1.1"
    assert set_a_ids <= executable_ids
    assert set_b_ids <= executable_ids
    assert all(m.get("execution_engine") == "r" for m in executable if m["method_id"] in (set_a_ids | set_b_ids))


def test_selection_matrix_contains_set_b_intents() -> None:
    catalog = build()
    intents = {row["analysis_intent"] for row in catalog["selection_matrix"]}
    for intent in ("compare_periods", "compare_year_over_year", "compare_to_baseline",
                   "measure_rate_of_change", "detect_change_point", "detect_anomalies",
                   "forecast_time_series", "contribution_to_change"):
        assert intent in intents, f"{intent} missing from selection matrix"


def test_implementation_available_python_executor() -> None:
    method = AnalyticalMethod(
        method_id="describe_numeric",
        execution_engine="python",
        executor_key="describe_numeric",
        is_executable=True,
    )
    assert implementation_available(method) is True


def test_implementation_available_r_method() -> None:
    method = AnalyticalMethod(
        method_id="period_change",
        execution_engine="r",
        executor_key="period_change",
        is_executable=True,
    )
    assert implementation_available(method) is True


def test_implementation_available_unknown_is_false() -> None:
    method = AnalyticalMethod(
        method_id="unknown_method",
        execution_engine="r",
        executor_key="no_such_r_method",
        is_executable=False,
    )
    assert implementation_available(method) is False


def test_r_fallback_to_python_when_r_service_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("R_ANALYTICS_ENABLED", "true")
    monkeypatch.setenv("R_ANALYTICS_FAILURE_MODE", "python_fallback")

    from app.services.analytical_method_engine.executors import ExecutorRegistry

    def _fake_post(self, url: str, *, json: dict, **kwargs: object) -> object:
        raise RuntimeError("Connection refused")

    with patch("httpx.Client.post", _fake_post):
        result = ExecutorRegistry().execute(
            {
                "method_id": "describe_numeric",
                "executor_key": "describe_numeric",
                "execution_engine": "r",
            },
            MagicMock(),
            {"value": "x"},
            {},
        )

    assert result.get("executionEngine") == "python"
    assert result.get("fallbackFrom") == "r"
    assert "method_executor.EXECUTORS" not in str(result)


def test_set_b_no_python_executor() -> None:
    for key in ("period_change", "detect_change_point", "detect_anomalies",
                "forecast_time_series", "contribution_to_change"):
        assert key not in method_executor.EXECUTORS, f"{key} should not have a Python executor yet"
