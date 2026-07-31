"""Phase 6: FP16 / safetensors -> GGUF conversion pipeline.

The platform-api never installs the conversion toolchain itself. A sandboxed
external command (container or host binary) performs the conversion; the worker
verifies, hashes, and signs the resulting GGUF bytes before creating a new
artifact.
"""

from __future__ import annotations

import logging
import shlex
import subprocess
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.llm_framework import LLMArtifactFile, LLMModelArtifact, LLMModelConversion
from app.services.llm_catalog_client import HuggingFaceCatalogClient
from app.services.llm_manifest import build_manifest, sign_manifest
from app.services.llm_model_vault import ModelVault
from app.services.llm_scanner import scan_file

logger = logging.getLogger(__name__)


class ModelConversionError(Exception):
    """A conversion step could not be completed safely."""


_SOURCE_EXTENSIONS = {".safetensors", ".bin", ".pt", ".json", ".txt", ".model", ".tiktoken"}


async def _download_source_files(
    vault: ModelVault,
    repo_id: str,
    commit_sha: str,
    artifact_id: int,
) -> Path:
    """Download model files for an FP16/safetensors repository into the vault."""
    client = HuggingFaceCatalogClient()
    model = await client.get_model_info(repo_id)
    commit = commit_sha or model.commit_sha or "main"

    base = vault.storage_dir(artifact_id)
    base.mkdir(parents=True, exist_ok=True)

    files = [f for f in model.siblings if any(f.filename.endswith(ext) for ext in _SOURCE_EXTENSIONS)]
    if not files:
        raise ModelConversionError("No convertible source files found in repository")

    for catalog_file in files:
        url = client.resolve_download_url(repo_id, commit, catalog_file.filename)
        dest = base / catalog_file.filename
        dest.parent.mkdir(parents=True, exist_ok=True)
        await client.download(
            url,
            str(dest),
            max_bytes=get_settings().llm_model_vault_max_bytes,
            expected_size=catalog_file.size or None,
        )

    return base


async def create_source_artifact_and_convert(
    session: AsyncSession,
    *,
    repo_url: str,
    quantization: str | None,
    requested_by_user_id: int,
) -> tuple[LLMModelArtifact, LLMModelConversion, str]:
    """Create a source artifact from an FP16 repo and enqueue conversion."""
    settings = get_settings()
    if not settings.llm_fp16_conversion_enabled:
        raise ModelConversionError("FP16 conversion is disabled")

    from app.services.llm_framework import _repo_id_from_url
    repo_id = _repo_id_from_url(repo_url)
    publisher, repo_name = repo_id.split("/", 1)

    artifact = LLMModelArtifact(
        name=f"{repo_name.replace('-', ' ').replace('_', ' ')} source",
        publisher=publisher,
        repo_url=repo_url,
        quantization=quantization,
        format="fp16",
        status="pending",
        requested_by_user_id=requested_by_user_id,
    )
    session.add(artifact)
    await session.flush()

    conversion = LLMModelConversion(
        source_artifact_id=artifact.id,
        quantization=quantization,
        status="pending",
    )
    session.add(conversion)
    await session.flush()

    from app.tasks.workflows import enqueue_convert_fp16_to_gguf
    job_id = await enqueue_convert_fp16_to_gguf(
        conversion_id=conversion.id,
        requested_by_user_id=requested_by_user_id,
    )
    return artifact, conversion, job_id


async def run_fp16_conversion(session: AsyncSession, conversion_id: int) -> dict[str, Any]:
    """Run the configured converter, scan the output GGUF, and create a new artifact."""
    settings = get_settings()
    if not settings.llm_fp16_conversion_enabled:
        raise ModelConversionError("FP16 conversion is disabled")

    conversion = await session.get(LLMModelConversion, conversion_id)
    if conversion is None:
        raise ModelConversionError("Conversion not found")

    source = await session.get(LLMModelArtifact, conversion.source_artifact_id)
    if source is None:
        raise ModelConversionError("Source artifact not found")

    command = settings.llm_fp16_converter_command.strip()
    if not command:
        conversion.status = "failed"
        conversion.detail = "No FP16 converter command configured (set LLM_FP16_CONVERTER_COMMAND)"
        await session.flush()
        return {"conversion_id": conversion_id, "status": "failed", "reason": conversion.detail}

    vault = ModelVault()
    conversion.status = "downloading"
    await session.flush()

    try:
        if not source.repo_url:
            raise ModelConversionError("Source artifact has no repository URL")
        from app.services.llm_framework import _repo_id_from_url
        repo_id = _repo_id_from_url(source.repo_url)
        input_dir = await _download_source_files(vault, repo_id, source.commit_sha or "", source.id)
    except Exception as exc:
        logger.exception("Download failed for conversion %s", conversion_id)
        conversion.status = "failed"
        conversion.detail = f"Download failed: {exc}"[:1024]
        await session.flush()
        return {"conversion_id": conversion_id, "status": "failed", "reason": conversion.detail}

    conversion.status = "converting"
    await session.flush()

    output_filename = f"converted-{conversion.id}.gguf"
    output_path = vault.temp_dir() / output_filename
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        cmd_parts = shlex.split(command)
        cmd_parts.extend([str(input_dir), str(output_path), conversion.quantization or ""])
        result = subprocess.run(
            cmd_parts,
            capture_output=True,
            text=True,
            timeout=3600,
            check=False,
        )
        if result.returncode != 0:
            raise ModelConversionError(
                f"Converter exited {result.returncode}: {result.stderr[:1024]}"
            )
    except Exception as exc:
        logger.exception("Conversion command failed for conversion %s", conversion_id)
        conversion.status = "failed"
        conversion.detail = str(exc)[:1024]
        await session.flush()
        return {"conversion_id": conversion_id, "status": "failed", "reason": conversion.detail}

    conversion.status = "verifying"
    await session.flush()

    try:
        scan = scan_file(output_filename, str(output_path))
        manifest = build_manifest(
            artifact_id=source.id,
            repo_url=source.repo_url,
            commit_sha=source.commit_sha,
            quantization=conversion.quantization,
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

        output_artifact = LLMModelArtifact(
            name=f"{source.name} (GGUF {conversion.quantization or 'default'})",
            publisher=source.publisher,
            repo_url=source.repo_url,
            commit_sha=source.commit_sha,
            quantization=conversion.quantization,
            format="gguf",
            size_bytes=scan.size_bytes,
            status="verified",
            manifest=manifest,
            manifest_signature=signature,
            manifest_public_key_fingerprint=fingerprint,
            embedding_dim=None,
            requested_by_user_id=source.requested_by_user_id,
        )
        session.add(output_artifact)
        await session.flush()

        dest = vault.storage_path(output_artifact.id, output_filename)
        vault.atomic_move(output_path, dest)

        session.add(
            LLMArtifactFile(
                artifact_id=output_artifact.id,
                filename=scan.filename,
                size_bytes=scan.size_bytes,
                hash_algorithm=scan.hash_algorithm,
                hash_value=scan.hash_value,
                storage_path=str(dest.relative_to(vault.base_path)),
            )
        )

        conversion.output_artifact_id = output_artifact.id
        conversion.output_size_bytes = scan.size_bytes
        conversion.output_manifest = manifest
        conversion.status = "completed"
        conversion.detail = None
        await session.flush()

        return {
            "conversion_id": conversion_id,
            "status": "completed",
            "output_artifact_id": output_artifact.id,
            "size_bytes": scan.size_bytes,
        }
    except Exception as exc:
        logger.exception("Verification failed for conversion %s", conversion_id)
        conversion.status = "failed"
        conversion.detail = f"Verification failed: {exc}"[:1024]
        await session.flush()
        return {"conversion_id": conversion_id, "status": "failed", "reason": conversion.detail}
