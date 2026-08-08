"""Document-profile scope contract.

Kept free of router imports so it runs without the optional vector-store deps
(qdrant). Verifies the ``include_family`` knob that lets tenant-wide reference
libraries request profiling without the project-scoped family step.
"""

from __future__ import annotations

from app.models.schemas import DocumentProfileRequest


def _req(**over: object) -> DocumentProfileRequest:
    base: dict = {
        "tenant_id": 1,
        "user_id": 1,
        "project_id": 0,
        "asset_id": 1,
        "filename": "policy.pdf",
        "asset_type": "document",
        "text_preview": "some text",
    }
    base.update(over)
    return DocumentProfileRequest(**base)


def test_include_family_defaults_true() -> None:
    # Project documents keep the family step by default.
    assert _req().include_family is True


def test_include_family_can_be_disabled_for_libraries() -> None:
    # Tenant-wide reference libraries disable the family step.
    assert _req(include_family=False).include_family is False
