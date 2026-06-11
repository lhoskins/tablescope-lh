"""Ollama LLM client with model routing.

- SQL generation → qwen2.5-coder:7b
- Reasoning/explanation → llama3.1:8b
- Embeddings → nomic-embed-text

The LLM only sees the context package built by the context_builder.
It never has direct access to files, databases, or vector collections.
"""

import logging
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(120.0, connect=10.0)


async def generate(
    prompt: str,
    system_prompt: str = "",
    model: str | None = None,
    temperature: float = 0.1,
    max_tokens: int | None = None,
) -> str:
    """Generate text completion from Ollama."""
    model = model or settings.reasoning_model

    options: dict[str, Any] = {"temperature": temperature}
    if max_tokens is not None:
        options["num_predict"] = max_tokens

    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": options,
    }
    if system_prompt:
        payload["system"] = system_prompt

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.post(
            f"{settings.ollama_url}/api/generate",
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()["response"]


async def generate_sql(
    prompt: str,
    context: str,
    allowed_tables: list[str],
) -> str:
    """Generate SQL using the code-specialized model."""
    system_prompt = (
        "You are Tablescope AI.\n"
        "You may only answer using the provided context package.\n"
        "Do not request or infer access to data outside the provided context.\n"
        "If context is insufficient, say what additional project data would be needed.\n"
        "Generate SQL only using the allowed tables and columns listed below.\n"
        "Do not use SELECT *.\n"
        "Do not generate INSERT, UPDATE, DELETE, DROP, or any write operations.\n"
        "Return only the SQL query, no explanation.\n\n"
        "IMPORTANT: This database uses Teiid (not MySQL, not PostgreSQL).\n"
        "Teiid imports CSV columns as strings.\n"
        "Rules for Teiid SQL:\n"
        "1. For ANY arithmetic (*, /, +, -) or aggregation (SUM, AVG, MIN, MAX) "
        "on numeric columns, CAST each column: CAST(col AS double).\n"
        "   Example: SUM(CAST(\"UnitPrice\" AS double) * CAST(\"Quantity\" AS double))\n"
        "2. COUNT does not need CAST.\n"
        "3. Do NOT use DATE_FORMAT, MONTH(), YEAR(), DAY() — these are MySQL functions.\n"
        "4. For date formatting use FORMATDATE(date_col, 'yyyy-MM') or "
        "CAST date columns: CAST(col AS date).\n"
        "5. For date extraction use EXTRACT(YEAR FROM col), EXTRACT(MONTH FROM col).\n"
        "6. For date truncation use DATE_TRUNC('MONTH', col) or DATE_TRUNC('YEAR', col).\n"
        "7. For grouping by month, use: FORMATDATE(CAST(\"OrderDate\" AS date), 'yyyy-MM')\n"
        "8. Alias columns using valid identifiers (letters/digits/underscore only, "
        "no reserved words like Month). Use SalesMonth, OrderYear, etc.\n"
        "9. The GROUP BY clause must match the SELECT expression exactly.\n\n"
        f"Allowed tables: {', '.join(allowed_tables)}\n\n"
        f"Context:\n{context}"
    )

    return await generate(
        prompt=prompt,
        system_prompt=system_prompt,
        model=settings.sql_model,
        temperature=0.0,
    )


async def generate_embeddings(texts: list[str]) -> list[list[float]]:
    """Generate embeddings using nomic-embed-text."""
    embeddings = []
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        for text in texts:
            resp = await client.post(
                f"{settings.ollama_url}/api/embeddings",
                json={
                    "model": settings.embedding_model,
                    "prompt": text,
                },
            )
            resp.raise_for_status()
            embeddings.append(resp.json()["embedding"])
    return embeddings


async def generate_embedding(text: str) -> list[float]:
    """Generate a single embedding vector."""
    result = await generate_embeddings([text])
    return result[0]


async def check_health() -> str:
    """Check if Ollama is reachable and has models loaded."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            resp = await client.get(f"{settings.ollama_url}/api/tags")
            resp.raise_for_status()
            models = resp.json().get("models", [])
            if models:
                return "ok"
            return "no_models"
    except Exception as e:
        logger.error("Ollama health check failed: %s", e)
        return "unavailable"
