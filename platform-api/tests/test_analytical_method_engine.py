"""Tests for the Analytical Method Engine (M1).

Covers: data profiling scope, deterministic method selection & gating, result
envelope structure, audit logging, and the Tier-1-only activation rule (Tier 2/3
seed as draft and never enter the runtime registry).
"""

from __future__ import annotations

import numpy as np
import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.models.analytical_method_catalog import (
    STATUS_ACTIVE,
    STATUS_DRAFT,
    AnalyticalMethod,
    MethodCatalogAuditLog,
)
from app.services.analytical_method_engine import (
    data_profiler,
    engine,
    method_executor,
    method_registry,
)
from app.services.analytical_method_engine.column_roles import resolve_roles
from app.services.analytical_method_engine.intent import infer_intent


@pytest_asyncio.fixture(scope="function")
async def seeded(db_session):
    """Seed the analytical catalog into the in-memory DB and reset the cache."""
    method_registry.invalidate_cache()
    import json

    from app.models.analytical_method_catalog import (
        AnalyticalSharedPolicy,
        MethodCatalog,
        MethodCatalogVersion,
        MethodSelectionMatrix,
    )
    from scripts.seed_analytical_catalog import CATALOG_FILE

    data = json.loads(CATALOG_FILE.read_text())
    catalog = MethodCatalog(
        catalog_key=data["catalog_key"], name=data["name"],
        description=data.get("description"), source_document=data.get("source_document"),
        is_system=True, is_active=True,
    )
    db_session.add(catalog)
    await db_session.flush()
    version = MethodCatalogVersion(
        catalog_id=catalog.id, version=data["version"], status=STATUS_ACTIVE,
    )
    db_session.add(version)
    await db_session.flush()
    for m in data["methods"]:
        executable = bool(m.get("is_executable"))
        db_session.add(AnalyticalMethod(
            catalog_version_id=version.id, method_id=m["method_id"],
            display_name=m["display_name"], category=m.get("category"),
            subcategory=m.get("subcategory"), tier=m.get("tier", 2),
            status=STATUS_ACTIVE if executable else STATUS_DRAFT,
            summary=m.get("summary"), applicability_condition=m.get("applicability_condition"),
            supported_intents=m.get("supported_intents", []),
            selection_rules=m.get("selection_rules", []),
            rejection_rules=m.get("rejection_rules", []),
            required_checks=m.get("required_checks", []),
            fallback_methods=m.get("fallback_methods", []),
            output_contract=m.get("output_contract", {}),
            method_card=m.get("method_card", {}),
            llm_guardrails=m.get("llm_guardrails", []),
            executor_key=m.get("executor_key"), dependencies=m.get("dependencies", []),
            is_executable=executable,
        ))
    for p in data["shared_policies"]:
        db_session.add(AnalyticalSharedPolicy(
            catalog_version_id=version.id, policy_key=p["policy_key"], name=p["name"],
            description=p.get("description"), rules=p.get("rules", {}),
        ))
    for row in data["selection_matrix"]:
        db_session.add(MethodSelectionMatrix(
            catalog_version_id=version.id, analysis_intent=row["analysis_intent"],
            data_profile=row.get("data_profile"), primary_method_id=row["primary_method_id"],
            alternative_method_ids=row.get("alternative_method_ids", []),
            priority=row.get("priority", 100),
        ))
    version.method_count = len(data["methods"])
    catalog.active_version_id = version.id
    await db_session.commit()
    method_registry.invalidate_cache()
    return db_session


def _linear_rows(n=60, slope=2.0, noise=3.0, seed=0):
    rng = np.random.default_rng(seed)
    x = np.arange(n, dtype=float)
    y = slope * x + rng.normal(0, noise, n)
    return ["x", "y"], [[float(a), float(b)] for a, b in zip(x, y, strict=False)]


# --------------------------------------------------------------------------- #
# Data profiler scope
# --------------------------------------------------------------------------- #
def test_profiler_classifies_columns_and_shape():
    cols = ["region", "revenue", "flag"]
    rows = [["west", 100.0, 1], ["east", 200.0, 0], ["west", 300.0, 1], ["east", 50.0, 0]]
    prof = data_profiler.profile(cols, rows)
    assert prof["row_count"] == 4
    assert "revenue" in prof["numeric_columns"]
    assert "region" in prof["categorical_columns"]
    assert "flag" in prof["binary_columns"]
    assert prof["columns"]["revenue"]["null_rate"] == 0.0


def test_profiler_computes_outliers_and_normality():
    cols, rows = _linear_rows(n=40)
    # inject an outlier
    rows.append([100.0, 100000.0])
    prof = data_profiler.profile(cols, rows)
    assert prof["columns"]["y"]["outlier_count"] >= 1
    assert prof["columns"]["y"]["n"] == 41


def test_profiler_caches_by_hash():
    cols, rows = _linear_rows()
    p1 = data_profiler.profile(cols, rows)
    p2 = data_profiler.profile(cols, rows)
    assert p1 is p2
    assert p1["hash"]


# --------------------------------------------------------------------------- #
# Intent + role resolution
# --------------------------------------------------------------------------- #
def test_intent_inference_relationship():
    cols, rows = _linear_rows()
    prof = data_profiler.profile(cols, rows)
    assert infer_intent("what is the correlation between x and y", prof) == "relationship_numeric"


def test_roles_none_when_shape_insufficient():
    prof = data_profiler.profile(["only_one"], [[1.0], [2.0], [3.0]])
    assert resolve_roles("relationship_numeric", prof) is None


# --------------------------------------------------------------------------- #
# Registry: Tier-1-only activation
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_registry_only_contains_active_executable(seeded):
    registry = await method_registry.get_active_registry(seeded)
    assert registry is not None
    # Every method in the runtime registry is executable + Tier 1.
    for m in registry["methods"].values():
        assert m["is_executable"] is True
        assert m["tier"] == 1
    assert "pearson_correlation" in registry["methods"]


@pytest.mark.asyncio
async def test_tier2_and_tier3_seed_as_draft(seeded):
    # Draft (non-executable) methods exist and are NOT in the active registry.
    draft_count = await seeded.scalar(
        select(func.count()).select_from(AnalyticalMethod).where(
            AnalyticalMethod.status == STATUS_DRAFT
        )
    )
    assert draft_count > 500
    registry = await method_registry.get_active_registry(seeded)
    # a known Tier-2/3 method id must not be runtime-available
    any_draft = await seeded.scalar(
        select(AnalyticalMethod.method_id).where(AnalyticalMethod.status == STATUS_DRAFT).limit(1)
    )
    assert any_draft not in registry["methods"]


# --------------------------------------------------------------------------- #
# Executor gating
# --------------------------------------------------------------------------- #
def test_executor_gates_on_minimum_sample():
    cols, rows = ["x", "y"], [[1.0, 2.0], [2.0, 3.0], [3.0, 5.0]]
    prof = data_profiler.profile(cols, rows)
    df = data_profiler.to_dataframe(cols, rows)
    out = method_executor.execute("pearson_correlation", df, {"x": "x", "y": "y"}, prof)
    assert out["status"] == "insufficient_data"


def test_executor_pearson_success_shape():
    cols, rows = _linear_rows()
    prof = data_profiler.profile(cols, rows)
    df = data_profiler.to_dataframe(cols, rows)
    out = method_executor.execute("pearson_correlation", df, {"x": "x", "y": "y"}, prof)
    assert out["status"] == "ok"
    assert out["results"]["effectName"] == "pearson_r"
    assert 0.9 < out["results"]["effect"] <= 1.0
    assert out["results"]["pValue"] < 0.05
    assert len(out["results"]["confidenceInterval"]) == 2


def test_executor_unknown_key_errors():
    prof = data_profiler.profile(*_linear_rows())
    df = data_profiler.to_dataframe(*_linear_rows())
    out = method_executor.execute("does_not_exist", df, {}, prof)
    assert out["status"] == "error"


# --------------------------------------------------------------------------- #
# End-to-end engine + envelope + audit
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_engine_produces_envelope_and_audit(seeded):
    cols, rows = _linear_rows()
    envelope = await engine.analyze(
        seeded, tenant_id=None, columns=cols, rows=rows,
        question="is x correlated with y?",
    )
    assert envelope is not None
    assert envelope["status"] == "ok"
    assert envelope["method"] == "pearson_correlation"
    assert envelope["analysisIntent"] == "relationship_numeric"
    # Envelope completeness
    assert envelope["selectedMethodReason"]
    assert envelope["results"]["effectName"] == "pearson_r"
    assert envelope["audit"]["engineVersion"]
    assert envelope["audit"]["catalogMethodId"] == "pearson_correlation"
    assert envelope["audit"]["inputDataHash"]
    # Audit row written
    count = await seeded.scalar(select(func.count()).select_from(MethodCatalogAuditLog))
    assert count == 1


@pytest.mark.asyncio
async def test_engine_selects_robust_when_outliers(seeded):
    # Non-linear/outlier-heavy monotonic data -> selector should prefer Spearman.
    rng = np.random.default_rng(1)
    x = np.arange(40, dtype=float)
    y = np.exp(x / 8.0) + rng.normal(0, 1, 40)
    y[39] = 100000.0  # heavy outlier
    cols = ["x", "y"]
    rows = [[float(a), float(b)] for a, b in zip(x, y, strict=False)]
    envelope = await engine.analyze(
        seeded, tenant_id=None, columns=cols, rows=rows,
        question="relationship between x and y",
    )
    assert envelope is not None
    assert envelope["method"] in ("spearman_rank_correlation", "kendalls_tau")


@pytest.mark.asyncio
async def test_engine_no_method_when_shape_unsupported(seeded):
    envelope = await engine.analyze(
        seeded, tenant_id=None, columns=["label"], rows=[["a"], ["b"], ["c"]],
        question="tell me about this",
    )
    # single text column -> no statistical intent resolvable
    assert envelope is None or envelope["status"] in ("no_method", "insufficient_data")


@pytest.mark.asyncio
async def test_engine_fails_closed_without_registry(db_session):
    # No catalog seeded -> engine returns None rather than raising.
    method_registry.invalidate_cache()
    cols, rows = _linear_rows()
    envelope = await engine.analyze(
        db_session, tenant_id=None, columns=cols, rows=rows, question="correlation?",
    )
    assert envelope is None


# --------------------------------------------------------------------------- #
# Startup seed: auto-activation + idempotency (production enablement)
# --------------------------------------------------------------------------- #
def _session_factory(db_engine):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    return async_sessionmaker(db_engine, expire_on_commit=False)


async def _patch_session_local(db_engine, monkeypatch):
    """Point ``seed_analytical_catalog``'s SessionLocal at the test DB."""
    import app.database as database_module

    factory = _session_factory(db_engine)
    monkeypatch.setattr(database_module, "SessionLocal", factory)
    return factory


@pytest.mark.asyncio
async def test_seed_activates_and_is_idempotent(db_engine, monkeypatch):
    from app.models.analytical_method_catalog import (
        MethodCatalog,
        MethodCatalogVersion,
    )
    from scripts.seed_analytical_catalog import seed_analytical_catalog

    factory = await _patch_session_local(db_engine, monkeypatch)
    method_registry.invalidate_cache()

    stats = await seed_analytical_catalog()
    # Seed reports the version is active with a real executable count.
    assert stats["active"] is True
    assert stats["version_id"] is not None
    assert stats["executable"] >= 24

    async with factory() as s:
        registry = await method_registry.get_active_registry(s)
        assert registry is not None  # runtime registry is live with no admin step
        catalog = await s.scalar(
            select(MethodCatalog).where(
                MethodCatalog.catalog_key == "tablescope_analytical_methods"
            )
        )
        assert catalog.active_version_id is not None
        version = await s.get(MethodCatalogVersion, catalog.active_version_id)
        assert version.status == STATUS_ACTIVE
        assert version.approved_at is not None  # system approval stamped
        versions_before = await s.scalar(
            select(func.count()).select_from(MethodCatalogVersion)
        )

    # Re-running the seed must not create or re-activate a duplicate version.
    method_registry.invalidate_cache()
    stats2 = await seed_analytical_catalog()
    assert stats2["skipped"] == 1
    assert stats2["active"] is True
    async with factory() as s:
        versions_after = await s.scalar(
            select(func.count()).select_from(MethodCatalogVersion)
        )
    assert versions_after == versions_before


@pytest.mark.asyncio
async def test_seed_repairs_deactivated_version(db_engine, monkeypatch):
    from app.models.analytical_method_catalog import (
        STATUS_DRAFT,
        MethodCatalog,
        MethodCatalogVersion,
    )
    from scripts.seed_analytical_catalog import seed_analytical_catalog

    factory = await _patch_session_local(db_engine, monkeypatch)
    method_registry.invalidate_cache()
    await seed_analytical_catalog()

    # Simulate a half-activated state left by a prior partial boot.
    async with factory() as s:
        catalog = await s.scalar(
            select(MethodCatalog).where(
                MethodCatalog.catalog_key == "tablescope_analytical_methods"
            )
        )
        version = await s.get(MethodCatalogVersion, catalog.active_version_id)
        version.status = STATUS_DRAFT
        catalog.active_version_id = None
        await s.commit()

    method_registry.invalidate_cache()
    async with factory() as s:
        assert await method_registry.get_active_registry(s) is None  # broken

    # Re-seeding repairs activation idempotently (without a duplicate version).
    method_registry.invalidate_cache()
    stats = await seed_analytical_catalog()
    assert stats["active"] is True
    method_registry.invalidate_cache()
    async with factory() as s:
        assert await method_registry.get_active_registry(s) is not None


@pytest.mark.asyncio
async def test_catalog_status_reports_counts(seeded):
    status = await method_registry.catalog_status(seeded)
    assert status["active"] is True
    assert status["version_id"] is not None
    assert status["executable"] >= 24
    assert status["methods"] > status["executable"]


@pytest.mark.asyncio
async def test_catalog_status_inactive_without_catalog(db_session):
    method_registry.invalidate_cache()
    status = await method_registry.catalog_status(db_session)
    assert status["active"] is False
    assert status["version_id"] is None
    assert status["executable"] == 0


# --------------------------------------------------------------------------- #
# Ask-and-run hook: hybrid attaches the envelope, off skips entirely
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_attach_envelope_hybrid_attaches_and_off_skips(seeded, monkeypatch):
    from types import SimpleNamespace

    from app.routes.ai_proxy import _attach_analytical_envelope

    cols, rows = _linear_rows()
    ctx = SimpleNamespace(tenant_id=None)

    monkeypatch.setenv("ANALYTICAL_METHOD_ENGINE_MODE", "hybrid")
    hybrid_resp: dict = {}
    await _attach_analytical_envelope(
        seeded, ctx, "correlation of x and y?", cols, rows, hybrid_resp
    )
    assert hybrid_resp.get("analyticalMethod") is not None
    assert hybrid_resp["analyticalMethod"]["method"] == "pearson_correlation"

    monkeypatch.setenv("ANALYTICAL_METHOD_ENGINE_MODE", "off")
    off_resp: dict = {}
    await _attach_analytical_envelope(
        seeded, ctx, "correlation of x and y?", cols, rows, off_resp
    )
    assert "analyticalMethod" not in off_resp
