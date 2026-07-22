#!/usr/bin/env python3
"""Repeatable canary for the R-backed analytical method execution path.

This script is non-destructive: it opens a read-only-ish platform database
session, calls the public Analytical Method Engine entry point with a fixed
numeric input, and validates that the selected method was executed by the R
runtime. No tenant, catalog, or schema mutation occurs; the optional audit
insert is the only write, and it logs only metadata (method id, intent,
status) — never raw rows.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import sys

# Allow running from either the repo root or platform-api/.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.database import SessionLocal
from app.services.analytical_method_engine.engine import analyze
from app.services.analytical_method_engine.r_config import is_r_analytics_enabled


COLUMNS = ["value"]
ROWS = [[10], [20], [30], [40], [50]]
INTENT = "r_descriptive_profile"


def _fail(message: str, extra: dict | None = None) -> dict:
    payload = {"status": "error", "reason": message}
    if extra:
        payload.update(extra)
    return payload


async def _run_canary() -> dict:
    if not is_r_analytics_enabled():
        return _fail(
            "R analytics is disabled; set R_ANALYTICS_ENABLED=true and restart the engine to validate the R path."
        )

    async with SessionLocal() as session:
        envelope = await analyze(
            session,
            tenant_id=None,
            columns=COLUMNS,
            rows=ROWS,
            question="summarize the value column",
            intent=INTENT,
            audit=True,
        )

    if envelope is None:
        return _fail("Analytical engine returned no envelope.")

    method = envelope.get("method")
    engine = envelope.get("executionEngine")
    status = envelope.get("status")
    results = envelope.get("results", {})
    audit = envelope.get("audit", {})

    # Required fields per validation spec.
    if status != "ok":
        return _fail(
            f"Expected status 'ok', got {status!r}.",
            {"envelope": {k: v for k, v in envelope.items() if k != "results"}},
        )
    if method != INTENT:
        return _fail(f"Expected method '{INTENT}', got {method!r}.", {"envelope": envelope})
    if engine != "r":
        return _fail(f"Expected executionEngine 'r', got {engine!r}.", {"envelope": envelope})

    n = results.get("n")
    mean = results.get("mean")
    median = results.get("median")
    min_val = results.get("min")
    max_val = results.get("max")

    if n != 5:
        return _fail(f"Expected n == 5, got {n!r}.", {"results": results})
    if not (isinstance(mean, (int, float)) and math.isclose(mean, 30, rel_tol=1e-3)):
        return _fail(f"Expected mean ~30, got {mean!r}.", {"results": results})
    if not (isinstance(median, (int, float)) and math.isclose(median, 30, rel_tol=1e-3)):
        return _fail(f"Expected median ~30, got {median!r}.", {"results": results})
    if not (isinstance(min_val, (int, float)) and math.isclose(min_val, 10, rel_tol=1e-3)):
        return _fail(f"Expected min ~10, got {min_val!r}.", {"results": results})
    if not (isinstance(max_val, (int, float)) and math.isclose(max_val, 50, rel_tol=1e-3)):
        return _fail(f"Expected max ~50, got {max_val!r}.", {"results": results})

    if not audit.get("parameterHash"):
        return _fail("Missing parameterHash in audit block.", {"envelope": envelope})
    if not audit.get("inputDataHash"):
        return _fail("Missing inputDataHash in audit block.", {"envelope": envelope})

    return {
        "status": "ok",
        "method": method,
        "executionEngine": engine,
        "n": n,
        "mean": mean,
        "median": median,
        "min": min_val,
        "max": max_val,
        "parameterHash": audit.get("parameterHash"),
        "inputDataHash": audit.get("inputDataHash"),
        "quality": envelope.get("quality"),
        "registryVersion": audit.get("methodRegistryVersion"),
    }


def main() -> int:
    try:
        result = asyncio.run(_run_canary())
    except Exception as exc:
        result = _fail(f"Canary raised an exception: {exc}")

    # Secrets and raw env vars are intentionally excluded from output.
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
