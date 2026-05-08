# services/inference/tests/test_routes_metrics.py
"""Metrics endpoints powering View 3 of the dashboard."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import pytest


def _pool_with_fetch(rows_for):  # type: ignore[no-untyped-def]
    class Conn:
        async def fetch(
            self, query: str, *args: object
        ) -> list[dict[str, Any]]:
            return rows_for(query, args)

    class Pool:
        @asynccontextmanager
        async def acquire(self) -> AsyncIterator[Conn]:
            yield Conn()

    return Pool()


@pytest.mark.asyncio
async def test_confusion_matrix_derives_precision_and_recall(
    app, client
) -> None:  # type: ignore[no-untyped-def]
    rows = [
        {"model_positive": True, "human_positive": True, "count": 12},  # TP
        {"model_positive": True, "human_positive": False, "count": 3},  # FP
        {"model_positive": False, "human_positive": True, "count": 1},  # FN
        {"model_positive": False, "human_positive": False, "count": 84},  # TN
    ]
    app.state.db_pool = _pool_with_fetch(lambda q, a: rows)

    response = await client.get("/v1/metrics/confusion?since_minutes=60")

    assert response.status_code == 200
    body = response.json()
    assert body["true_positive"] == 12
    assert body["false_positive"] == 3
    assert body["false_negative"] == 1
    assert body["true_negative"] == 84
    # precision = TP / (TP + FP) = 12 / 15 = 0.8
    assert body["precision"] == pytest.approx(0.8)
    # recall = TP / (TP + FN) = 12 / 13
    assert body["recall"] == pytest.approx(12 / 13)


@pytest.mark.asyncio
async def test_confusion_matrix_null_when_no_audits(app, client) -> None:  # type: ignore[no-untyped-def]
    app.state.db_pool = _pool_with_fetch(lambda q, a: [])

    response = await client.get("/v1/metrics/confusion")

    body = response.json()
    assert body["true_positive"] == 0
    # No data -> P/R must be null, not 0 (which would be misleading).
    assert body["precision"] is None
    assert body["recall"] is None


@pytest.mark.asyncio
async def test_confusion_matrix_recall_null_when_only_fps(app, client) -> None:  # type: ignore[no-untyped-def]
    """If TP=FN=0 the recall denominator is zero; must report null."""

    rows = [
        {"model_positive": True, "human_positive": False, "count": 5},  # FP
        {"model_positive": False, "human_positive": False, "count": 10},  # TN
    ]
    app.state.db_pool = _pool_with_fetch(lambda q, a: rows)

    response = await client.get("/v1/metrics/confusion")
    body = response.json()
    assert body["precision"] == pytest.approx(0.0)  # TP=0, FP>0
    assert body["recall"] is None  # TP=0, FN=0


@pytest.mark.asyncio
async def test_timeseries_returns_points(app, client) -> None:  # type: ignore[no-untyped-def]
    bucket = datetime.now(UTC).replace(microsecond=0, second=0)
    app.state.db_pool = _pool_with_fetch(
        lambda q, a: [
            {"bucket": bucket, "verdict": "block", "count": 5},
            {"bucket": bucket, "verdict": "review", "count": 12},
            {"bucket": bucket, "verdict": "safe", "count": 100},
        ]
    )

    response = await client.get(
        "/v1/metrics/timeseries?since_minutes=60&bucket_seconds=60",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["bucket_seconds"] == 60
    assert len(body["points"]) == 3


@pytest.mark.asyncio
async def test_timeseries_validates_query_params(client) -> None:  # type: ignore[no-untyped-def]
    # since_minutes capped at 24 * 60.
    response = await client.get("/v1/metrics/timeseries?since_minutes=999999")
    assert response.status_code == 422

    response = await client.get("/v1/metrics/timeseries?bucket_seconds=0")
    assert response.status_code == 422
