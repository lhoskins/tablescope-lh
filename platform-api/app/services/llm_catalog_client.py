"""Server-side Hugging Face catalog client.

The worker uses this to search the catalog and download GGUF files. It is
intentionally not exposed to the browser: download URLs are derived from the
repo id and validated against an egress allowlist, not accepted from clients.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException, status

from app.config import get_settings

logger = logging.getLogger(__name__)

_HF_API_BASE = "https://huggingface.co"
_GGUF_SUFFIX = ".gguf"


def _is_allowed_host(host: str) -> bool:
    host = host.lower()
    return (
        host == "huggingface.co"
        or host.endswith(".huggingface.co")
        or host == "hf.co"
        or host.endswith(".hf.co")
    )


def _validate_url(url: str) -> None:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Invalid URL: {url}")
    if not _is_allowed_host(parsed.netloc):
        raise ValueError(f"URL host not in Hugging Face allowlist: {parsed.netloc}")


@dataclass(frozen=True)
class CatalogFile:
    filename: str
    size: int | None
    oid: str | None
    lfs: bool


@dataclass(frozen=True)
class CatalogModel:
    repo_id: str
    publisher: str
    name: str
    commit_sha: str | None
    tags: list[str]
    license: str | None
    license_url: str | None
    description: str | None
    downloads: int | None
    likes: int | None
    last_modified: str | None
    siblings: list[CatalogFile]

    @property
    def gguf_files(self) -> list[CatalogFile]:
        return [f for f in self.siblings if f.filename.endswith(_GGUF_SUFFIX)]


def _parse_model_info(payload: dict[str, Any]) -> CatalogModel:
    repo_id = payload.get("id", "")
    if "/" not in repo_id:
        raise ValueError("Payload does not contain a valid repo id")
    publisher, name = repo_id.split("/", 1)
    card = payload.get("cardData") or {}
    license_val = card.get("license")
    if isinstance(license_val, list):
        license_val = license_val[0] if license_val else None
    license_str = str(license_val).strip() if license_val else None
    siblings = [
        CatalogFile(
            filename=s.get("rfilename", ""),
            size=s.get("size"),
            oid=s.get("oid"),
            lfs=bool(s.get("lfs")),
        )
        for s in payload.get("siblings", [])
        if isinstance(s, dict)
    ]
    return CatalogModel(
        repo_id=repo_id,
        publisher=publisher,
        name=name,
        commit_sha=payload.get("sha"),
        tags=payload.get("tags", []),
        license=license_str,
        license_url=f"https://huggingface.co/{repo_id}/raw/main/README.md",
        description=card.get("language") or payload.get("description"),
        downloads=payload.get("downloads"),
        likes=payload.get("likes"),
        last_modified=payload.get("lastModified"),
        siblings=siblings,
    )


class HuggingFaceCatalogClient:
    """Client for Hugging Face model catalog and LFS downloads.

    All network calls use bounded timeouts, a small number of retries with
    exponential backoff, and strict egress allowlist validation. Redirects are
    followed only onto ``*.huggingface.co`` and ``*.hf.co`` hosts.
    """

    def __init__(self) -> None:
        self.settings = get_settings()
        self.headers: dict[str, str] = {}
        if self.settings.llm_huggingface_token:
            self.headers["Authorization"] = f"Bearer {self.settings.llm_huggingface_token}"

    async def _request(
        self,
        method: str,
        path_or_url: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        url = path_or_url if path_or_url.startswith("http") else f"{_HF_API_BASE}{path_or_url}"
        _validate_url(url)
        limits = httpx.Limits(max_connections=10)
        timeout = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=5.0)
        for attempt in range(3):
            async with httpx.AsyncClient(
                limits=limits,
                timeout=timeout,
                headers=self.headers,
                follow_redirects=True,
                event_hooks={"response": [self._assert_redirect_allowed]},
            ) as client:
                try:
                    response = await client.request(method, url, params=params)
                    if response.status_code == 429:
                        retry_after = int(response.headers.get("Retry-After", "5"))
                        await asyncio.sleep(min(retry_after, 30))
                        continue
                    if response.status_code >= 500:
                        await asyncio.sleep(2 ** attempt)
                        continue
                    response.raise_for_status()
                    return response
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code >= 500 and attempt < 2:
                        await asyncio.sleep(2 ** attempt)
                        continue
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=f"Hugging Face returned {exc.response.status_code}: {exc.response.text[:200]}",
                    ) from exc
                except httpx.TimeoutException:
                    if attempt == 2:
                        raise HTTPException(
                            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                            detail="Hugging Face request timed out",
                        ) from None
                    await asyncio.sleep(2 ** attempt)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Hugging Face returned repeated errors",
        )

    async def search(self, query: str, *, limit: int = 20) -> list[CatalogModel]:
        """Search public Hugging Face models.

        Only results with at least one ``.gguf`` sibling are returned when the
        GGUF-only policy is active.
        """
        params: dict[str, Any] = {
            "search": query,
            "limit": limit,
            "full": "full",
            "config": "false",
            "sort": "downloads",
            "direction": "-1",
        }
        response = await self._request("GET", "/api/models", params=params)
        payload = response.json()
        models: list[CatalogModel] = []
        for item in payload:
            try:
                model = _parse_model_info(item)
            except Exception:
                continue
            if self.settings.llm_model_catalog_gguf_only and not model.gguf_files:
                continue
            models.append(model)
        return models

    async def get_model_info(self, repo_id: str) -> CatalogModel:
        """Fetch model info, card data, and sibling list for ``repo_id``."""
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo_id):
            raise HTTPException(status_code=400, detail="Invalid repository id")
        response = await self._request(
            "GET",
            f"/api/models/{repo_id}",
            params={"expand[]": ["cardData", "siblings", "sha"]},
        )
        return _parse_model_info(response.json())

    def resolve_download_url(self, repo_id: str, revision: str, filename: str) -> str:
        """Build the canonical ``/resolve`` URL for a file.

        This is the only download entry point. The resolved redirect is
        validated before bytes are written.
        """
        if "/" in filename or "\\" in filename or filename.startswith("/"):
            raise ValueError("Invalid filename")
        return f"https://huggingface.co/{repo_id}/resolve/{revision}/{filename}"

    async def download(
        self,
        url: str,
        destination: str,
        *,
        max_bytes: int | None = None,
        expected_size: int | None = None,
        chunk_size: int = 1024 * 1024,
    ) -> int:
        """Stream ``url`` to ``destination`` with quota and redirect validation."""
        _validate_url(url)
        os.makedirs(os.path.dirname(destination) or ".", exist_ok=True)
        limits = httpx.Limits(max_connections=5)
        timeout = httpx.Timeout(connect=15.0, read=120.0, write=30.0, pool=5.0)
        written = 0
        async with httpx.AsyncClient(
            limits=limits,
            timeout=timeout,
            follow_redirects=True,
            headers=self.headers,
            event_hooks={"response": [self._assert_redirect_allowed]},
        ) as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                with open(destination, "wb") as fh:
                    async for chunk in response.aiter_bytes(chunk_size):
                        written += len(chunk)
                        if max_bytes is not None and written > max_bytes:
                            raise HTTPException(
                                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                                detail=f"Download exceeded max bytes: {max_bytes}",
                            )
                        fh.write(chunk)
        if expected_size is not None and written != expected_size:
            raise ValueError(f"Download size mismatch: expected {expected_size}, got {written}")
        return written

    async def _assert_redirect_allowed(self, response: httpx.Response) -> None:
        """Reject any final response whose URL host is not on the allowlist."""
        _validate_url(str(response.request.url))
