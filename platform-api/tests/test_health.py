"""Liveness probe smoke test."""

from __future__ import annotations


async def test_live_returns_ok(client) -> None:
    response = await client.get("/health/live")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"]
