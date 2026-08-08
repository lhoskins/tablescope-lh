"""Tests for the R-first catalog activation and curated R method sets."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.models.analytical_method_catalog import (
    STATUS_ACTIVE,
    STATUS_DRAFT,
    AnalyticalMethod,
    MethodCatalog,
    MethodCatalogVersion,
)
from app.services.analytical_method_engine import method_executor
from app.services.analytical_method_engine.catalog_admin import (
    activate_method,
    deactivate_method,
    implementation_available,
)
from scripts.convert_analytical_catalog import EXECUTABLE, EXECUTABLE_R, build

pytestmark = pytest.mark.anyio


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


def test_available_r_methods_falls_back_to_static_when_service_is_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A transient R service outage must not hard-disable every R method."""
    from app.services.analytical_method_engine import catalog_admin

    monkeypatch.setenv("R_ANALYTICS_ENABLED", "true")
    # Reset the cache so the service query is attempted fresh.
    catalog_admin._r_methods_cache = None
    with patch("httpx.Client.get", side_effect=RuntimeError("connection refused")):
        methods = catalog_admin.available_r_methods()
    assert "period_change" in methods
    assert "describe_numeric" in methods


def test_available_r_methods_uses_cached_list_on_subsequent_unreachable_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.analytical_method_engine import catalog_admin

    monkeypatch.setenv("R_ANALYTICS_ENABLED", "true")
    catalog_admin._r_methods_cache = ({"cached_method"}, 0.0)
    with patch("httpx.Client.get", side_effect=RuntimeError("connection refused")):
        methods = catalog_admin.available_r_methods()
    # TTL expired, but the stale cache should still be returned when the service fails.
    assert "cached_method" in methods


def test_implementation_available_set_b_false_when_r_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("R_ANALYTICS_ENABLED", "false")
    method = AnalyticalMethod(
        method_id="period_change",
        execution_engine="r",
        executor_key="period_change",
        is_executable=True,
    )
    assert implementation_available(method) is False


def test_implementation_available_set_a_true_when_r_disabled_due_to_python_twin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("R_ANALYTICS_ENABLED", "false")
    method = AnalyticalMethod(
        method_id="describe_numeric",
        execution_engine="r",
        executor_key="describe_numeric",
        is_executable=True,
    )
    assert implementation_available(method) is True


async def test_activate_and_deactivate_persist_on_active_version(db_session) -> None:
    """Admin toggles survive in the active catalog version and invalidate the registry cache."""
    from app.services.analytical_method_engine import method_registry

    catalog = MethodCatalog(catalog_key="tablescope_analytical_methods", name="Test", is_active=True)
    db_session.add(catalog)
    await db_session.flush()

    version = MethodCatalogVersion(
        catalog_id=catalog.id,
        version="1.0",
        status=STATUS_ACTIVE,
    )
    db_session.add(version)
    await db_session.flush()

    catalog.active_version_id = version.id
    method = AnalyticalMethod(
        catalog_version_id=version.id,
        method_id="describe_numeric",
        display_name="Describe numeric",
        execution_engine="r",
        executor_key="describe_numeric",
        status=STATUS_DRAFT,
        is_executable=False,
    )
    db_session.add(method)
    await db_session.commit()

    method_registry.invalidate_cache()
    activated = await activate_method(db_session, "describe_numeric", actor_user_id=1)
    assert activated["status"] == STATUS_ACTIVE
    assert activated["is_executable"] is True

    await db_session.refresh(method)
    assert method.status == STATUS_ACTIVE
    assert method.is_executable is True

    deactivated = await deactivate_method(db_session, "describe_numeric", actor_user_id=1)
    assert deactivated["status"] == STATUS_DRAFT
    assert deactivated["is_executable"] is False


async def test_activate_rejects_unimplemented_method(db_session) -> None:
    catalog = MethodCatalog(catalog_key="tablescope_analytical_methods", name="Test 2", is_active=True)
    db_session.add(catalog)
    await db_session.flush()

    version = MethodCatalogVersion(
        catalog_id=catalog.id,
        version="1.0",
        status=STATUS_ACTIVE,
    )
    db_session.add(version)
    await db_session.flush()

    catalog.active_version_id = version.id
    method = AnalyticalMethod(
        catalog_version_id=version.id,
        method_id="no_such_method",
        display_name="No such method",
        execution_engine="r",
        executor_key="no_such_r_method",
        status=STATUS_DRAFT,
        is_executable=False,
    )
    db_session.add(method)
    await db_session.commit()

    with pytest.raises(ValueError, match="No implementation available"):
        await activate_method(db_session, "no_such_method", actor_user_id=1)
