# services/inference/tests/test_routes_audits.py
"""POST /v1/audits route."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import asyncpg
import pytest


def _success_pool():  # type: ignore[no-untyped-def]
    class Conn:
        async def fetchrow(
            self,
            query: str,
            *args: object,
        ) -> dict[str, Any]:
            return {
                "id": uuid4(),
                "event_id": args[0],
                "auditor_id": args[1],
                "decision": args[2],
                "notes": args[3],
                "decided_at": datetime.now(UTC),
            }

    class Pool:
        @asynccontextmanager
        async def acquire(self) -> AsyncIterator[Conn]:
            yield Conn()

    return Pool()


def _fk_violation_pool():  # type: ignore[no-untyped-def]
    class Conn:
        async def fetchrow(self, query: str, *args: object) -> Any:
            raise asyncpg.ForeignKeyViolationError("event does not exist")

    class Pool:
        @asynccontextmanager
        async def acquire(self) -> AsyncIterator[Conn]:
            yield Conn()

    return Pool()


@pytest.mark.asyncio
async def test_create_audit_returns_201_with_payload(app, client) -> None:  # type: ignore[no-untyped-def]
    app.state.db_pool = _success_pool()

    response = await client.post(
        "/v1/audits",
        json={
            "event_id": str(uuid4()),
            "auditor_id": "reviewer-7",
            "decision": "rejected",
            "notes": "clearly toxic",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["decision"] == "rejected"
    assert body["auditor_id"] == "reviewer-7"
    assert body["notes"] == "clearly toxic"


@pytest.mark.asyncio
async def test_create_audit_rejects_unknown_decision(client) -> None:  # type: ignore[no-untyped-def]
    response = await client.post(
        "/v1/audits",
        json={
            "event_id": str(uuid4()),
            "auditor_id": "x",
            "decision": "bogus",
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_audit_returns_404_on_unknown_event(app, client) -> None:  # type: ignore[no-untyped-def]
    app.state.db_pool = _fk_violation_pool()

    response = await client.post(
        "/v1/audits",
        json={
            "event_id": str(uuid4()),
            "auditor_id": "x",
            "decision": "approved",
        },
    )

    # FK violation in the repo must surface as a clean 404, not a 500.
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_create_audit_requires_auditor_id(client) -> None:  # type: ignore[no-untyped-def]
    response = await client.post(
        "/v1/audits",
        json={
            "event_id": str(uuid4()),
            "auditor_id": "",
            "decision": "approved",
        },
    )
    assert response.status_code == 422
