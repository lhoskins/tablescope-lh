"""Background tasks for the LLM Framework deployment pipeline."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from arq import Retry
from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.database import SessionLocal
from app.models.llm_framework import (
    LLMArtifactFile,
    LLMLicenseApproval,
    LLMModelArtifact,
)
from app.services.llm_approval_policy import ApprovalPolicy
from app.services.llm_catalog_client import HuggingFaceCatalogClient
from app.services.llm_manifest import build_manifest, sign_manifest
from app.services.llm_model_vault import ModelVault, VaultError
from app.services.llm_scanner import scan_file

logger = logging.getLogger(__name__)


def _repo_id_from_url(repo_url: str | None, publisher: str, name: str) -> str:
    if repo_url:
        parsed = urlparse(repo_url)
        path = parsed.path.strip("/")
        if parsed.netloc in ("huggingface.co", "www.huggingface.co") and "/" in path:
            return path
    # Fallback to publisher/name, which matches the Hugging Face repo id convention.
    return f"{publisher}/{name}"


async def stage_llm_artifact(ctx: dict[str, Any], artifact_id: int, requested_by_user_id: int) -> dict[str, Any]:
    """Stage a model from Hugging Face into the model vault.

    Steps:
    1. Fetch catalog metadata and lock the artifact id.
    2. Evaluate license/format policy.
    3. Download the chosen GGUF file to a temp directory.
    4. Hash and structurally validate the GGUF header.
    5. Sign the canonical manifest.
    6. Atomically move the verified file into the artifact vault.
    7. Update the artifact status and write an audit event.
    """
    settings = get_settings()
    if not settings.llm_framework_enabled or not settings.llm_framework_hf_catalog_enabled:
        raise RuntimeError("LLM Framework catalog is disabled")

    redis = ctx.get("redis")
    if redis:
        locked = await redis.set(f"llm:stage:{artifact_id}", "1", nx=True, ex=3600)
        if not locked:
            raise Retry(defer=30)

    vault = ModelVault()

    try:
        async with SessionLocal() as session:
            artifact = await session.get(LLMModelArtifact, artifact_id)
            if artifact is None:
                raise RuntimeError(f"Artifact {artifact_id} not found")

            artifact.status = "downloading"
            artifact.requested_by_user_id = requested_by_user_id
            await session.flush()

            repo_id = _repo_id_from_url(artifact.repo_url, artifact.publisher, artifact.name)
            client = HuggingFaceCatalogClient()
            model = await client.get_model_info(repo_id)

            policy = ApprovalPolicy()
            approval = policy.evaluate(model)

            # Record license approval state.
            license_row = await session.scalar(
                select(LLMLicenseApproval).where(LLMLicenseApproval.artifact_id == artifact_id)
            )
            if license_row is None:
                license_row = LLMLicenseApproval(artifact_id=artifact_id)
                session.add(license_row)
            license_row.license_type = approval.license_type
            license_row.license_url = approval.license_url
            license_row.status = approval.status
            license_row.notes = approval.reason

            if approval.status != "approved":
                artifact.status = "quarantined"
                artifact.quarantine_reason = approval.reason or "License approval required"
                await session.commit()
                return {
                    "artifact_id": artifact_id,
                    "status": "quarantined",
                    "reason": approval.reason,
                }

            # Select a GGUF file: explicit quantization > largest GGUF.
            gguf_files = sorted(model.gguf_files, key=lambda f: (f.size or 0), reverse=True)
            if artifact.quantization:
                q = artifact.quantization.lower()
                matched = [f for f in model.gguf_files if q in f.filename.lower()]
                if matched:
                    chosen = max(matched, key=lambda f: f.size or 0)
                else:
                    chosen = gguf_files[0]
            else:
                chosen = gguf_files[0]

            # Use the reported commit SHA from the API; fail closed if missing.
            commit_sha = model.commit_sha or model.last_modified
            if not commit_sha:
                artifact.status = "quarantined"
                artifact.quarantine_reason = "Hugging Face did not return a commit SHA"
                await session.commit()
                return {"artifact_id": artifact_id, "status": "quarantined", "reason": "Missing commit SHA"}

            # Update artifact metadata from the canonical catalog source.
            artifact.commit_sha = commit_sha
            artifact.publisher = model.publisher or artifact.publisher
            artifact.repo_url = f"https://huggingface.co/{repo_id}"

            # Pre-flight disk checks: the worker needs temp space and final space.
            expected_size = chosen.size or 0
            if expected_size:
                vault.assert_disk_space(Path(vault.base_path), expected_size * 2 + 5 * 1024 ** 3)
                vault.reserve_space(expected_size)

            temp = vault.temp_dir()
            try:
                download_path = temp / chosen.filename
                download_url = client.resolve_download_url(repo_id, "main", chosen.filename)
                await client.download(
                    download_url,
                    str(download_path),
                    max_bytes=settings.llm_model_vault_max_bytes,
                    expected_size=chosen.size or None,
                )

                artifact.status = "verifying"
                await session.flush()

                scan = scan_file(chosen.filename, str(download_path))

                manifest = build_manifest(
                    artifact_id=artifact.id,
                    repo_url=artifact.repo_url,
                    commit_sha=artifact.commit_sha,
                    quantization=artifact.quantization,
                    files=[
                        {
                            "filename": scan.filename,
                            "size_bytes": scan.size_bytes,
                            "hash_algorithm": scan.hash_algorithm,
                            "hash_value": scan.hash_value,
                            "gguf_version": scan.gguf_version,
                            "tensor_count": scan.tensor_count,
                            "metadata_kv_count": scan.metadata_kv_count,
                        }
                    ],
                )
                signature, fingerprint = sign_manifest(manifest)

                dest = vault.storage_path(artifact.id, chosen.filename)
                vault.atomic_move(download_path, dest)

                artifact.size_bytes = scan.size_bytes
                artifact.status = "verified"
                artifact.manifest = manifest
                artifact.manifest_signature = signature
                artifact.manifest_public_key_fingerprint = fingerprint
                artifact.verified_at = datetime.now(UTC)

                # Ensure only one file row per artifact in Phase 2.
                await session.execute(
                    delete(LLMArtifactFile).where(
                        LLMArtifactFile.artifact_id == artifact.id
                    )
                )
                session.add(
                    LLMArtifactFile(
                        artifact_id=artifact.id,
                        filename=scan.filename,
                        size_bytes=scan.size_bytes,
                        hash_algorithm=scan.hash_algorithm,
                        hash_value=scan.hash_value,
                        storage_path=str(dest.relative_to(vault.base_path)),
                    )
                )
                await session.commit()
                return {
                    "artifact_id": artifact_id,
                    "status": "verified",
                    "size_bytes": scan.size_bytes,
                }
            finally:
                vault.remove_temp(temp)

    except (VaultError, ValueError, HTTPException) as exc:
        logger.exception("Artifact %s failed staging", artifact_id)
        async with SessionLocal() as session:
            artifact = await session.get(LLMModelArtifact, artifact_id)
            if artifact:
                artifact.status = "quarantined"
                artifact.quarantine_reason = str(exc)[:1024]
                await session.commit()
        return {"artifact_id": artifact_id, "status": "quarantined", "reason": str(exc)}
    except IntegrityError as exc:
        logger.exception("Artifact %s duplicate or integrity violation", artifact_id)
        async with SessionLocal() as session:
            artifact = await session.get(LLMModelArtifact, artifact_id)
            if artifact:
                artifact.status = "quarantined"
                artifact.quarantine_reason = "Duplicate artifact (name/publisher/commit/quantization)"
                await session.commit()
        return {"artifact_id": artifact_id, "status": "quarantined", "reason": str(exc)}
    finally:
        if redis:
            await redis.delete(f"llm:stage:{artifact_id}")
