# services/inference/tests/test_routes_events.py
"""GET /v1/events/* routes."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest


def _row(event_id, *, scores_json='{"toxic": 0.95}', verdict="block"):  # type: ignore[no-untyped-def]
    now = datetime.now(UTC)
    return {
        "id": event_id,
        "source_id": "src-1",
        "modality": "text",
        "content": "I hate everyone",
        "content_uri": None,
        "metadata": {},
        "ingested_at": now,
        "model_name": "unitary/toxic-bert",
        "model_version": "default",
        "scores": scores_json,
        "verdict": verdict,
        "inference_latency_ms": 42,
        "predicted_at": now,
    }


def _pool_with(fetch=None, fetchrow=None):  # type: ignore[no-untyped-def]
    class Conn:
        async def fetch(
            self, query: str, *args: object
        ) -> list[dict[str, Any]]:
            return fetch(query, args) if fetch else []

        async def fetchrow(
            self,
            query: str,
            *args: object,
        ) -> dict[str, Any] | None:
            return fetchrow(query, args) if fetchrow else None

        async def fetchval(self, query: str, *args: object) -> Any:
            return 1

    class Pool:
        @asynccontextmanager
        async def acquire(self) -> AsyncIterator[Conn]:
            yield Conn()

    return Pool()


@pytest.mark.asyncio
async def test_recent_events_parses_json_scores(app, client) -> None:  # type: ignore[no-untyped-def]
    eid = uuid4()
    app.state.db_pool = _pool_with(fetch=lambda q, a: [_row(eid)])

    response = await client.get("/v1/events/recent?limit=10")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    event = body["events"][0]
    # Scores arrive from Postgres as a JSON string; the mapping layer
    # must parse them into a real dict.
    assert event["scores"] == {"toxic": 0.95}
    assert event["verdict"] == "block"
    assert event["event_id"] == str(eid)


@pytest.mark.asyncio
async def test_recent_events_forwards_verdict_filter(app, client) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, Any] = {}

    def fetch(query: str, args: tuple[Any, ...]) -> list[dict[str, Any]]:
        captured["query"] = query
        captured["args"] = args
        return []

    app.state.db_pool = _pool_with(fetch=fetch)

    response = await client.get(
        "/v1/events/recent?verdicts=block&verdicts=review&limit=5",
    )

    assert response.status_code == 200
    # First positional arg is the verdicts list.
    assert captured["args"][0] == ["block", "review"]
    assert captured["args"][1] == 5


@pytest.mark.asyncio
async def test_get_event_404_when_missing(app, client) -> None:  # type: ignore[no-untyped-def]
    app.state.db_pool = _pool_with(fetchrow=lambda q, a: None)

    response = await client.get(f"/v1/events/{uuid4()}")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_event_returns_event(app, client) -> None:  # type: ignore[no-untyped-def]
    eid = uuid4()
    app.state.db_pool = _pool_with(
        fetchrow=lambda q, a: _row(eid),
    )

    response = await client.get(f"/v1/events/{eid}")

    assert response.status_code == 200
    assert response.json()["event_id"] == str(eid)


@pytest.mark.asyncio
async def test_get_event_rejects_invalid_uuid(client) -> None:  # type: ignore[no-untyped-def]
    response = await client.get("/v1/events/not-a-uuid")
    # FastAPI rejects this at validation time.
    assert response.status_code == 422
