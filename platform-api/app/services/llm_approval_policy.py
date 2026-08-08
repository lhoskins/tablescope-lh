"""Model approval policy for the LLM Framework catalog.

The policy is deterministic and human-auditable: an artifact is approved only
when its license is on the allowlist *and* it matches the GGUF-only catalog
setting. The LLM is never asked to approve a model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.config import get_settings

if TYPE_CHECKING:
    from app.services.llm_catalog_client import CatalogModel


@dataclass(frozen=True)
class ApprovalResult:
    status: str  # approved | review_required | rejected
    license_type: str | None
    license_url: str | None
    reason: str | None


class ApprovalPolicy:
    """Deterministic allowlist for model license and format."""

    DEFAULT_APPROVED_LICENSES: frozenset[str] = frozenset(
        {
            "llama3.1",
            "llama3.2",
            "llama3",
            "llama2",
            "apache-2.0",
            "mit",
            "bsd-3-clause",
            "bsd-2-clause",
            "gpl-3.0",
            "lgpl-3.0",
            "openrail",
            "openrail++",
            "bigscience-openrail-m",
            "cc-by-4.0",
            "cc-by-sa-4.0",
            "cc0-1.0",
            "artistic-2.0",
        }
    )

    def __init__(self, approved_licenses: frozenset[str] | None = None) -> None:
        self.approved_licenses = approved_licenses or self.DEFAULT_APPROVED_LICENSES

    def evaluate(self, model: CatalogModel) -> ApprovalResult:
        settings = get_settings()
        if settings.llm_model_catalog_gguf_only and not model.gguf_files:
            return ApprovalResult(
                status="rejected",
                license_type=None,
                license_url=None,
                reason="Catalog is GGUF-only and repository contains no .gguf files",
            )

        raw_license = (model.license or "").lower().strip()
        if not raw_license:
            return ApprovalResult(
                status="review_required",
                license_type=None,
                license_url=model.license_url,
                reason="No license metadata found in model card",
            )

        # Allow licenses written with or without the version suffix.
        normalized = raw_license.replace(" ", "-").replace("_", "-")
        if normalized in self.approved_licenses:
            return ApprovalResult(
                status="approved",
                license_type=model.license,
                license_url=model.license_url,
                reason=None,
            )

        return ApprovalResult(
            status="review_required",
            license_type=model.license,
            license_url=model.license_url,
            reason=f"License '{model.license}' is not on the approved allowlist",
        )
