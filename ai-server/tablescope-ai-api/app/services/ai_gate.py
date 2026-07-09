"""In-process admission control for Ollama requests.

This gate is authoritative only while ``tablescope-ai-api`` runs as a single
process. Horizontal scaling would require shared coordination (for example,
Redis); do not assume these semaphores coordinate across replicas.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from app.core.config import settings


class AIGateBusyError(RuntimeError):
    """Raised when an Ollama admission slot is not available quickly enough."""


class AIGate:
    def __init__(
        self,
        *,
        global_limit: int,
        tenant_limit: int,
        acquire_timeout_seconds: float,
    ) -> None:
        self._global = asyncio.Semaphore(max(1, global_limit))
        self._tenant_limit = max(1, tenant_limit)
        self._acquire_timeout_seconds = max(0.001, acquire_timeout_seconds)
        self._tenants: dict[int, asyncio.Semaphore] = {}

    def _tenant_semaphore(self, tenant_id: int) -> asyncio.Semaphore:
        # There is no await between lookup and setdefault, so concurrent tasks on
        # the single event loop cannot create two authoritative semaphores.
        semaphore = self._tenants.get(tenant_id)
        if semaphore is None:
            semaphore = self._tenants.setdefault(
                tenant_id, asyncio.Semaphore(self._tenant_limit)
            )
        return semaphore

    @asynccontextmanager
    async def acquire(self, tenant_id: int | None) -> AsyncIterator[None]:
        """Acquire tenant then global capacity, failing fast when the gate is busy."""
        tenant_semaphore = (
            self._tenant_semaphore(tenant_id) if tenant_id is not None else None
        )
        tenant_acquired = False
        global_acquired = False
        try:
            deadline = (
                asyncio.get_running_loop().time() + self._acquire_timeout_seconds
            )

            async def acquire_before_deadline(semaphore: asyncio.Semaphore) -> None:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise asyncio.TimeoutError
                await asyncio.wait_for(semaphore.acquire(), timeout=remaining)

            try:
                if tenant_semaphore is not None:
                    await acquire_before_deadline(tenant_semaphore)
                    tenant_acquired = True
                await acquire_before_deadline(self._global)
                global_acquired = True
            except asyncio.TimeoutError as exc:
                raise AIGateBusyError(
                    "AI server is busy; retry shortly."
                ) from exc
            yield
        finally:
            if global_acquired:
                self._global.release()
            if tenant_acquired and tenant_semaphore is not None:
                tenant_semaphore.release()


_gate = AIGate(
    global_limit=settings.ollama_max_concurrent,
    tenant_limit=settings.tenant_max_concurrent,
    acquire_timeout_seconds=settings.ai_gate_acquire_timeout_seconds,
)


@asynccontextmanager
async def acquire(tenant_id: int | None) -> AsyncIterator[None]:
    async with _gate.acquire(tenant_id):
        yield
