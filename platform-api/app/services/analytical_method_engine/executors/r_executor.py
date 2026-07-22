"""R analytics executor.

Posts a normalized execution request to the ``r-analytics`` service and
returns the JSON envelope. Failures are converted to a safe ``error`` status
so the engine can fall back to the Python executor or return a soft envelope.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
import pandas as pd

from app.services.analytical_method_engine.executors.base import ExecRequest, Executor
from app.services.analytical_method_engine.r_config import (
    r_analytics_timeout_seconds,
    r_analytics_url,
)

logger = logging.getLogger(__name__)


def _serialize_value(obj: Any) -> Any:
    """Convert numpy/pandas scalar types to plain Python for JSON."""
    if pd.isna(obj):
        return None
    if hasattr(obj, "item"):
        return obj.item()
    return obj


class RExecutor(Executor):
    def execute(self, request: ExecRequest) -> dict[str, Any]:
        url = f"{r_analytics_url()}/execute"
        df = request.df
        if request.max_rows is not None and len(df) > request.max_rows:
            df = df.head(request.max_rows)

        rows = df.head(10_000).to_dict(orient="records") if not df.empty else []
        payload = {
            "method_id": request.method_id,
            "executor_key": request.executor_key,
            "columns": list(df.columns),
            "rows": rows,
            "roles": request.roles,
            "profile": request.profile,
            "policies": request.policies or {},
            "max_rows": request.max_rows,
        }

        timeout = request.timeout_seconds or r_analytics_timeout_seconds()
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(
                    url,
                    json=json.loads(json.dumps(payload, default=str)),
                    headers={"Content-Type": "application/json"},
                )
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:
            logger.warning("R analytics request failed for %s: %s", request.method_id, exc)
            return {
                "status": "error",
                "reason": f"R analytics unavailable: {exc}",
                "results": {},
                "assumptions": [],
                "caveats": [],
                "n": 0,
                "usable_n": 0,
                "excluded": 0,
                "missing": 0,
                "quality": "unavailable",
                "warnings": ["R executor failed; falling back to Python is recommended"],
            }
