"""Tests for the analytical result envelope."""

from __future__ import annotations

import hashlib
import json

from app.services.analytical_method_engine import result_envelope


def test_parameter_hash_includes_roles() -> None:
    profile = {"hash": "abc123"}
    method = {"method_id": "describe_numeric", "display_name": "Describe"}
    exec_result = {
        "status": "ok",
        "n": 5,
        "results": {"mean": 3.0},
    }

    envelope = result_envelope.build(
        intent="describe_numeric",
        profile=profile,
        method=method,
        roles={"value": "x"},
        selection_reasons=["exactly one numeric field"],
        alternatives=[],
        exec_result=exec_result,
        registry_version=1,
    )

    expected_payload = json.dumps(
        {"intent": "describe_numeric", "method": "describe_numeric", "roles": {"value": "x"}},
        sort_keys=True,
        default=str,
    )
    expected_hash = hashlib.sha256(expected_payload.encode()).hexdigest()[:16]
    assert envelope["audit"]["parameterHash"] == expected_hash


def test_parameter_hash_changes_with_roles() -> None:
    profile = {"hash": "abc123"}
    method = {"method_id": "describe_numeric", "display_name": "Describe"}
    exec_result = {"status": "ok", "n": 5, "results": {}}

    a = result_envelope.build(
        intent="describe_numeric",
        profile=profile,
        method=method,
        roles={"value": "x"},
        selection_reasons=[],
        alternatives=[],
        exec_result=exec_result,
        registry_version=1,
    )
    b = result_envelope.build(
        intent="describe_numeric",
        profile=profile,
        method=method,
        roles={"value": "y"},
        selection_reasons=[],
        alternatives=[],
        exec_result=exec_result,
        registry_version=1,
    )
    assert a["audit"]["parameterHash"] != b["audit"]["parameterHash"]
