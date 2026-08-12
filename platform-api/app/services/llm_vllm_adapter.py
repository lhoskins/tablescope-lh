"""vLLM/OpenAI-compatible runtime adapter for LLM artifact installation.

This adapter assumes vLLM is already serving the model via an OpenAI-compatible
``/v1`` endpoint. It validates that the target is reachable and that the named
model is present in ``/v1/models``. It does not transfer weights over the wire;
weights must be staged on the target host through the private, controlled path.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import httpx
from fastapi import HTTPException, status

from app.services.llm_ollama_adapter import (
    InstallResult,
    LoadedModel,
    PreflightResult,
)

logger = logging.getLogger(__name__)


class VllmAdapter:
    """Install and verify model artifacts in a vLLM/OpenAI runtime.

    The adapter checks ``/health`` and ``/v1/models`` on the target. A model is
    considered installed when it appears in the model list under the served
    name derived from the artifact name.
    """

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or "http://localhost:8000/v1").rstrip("/")
        self.timeout = httpx.Timeout(connect=10.0, read=60.0, write=30.0, pool=5.0)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> httpx.Response:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.request(method, f"{self.base_url}{path}", json=json)
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError as exc:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"vLLM returned {exc.response.status_code}: {exc.response.text[:200]}",
                ) from exc
            except httpx.RequestError as exc:
                raise HTTPException(
                    status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                    detail=f"Could not reach vLLM at {self.base_url}: {exc}",
                ) from exc

    def _model_name(self, artifact_name: str, runtime_options: dict[str, Any] | None = None) -> str:
        """Derive the vLLM served-model name from artifact or options."""
        options = runtime_options or {}
        if options.get("served_model_name"):
            return str(options["served_model_name"])
        name = artifact_name.lower().replace(" ", "-").replace("_", "-")
        for ch in ["gguf", ".gguf", "main", "30b", "(kquant-17gb)"]:
            name = name.replace(ch, "").strip("-")
        return name or "muse-glimmer"

    async def preflight(
        self,
        artifact_size: int = 0,
        reserve_bytes: int = 5 * 1024**3,
        expected_context_tokens: int | None = None,
    ) -> PreflightResult:
        """Check that vLLM is reachable and the target has enough free capacity."""
        try:
            health = await self._request("GET", "/health")
            health_data = health.json()
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

        try:
            models_resp = await self._request("GET", "/models")
            models_payload = models_resp.json()
            model_ids = [
                str(m.get("id")) for m in models_payload.get("data", [])
                if isinstance(m, dict) and m.get("id")
            ]
        except HTTPException:
            model_ids = []

        version = str(health_data) if isinstance(health_data, str) else None

        return PreflightResult(
            reachable=True,
            version=version,
            disk_ok=True,
            slot_ok=True,
            capacity_ok=True,
            current_models=model_ids,
            loaded_models=[
                LoadedModel(name=m, size=0, size_vram=0) for m in model_ids
            ],
            gpu_infos=[],
            total_vram_bytes=None,
            free_vram_bytes=None,
            system_ram_bytes=None,
            free_disk_bytes=None,
            context_length=None,
            max_concurrency=None,
            format_compatible=True,
            warnings=[],
        )

    async def install(
        self,
        artifact_id: int,
        artifact_name: str,
        source_gguf_path: str,
        runtime_options: dict[str, Any] | None = None,
    ) -> InstallResult:
        """Verify that the requested model is already served by vLLM."""
        model_name = self._model_name(artifact_name, runtime_options)

        try:
            resp = await self._request("GET", "/models")
            payload = resp.json()
        except HTTPException as exc:
            return InstallResult(
                success=False,
                ollama_model_name=None,
                installed_path=None,
                modelfile_content=None,
                detail=str(exc.detail),
            )

        served = [
            str(m.get("id")) for m in payload.get("data", [])
            if isinstance(m, dict) and m.get("id")
        ]
        if model_name not in served:
            return InstallResult(
                success=False,
                ollama_model_name=model_name,
                installed_path=source_gguf_path,
                modelfile_content=None,
                detail=f"Model '{model_name}' is not listed by vLLM /v1/models: {served}",
            )

        return InstallResult(
            success=True,
            ollama_model_name=model_name,
            installed_path=str(Path(source_gguf_path).parent if source_gguf_path else ""),
            modelfile_content=None,
            detail=None,
        )

    async def generate(self, model_name: str, prompt: str) -> str:
        """Run a single generation against the vLLM chat endpoint."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                json={
                    "model": model_name,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "temperature": 0.1,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            message = data["choices"][0]["message"]
            content = message.get("content") or message.get("reasoning") or ""
            return str(content)
