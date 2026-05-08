# services/inference/tests/test_routes_health.py
"""Health and readiness endpoints."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest


@pytest.mark.asyncio
async def test_healthz_always_ok(client) -> None:  # type: ignore[no-untyped-def]
    response = await client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"


@pytest.mark.asyncio
async def test_readyz_reports_db_unreachable(app, client) -> None:  # type: ignore[no-untyped-def]
    """When the DB pool raises on SELECT 1, readiness must degrade."""

    class BrokenConn:
        async def fetchval(self, query: str, *args: object) -> object:
            raise RuntimeError("postgres down")

    class BrokenPool:
        @asynccontextmanager
        async def acquire(self) -> AsyncIterator[BrokenConn]:
            yield BrokenConn()

    app.state.db_pool = BrokenPool()

    response = await client.get("/readyz")
    assert response.status_code == 200
    body = response.json()
    assert body["database_reachable"] is False


@pytest.mark.asyncio
async def test_readyz_db_ok(client) -> None:  # type: ignore[no-untyped-def]
    response = await client.get("/readyz")
    body = response.json()
    assert body["database_reachable"] is True
    # All the *_loaded fields exist and are booleans.
    assert isinstance(body["text_model_loaded"], bool)
    assert isinstance(body["vision_model_loaded"], bool)
    assert isinstance(body["embedder_loaded"], bool)
    assert isinstance(body["vector_store_reachable"], bool)
