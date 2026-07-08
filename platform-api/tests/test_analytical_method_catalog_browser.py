"""Tests for the read-only analytical-method catalog browser (admin surface)."""

from __future__ import annotations

import pytest_asyncio

from app.models.analytical_method_catalog import (
    STATUS_ACTIVE,
    STATUS_DRAFT,
    AnalyticalMethod,
    MethodCatalog,
    MethodCatalogVersion,
)
from app.services.analytical_method_engine import catalog_browser
from app.services.analytical_method_engine.method_registry import CATALOG_KEY


def _method(version_id: int, mid: str, *, tier: int, executable: bool, category: str):
    return AnalyticalMethod(
        catalog_version_id=version_id,
        method_id=mid,
        display_name=mid.replace("_", " ").title(),
        category=category,
        tier=tier,
        status=STATUS_ACTIVE if executable else STATUS_DRAFT,
        summary=f"Summary for {mid}",
        supported_intents=["compare"] if tier == 1 else ["forecast"],
        is_executable=executable,
    )


@pytest_asyncio.fixture(scope="function")
async def seeded(db_session):
    catalog = MethodCatalog(
        catalog_key=CATALOG_KEY, name="Analytical Methods", is_system=True, is_active=True
    )
    db_session.add(catalog)
    await db_session.flush()
    version = MethodCatalogVersion(
        catalog_id=catalog.id, version="1.0", status=STATUS_ACTIVE
    )
    db_session.add(version)
    await db_session.flush()
    db_session.add_all(
        [
            _method(version.id, "descriptive_stats", tier=1, executable=True, category="Descriptive"),
            _method(version.id, "correlation", tier=1, executable=True, category="Descriptive"),
            _method(version.id, "arima_forecast", tier=2, executable=False, category="Forecasting"),
            _method(version.id, "monte_carlo", tier=3, executable=False, category="Forecasting"),
        ]
    )
    version.method_count = 4
    catalog.active_version_id = version.id
    await db_session.commit()
    return db_session


async def test_overview_breaks_down_by_tier_status_category(seeded):
    overview = await catalog_browser.get_catalog_overview(seeded)
    assert overview is not None
    assert overview["methods_total"] == 4
    assert overview["executable_total"] == 2
    assert overview["by_tier"] == {"tier_1": 2, "tier_2": 1, "tier_3": 1}
    assert overview["by_status"] == {STATUS_ACTIVE: 2, STATUS_DRAFT: 2}
    assert overview["by_category"]["Forecasting"] == 2


async def test_list_filters_by_tier_and_search(seeded):
    tier1 = await catalog_browser.list_methods(seeded, tier=1)
    assert tier1["total"] == 2
    assert {m["method_id"] for m in tier1["methods"]} == {"descriptive_stats", "correlation"}

    search = await catalog_browser.list_methods(seeded, query="monte")
    assert search["total"] == 1
    assert search["methods"][0]["method_id"] == "monte_carlo"

    executable = await catalog_browser.list_methods(seeded, executable=True)
    assert executable["total"] == 2


async def test_list_paginates(seeded):
    page = await catalog_browser.list_methods(seeded, limit=2, offset=0)
    assert page["total"] == 4
    assert len(page["methods"]) == 2
    page2 = await catalog_browser.list_methods(seeded, limit=2, offset=2)
    assert len(page2["methods"]) == 2
    assert {m["method_id"] for m in page["methods"]} != {
        m["method_id"] for m in page2["methods"]
    }


async def test_detail_returns_full_record_or_none(seeded):
    detail = await catalog_browser.get_method_detail(seeded, "correlation")
    assert detail is not None
    assert detail["method_id"] == "correlation"
    assert "output_contract" in detail
    assert await catalog_browser.get_method_detail(seeded, "does_not_exist") is None
