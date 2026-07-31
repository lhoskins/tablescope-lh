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

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import ai, health, internal

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

app.include_router(health.router)
app.include_router(ai.router)
app.include_router(internal.router, prefix="/internal")
