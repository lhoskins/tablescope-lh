"""Tablescope AI Server — FastAPI application.

This server receives AI requests ONLY from the Tablescope app server.
All requests are HMAC-signed and permission-checked before processing.

Architecture:
  App Server → (HMAC-signed request) → AI API → Context Builder → Qdrant + Ollama
  The LLM never decides what it can access. Tablescope decides first.

Services:
  - Ollama (LLM inference, not exposed externally)
  - Qdrant (vector DB, not exposed externally)
  - This API (only service accessible from app server)
"""

import logging

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.routers import ai, health
from app.services.ai_gate import AIGateBusyError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)

app = FastAPI(
    title="Tablescope AI Server",
    description="Tenant-isolated AI with strict context boundaries",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restricted by security group — only app server can reach
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(AIGateBusyError)
async def ai_gate_busy_handler(
    _request: Request, exc: AIGateBusyError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": str(exc), "code": "ai_busy"},
        headers={"Retry-After": "5"},
    )


app.include_router(health.router)
app.include_router(ai.router)
