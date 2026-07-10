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
        plan_reserved_global_slots: int = 0,
        plan_reserved_slots: int = 0,
        plan_acquire_timeout_seconds: float | None = None,
    ) -> None:
        global_capacity = max(1, global_limit)
        self._plan_reserved_global_slots = min(
            max(0, plan_reserved_global_slots),
            max(0, global_capacity - 1),
        )
        self._global = asyncio.Semaphore(
            global_capacity - self._plan_reserved_global_slots
        )
        self._global_plans = asyncio.Semaphore(self._plan_reserved_global_slots)
        self._tenant_limit = max(1, tenant_limit)
        self._acquire_timeout_seconds = max(0.001, acquire_timeout_seconds)
        self._plan_acquire_timeout_seconds = max(
            0.001,
            plan_acquire_timeout_seconds or acquire_timeout_seconds,
        )
        self._plan_reserved_slots = min(
            max(0, plan_reserved_slots),
            max(0, self._tenant_limit - 1),
        )
        self._regular_tenant_limit = self._tenant_limit - self._plan_reserved_slots
        self._tenants: dict[int, asyncio.Semaphore] = {}
        self._tenant_plans: dict[int, asyncio.Semaphore] = {}

    def _tenant_semaphore(
        self, tenant_id: int, request_kind: str
    ) -> asyncio.Semaphore:
        if request_kind == "plan" and self._plan_reserved_slots:
            semaphore = self._tenant_plans.get(tenant_id)
            if semaphore is None:
                semaphore = self._tenant_plans.setdefault(
                    tenant_id, asyncio.Semaphore(self._plan_reserved_slots)
                )
            return semaphore

        semaphore = self._tenants.get(tenant_id)
        if semaphore is None:
            semaphore = self._tenants.setdefault(
                tenant_id, asyncio.Semaphore(self._regular_tenant_limit)
            )
        return semaphore

    @asynccontextmanager
    async def acquire(
        self, tenant_id: int | None, *, request_kind: str = "default"
    ) -> AsyncIterator[None]:
        """Acquire tenant then global capacity, failing fast when the gate is busy."""
        tenant_semaphore = (
            self._tenant_semaphore(tenant_id, request_kind)
            if tenant_id is not None
            else None
        )
        global_semaphore = (
            self._global_plans
            if request_kind == "plan" and self._plan_reserved_global_slots
            else self._global
        )
        tenant_acquired = False
        global_acquired = False
        try:
            timeout_seconds = (
                self._plan_acquire_timeout_seconds
                if request_kind == "plan"
                else self._acquire_timeout_seconds
            )
            deadline = asyncio.get_running_loop().time() + timeout_seconds

            async def acquire_before_deadline(semaphore: asyncio.Semaphore) -> None:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise asyncio.TimeoutError
                await asyncio.wait_for(semaphore.acquire(), timeout=remaining)

            try:
                if tenant_semaphore is not None:
                    await acquire_before_deadline(tenant_semaphore)
                    tenant_acquired = True
                await acquire_before_deadline(global_semaphore)
                global_acquired = True
            except asyncio.TimeoutError as exc:
                raise AIGateBusyError(
                    "AI server is busy; retry shortly."
                ) from exc
            yield
        finally:
            if global_acquired:
                global_semaphore.release()
            if tenant_acquired and tenant_semaphore is not None:
                tenant_semaphore.release()


_gate = AIGate(
    global_limit=settings.ollama_max_concurrent,
    tenant_limit=settings.tenant_max_concurrent,
    acquire_timeout_seconds=settings.ai_gate_acquire_timeout_seconds,
    plan_reserved_global_slots=settings.ai_plan_reserved_global_slots,
    plan_reserved_slots=settings.ai_plan_reserved_tenant_slots,
    plan_acquire_timeout_seconds=settings.ai_plan_gate_acquire_timeout_seconds,
)


@asynccontextmanager
async def acquire(
    tenant_id: int | None, *, request_kind: str = "default"
) -> AsyncIterator[None]:
    async with _gate.acquire(tenant_id, request_kind=request_kind):
        yield
