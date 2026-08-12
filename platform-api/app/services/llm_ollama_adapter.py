"""Ollama runtime adapter for LLM artifact installation and health checks.

The adapter operates on the principle that it must never fetch weights from the
internet. It installs a GGUF that is already present on the local filesystem and
blocks any operation that would trigger ``ollama pull``.
"""

from __future__ import annotations

import logging
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from fastapi import HTTPException, status

from app.config import get_settings

logger = logging.getLogger(__name__)


def _sanitize_model_name(name: str) -> str:
    """Produce a valid Ollama model name from free text."""
    name = name.lower().replace(" ", "-")
    return re.sub(r"[^a-z0-9._-]+", "", name).strip("-._") or "artifact"


@dataclass(frozen=True)
class GpuInfo:
    name: str | None
    total_vram: int | None
    free_vram: int | None


@dataclass(frozen=True)
class LoadedModel:
    name: str
    size: int
    size_vram: int


@dataclass(frozen=True)
class PreflightResult:
    reachable: bool
    version: str | None
    disk_ok: bool
    slot_ok: bool
    capacity_ok: bool
    current_models: list[str]
    detail: str | None = None
    gpu_infos: list[GpuInfo] | None = None
    loaded_models: list[LoadedModel] | None = None
    total_vram_bytes: int | None = None
    free_vram_bytes: int | None = None
    system_ram_bytes: int | None = None
    free_disk_bytes: int | None = None
    context_length: int | None = None
    max_concurrency: int | None = None
    format_compatible: bool = True
    warnings: list[str] | None = None


@dataclass(frozen=True)
class InstallResult:
    success: bool
    ollama_model_name: str | None
    installed_path: str | None
    modelfile_content: str | None
    detail: str | None = None


class OllamaAdapter:
    """Install and verify GGUF artifacts in an Ollama runtime.

    The install path must be a directory that is visible both to this process
    and to the Ollama server (usually via a shared volume mount). The adapter
    copies the verified GGUF into that directory, writes a Modelfile that
    references it, and asks Ollama to create a model.
    """

    def __init__(
        self,
        base_url: str | None = None,
        install_path: str | None = None,
        rollback_slots: int | None = None,
    ) -> None:
        settings = get_settings()
        self.base_url = (base_url or settings.llm_ollama_url).rstrip("/")
        self.install_path = Path(install_path or settings.llm_model_install_path)
        self.rollback_slots = rollback_slots if rollback_slots is not None else settings.llm_ollama_rollback_slots
        self.timeout = httpx.Timeout(connect=10.0, read=60.0, write=30.0, pool=5.0)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.request(method, f"{self.base_url}{path}", json=json, params=params)
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError as exc:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Ollama returned {exc.response.status_code}: {exc.response.text[:200]}",
                ) from exc
            except httpx.RequestError as exc:
                raise HTTPException(
                    status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                    detail=f"Could not reach Ollama at {self.base_url}: {exc}",
                ) from exc

    async def preflight(
        self,
        artifact_size: int = 0,
        reserve_bytes: int = 5 * 1024 ** 3,
        expected_context_tokens: int | None = None,
    ) -> PreflightResult:
        """Check that Ollama is up and the host has enough free capacity."""
        try:
            response = await self._request("GET", "/api/tags")
            payload = response.json()
            models = [m["name"] for m in payload.get("models", []) if isinstance(m, dict) and "name" in m]
            version = payload.get("version")
        except HTTPException as exc:
            return PreflightResult(
                reachable=False,
                version=None,
                disk_ok=False,
                slot_ok=False,
                capacity_ok=False,
                current_models=[],
                detail=str(exc.detail),
            )

        # Probe running models for VRAM use.
        loaded_models: list[LoadedModel] = []
        gpu_infos: list[GpuInfo] = []
        total_vram_bytes: int | None = None
        free_vram_bytes: int | None = None
        system_ram_bytes: int | None = None
        context_length: int | None = None
        max_concurrency: int | None = None
        format_compatible = True
        warnings: list[str] = []

        try:
            ps_response = await self._request("GET", "/api/ps")
            ps_payload = ps_response.json()
            for m in ps_payload.get("models", []):
                if isinstance(m, dict) and "name" in m:
                    loaded_models.append(
                        LoadedModel(
                            name=m["name"],
                            size=m.get("size", 0) or 0,
                            size_vram=m.get("size_vram", 0) or 0,
                        )
                    )
            if isinstance(ps_payload.get("gpu_infos"), list):
                for g in ps_payload["gpu_infos"]:
                    if isinstance(g, dict):
                        gpu_infos.append(
                            GpuInfo(
                                name=g.get("name"),
                                total_vram=g.get("total_vram"),
                                free_vram=g.get("free_vram"),
                            )
                        )
            # Ollama may expose system info at /api/v1/runtime or in the same payload.
            system = ps_payload.get("system") or {}
            total_vram_bytes = system.get("total_vram")
            free_vram_bytes = system.get("free_vram")
            system_ram_bytes = system.get("total_memory")
        except Exception:
            warnings.append("Could not retrieve running-model / GPU details")

        # Default context length from first model details if available.
        if models and not context_length:
            try:
                tags_response = await self._request("GET", "/api/tags")
                for m in tags_response.json().get("models", []):
                    if m.get("name") == models[0]:
                        context_length = m.get("details", {}).get("context_length")
                        break
            except Exception:
                pass

        # Ollama can keep multiple models loaded concurrently. Reserve slots.
        max_loaded = get_settings().llm_ollama_rollback_slots + 1
        slot_ok = len(models) < max_loaded

        # Local disk check on the install path's filesystem.
        free_disk_bytes: int | None = None
        disk_ok = False
        try:
            usage = shutil.disk_usage(self.install_path)
            free_disk_bytes = usage.free
            disk_ok = usage.free >= artifact_size + reserve_bytes
        except OSError as exc:
            return PreflightResult(
                reachable=True,
                version=version,
                disk_ok=False,
                slot_ok=slot_ok,
                capacity_ok=False,
                current_models=models,
                detail=f"Cannot read disk usage: {exc}",
            )

        # Capacity warnings for context/concurrency.
        if expected_context_tokens and context_length and expected_context_tokens > context_length:
            warnings.append(
                f"Requested context {expected_context_tokens} exceeds target context length {context_length}"
            )
            format_compatible = False

        capacity_ok = disk_ok and slot_ok and format_compatible

        return PreflightResult(
            reachable=True,
            version=version,
            disk_ok=disk_ok,
            slot_ok=slot_ok,
            capacity_ok=capacity_ok,
            current_models=models,
            loaded_models=loaded_models,
            gpu_infos=gpu_infos,
            total_vram_bytes=total_vram_bytes,
            free_vram_bytes=free_vram_bytes,
            system_ram_bytes=system_ram_bytes,
            free_disk_bytes=free_disk_bytes,
            context_length=context_length,
            max_concurrency=max_concurrency,
            format_compatible=format_compatible,
            warnings=warnings,
            detail=None,
        )

    def _target_paths(self, artifact_id: int, filename: str) -> tuple[Path, str]:
        """Return (absolute filesystem path, ollama-visible path) for a GGUF."""
        safe_filename = Path(filename).name
        if safe_filename != filename or "/" in filename or "\\" in filename:
            raise ValueError("Invalid GGUF filename")
        if not safe_filename.endswith(".gguf"):
            raise ValueError("Ollama adapter only accepts .gguf files")

        dest_dir = self.install_path / f"artifact-{artifact_id}"
        dest_dir.mkdir(parents=True, exist_ok=True)
        fs_path = dest_dir / safe_filename

        # Ollama sees the same path if the volume is mounted identically; otherwise
        # the caller is responsible for aligning the agent's view with Ollama's view.
        ollama_visible_path = str(fs_path)
        return fs_path, ollama_visible_path

    def _build_modelfile(self, gguf_path: str, artifact_name: str) -> str:
        return (
            f"FROM {gguf_path}\n"
            f"# Generated by Tablescope LLM Framework for {artifact_name}\n"
            "PARAMETER stop \"User:\"\n"
            "PARAMETER stop \"Assistant:\"\n"
        )

    async def install(
        self,
        artifact_id: int,
        artifact_name: str,
        source_gguf_path: str,
    ) -> InstallResult:
        """Copy the GGUF to the install directory and run ``ollama create``."""
        source = Path(source_gguf_path)
        if not source.exists():
            return InstallResult(
                success=False,
                ollama_model_name=None,
                installed_path=None,
                modelfile_content=None,
                detail=f"Source GGUF not found: {source_gguf_path}",
            )

        fs_path, ollama_path = self._target_paths(artifact_id, source.name)

        try:
            shutil.copy2(str(source), str(fs_path))
        except OSError as exc:
            return InstallResult(
                success=False,
                ollama_model_name=None,
                installed_path=None,
                modelfile_content=None,
                detail=f"Could not copy GGUF to install path: {exc}",
            )

        model_name = f"tablescope-{artifact_id}-{_sanitize_model_name(artifact_name)}"
        modelfile = self._build_modelfile(ollama_path, artifact_name)

        try:
            await self._request(
                "POST",
                "/api/create",
                json={"name": model_name, "modelfile": modelfile},
            )
        except HTTPException as exc:
            return InstallResult(
                success=False,
                ollama_model_name=None,
                installed_path=str(fs_path),
                modelfile_content=modelfile,
                detail=str(exc.detail),
            )

        # Verify the model appears in the local tag list.
        tags_response = await self._request("GET", "/api/tags")
        tag_names = [m["name"] for m in tags_response.json().get("models", [])]
        if model_name not in tag_names and f"{model_name}:latest" not in tag_names:
            return InstallResult(
                success=False,
                ollama_model_name=model_name,
                installed_path=str(fs_path),
                modelfile_content=modelfile,
                detail="ollama create succeeded but model is not in /api/tags",
            )

        return InstallResult(
            success=True,
            ollama_model_name=model_name,
            installed_path=str(fs_path),
            modelfile_content=modelfile,
            detail=None,
        )

    async def generate(self, model_name: str, prompt: str) -> str:
        """Run a single generation against the model and return the response text."""
        response = await self._request(
            "POST",
            "/api/generate",
            json={"model": model_name, "prompt": prompt, "stream": False},
        )
        payload = response.json()
        return str(payload.get("response", ""))

    async def remove(self, model_name: str) -> bool:
        """Delete a model from Ollama; used during rollback cleanup."""
        try:
            await self._request("DELETE", "/api/delete", json={"name": model_name})
            return True
        except HTTPException:
            return False
